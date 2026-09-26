r"""Command line: typed decisions and ChipJev searches for a design request.

  chipjev tasks
  chipjev decide "Design a two-stage op-amp with the highest gain-bandwidth product" \
      --vdd 1.2 --load 100
  chipjev design --task opampN-gbw                       # one run of the paper's protocol
  chipjev design "Design a folded-cascode op-amp with maximum gain" --vdd 1.2 --load 10
  chipjev design --task opampN-gbw --technology sky130   # open SKY130 PDK, 1.8 V

``design`` runs ChipJev exactly as the frozen studies did (typed decisions with the
fine-tuned weights, a 1,024-simulation search with eight ngspice workers, strict
qualification) and writes the result, the qualified circuit and its testbench deck to
runs/designs/. Pass ``python -m chipjev`` when the console script is not on the PATH.
"""

import argparse
import gzip
import json
import os
import re
import sys
import time
from pathlib import Path

from .paths import ROOT, WEIGHTS

DEFAULT_VDD = {"ptm45": 1.2, "sky130": 1.8}
DEFAULT_LOAD_PF = 100.0


def _weights(path):
    """--weights, else $CHIPJEV_WEIGHTS, else the fine-tuned weights of the PTM 45 nm study,
    else the zero-shot checkpoint (None)."""
    for candidate in (path, os.environ.get("CHIPJEV_WEIGHTS"), WEIGHTS):
        if candidate and Path(candidate).exists():
            return Path(candidate)
    return None


def _pinned(weights):
    """The vendored ChipLaya release's SHA-256 for the default weights; None for others."""
    if weights is None or Path(weights).resolve() != WEIGHTS.resolve():
        return None
    from .decisions.typed import released_sha256

    return released_sha256()


def _decisions(args):
    from .decisions.typed import TypedDecisions

    weights = _weights(args.weights)
    model = TypedDecisions(weights=weights, device=args.device, expected_sha256=_pinned(weights))
    model.warm()
    print(f"typed decisions: {model_label(model)} on {model.metadata['device']}", flush=True)
    return model


def model_label(model):
    """ChipLaya's release for released weights, else what the weights are."""
    from .decisions.typed import release_label

    if model.weights is None:
        return "base Laya, zero-shot (no fine-tuned weights found)"
    label = release_label(model.weights["sha256"]) or "Laya fine-tuned"
    return f"{label} ({model.weights['path']})"


def _print_answer(answer, top):
    import numpy as np

    print(f"class {answer['class']}, objective {answer['objective']} "
          f"(parsed); topology prior over {len(answer['topologies'])} "
          f"{answer['topology_class']} topologies for {answer['topology_objective']}, "
          f"{1000 * answer['seconds']:.1f} ms")
    for question, reply in answer["answers"].items():
        options = ", ".join(f"{k} {v:.2f}" for k, v in sorted(
            reply["probabilities"].items(), key=lambda kv: -kv[1]))
        print(f"  {question:15s} {options}")
    print("most probable topologies:")
    for j in np.argsort(answer["prior"])[::-1][:top]:
        print(f"  {answer['prior'][j]:.3f}  {answer['topologies'][j]}")


def decide(args):
    model = _decisions(args)
    answer = model.ask(args.request, vdd=args.vdd, load_pf=args.load, cls=args.cls,
                       objective=args.objective)
    if args.json:
        print(json.dumps(answer, indent=1))
    else:
        _print_answer(answer, args.top)


def tasks_command(args):
    from .tasks import tasks

    for t in tasks():
        print(f"{t['id']:12s} {t['acpro_id']}  VDD {t['vdd']:g} V, CL {t['load_pf']:g} pF  "
              f"{t['statement']}")


def _slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:48] or "request"


