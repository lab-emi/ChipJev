"""Self-play labels for Laya's layout policy: every action measured, no human labels.

collect: for each design, evaluate the seed plan and every one-knob action
through the full physical flow (DRC, LVS, RC extraction, post-layout ngspice,
critic). One row per design holds the state text, the option texts with the
knowledge cards injected for that action, and each option's measured outcome.

train: turn rows into soft-labelled choice questions (softmax of the measured
objective gain over random option subsets), fine-tune Laya's decision head
with decisions.finetune.train, and report held-out regret on unseen topology
families against the knowledge-card prior, the untrained model and random.

    python -m chipjev.decisions.layout_selfplay collect designs.txt --output runs/selfplay
    python -m chipjev.decisions.layout_selfplay train runs/selfplay/rows.jsonl \\
        --holdout tele cmota --output runs/layout-policy
"""

import argparse
import gzip
import json
import math
import random
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from ..circuits.published import lookup
from ..layout.pro.knowledge import symptoms_of
from ..layout.pro.planner import ProPlan
from ..search.pro_layout import _evaluate, _prior, objective
from ..simulation.sky130 import evaluate
from .pro_layout import INSTRUCTIONS, option_text, state_text

TAU = 3.0  # objective points (critic score and 10*log10 area) per e-fold of preference
UNIFORM = 0.05


def _family(topology_id):
    return topology_id.split("+")[0].rsplit("_", 1)[0]


def _load(path):
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rt") as stream:
        record = json.load(stream)
    best = record.get("best") or record
    return record, best


def _round(pool, topology, values, vdd, load, bias, pre, parent_plan, parent, base, goal, reference):
    """Evaluate every one-knob action of ``parent_plan``; return (row, results)."""
    plans = list(parent_plan.neighbors())
    jobs = [(topology.cls, topology.id, values, str(base / f"o{k:02d}"), p.to_dict(), vdd, load, bias, pre, None)
            for k, (_, p) in enumerate(plans)]
    results = list(pool.map(_evaluate, jobs))
    for r in results:
        r["objective"] = objective(r, goal, reference) if r.get("metrics") else None
    symptoms = parent.get("symptoms", [])
    options = []
    for (field, plan), r in zip(plans, results):
        old, new = getattr(parent_plan, field), getattr(plan, field)
        text, cards = option_text(field, old, new, symptoms)
        options.append({"field": field, "value": new, "plan": plan.to_dict(), "text": text, "cards": cards,
                        "prior": _prior(field, new, parent, goal), "valid": r.get("valid"),
                        "objective": r["objective"], "area_um2": r.get("area_um2"), "critic": r.get("critic")})
    row = {"schema": "chipjev-layout-selfplay-v1", "topology": topology.id, "family": _family(topology.id),
           "goal": goal, "parent_valid": parent.get("valid"), "parent_plan": parent_plan.to_dict(),
           "state": state_text(goal, parent, symptoms, parent_plan.to_dict()),
           "parent_objective": parent.get("objective"), "options": options}
    return row, results


