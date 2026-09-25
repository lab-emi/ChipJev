"""Re-simulate every design behind the paper's numbers and compare it with the archives.

The searches ran on a GPU and are not bit-reproducible under a seed, but every design they
delivered is archived with its sizes, and ngspice is deterministic. This script measures,
with the package (chipjev.simulation), the verified best design of every run of the four
reported stages (PTM 45 nm main and ablation, SKY130, System Two) on the strict testbench,
and repeats the corner and mismatch checks of the robustness stage for every delivered
grammar design. Each result must equal the archived one: validity, every metric, the
objective and the reported value, and every corner and mismatch sample. AnalogCoder-Pro's
own netlists are not re-simulated here.

  .venv/bin/python reproduce/resimulate.py [--workers N] [--no-robustness]

Numbers must agree to a relative 1e-6: on the study host they are identical; another CPU or
compiler can change the last digits of an ngspice result. About half a minute on the study
host (Ryzen 9 7950X).
"""

import argparse
import gzip
import json
import math
import multiprocessing
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PTM45 = ROOT / "experiments/ptm45/results"
SKY130 = ROOT / "experiments/sky130-system-two/results"
# (label, stage directory): every archived run of the stages the paper reports.
STAGES = (
    ("PTM 45 nm main (Table I, Fig. 2)", PTM45 / "main"),
    ("PTM 45 nm ablation", PTM45 / "ablation"),
    ("SKY130 (Table III)", SKY130 / "sky130"),
    ("System Two (Table II)", SKY130 / "system2"),
)
RTOL = 1e-6


def design_jobs(stages=STAGES, limit=None):
    """One job per verified run (at most `limit` runs per stage): the archived best design and
    the conditions it ran at."""
    jobs = []
    for label, stage in stages:
        rows = [json.loads(line) for path in sorted(stage.glob("results*.jsonl"))
                for line in path.read_text().splitlines() if line.strip()]
        for row in rows[:limit]:
            record = json.load(gzip.open(stage / "runs" / row["run_file"], "rt"))
            if record["best"] is None:
                continue
            jobs.append({"kind": "design", "stage": label, "run": row["run_file"],
                         "technology": record.get("technology") or "ptm45",
                         "corner": record.get("corner") or "tt", "cls": record["cls"],
                         "target": record["target"], "vdd": record["vdd"],
                         "load_pf": record["load_pf"], "rules": record["rules"],
                         "best": record["best"]})
    return jobs


def robustness_jobs(limit=None):
    """The robustness stage's corner and mismatch checks of the delivered grammar designs."""
    jobs = []
    for line in (PTM45 / "robustness/results.jsonl").read_text().splitlines()[:limit]:
        row = json.loads(line)
        if row["source"] != "main":
            continue  # AnalogCoder-Pro's netlists
        record = json.load(gzip.open(PTM45 / "main/runs" / row["key"], "rt"))
        jobs.append({"kind": "robustness", "stage": "PTM 45 nm robustness", "run": row["key"],
                     "cls": record["cls"], "target": record["target"], "vdd": record["vdd"],
                     "load_pf": record["load_pf"], "best": record["best"], "archived": row})
    return jobs


def run(job):
    """Measure one job with the package; returns (job, differences, largest relative gap)."""
    from chipjev.circuits.published import lookup
    from chipjev.simulation.analysis import objective, reported

    topology = lookup(job["cls"], job["best"]["topology"])
    values = job["best"]["values"]
    if job["kind"] == "robustness":
        from chipjev.simulation.robustness import check

        archived = job["archived"]
        fresh = check(topology, values, target=job["target"], vdd=job["vdd"],
                      load_pf=job["load_pf"], seed=archived["mc_seed"])
        expected = {k: archived[k] for k in fresh}
        return job, *compare(expected, fresh)
    if job["technology"] == "sky130":
        from chipjev.simulation.sky130 import evaluate

        record = evaluate(topology, values, strict=True, load_pf=job["load_pf"],
                          vdd=job["vdd"], rules=job["rules"], corner=job["corner"])
    else:
        from chipjev.simulation.ptm45 import evaluate

        record = evaluate(topology, values, strict=True, load_pf=job["load_pf"],
                          vdd=job["vdd"], rules=job["rules"])
    best = job["best"]
    fresh = {"valid": record["valid"], "metrics": record["metrics"],
             "objective": objective(record, job["target"]),
             "reported": reported(record, job["target"])}
    expected = {"valid": True, "metrics": best["metrics"], "objective": best["objective"],
                "reported": best["reported"]}
    return job, *compare(expected, fresh)


