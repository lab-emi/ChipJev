"""AnalogCoder-Pro's sizing stage, reconstructed on the common testbench.

AnalogCoder-Pro (IEEE TCAD 2026; code github.com/laiyao1/AnalogCoderPro @ 05542af) does not
release its device-model module or its optimizer helper. This module supplies both:

* ``model_module()``: ``nmos_params``/``pmos_params`` built from the testbench's PTM 45 nm
  HP card, which the generated PySpice code imports as ``from model import ...``.
* ``helper_main``: the helper that ``run.py`` invokes as
  ``python circuit_optimizer_helper.py <parameterized code> <target>``. As published, it
  runs Optuna TPE for 1,000 trials with 250 random start-up trials and multivariate
  sampling over the LLM-extracted parameter ranges, starting from the LLM's initial values.
  Each trial is measured on the common testbench under the qualified rules (bias search,
  saturation, stability, CMRR for op-amps); TPE maximizes the same feasibility-first score
  as every other method, and each new online incumbent is re-simulated strictly, including
  the unity-buffer steps for op-amps. Only strict passes are reported.
"""

import json
import math
import os
import re
import sys
import time
from pathlib import Path

from ..simulation.analysis import LOAD_PF, objective, reported
from ..simulation.ptm45 import MODEL, evaluate

# AnalogCoder-Pro's unified topology-generation-and-optimization task ids.
TASKS = {
    51: ("amp1", "gain"), 52: ("opamp1", "gain"), 53: ("ampN", "gain"), 54: ("opampN", "gain"),
    55: ("amp1", "gbw"), 56: ("opamp1", "gbw"), 57: ("ampN", "gbw"), 58: ("opampN", "gbw"),
    59: ("amp1", "fom"), 60: ("opamp1", "fom"), 61: ("ampN", "fom"), 62: ("opampN", "fom"),
}
TRIALS = 1000
STARTUP = 250
VDD = 1.2


def ptm_params(kind):
    """Model parameters of the PTM card for one device type, as a PySpice keyword dict."""
    statements, current = [], None
    for raw in Path(MODEL).read_text().splitlines():
        line = raw.split("*", 1)[0] if raw.lstrip().startswith("*") else raw
        if line.lower().lstrip().startswith(".model"):
            current = [line.strip()]
            statements.append(current)
        elif current is not None and line.lstrip().startswith("+"):
            current.append(line.strip()[1:])
    for statement in statements:
        head = statement[0].split()
        if len(head) >= 3 and head[1].lower() == kind and head[2].lower() == kind:
            text = " ".join([" ".join(head[3:])] + statement[1:])
            return {k.lower(): _number(v) for k, v in re.findall(r"(\w+)\s*=\s*([^\s]+)", text)}
    raise ValueError(f"no {kind} model in {MODEL}")


def _number(token):
    try:
        number = float(token)
    except ValueError:
        return token
    return int(number) if re.fullmatch(r"[-+]?\d+", token) else number


def model_module():
    """Source of the model.py that AnalogCoder-Pro's generated code imports."""
    return (
        '"""PTM 45 nm HP card of the common testbench, as PySpice model parameters."""\n'
        f"nmos_params = {ptm_params('nmos')!r}\n"
        f"pmos_params = {ptm_params('pmos')!r}\n"
    )


def feasibility_score(record, target):
    from ..search.baselines import score

    return score(record, target)