def collect(paths, output, parallel=8, goal="quality", depth=2):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    with ProcessPoolExecutor(parallel) as pool:
        for n, path in enumerate(paths):
            record, best = _load(path)
            if not record.get("technology", "sky130").startswith("sky130") or not best.get("topology"):
                continue
            topology = lookup(record["cls"], best["topology"])
            vdd, load = record.get("vdd", 1.8), record.get("load_pf", 100)
            base = output / f"d{n:03d}"
            pre = None
            for bias in ((best.get("metrics") or {}).get("vin_dc"), None):
                # The recorded bias first; if the grid-quantized schematic no longer
                # qualifies there, let the bench search its operating point once.
                pre = evaluate(topology, best["values"], directory=base / f"schematic-{bias}", strict=True,
                               keep=True, vdd=vdd, load_pf=load, input_bias=bias, quantize_geometry=True)
                if pre.get("valid"):
                    break
            if not pre.get("valid"):
                print(f"{path}: schematic does not qualify on the grid; skipped", flush=True)
                continue
            bias = pre["metrics"]["vin_dc"]
            start = time.perf_counter()
            seed = ProPlan()
            parent = _evaluate((topology.cls, topology.id, best["values"], str(base / "seed"), seed.to_dict(),
                                vdd, load, bias, pre, None))
            if not parent.get("metrics"):
                print(f"{path}: seed layout failed ({parent.get('error', '')[:80]}); skipped", flush=True)
                continue
            reference = parent["area_um2"]
            parent["objective"] = objective(parent, goal, reference)
            plan = seed
            for level in range(depth):
                row, results = _round(pool, topology, best["values"], vdd, load, bias, pre, plan, parent,
                                      base / f"level{level}", goal, reference)
                row.update(design=str(path), level=level)
                valid = sum(bool(o["valid"]) for o in row["options"])
                print(f"{path}: {topology.id} level {level}: {valid}/{len(row['options'])} options valid, "
                      f"{time.perf_counter() - start:.0f}s", flush=True)
                if valid:
                    rows.append(row)
                    with open(output / "rows.jsonl", "a") as stream:
                        stream.write(json.dumps(row, default=str) + "\n")
                scored = [(o["objective"], o, r) for o, r in zip(row["options"], results)
                          if o["valid"] and o["objective"] is not None]
                if not scored:
                    break
                _, option, parent = max(scored, key=lambda t: t[0])
                parent["objective"] = option["objective"]
                plan = ProPlan(**option["plan"])
    return rows


def _entry(path):
    """An evaluated option rebuilt from its evidence directory (physical.json)."""
    physical = path / "physical.json"
    if not physical.exists():
        return {"valid": False}
    r = json.loads(physical.read_text())
    return {"valid": r["valid"], "metrics": r["postlayout"]["metrics"], "area_um2": r["layout"]["area_um2"],
            "critic": r["critic"]["score"], "symptoms": symptoms_of(r), "findings": r["critic"]["findings"]}


def rebuild(paths, output, goal="quality"):
    """Rows from already measured evidence, including designs whose seed layout failed:
    which action rescues a failing layout is exactly the closure signal to learn."""
    output = Path(output)
    rows = []
    seed = ProPlan()
    plans = [("seed", seed), *seed.neighbors()]
    for n, path in enumerate(paths):
        base = output / f"d{n:03d}"
        if not (base / "o00").exists():
            continue
        record, best = _load(path)
        topology = lookup(record["cls"], best["topology"])
        results = [_entry(base / f"o{k:02d}") for k in range(len(plans))]
        parent = results[0]
        if not parent.get("metrics"):
            continue
        area = parent["area_um2"]
        for r in results:
            r["objective"] = objective(r, goal, area) if r.get("metrics") else None
        if not any(r.get("valid") for r in results[1:]):
            continue
        symptoms = parent.get("symptoms", [])
        options = []
        for (field, plan), r in zip(plans[1:], results[1:]):
            old, new = getattr(seed, field), getattr(plan, field)
            text, cards = option_text(field, old, new, symptoms)
            options.append({"field": field, "value": new, "text": text, "cards": cards,
                            "prior": _prior(field, new, parent, goal), "valid": r.get("valid"),
                            "objective": r["objective"], "area_um2": r.get("area_um2"),
                            "critic": r.get("critic")})
        rows.append({"schema": "chipjev-layout-selfplay-v1", "design": str(path), "topology": topology.id,
                     "family": _family(topology.id), "goal": goal, "parent_valid": parent["valid"],
                     "state": state_text(goal, parent, symptoms, seed.to_dict()),
                     "parent_objective": parent["objective"], "options": options})
    (output / "rows.jsonl").write_text("".join(json.dumps(r, default=str) + "\n" for r in rows))
    return rows


def _target(options):
    scores = [o["objective"] if o["valid"] and o["objective"] is not None else None for o in options]
    finite = [s for s in scores if s is not None]
    if not finite:
        return None
    top = max(finite)
    weights = [math.exp((s - top) / TAU) if s is not None else 0.0 for s in scores]
    total = sum(weights)
    return [(1 - UNIFORM) * w / total + UNIFORM / len(options) for w in weights]