def compare(expected, actual, path=""):
    """Differences between two JSON values (floats to RTOL) and the largest relative gap."""
    if isinstance(expected, dict) and isinstance(actual, dict):
        differences, gap = [], 0.0
        for key in sorted(set(expected) | set(actual)):
            if key not in expected or key not in actual:
                differences.append(f"{path}{key}: only in {'archive' if key in expected else 'rerun'}")
                continue
            d, g = compare(expected[key], actual[key], f"{path}{key}.")
            differences += d
            gap = max(gap, g)
        return differences, gap
    if isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            return [f"{path[:-1]}: {len(expected)} archived, {len(actual)} measured"], 0.0
        differences, gap = [], 0.0
        for i, (e, a) in enumerate(zip(expected, actual, strict=True)):
            d, g = compare(e, a, f"{path}{i}.")
            differences += d
            gap = max(gap, g)
        return differences, gap
    numbers = (int, float)
    if (isinstance(expected, numbers) and isinstance(actual, numbers)
            and not isinstance(expected, bool) and not isinstance(actual, bool)):
        if expected == actual:
            return [], 0.0
        gap = abs(expected - actual) / max(abs(expected), abs(actual))
        if math.isfinite(gap) and gap <= RTOL:
            return [], gap
        return [f"{path[:-1]}: archived {expected!r}, measured {actual!r}"], gap
    if expected == actual:
        return [], 0.0
    return [f"{path[:-1]}: archived {expected!r}, measured {actual!r}"], 0.0


def _worker_init():
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[name] = "1"


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workers", type=int, default=os.cpu_count(),
                        help="ngspice processes (default: every CPU)")
    parser.add_argument("--no-robustness", action="store_true",
                        help="skip the corner and mismatch checks (the longest part)")
    args = parser.parse_args()

    jobs = [] if args.no_robustness else robustness_jobs()  # longest first
    jobs += design_jobs()
    start = time.perf_counter()
    totals, failures = {}, []
    context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(args.workers, mp_context=context, initializer=_worker_init) as pool:
        for future in as_completed([pool.submit(run, job) for job in jobs]):
            job, differences, gap = future.result()
            total = totals.setdefault(job["stage"], {"designs": 0, "identical": 0, "gap": 0.0})
            total["designs"] += 1
            total["identical"] += not differences and gap == 0.0
            total["gap"] = max(total["gap"], gap)
            if differences:
                failures.append(f"{job['stage']}: {job['run']}: " + "; ".join(differences[:3]))
    order = [label for label, _ in STAGES] + ["PTM 45 nm robustness"]
    for label in sorted(totals, key=order.index):
        t = totals[label]
        unit = "designs at 4 corners and 64 mismatch samples" if "robustness" in label else "designs"
        gap = "" if t["identical"] == t["designs"] else f", largest relative gap {t['gap']:.1e}"
        print(f"{label}: {t['designs']} {unit}; {t['identical']} identical{gap}")
    print(f"{len(jobs)} jobs in {time.perf_counter() - start:.0f} s with {args.workers} processes")
    if failures:
        print("\n".join("FAIL " + f for f in failures[:20]))
        print(f"{len(failures)} designs differ from the archives.")
        sys.exit(1)
    print("Every archived design re-simulates to its archived results.")


if __name__ == "__main__":
    main()
