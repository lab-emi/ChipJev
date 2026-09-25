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

from .paths import ROOT

WEIGHTS = ROOT / "experiments/ptm45/typed-decisions.pt"
DEFAULT_VDD = {"ptm45": 1.2, "sky130": 1.8}
DEFAULT_LOAD_PF = 100.0


def _weights(path):
    """--weights, else $CHIPJEV_WEIGHTS, else the fine-tuned weights of the PTM 45 nm study,
    else the zero-shot checkpoint (None)."""
    for candidate in (path, os.environ.get("CHIPJEV_WEIGHTS"), WEIGHTS):
        if candidate and Path(candidate).exists():
            return Path(candidate)
    return None


def _decisions(args):
    from .decisions.typed import TypedDecisions

    weights = _weights(args.weights)
    model = TypedDecisions(weights=weights, device=args.device)
    model.warm()
    label = f"fine-tuned ({weights})" if weights else "zero-shot (no fine-tuned weights found)"
    print(f"typed decisions: Laya on {model.metadata['device']}, {label}", flush=True)
    return model


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
    evaluator = Evaluator(args.workers, technology=args.technology, corner=args.corner)
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
    p.set_defaults(run=design)

    p = sub.add_parser("tasks", help="AnalogCoder-Pro's twelve benchmark tasks")
    p.set_defaults(run=tasks_command)

    args = parser.parse_args(argv)
    tools = ROOT / ".tools/bin"
    if tools.exists() and str(tools) not in os.environ.get("PATH", ""):
        os.environ["PATH"] = f"{tools}{os.pathsep}{os.environ.get('PATH', '')}"
    return args.run(args) or 0


if __name__ == "__main__":
    sys.exit(main())
