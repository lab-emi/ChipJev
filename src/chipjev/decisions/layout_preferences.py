"""Reviewable expert preferences; unlabeled traces are never called expert data."""

import argparse
import hashlib
import json
from itertools import combinations
from pathlib import Path


def export(directory, output, family):
    directory = Path(directory)
    physical = json.loads((directory / "physical.json").read_text())
    trace = physical["optimization"]
    valid = [h for h in trace["history"] if h["valid"]]
    rows = []
    for a, b in combinations(valid, 2):
        if a["plan"] == b["plan"]:
            continue
        rows.append(
            {
                "schema": "chipjev-layout-review-v1",
                "family": family,
                "design_identity": trace["identity_sha256"],
                "goal": trace["goal"],
                "fixed_input_bias_v": trace["fixed_input_bias_v"],
                "candidates": {"a0": a, "a1": b},
                "preferred": None,
                "reviewer": None,
                "reason": None,
                "label_source": "unreviewed",
                "evidence_sha256": hashlib.sha256(
                    (directory / "optimization.json").read_bytes()
                ).hexdigest(),
            }
        )
    Path(output).write_text("".join(json.dumps(r, allow_nan=False) + "\n" for r in rows))
    return len(rows)


def examples(paths, holdout_families):
    """Split entire topology families, never near-duplicate plans, across sets."""
    train, test = [], []
    seen = {}
    for path in paths:
        for line in Path(path).read_text().splitlines():
            r = json.loads(line)
            if (
                r.get("label_source") != "expert"
                or r.get("preferred") not in ("a0", "a1")
                or not r.get("reviewer")
                or not r.get("reason")
            ):
                raise ValueError(
                    "Expert labels require an explicit preference, reviewer and reason"
                )
            if len(r["candidates"]) != 2 or not all(c["valid"] for c in r["candidates"].values()):
                raise ValueError("Taste comparisons require two fully qualified candidates")
            identity = r["design_identity"]
            if identity in seen and seen[identity] != r["family"]:
                raise ValueError("A design identity cannot cross family partitions")
            seen[identity] = r["family"]
            state = json.dumps(
                {"goal": r["goal"], "fixed_input_bias_v": r["fixed_input_bias_v"]}, sort_keys=True
            )
            question = {
                "type": "choice",
                "instructions": "Choose the professional analog layout that best satisfies the goal.",
                "criteria": {
                    k: json.dumps(c["plan"], sort_keys=True) for k, c in r["candidates"].items()
                },
            }
            target = {k: float(k == r["preferred"]) for k in r["candidates"]}
            (test if r["family"] in holdout_families else train).append((state, question, target))
    return train, test


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("export")
    p.add_argument("directory", type=Path)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--family", required=True)
    p = sub.add_parser("train")
    p.add_argument("reviews", type=Path, nargs="+")
    p.add_argument("--holdout-family", nargs="+", required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--epochs", type=int, default=3)
    p.add_argument("--device", default="cuda", choices=("cuda", "cpu"))
    args = parser.parse_args()
    if args.command == "export":
        print(export(args.directory, args.output, args.family))
        return
    train, test = examples(args.reviews, set(args.holdout_family))
    if not train or not test:
        raise ValueError("Both training and held-out families need reviewed examples")
    from .finetune import train as fit
    from .typed import TypedDecisions

    metadata = {
        "source": "explicit expert reviews",
        "holdout_families": args.holdout_family,
        "files": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in args.reviews},
    }
    fit({"summary": metadata}, args.output, epochs=args.epochs, device=args.device, examples=train)
    model = TypedDecisions(weights=args.output / "typed-decisions.pt", device=args.device)
    correct = 0
    for state, question, target in test:
        answer, _ = model._predict(state, {"layout": question})
        correct += bool(target[answer["layout"]["choice"]])
    (args.output / "heldout.json").write_text(
        json.dumps(
            {
                "examples": len(test),
                "accuracy": correct / len(test),
                "families": args.holdout_family,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