def layout_command(args):
    from .circuits.published import lookup
    from .layout.flow import complete

    if args.legacy and (args.corners or args.mismatch_samples or args.sizing_evaluations
                        or args.goal or args.input_bias is not None):
        raise ValueError("Legacy layout cannot use the new physical-goal or robustness options")

    opener = gzip.open if args.input.suffix == ".gz" else open
    with opener(args.input, "rt") as stream:
        record = json.load(stream)
    if args.mismatch_samples < 0 or args.sizing_evaluations < 0:
        raise ValueError("Sample and refinement counts cannot be negative")
    technology = record.get("technology", "")
    if not technology.startswith("sky130"):
        raise ValueError("Physical synthesis requires a SKY130 result, not PTM sizing")
    selected = record.get("best") or record
    topology = lookup(record["cls"], selected["topology"])
    if not args.legacy and args.generator == "pro":
        return _layout_pro(args, record, selected, topology)
    args.objective = args.objective or "area"
    if args.legacy:
        result = complete(topology, selected["values"], args.output,
                          vdd=record.get("vdd", 1.8), load_pf=record.get("load_pf", 100),
                          max_candidates=0 if args.no_recovery else 48,
                          observer=lambda name, data: print(name, flush=True))
    else:
        from .decisions.typed import TypedDecisions
        from .search.layout import LayoutGoal, optimize
        from .simulation.analog import AnalogConditions

        config=json.loads(args.goal.read_text()) if args.goal else {}
        if "analog" in config:
            config["analog"]=AnalogConditions(**config["analog"])
        config.setdefault("objective",args.objective)
        model=None if args.no_laya else TypedDecisions(weights=_weights(None),device=args.device)
        result=optimize(topology,selected["values"],args.output,goal=LayoutGoal(**config),
                        vdd=record.get("vdd",1.8),load_pf=record.get("load_pf",100),
                        input_bias=args.input_bias,model=model,max_evaluations=args.evaluations,
                        budget_seconds=args.seconds,
                        observer=lambda name,data:print(name,flush=True))
        if args.sizing_evaluations:
            from .search.layout_joint import refine
            result=refine(topology,result,args.output,max_evaluations=args.sizing_evaluations,
                          budget_seconds=args.seconds,vdd=record.get("vdd",1.8),
                          load_pf=record.get("load_pf",100))
        if args.corners or args.mismatch_samples:
            from .circuits.sky130_devices import build
            from .layout.verification import ExtractedCircuit
            from .simulation.physical_robustness import qualify

            circuit=ExtractedCircuit(build(topology,result["values"],record.get("vdd",1.8)),
                                     args.output/"pex.spice")
            result["robustness"]=qualify(topology,result["values"],circuit,args.output/"robustness",
                input_bias=result["optimization"]["fixed_input_bias_v"],vdd=record.get("vdd",1.8),
                load_pf=record.get("load_pf",100),corners=tuple(args.corners or ()),
                mismatch_seeds=range(args.mismatch_samples),conditions=LayoutGoal(**config).analog,
                temperatures=(LayoutGoal(**config).analog.temperature_c,))
            result["valid"] &= result["robustness"]["status"]=="pass"
            (args.output/"physical.json").write_text(json.dumps(result,indent=2,allow_nan=False))
    print(json.dumps({"valid": result["valid"], "layout_seconds": result["layout"]["layout_seconds"],
                      "physical_seconds": result["total_seconds"],
                      "drc_errors": result["layout"]["drc_errors"], "lvs": result["lvs"]["passed"],
                      "postlayout": result["postlayout"]["metrics"], "output": str(args.output)}, indent=2))
    return 0 if result["valid"] else 1


def _layout_pro(args, record, selected, topology):
    """Goal-driven search over the professional templates (Laya + knowledge cards)."""
    from .search.pro_layout import GOALS, optimize_pro

    goal = args.objective or "quality"
    if goal not in GOALS:
        raise ValueError(f"The pro generator optimizes {GOALS}; use --generator groups for {goal}")
    if args.goal or args.corners or args.mismatch_samples or args.sizing_evaluations:
        raise ValueError("Physical-goal files, corners and joint sizing run with --generator groups")
    model = None
    if not args.no_laya:
        from .decisions.typed import TypedDecisions

        weights = args.layout_policy or _weights(None)
        model = TypedDecisions(weights=weights, device=args.device)
        model.layout_policy = args.layout_policy is not None
    bias = args.input_bias if args.input_bias is not None else (selected.get("metrics") or {}).get("vin_dc")
    try:
        trace = optimize_pro(topology, selected["values"], args.output, goal=goal,
                             vdd=record.get("vdd", 1.8), load_pf=record.get("load_pf", 100),
                             input_bias=bias, model=model, max_evaluations=args.evaluations,
                             parallel=args.parallel, budget_seconds=args.seconds,
                             patience=args.patience,
                             finger_max_um=record.get("finger_max_um") or selected.get("finger_max_um"))["optimization"]
    except RuntimeError as exc:
        print(json.dumps({"valid": False, "error": str(exc), "output": str(args.output)}, indent=2))
        return 1
    best = next((h for h in trace["history"] if h["directory"] == trace["selected"]), {})
    print(json.dumps({"valid": best.get("valid", False), "selected": trace["selected"],
                      "area_um2": best.get("area_um2"), "critic": best.get("critic"),
                      "plan": best.get("plan"), "postlayout": best.get("metrics"),
                      "evaluations": trace["evaluations"], "wall_seconds": trace["wall_seconds"],
                      "output": str(args.output)}, indent=2, default=str))
    return 0 if best.get("valid") else 1