def examples(rows, per_row=8, size=5, seed=0):
    rng = random.Random(seed)
    out = []
    for row in rows:
        options = [o for o in row["options"]]
        for _ in range(per_row):
            subset = rng.sample(options, min(size, len(options)))
            target = _target(subset)
            if target is None:
                continue
            criteria = {f"a{i}": o["text"] for i, o in enumerate(subset)}
            question = {"type": "choice", "instructions": INSTRUCTIONS, "criteria": criteria}
            out.append((row["state"], question, dict(zip(criteria, target)), subset))
    return out


def regret(choice, subset):
    best = max((o["objective"] for o in subset if o["valid"] and o["objective"] is not None), default=None)
    picked = subset[choice]
    if best is None:
        return None
    value = picked["objective"] if picked["valid"] and picked["objective"] is not None else best - 20.0
    return best - value


def score_policies(test, model=None):
    """Mean regret and best-pick rate of each policy on held-out questions."""
    policies = {"random": [], "knowledge_prior": []}
    if model is not None:
        policies["laya"] = []
    rng = random.Random(1)
    for state, question, target, subset in test:
        policies["random"].append(regret(rng.randrange(len(subset)), subset))
        prior = max(range(len(subset)), key=lambda i: subset[i]["prior"])
        policies["knowledge_prior"].append(regret(prior, subset))
        if model is not None:
            answer, _ = model._predict(state, {"action": question})
            probabilities = answer["action"]["probabilities"]
            policies["laya"].append(regret(int(max(probabilities, key=probabilities.get)[1:]), subset))
    summary = {}
    for name, values in policies.items():
        values = [v for v in values if v is not None]
        summary[name] = {"questions": len(values), "mean_regret": sum(values) / max(1, len(values)),
                         "best_pick_rate": sum(v <= 1e-9 for v in values) / max(1, len(values))}
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("collect")
    p.add_argument("designs", type=Path, help="text file: one result.json(.gz) path per line")
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--parallel", type=int, default=8)
    p = sub.add_parser("rebuild")
    p.add_argument("designs", type=Path)
    p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("train")
    p.add_argument("rows", type=Path, nargs="+")
    p.add_argument("--holdout", nargs="+", required=True, help="topology families kept out of training")
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--epochs", type=int, default=4)
    p.add_argument("--device", default="cuda")
    args = parser.parse_args()
    if args.command in ("collect", "rebuild"):
        paths = [line.strip() for line in args.designs.read_text().splitlines() if line.strip()]
        if args.command == "collect":
            collect(paths, args.output, args.parallel)
        else:
            rows = rebuild(paths, args.output)
            print(f"{len(rows)} rows from measured evidence")
        return
    rows = [json.loads(line) for path in args.rows for line in path.read_text().splitlines() if line]
    train_rows = [r for r in rows if r["family"] not in args.holdout]
    test_rows = [r for r in rows if r["family"] in args.holdout]
    if not train_rows or not test_rows:
        raise ValueError("Both training and held-out families need rows")
    train_set, test_set = examples(train_rows, seed=0), examples(test_rows, seed=1)
    from ..paths import ROOT
    from .finetune import train as fit
    from .typed import TypedDecisions

    baseline = score_policies(test_set, TypedDecisions(device=args.device))
    # The weights the loop runs today (fine-tuned on circuit-topology decisions only).
    topology_weights = score_policies(
        test_set, TypedDecisions(weights=ROOT / "experiments/ptm45/typed-decisions.pt", device=args.device))
    summary = fit({"summary": {"source": "layout self-play (measured outcomes)",
                               "rows": len(train_rows), "holdout_families": args.holdout}},
                  args.output, epochs=args.epochs, device=args.device,
                  examples=[e[:3] for e in train_set])
    after = score_policies(test_set, TypedDecisions(weights=args.output / "typed-decisions.pt",
                                                    device=args.device))
    report = {"train_questions": len(train_set), "test_questions": len(test_set),
              "train_families": sorted({r["family"] for r in train_rows}),
              "holdout_families": args.holdout, "base_laya": baseline,
              "topology_weights_laya": topology_weights, "after_finetune": after,
              "training": summary}
    (args.output / "heldout.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