def helper_main(argv):
    """Entry point of the reconstructed circuit_optimizer_helper.py."""
    import optuna

    from .netlist import NetlistError, NetlistTopology

    code_name, target = argv[0], argv[1]
    task_id = int(os.environ["ACPRO_TASK_ID"])
    seed = int(os.environ.get("ACPRO_SEED", "0"))
    trials = int(os.environ.get("ACPRO_TRIALS", TRIALS))
    cls, task_target = TASKS[task_id]
    if target != task_target:
        raise SystemExit(f"target {target} does not match task {task_id}")
    start = time.perf_counter()
    result_path = Path(code_name + ".result.json")
    result = {
        "task_id": task_id, "cls": cls, "target": target, "seed": seed, "code": code_name,
        "trials": trials, "startup": STARTUP, "status": "started",
    }
    namespace = {"__name__": "llm_parameterized"}
    try:
        source = Path(code_name).read_text()
        exec(compile(source, code_name, "exec"), namespace)  # sandboxed LLM code
        create = namespace["create_circuit"]
        ranges = namespace["param_ranges_definition"]
        initial = dict(namespace.get("initial_params") or {})
    except Exception as exc:  # the LLM's parameterized code is unusable
        result.update(status="unusable-code", error=f"{type(exc).__name__}: {exc}")
        result_path.write_text(json.dumps(result, indent=1))
        return 0
    names = sorted(ranges)

    def factory(values):
        return str(create(dict(values)))

    topology = NetlistTopology(cls, f"acpro-{task_id}-{Path(code_name).stem}", factory)
    optuna.logging.set_verbosity(optuna.logging.ERROR)
    sampler = optuna.samplers.TPESampler(
        n_startup_trials=STARTUP, multivariate=True, seed=seed
    )
    study = optuna.create_study(direction="maximize", sampler=sampler)
    start_values = {}
    for name in names:
        spec = ranges[name]
        low, high = float(spec["min"]), float(spec["max"])
        if name in initial:
            try:
                v = float(initial[name])
            except (TypeError, ValueError):
                continue
            if low <= v <= high:
                start_values[name] = v
    if len(start_values) == len(names):
        study.enqueue_trial(start_values)
    best, first, trajectory = None, None, []
    online = {"valid": 0, "errors": 0, "unevaluable": 0}
    evaluate_seconds = verify_seconds = 0.0
    for k in range(trials):
        trial = study.ask()
        try:
            values = {}
            for name in names:
                spec = ranges[name]
                low, high = float(spec["min"]), float(spec["max"])
                log = bool(spec.get("log", False)) and low > 0
                values[name] = trial.suggest_float(name, low, high, log=log)
        except Exception as exc:
            result.update(status="bad-ranges", error=f"{type(exc).__name__}: {exc}")
            break
        t0 = time.perf_counter()
        try:
            record = evaluate(topology, values, load_pf=LOAD_PF, vdd=VDD, rules="qualified")
        except NetlistError as exc:
            record = {"valid": False, "error": str(exc), "checks": {}, "metrics": {},
                      "margins": {}}
            online["unevaluable"] += 1
        except Exception as exc:  # LLM code failing for these parameter values
            record = {"valid": False, "error": f"{type(exc).__name__}: {exc}", "checks": {},
                      "metrics": {}, "margins": {}}
            online["unevaluable"] += 1
        evaluate_seconds += time.perf_counter() - t0
        record["objective"] = objective(record, target)
        online["valid"] += bool(record.get("valid"))
        online["errors"] += bool(record.get("error"))
        study.tell(trial, feasibility_score(record, target))
        threshold = -math.inf if best is None else best["objective"]
        if record.get("valid") and record["objective"] is not None and record["objective"] > threshold:
            t1 = time.perf_counter()
            strict = evaluate(topology, values, strict=True, load_pf=LOAD_PF, vdd=VDD,
                              rules="qualified")
            verify_seconds += time.perf_counter() - t1
            strict["objective"] = objective(strict, target)
            if strict.get("valid") and strict["objective"] is not None and strict["objective"] > threshold:
                at = time.perf_counter() - start
                best = dict(strict, seconds=at, trial=k, params=values)
                if first is None:
                    first = {"seconds": at, "trial": k}
        trajectory.append((k, round(time.perf_counter() - start, 4),
                           None if best is None else best["objective"]))
        if k % 100 == 99:
            _write(result_path, result, best, first, trajectory, online, start,
                   evaluate_seconds, verify_seconds, topology, target, running=True)
    else:
        result["status"] = "finished"
    _write(result_path, result, best, first, trajectory, online, start, evaluate_seconds,
           verify_seconds, topology, target, running=False)
    return 0


def _write(path, result, best, first, trajectory, online, start, evaluate_seconds,
           verify_seconds, topology, target, running):
    netlist = None
    if best is not None:
        try:
            b = topology.build(best["params"], VDD)
            netlist = {"lines": b.lines, "bias": b.bias, "mos": b.mos, "nodes": sorted(b.nodes)}
        except Exception:
            netlist = None
    out = dict(result)
    out.update(
        running=running,
        wall_seconds=time.perf_counter() - start,
        evaluate_seconds=evaluate_seconds,
        verify_seconds=verify_seconds,
        online=online,
        verified=best is not None,
        first_verified=first,
        best=None if best is None else {
            "params": best["params"], "metrics": best.get("metrics"),
            "objective": best["objective"], "reported": reported(best, target),
            "seconds": best["seconds"], "trial": best["trial"],
            "qualification": best.get("qualification"), "netlist": netlist,
        },
        trajectory=trajectory,
    )
    path.write_text(json.dumps(_clean(out), allow_nan=False))


def _clean(value):
    """JSON-safe copy: non-finite floats become None, tuples become lists."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if value is None or isinstance(value, (bool, int, str)):
        return value
    return str(value)


if __name__ == "__main__":
    sys.exit(helper_main(sys.argv[1:]))