def design(args):
    from .circuits.published import lookup
    from .search.evaluator import Evaluator
    from .search.loop import ChipJevSearch, Settings, warm
    from .tasks import task

    request, cls, objective = args.request, args.cls, args.objective
    vdd, load = args.vdd, args.load
    if args.task:
        spec = task(args.task)
        request = request or spec["statement"]
        cls, objective = cls or spec["cls"], objective or spec["target"]
        load = spec["load_pf"] if load is None else load
        name = spec["id"]
    elif not request:
        raise SystemExit("give a design request or --task (see `chipjev tasks`)")
    else:
        name = _slug(request)
    vdd = DEFAULT_VDD[args.technology] if vdd is None else vdd
    load = DEFAULT_LOAD_PF if load is None else load
    if vdd <= 0 or load <= 0:
        raise SystemExit("--vdd and --load must be positive")
    if args.budget < 8:
        raise SystemExit("--budget must be at least one round of 8 simulations")
    output = args.output or ROOT / "runs/designs" / f"{name}-{args.technology}-s{args.seed}"
    output.mkdir(parents=True, exist_ok=True)

    model = _decisions(args)
    answer = model.ask(request, vdd=vdd, load_pf=load, cls=cls, objective=objective)
    _print_answer(answer, 5)
    cls, objective = answer["topology_class"], answer["topology_objective"]
    prior = None if args.no_prior else answer["prior"]

    print(f"search: {args.technology}, {args.budget} simulations, {args.workers} ngspice "
          f"workers, VDD {vdd:g} V, CL {load:g} pF", flush=True)
    options = None
    if args.finger_max is not None:
        if args.technology != "sky130":
            raise ValueError("--finger-max is the SKY130 layout-aware device template")
        # Physical profile: size the devices exactly as the layout will draw them.
        options = {"quantize_geometry": float(args.finger_max)}
    evaluator = Evaluator(args.workers, technology=args.technology, corner=args.corner,
                          evaluate_options=options)
    try:
        warm(args.device, classes=(cls,))
        settings = Settings(seed=args.seed, rounds=max(1, args.budget // 8), device=args.device,
                            prior_mix=0.5, typed_starts=4)
        start = time.perf_counter()
        result = ChipJevSearch(settings).run(cls, objective, evaluator, prior=prior,
                                             load_pf=load, vdd=vdd, rules="qualified")
        seconds = time.perf_counter() - start
    finally:
        evaluator.close()

    result.update(request=request, technology=args.technology, corner=args.corner,
                  typed={k: answer[k] for k in ("state", "class", "objective", "answers",
                                                "seconds")})
    if args.finger_max is not None:
        result["finger_max_um"] = float(args.finger_max)
    with gzip.open(output / "result.json.gz", "wt") as stream:
        json.dump(result, stream, allow_nan=False)
    best = result["best"]
    first = result["first_verified"] or {}
    print(f"search finished in {seconds:.1f} s ({result['evaluations']} simulations, "
          f"{result['verifications']} strict re-simulations)")
    if best is None:
        print("no design passed strict qualification; try a larger --budget or another seed")
        return 1
    topology = lookup(cls, best["topology"])
    _write_design(output, args.technology, args.corner, topology, best, vdd, load)
    metrics = best["metrics"]
    print(f"qualified design: {best['topology']} after {first.get('seconds', 0.0):.2f} s "
          f"(first qualified), best at {best['seconds']:.2f} s")
    print("  " + ", ".join(f"{k} {metrics[k]:.4g}" for k in (
        "gain_db", "gbw_mhz", "pm_deg", "power_uw", "fom", "cmrr_db")
        if metrics.get(k) is not None))
    print(f"written to {output}: result.json.gz, circuit.spice, testbench.spice")
    return 0


def _write_design(output, technology, corner, topology, best, vdd, load):
    """The qualified circuit (devices and bias sources) and its strict testbench deck."""
    if technology == "sky130":
        from .circuits.sky130_devices import build
        from .simulation.sky130 import deck
    else:
        from .circuits.grammar import build
        from .simulation.ptm45 import deck
    b = build(topology, best["values"], vdd)
    ports = "inp inn out" if topology.differential else "in out"
    lines = [f"* ChipJev {technology} design {best['topology']}: ports {ports}, supply vdd",
             f"* reported {best['reported']:.6g} ({json.dumps(best['metrics'])})"]
    lines += [f"v_{node} {node} 0 DC {volts:.6f}" for node, volts in sorted(b.bias.items())]
    lines += b.lines
    (output / "circuit.spice").write_text("\n".join(lines) + "\n")
    extra = {"corner": corner} if technology == "sky130" else {}
    text, _ = deck(topology, best["values"], strict=True, load_pf=load, vdd=vdd, **extra)
    (output / "testbench.spice").write_text(text)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="chipjev", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p):
        p.add_argument("--class", dest="cls", choices=("amp1", "opamp1", "ampN", "opampN"),
                       help="circuit class (default: parsed from the request)")
        p.add_argument("--objective", choices=("gain", "gbw", "fom"),
                       help="objective (default: parsed from the request)")
        p.add_argument("--vdd", type=float, help="supply voltage (V)")
        p.add_argument("--load", type=float, help="load capacitance (pF)")
        p.add_argument("--weights", type=Path, help="fine-tuned typed-decision weights")
        p.add_argument("--device", help="cuda, mps or cpu (default: the best available)")

    p = sub.add_parser("decide", help="typed decisions for a design request")
    p.add_argument("request")
    common(p)
    p.add_argument("--top", type=int, default=5)
    p.add_argument("--json", action="store_true")
    p.set_defaults(run=decide)

    p = sub.add_parser("design", help="typed decisions and a ChipJev search")
    p.add_argument("request", nargs="?")
    p.add_argument("--task", help="one of AnalogCoder-Pro's twelve tasks (`chipjev tasks`)")
    common(p)
    p.add_argument("--technology", choices=("ptm45", "sky130"), default="ptm45")
    p.add_argument("--corner", default="tt", choices=("tt", "ss", "ff", "sf", "fs"),
                   help="SKY130 process corner")
    p.add_argument("--budget", type=int, default=1024, help="simulations (default 1024)")
    p.add_argument("--workers", type=int, default=8, help="ngspice worker processes")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--no-prior", action="store_true",
                   help="ignore the typed topology prior (the paper's ablation)")
    p.add_argument("--output", type=Path, help="output directory (default runs/designs/...)")
    p.add_argument("--finger-max", type=float, metavar="UM",
                   help="SKY130 layout-aware sizing: simulate devices with fingers of at most UM um "
                        "on the 10 nm grid, exactly as the layout generator draws them")
    p.set_defaults(run=design)

    p = sub.add_parser("tasks", help="AnalogCoder-Pro's twelve benchmark tasks")
    p.set_defaults(run=tasks_command)

    p = sub.add_parser("layout", help="SKY130 Magic layout, LVS, RC extraction and ngspice post-layout verification")
    p.add_argument("input", type=Path, help="SKY130 result.json or result.json.gz")
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--no-recovery", action="store_true", help="verify the supplied sizing without refinement")
    p.add_argument("--legacy", action="store_true", help="use the original single-row flow for comparison")
    p.add_argument("--generator", choices=("pro", "groups"), default="pro",
                   help="pro: professional template generator (default); groups: the analog-groups-v1 flow")
    p.add_argument("--parallel", type=int, default=4, help="layout candidates verified concurrently (pro)")
    p.add_argument("--layout-policy", type=Path,
                   help="Laya weights fine-tuned on layout self-play (decisions.layout_selfplay train)")
    p.add_argument("--goal", type=Path, help="JSON physical goal and analog test conditions")
    p.add_argument("--objective", choices=("quality","area","gain","gbw","pm","fom","noise","matching"),
                   default=None, help="pro: quality (default), area, gain, gbw, pm")
    p.add_argument("--evaluations",type=int,default=8)
    p.add_argument("--seconds",type=float,default=60)
    p.add_argument("--patience", type=int, default=2,
                   help="pro: stop after this many iterations without a better qualified layout (0: off)")
    p.add_argument("--input-bias",type=float,help="fixed common-mode/input bias for every candidate")
    p.add_argument("--device",choices=("cpu","cuda","mps"))
    p.add_argument("--no-laya",action="store_true",help="ablate the typed physical-action prior")
    p.add_argument("--corners",nargs="+",choices=("tt","ss","ff","sf","fs"))
    p.add_argument("--mismatch-samples",type=int,default=0)
    p.add_argument("--sizing-evaluations",type=int,default=0,help="optional separate joint sizing/layout refinement budget")
    p.set_defaults(run=layout_command)

    args = parser.parse_args(argv)
    tools = ROOT / ".tools/bin"
    if tools.exists() and str(tools) not in os.environ.get("PATH", ""):
        os.environ["PATH"] = f"{tools}{os.pathsep}{os.environ.get('PATH', '')}"
    return args.run(args) or 0


if __name__ == "__main__":
    sys.exit(main())
