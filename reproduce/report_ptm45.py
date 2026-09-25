"""Report of the PTM 45 nm study (protocol topo-v3): Table I, Fig. 2, the paper's Ptm*
macros, report/summary.json and report/RESULTS.md, from the archived evidence.

  .venv/bin/python reproduce/report_ptm45.py        # from experiments/ptm45/results
  .venv/bin/python reproduce/report_ptm45.py --study DIR [--runs DIR] [--llm DIR] [--paper DIR]

--study is a study directory in the layout of experiments/ptm45 (protocol.json, the typed,
latency and corner-selection records, results/); --runs and --llm default to its archived
runs and AnalogCoder-Pro flow. Refuses missing or duplicate runs of the frozen job list
(unless --preview, which writes only to runs/preview/ptm45). Secondary endpoints follow the
study's PROTOCOL.md.
"""

import argparse
import gzip
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "experiments/ptm45"
PAPER = ROOT / "runs/reports"
CLASSES = ("amp1", "opamp1", "ampN", "opampN")
TARGETS = ("gain", "gbw", "fom")
NAMES = {"amp1": "1-stage amp", "opamp1": "1-stage op-amp", "ampN": "Multi-stage amp",
         "opampN": "Multi-stage op-amp"}
METHODS = ("chipjev", "chipjev-v2", "tpe8", "random8")
ACPRO_TASK = {
    ("amp1", "gain"): 51, ("opamp1", "gain"): 52, ("ampN", "gain"): 53, ("opampN", "gain"): 54,
    ("amp1", "gbw"): 55, ("opamp1", "gbw"): 56, ("ampN", "gbw"): 57, ("opampN", "gbw"): 58,
    ("amp1", "fom"): 59, ("opamp1", "fom"): 60, ("ampN", "fom"): 61, ("opampN", "fom"): 62,
}
LLM_DIR = ARCHIVE / "results/acpro-llm/deepseek-deepseek-chat-v3-0324"
BOOTSTRAP = 10000
TIE = {"gain": 0.5, "gbw": math.log10(1.05), "fom": math.log10(1.05)}
COLORS = {"chipjev": "#005CB8", "tpe8": "#BD2727", "random8": "#626262", "acpro": "#C55A11",
          "chipjev-v2": "#7F9CC7"}


# ---------------------------------------------------------------------------- utilities


def number(value, gain=False):
    if value is None or not np.isfinite(value):
        return "--"
    if gain:
        return f"{value:.1f}"
    if abs(value) >= 1e6:
        return f"{value / 1e6:.3g}M"
    if abs(value) >= 1e4:
        return f"{value / 1e3:.3g}k"
    if abs(value) >= 1e3:
        return f"{value:.0f}"
    return f"{value:.3g}"


def duration(value, space="~"):
    if value is None or not np.isfinite(value):
        return "--"
    if value >= 3600:
        return f"{value / 3600:.1f}{space}h"
    if value >= 100:
        return f"{value / 60:.0f}{space}min"
    if value >= 10:
        return f"{value:.0f}{space}s"
    return f"{value:.2g}{space}s" if value < 1 else f"{value:.1f}{space}s"


def ratio(value):
    if value is None or not np.isfinite(value):
        return "--"
    return f"{value:.0f}" if value >= 20 else f"{value:.1f}"


def quantile(values, p):
    """Linear-interpolation quantile; infinities rank as extremes."""
    values = sorted(values)
    if not values:
        return None
    i = p * (len(values) - 1)
    low, high = values[math.floor(i)], values[math.ceil(i)]
    if low == high:
        return low
    if not np.isfinite(low) or not np.isfinite(high):
        return None
    return low + (high - low) * (i - math.floor(i))


def to_reported(objective, target):
    if objective is None or not np.isfinite(objective):
        return None
    return objective if target == "gain" else 10 ** objective


def clean(value):
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, (np.floating, np.integer)):
        return clean(value.item())
    return value


# ---------------------------------------------------------------------------- loading


def load_search(runs_dir, stage, jobs, preview):
    path = runs_dir / stage / "results.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    keys = [(r["task"], r["method"], r["seed"]) for r in rows]
    if len(keys) != len(set(keys)):
        raise ValueError(f"duplicate runs in {stage}")
    expected = {(t["id"], m, s) for t, m, s in jobs}
    if set(keys) - expected:
        raise ValueError(f"unexpected runs in {stage}")
    missing = sorted(expected - set(keys))
    if missing and not preview:
        raise ValueError(f"{len(missing)} missing runs in {stage}; no paper output written")
    for row in rows:
        raw = json.load(gzip.open(runs_dir / stage / "runs" / row["run_file"], "rt"))
        if raw["evaluations"] != 1024:
            raise ValueError(f"wrong budget: {row['run_file']}")
        if raw["verified"] != bool(raw["best"]):
            raise ValueError(f"inconsistent incumbent: {row['run_file']}")
        if raw["verified"] != row["verified"]:
            raise ValueError(f"journal and raw disagree: {row['run_file']}")
        if row["cls"].startswith("opamp") and raw["best"]:
            if not raw["best"]["qualification"]["passed"]:
                raise ValueError(f"unqualified reported op-amp: {row['run_file']}")
        offset = row.get("typed_seconds") or 0.0
        row["time"] = raw["wall_seconds"] + offset
        row["events"] = incumbent_events(raw, offset)
        row["metrics"] = (raw.get("best") or {}).get("metrics")
        row["typed_ms"] = 1000 * offset if row.get("typed_seconds") is not None else None
        row["timing"] = raw.get("timing")
    return rows, missing


def incumbent_events(raw, offset=0.0):
    """(elapsed seconds, online evaluations, best strictly qualified objective) whenever the
    incumbent improves: strict records (ChipJev) or the tracker trajectory (baselines)."""
    events, best = [], -np.inf
    if "rounds" in raw:
        batch = raw["settings"]["batch"]
        for r in sorted(raw["strict"], key=lambda r: r["elapsed_seconds"]):
            if r["valid"] and r["objective"] is not None and r["objective"] > best:
                best = r["objective"]
                events.append((r["elapsed_seconds"] + offset, batch * (r["round"] + 1), best))
    else:
        for count, at, value in raw["trajectory"]:
            if value is not None and value > best:
                best = value
                events.append((at + offset, count, best))
    return events


def load_llm(preview, llm_dir=None):
    """AnalogCoder-Pro attempts from the run directory or its archive (helpers.jsonl.gz)."""
    global LLM_DIR
    if llm_dir is not None:
        LLM_DIR = Path(llm_dir)
    path = LLM_DIR / "results.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    keys = [(r["task_id"], r["attempt"]) for r in rows]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate LLM attempts")
    expected = {(t, a) for t in range(51, 63) for a in range(30)}
    missing = sorted(expected - set(keys))
    if missing and not preview:
        raise ValueError(f"{len(missing)} missing LLM attempts")
    archived = LLM_DIR / "helpers.jsonl.gz"
    if archived.exists():
        with gzip.open(archived, "rt") as stream:
            helpers = {(h["task_id"], h["attempt"]): h["helper"] for h in map(json.loads, stream)}
        for row in rows:
            row["helper"] = helpers.get((row["task_id"], row["attempt"]))
        return rows, missing
    for row in rows:
        row["helper"] = None
        # Run layout (no helpers.jsonl.gz yet): workdir is relative to the repository root of
        # the run, the tree that holds the study directory (ARCHIVE = <root>/experiments/<study>).
        found = sorted((ARCHIVE.parents[1] / row["workdir"]).glob("*/p*/0/*.result.json"))
        if found:
            row["helper"] = json.loads(found[0].read_text())
    return rows, missing


# ---------------------------------------------------------------------------- statistics


def summarize(rows):
    values = [r["best"] if r["verified"] else -np.inf for r in rows]
    return {
        "n": len(rows),
        "success": sum(r["verified"] for r in rows),
        "median": quantile(values, 0.5),
        "q1": quantile(values, 0.25),
        "q3": quantile(values, 0.75),
        "time": quantile([r["time"] for r in rows], 0.5),
        "first": quantile([r["first_seconds"] if r["verified"] else np.inf for r in rows], 0.5),
    }


def compare(ours, baseline, target):
    if ours is None or not np.isfinite(ours):
        return "both_failed" if baseline is None or not np.isfinite(baseline) else "loss"
    if baseline is None or not np.isfinite(baseline):
        return "feasibility_win"
    delta = ours - baseline if target == "gain" else math.log(ours / baseline)
    tolerance = 0.5 if target == "gain" else math.log(1.05)
    return "tie" if abs(delta) <= tolerance else "numeric_win" if delta > 0 else "loss"


def reference(rows, target):
    """The task reference: the failure-aware median final objective of `rows` lowered by the
    tie band; None when that median is unqualified (then any qualified design counts)."""
    objectives = [(r["best"] if target == "gain" else math.log10(r["best"])) if r["verified"]
                  else -np.inf for r in rows]
    center = quantile(objectives, 0.5)
    if center is None or not np.isfinite(center):
        return None
    return center - TIE[target]


def reach(events, threshold):
    for at, count, value in events:
        if threshold is None or value >= threshold - 1e-12:
            return at, count
    return np.inf, np.inf


def speedups(groups, method="chipjev", baseline="tpe8", field=0, seed=20270925):
    """Per-task ratio of the baseline's median to the method's median time (field 0) or
    evaluations (field 1) to the baseline's reference; geometric mean over tasks where both
    medians are finite, with a percentile bootstrap over seeds within tasks."""
    rng = np.random.default_rng(seed)
    per_task, samples = {}, []
    for cls in CLASSES:
        for target in TARGETS:
            task = f"{cls}-{target}"
            ref = reference(groups[(task, "tpe8")], target)
            ours = np.array([reach(r["events"], ref)[field] for r in groups[(task, method)]])
            base = np.array([reach(r["events"], ref)[field] for r in groups[(task, baseline)]])
            per_task[task] = {"reference": ref, "ours": ours.tolist(), "baseline": base.tolist(),
                              "ours_median": float(np.median(ours)),
                              "baseline_median": float(np.median(base)),
                              "ratio": float(np.median(base) / np.median(ours))
                              if np.isfinite(np.median(ours)) and np.isfinite(np.median(base))
                              else None}
            samples.append((task, ours, base))
    finite = [(t, o, b) for t, o, b in samples
              if np.isfinite(np.median(o)) and np.isfinite(np.median(b))]

    def gmean(pairs):
        logs = [math.log(np.median(b) / np.median(o)) for _, o, b in pairs]
        return math.exp(sum(logs) / len(logs)) if logs else float("nan")

    boot = []
    for _ in range(BOOTSTRAP):
        drawn = []
        for t, o, b in finite:
            oo = rng.choice(o, size=len(o), replace=True)
            bb = rng.choice(b, size=len(b), replace=True)
            if np.isfinite(np.median(oo)) and np.isfinite(np.median(bb)):
                drawn.append((t, oo, bb))
        if drawn:
            boot.append(gmean(drawn))
    low, high = (np.quantile(boot, [0.025, 0.975]).tolist() if boot else (None, None))
    only_ours = [t for t, o, b in samples
                 if np.isfinite(np.median(o)) and not np.isfinite(np.median(b))]
    only_base = [t for t, o, b in samples
                 if not np.isfinite(np.median(o)) and np.isfinite(np.median(b))]
    return {"geomean": gmean(finite), "ci": [low, high], "tasks": [t for t, _, _ in finite],
            "only_ours": only_ours, "only_baseline": only_base, "per_task": per_task}


# ---------------------------------------------------------------------------- LLM flow


def llm_summary(llm_rows, groups):
    """Per task: AnalogCoder-Pro attempts in index order, functional netlists (its checks),
    qualified designs, best of 30, protocol time and the time to the tpe8 reference."""
    out = {}
    for (cls, target), task_id in ACPRO_TASK.items():
        task = f"{cls}-{target}"
        attempts = sorted((r for r in llm_rows if r["task_id"] == task_id),
                          key=lambda r: r["attempt"])
        ref = reference(groups[(task, "tpe8")], target) if groups.get((task, "tpe8")) else None
        elapsed, first_q, first_ref, best, qualified = 0.0, None, None, None, 0
        for row in attempts:
            helper = row.get("helper") or {}
            b = helper.get("best")
            offset = row["wall_seconds"] - (helper.get("wall_seconds") or 0.0)
            if b:
                qualified += 1
                best = b["objective"] if best is None else max(best, b["objective"])
                first = (helper.get("first_verified") or {}).get("seconds")
                if first_q is None and first is not None:
                    first_q = elapsed + offset + first
                if first_ref is None:
                    for _, at, value in helper.get("trajectory") or []:
                        if value is not None and (ref is None or value >= ref - 1e-12):
                            first_ref = elapsed + offset + at
                            break
            elapsed += row["wall_seconds"]
        out[task] = {
            "attempts": len(attempts),
            "functional": sum(r["functional_netlist"] for r in attempts),
            "first_round": sum(1 for r in attempts
                               if r["functional_netlist"] and r["feedback_rounds"] == 1),
            "sized": sum(bool(r.get("helper")) for r in attempts),
            "qualified": qualified,
            "best": to_reported(best, target),
            "protocol_seconds": elapsed,
            "first_qualified_seconds": first_q,
            "reference_seconds": first_ref,
            "llm_seconds": sum(r["llm_seconds"] for r in attempts),
            "llm_calls": sum(r["llm_calls"] for r in attempts),
            "llm_errors": sum(r["llm_errors"] for r in attempts),
            "tokens": sum(r["prompt_tokens"] + r["completion_tokens"] for r in attempts),
            "cost_usd": sum(r["cost_usd"] for r in attempts),
            "sizing_seconds": sum(((r.get("helper") or {}).get("wall_seconds") or 0.0)
                                  for r in attempts),
            "median_attempt_seconds": quantile([r["wall_seconds"] for r in attempts], 0.5),
            "timeouts": sum(r["status"] == "timeout" for r in attempts),
        }
    return out


def beat_llm(groups, llm_rows):
    """Descriptive (not preregistered): on the tasks where AnalogCoder-Pro qualified a design,
    ChipJev's time to match its best-of-30 quality versus the protocol time at which
    AnalogCoder-Pro first reached that best."""
    out = {}
    for (cls, target), task_id in ACPRO_TASK.items():
        events, _ = llm_events(llm_rows, task_id)
        if not events:
            continue
        best = events[-1][1]
        reached = next(t for t, v in events if v >= best - 1e-12)
        task = f"{cls}-{target}"
        times = [reach(r["events"], best)[0] for r in groups[(task, "chipjev")]]
        out[task] = {"acpro_best": to_reported(best, target), "acpro_seconds": reached,
                     "chipjev_seconds": times, "chipjev_median": float(np.median(times)),
                     "ratio": reached / float(np.median(times))}
    ratios = [v["ratio"] for v in out.values() if np.isfinite(v["ratio"])]
    gmean = math.exp(sum(math.log(r) for r in ratios) / len(ratios)) if ratios else None
    return {"tasks": out, "geomean": gmean,
            "all_runs_reached": all(np.isfinite(t) for v in out.values()
                                    for t in v["chipjev_seconds"]),
            "slowest_chipjev": max((t for v in out.values() for t in v["chipjev_seconds"]),
                                   default=None)}


def second_llm(path):
    """Supplementary AnalogCoder-Pro check with another LLM (added after the freeze).

    Released: the flow as released. Lenient: attempts whose released extraction kept only an
    incomplete last code block, rerun with all blocks joined (frozen code: scripts/acpro-lenient.py)."""
    journal = Path(path) / "results.jsonl"
    if not journal.exists():
        return None
    rows = [json.loads(line) for line in journal.read_text().splitlines()]
    extra = Path(path) / "lenient/results.jsonl"
    lenient = [json.loads(line) for line in extra.read_text().splitlines()] if extra.exists() else []
    qualified = [r["task_id"] for r in rows if (r.get("sizing") or {}).get("best")]
    rescued = [r["task_id"] for r in lenient if r.get("verified")]
    joined = qualified + rescued
    return {
        "attempts": len(rows),
        "functional": sum(r["functional_netlist"] for r in rows),
        "unusable": sum(1 for r in rows
                        if (r.get("sizing") or {}).get("status") == "unusable-code"),
        "multiblock": sum(1 for r in lenient if (r.get("blocks") or 0) > 1),
        "qualified": len(qualified),
        "tasks": sorted(set(qualified)),
        "opamps": sum(1 for t in qualified if (t - 51) % 2 == 1),
        "lenient_qualified": len(joined),
        "lenient_tasks": sorted(set(joined)),
        "lenient_opamps": sum(1 for t in joined if (t - 51) % 2 == 1),
        "median_attempt_seconds": quantile([r["wall_seconds"] for r in rows], 0.5),
        "llm_share": sum(r["llm_seconds"] for r in rows) / max(1e-9, sum(
            r["wall_seconds"] for r in rows)),
        "cost_usd": sum(r["cost_usd"] for r in rows),
    }


# ---------------------------------------------------------------------------- tables


def versus(ours, theirs, gain):
    """ChipJev's median against AnalogCoder-Pro's best design: dB more gain or a ratio; feas.
    when only ChipJev qualifies."""
    if ours is None or not np.isfinite(ours):
        return "--"
    if theirs is None:
        return "feas."
    if gain:
        return f"{ours - theirs:+.0f} dB"
    return ratio(ours / theirs) + r"$\times$"


def main_table(groups, llm, speed):
    """Per-task results; ChipJev's columns are shaded."""
    shade = r">{\columncolor{paperpale}}"
    lines = [
        r"\begin{tabular}{ll" + shade + "r" + shade + "c" + shade + "r" + shade + "r"
        + r" rcr rc rcr" + shade + "r}",
        r"\toprule",
        r"& & \multicolumn{4}{c}{\cellcolor{paperpale}\textbf{ChipJev (this work)}}"
        r" & \multicolumn{3}{c}{Joint TPE, 8 workers} & \multicolumn{2}{c}{Random, 8 w.}"
        r" & \multicolumn{3}{c}{AnalogCoder-Pro flow} & \cellcolor{paperpale}\textbf{ChipJev} \\",
        r"\cmidrule(lr){3-6}\cmidrule(lr){7-9}\cmidrule(lr){10-11}\cmidrule(lr){12-14}",
        r"Class & Target & \cellcolor{paperpale}Median [Q1, Q3] & \cellcolor{paperpale}Pass"
        r" & \cellcolor{paperpale}Time & \cellcolor{paperpale}Speedup"
        r" & Median & Pass & Time & Median & Pass & Best of 30 & Qual. & Time"
        r" & \cellcolor{paperpale}vs. best \\",
        r"\midrule",
    ]
    for cls in CLASSES:
        for index, target in enumerate(TARGETS):
            task = f"{cls}-{target}"
            gain = target == "gain"
            s = {m: summarize(groups.get((task, m), [])) for m in ("chipjev", "tpe8", "random8")}
            a = llm.get(task, {})
            values = [s[m]["median"] for m in s] + [a.get("best")]
            highest = max((v for v in values if v is not None and np.isfinite(v)), default=None)

            def fmt(v):
                text = number(v, gain)
                if v is not None and highest is not None and np.isfinite(v) and v == highest:
                    text = r"\textbf{" + text + "}"
                return text

            c = s["chipjev"]
            chip = f"{fmt(c['median'])} [{number(c['q1'], gain)}, {number(c['q3'], gain)}]"
            if all(x is None or not np.isfinite(x) for x in (c["median"], c["q1"], c["q3"])):
                chip = "--"
            data = speed["per_task"][task]
            if data["ratio"] is not None:
                sp = ratio(data["ratio"]) + r"$\times$"
            elif np.isfinite(data["ours_median"]):
                sp = "feas."
            else:
                sp = "--"
            cells = [
                NAMES[cls] if index == 0 else "",
                {"gain": "Gain (dB)", "gbw": "GBW (MHz)", "fom": "FoM"}[target],
                chip, f"{c['success']}/{c['n']}", duration(c["time"], " ").replace(" s", ""),
                sp,
                fmt(s["tpe8"]["median"]), f"{s['tpe8']['success']}/{s['tpe8']['n']}",
                duration(s["tpe8"]["time"], " ").replace(" s", ""),
                fmt(s["random8"]["median"]), f"{s['random8']['success']}/{s['random8']['n']}",
                fmt(a.get("best")), f"{a.get('qualified', 0)}/{a.get('attempts', 0)}",
                f"{a['protocol_seconds'] / 3600:.1f} h" if a.get("protocol_seconds") else "--",
                versus(c["median"], a.get("best"), gain),
            ]
            lines.append(" & ".join(cells) + r" \\")
        if cls != CLASSES[-1]:
            lines.append(r"\midrule")
    return "\n".join(lines + [r"\bottomrule", r"\end{tabular}"]) + "\n"


def figure_style():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({
        "font.family": "Verdana", "font.size": 7.0, "axes.titlesize": 7.4,
        "axes.labelsize": 7.0, "xtick.labelsize": 6.4, "ytick.labelsize": 6.6,
        "legend.fontsize": 6.4, "pdf.fonttype": 42, "ps.fonttype": 42,
        "axes.linewidth": 0.6, "lines.linewidth": 1.1, "xtick.direction": "in",
        "ytick.direction": "in",
    })
    return plt


def llm_events(llm_rows, task_id):
    """AnalogCoder-Pro's best qualified objective over its protocol time (attempt order)."""
    events, elapsed, best = [], 0.0, -np.inf
    for row in sorted((r for r in llm_rows if r["task_id"] == task_id), key=lambda r: r["attempt"]):
        helper = row.get("helper") or {}
        offset = row["wall_seconds"] - (helper.get("wall_seconds") or 0.0)
        if helper.get("best"):
            for _, at, value in helper.get("trajectory") or []:
                if value is not None and value > best:
                    best = value
                    events.append((elapsed + offset + at, best))
        elapsed += row["wall_seconds"]
    return events, elapsed


def anytime_figure(groups, llm_rows, out):
    """Best qualified FoM versus elapsed time (log-log): medians and IQRs over five seeds
    for ChipJev and joint TPE, the random-search median, and AnalogCoder-Pro's protocol."""
    from matplotlib.lines import Line2D
    from matplotlib.ticker import FuncFormatter, LogLocator, NullLocator

    plt = figure_style()
    fig, axes = plt.subplots(1, 4, figsize=(7.16, 1.2))
    for ax, cls in zip(axes, CLASSES, strict=True):
        task = f"{cls}-fom"
        acpro, total = llm_events(llm_rows, ACPRO_TASK[(cls, "fom")])
        end = max([total] + [r["time"] for m in METHODS for r in groups.get((task, m), [])])
        grid = np.geomspace(0.05, end * 1.05, 400)
        extent = []
        for method, style in (("chipjev", "-"), ("tpe8", "--"), ("random8", ":")):
            rows = groups.get((task, method), [])
            if not rows:
                continue
            curves = []
            for r in rows:
                ev = np.array([(t, 10 ** v) for t, _, v in r["events"]]) if r["events"] else None
                if ev is None:
                    curves.append(np.full(len(grid), np.nan))
                    continue
                k = np.searchsorted(ev[:, 0], grid, side="right") - 1
                c = np.where(k >= 0, ev[np.maximum(k, 0), 1], np.nan)
                c[grid > r["time"]] = c[grid <= r["time"]][-1] if (grid <= r["time"]).any() else np.nan
                curves.append(c)
            data = np.array(curves)
            filled = np.where(np.isnan(data), -np.inf, data)
            q1, center, q3 = np.quantile(filled, [0.25, 0.5, 0.75], axis=0, method="nearest")
            finish = max(r["time"] for r in rows)
            mask = np.isfinite(center) & (grid <= finish)
            ax.plot(grid[mask], center[mask], color=COLORS[method], ls=style, zorder=3)
            extent += center[mask].tolist()
            if method != "random8":
                band = mask & np.isfinite(q1) & np.isfinite(q3)
                ax.fill_between(grid, q1, q3, where=band, color=COLORS[method], alpha=0.13, lw=0)
        notes = []
        for method, label in (("chipjev", "ChipJev"), ("tpe8", "TPE"), ("random8", "Random")):
            rows = groups.get((task, method), [])
            done = sum(r["verified"] for r in rows)
            if rows and done < 3:
                notes.append(f"{label}: {done}/{len(rows)}")
        if acpro:
            ev = np.array([(t, 10 ** v) for t, v in acpro])
            ax.step(np.append(ev[:, 0], total), np.append(ev[:, 1], ev[-1, 1]), where="post",
                    color=COLORS["acpro"], lw=1.1, zorder=3)
            ax.plot(total, ev[-1, 1], marker="D", ms=2.8, color=COLORS["acpro"])
            extent += ev[:, 1].tolist()
        else:
            notes.append("AnalogCoder-Pro: 0/30")
        if notes:
            ax.text(0.97, 0.05, "\n".join(notes), ha="right", va="bottom", transform=ax.transAxes,
                    fontsize=6.0, linespacing=1.1,
                    bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.85, "pad": 0.6})
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_xlim(0.05, end * 1.3)
        ax.set_title(NAMES[cls], pad=4, color="#005CB8")
        ax.set_xlabel("Elapsed time (s)", labelpad=1.5)
        ax.xaxis.set_major_locator(LogLocator(base=10, numticks=6))
        ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}" if v < 1000 else
                                                   f"$10^{{{int(round(np.log10(v)))}}}$"))
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: number(v)))
        ax.yaxis.set_minor_locator(NullLocator())
        finite = [v for v in extent if np.isfinite(v) and v > 0]
        low, high = (min(finite) / 1.4, max(finite) * 1.4) if finite else (1, 10)
        ax.set_ylim(low, high)
        nice = [m * 10.0 ** k for k in range(-3, 9) for m in (1.0, 1.5, 2.0, 3.0, 5.0, 7.0)
                if low <= m * 10.0 ** k <= high]
        while len(nice) > 4:
            nice = nice[::2]
        ax.set_yticks(nice)
        ax.grid(True, which="major", lw=0.35, color=".86")
    axes[0].set_ylabel("FoM (MHz·pF/mW)", labelpad=2)
    handles = [Line2D([], [], color=COLORS["chipjev"], ls="-", label="ChipJev"),
               Line2D([], [], color=COLORS["tpe8"], ls="--", label="Joint TPE (8 workers)"),
               Line2D([], [], color=COLORS["random8"], ls=":", label="Random (8 workers)"),
               Line2D([], [], color=COLORS["acpro"], ls="-", marker="D", ms=2.8,
                      label="AnalogCoder-Pro flow (30 attempts)")]
    fig.legend(handles=handles, loc="lower center", ncol=4, frameon=False,
               bbox_to_anchor=(0.5, -0.03), handlelength=2.4)
    fig.subplots_adjust(left=0.07, right=0.995, top=0.86, bottom=0.33, wspace=0.36)
    fig.savefig(out / "ptm45-anytime.pdf", bbox_inches="tight", pad_inches=0.02,
                metadata={"CreationDate": None})
    plt.close(fig)


# ---------------------------------------------------------------------------- macros


def typed_summary():
    path = ARCHIVE / "typed-results.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text())

    def correct(rows):
        return sum(r["parsed_cls"] == r["cls"] and r["parsed_objective"] == r["objective"]
                   for r in rows)

    llm = data["llm_parse"]["rows"] if data.get("llm_parse") else []
    return {
        "statements": {k: [correct(v), len(v)] for k, v in data["statements"].items()},
        "heldout": {k: [correct(v), len(v)] for k, v in data["heldout"].items()},
        "latency": data["latency"],
        "llm_statements": [correct([r for r in llm if r["source"] == "statement"]),
                           sum(r["source"] == "statement" for r in llm)],
        "llm_heldout": [correct([r for r in llm if r["source"] == "held-out"]),
                        sum(r["source"] == "held-out" for r in llm)],
        "llm_valid": [sum(r["valid"] for r in llm), len(llm)],
        "llm_median_seconds": quantile([r["seconds"] for r in llm], 0.5),
        "llm_model": (data.get("llm_parse") or {}).get("model"),
    }


def diagnosis_summary():
    """Post-hoc diagnosis of AnalogCoder-Pro's own initial sizes (frozen code: scripts/acpro-diagnose.py)."""
    path = LLM_DIR / "diagnosis.jsonl"
    if not path.exists():
        return None
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    out = {}
    for kind, parity in (("amp", 0), ("opamp", 1)):
        chosen = [r for r in rows if (r["task_id"] - 51) % 2 == parity]
        failed = Counter(f for r in chosen for f in r.get("failed", []))
        out[kind] = {"n": len(chosen), "valid": sum(r["valid"] for r in chosen),
                     "failed": dict(failed),
                     "l45": sum(tuple(r.get("lengths") or []) == (45.0,) for r in chosen)}
    return out


def robustness_summary(runs_dir):
    path = runs_dir / "robustness/results.jsonl"
    if not path.exists():
        return None
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    out = {}
    for method in sorted({r["method"] for r in rows}):
        chosen = [r for r in rows if r["method"] == method]
        out[method] = {
            "designs": len(chosen),
            "corners_pass": sum(r["corners_pass"] for r in chosen),
            "corner_rates": {c: sum(next(x for x in r["corners"] if x["name"] == c)["valid"]
                                    for r in chosen)
                             for c in ("cold", "hot", "low-supply", "high-supply")},
            "median_yield": quantile([r["mismatch_yield"] for r in chosen], 0.5),
            "mean_yield": float(np.mean([r["mismatch_yield"] for r in chosen])),
            "full_yield": sum(r["mismatch_yield"] >= 1.0 for r in chosen),
            "failed_checks": Counter(f for r in chosen for x in r["mismatch"] for f in x["failed"]),
        }
    return out


def macros(groups, ablation_groups, speed_time, speed_eval, typed_speed, llm, typed, robust,
           startup):
    def count(method, source=groups):
        return sum(r["verified"] for (t, m), rows in source.items() if m == method for r in rows)

    def med(method, key="time", source=groups):
        return quantile([r[key] for (t, m), rows in source.items() if m == method
                         for r in rows], 0.5)

    chip = [r for (t, m), rows in groups.items() if m == "chipjev" for r in rows]
    outcomes = Counter()
    for cls in CLASSES:
        for target in TARGETS:
            task = f"{cls}-{target}"
            outcomes[compare(summarize(groups[(task, "chipjev")])["median"],
                             summarize(groups[(task, "tpe8")])["median"], target)] += 1
    ci = speed_time["ci"]
    eci = speed_eval["ci"]
    tci = typed_speed["ci"]
    tasks_llm = sum(1 for v in llm.values() if v["qualified"])
    protocol = [v["protocol_seconds"] for v in llm.values() if v["attempts"]]
    per_task_llm = quantile(protocol, 0.5) if protocol else None
    attempts = sum(v["attempts"] for v in llm.values())
    cpu = [r["time"] for rows in ablation_groups.values() for r in rows
           if r["method"] == "cpu-acquisition"]
    full_ablation = [r["time"] for t in ("ampN-gain", "ampN-fom", "opampN-gain", "opampN-fom")
                     for r in groups[(t, "chipjev")]]
    reached_llm = sum(1 for v in llm.values() if v["reference_seconds"] is not None)
    m = {
        "PtmPass": str(count("chipjev")),
        "PtmNoPriorPass": str(count("chipjev-v2")),
        "PtmTpePass": str(count("tpe8")),
        "PtmRandomPass": str(count("random8")),
        "PtmWall": duration(med("chipjev")),
        "PtmTpeWall": duration(med("tpe8")),
        "PtmRandomWall": duration(med("random8")),
        "PtmStrictMedian": f"{quantile([r['verifications'] for r in chip], 0.5):.0f}",
        "PtmFirst": duration(quantile([r["first_seconds"] + (r.get("typed_seconds") or 0.0)
                                          for r in chip if r["verified"]],
                                         0.5)),
        "PtmSpeedup": ratio(speed_time["geomean"]) + r"$\times$",
        "PtmSpeedupCI": f"{ratio(ci[0])}--{ratio(ci[1])}$\\times$" if ci[0] else "--",
        "PtmSpeedupTasks": str(len(speed_time["tasks"])),
        "PtmOnlyOurs": str(len(speed_time["only_ours"])),
        "PtmOnlyTpe": str(len(speed_time["only_baseline"])),
        "PtmEvalSpeedup": ratio(speed_eval["geomean"]) + r"$\times$",
        "PtmEvalSpeedupCI": f"{ratio(eci[0])}--{ratio(eci[1])}$\\times$" if eci[0] else "--",
        "PtmTypedSpeedup": ratio(typed_speed["geomean"]) + r"$\times$",
        "PtmTypedSpeedupCI": f"{ratio(tci[0])}--{ratio(tci[1])}$\\times$" if tci[0] else "--",
        "PtmTypedTasks": str(len(typed_speed["tasks"])),
        "PtmNumericWins": str(outcomes["numeric_win"]),
        "PtmFeasibleWins": str(outcomes["feasibility_win"]),
        "PtmTies": str(outcomes["tie"]),
        "PtmLosses": str(outcomes["loss"]),
        "PtmStartup": duration(startup),
        "PtmTypedMs": f"{quantile([r['typed_ms'] for r in chip], 0.5):.1f}",
        "PtmAcproAttempts": str(attempts),
        "PtmAcproFunctional": str(sum(v["functional"] for v in llm.values())),
        "PtmAcproQualified": str(sum(v["qualified"] for v in llm.values())),
        "PtmAcproTasks": str(tasks_llm),
        "PtmAcproReached": str(reached_llm),
        "PtmAcproHours": duration(per_task_llm),
        "PtmAcproAttemptTime": duration(quantile([v["median_attempt_seconds"]
                                                     for v in llm.values()], 0.5)),
        "PtmAcproLlmShare": f"{100 * sum(v['llm_seconds'] for v in llm.values()) / max(1, sum(protocol)):.0f}",
        "PtmAcproCalls": str(sum(v["llm_calls"] for v in llm.values())),
        "PtmAcproCallsPerTask": f"{quantile([v['llm_calls'] for v in llm.values()], 0.5):.0f}",
        "PtmAcproTokens": f"{sum(v['tokens'] for v in llm.values()) / 1e6:.1f}M",
        "PtmAcproCost": f"{sum(v['cost_usd'] for v in llm.values()):.2f}",
        "PtmAcproTotalHours": duration(sum(protocol)),
        "PtmCpuWall": duration(quantile(cpu, 0.5)) if cpu else "--",
        "PtmCpuSlowdown": ratio(quantile(cpu, 0.5) / quantile(full_ablation, 0.5))
        + r"$\times$" if cpu else "--",
        "PtmScrambledPass": str(count("scrambled-roles", ablation_groups)),
        "PtmCpuPass": str(count("cpu-acquisition", ablation_groups)),
    }
    diag = diagnosis_summary()
    if diag:
        m.update(
            PtmDiagOpamps=str(diag["opamp"]["n"]),
            PtmDiagOpampGain=str(diag["opamp"]["failed"].get("gain", 0)),
            PtmDiagOpampCmrr=str(diag["opamp"]["failed"].get("cmrr", 0)),
            PtmDiagAmps=str(diag["amp"]["n"]),
            PtmDiagAmpGain=str(diag["amp"]["failed"].get("gain", 0)),
            PtmDiagLengths=str(diag["amp"]["l45"] + diag["opamp"]["l45"]),
            PtmDiagCount=str(diag["amp"]["n"] + diag["opamp"]["n"]),
        )
    first_round = sum(1 for v in llm.values() for _ in range(v.get("first_round", 0)))
    m["PtmAcproFirstRound"] = str(first_round)
    if typed:
        m.update(
            PtmParseStatements=f"{typed['statements']['fine-tuned'][0]}/{typed['statements']['fine-tuned'][1]}",
            PtmParseStatementsZero=f"{typed['statements']['zero-shot'][0]}/{typed['statements']['zero-shot'][1]}",
            PtmParseHeld=f"{typed['heldout']['fine-tuned'][0]}/{typed['heldout']['fine-tuned'][1]}",
            PtmParseHeldZero=f"{typed['heldout']['zero-shot'][0]}/{typed['heldout']['zero-shot'][1]}",
            PtmParseLlmHeld=f"{typed['llm_heldout'][0]}/{typed['llm_heldout'][1]}",
            PtmParseLlmStatements=f"{typed['llm_statements'][0]}/{typed['llm_statements'][1]}",
            PtmParseLlmSeconds=duration(typed["llm_median_seconds"]),
            PtmParseMs=number(typed["latency"]["fine-tuned"]["median_ms"]),
        )
    opamps = [r for r in chip if r["cls"].startswith("opamp") and r["verified"]]
    if opamps:
        m.update(
            PtmCmrrMin=number(min(r["metrics"]["cmrr_db"] for r in opamps), True),
            PtmGainErrorMax=number(100 * max(r["metrics"]["buffer_gain_error"] for r in opamps)),
            PtmOpampPass=str(len(opamps)),
        )
    if robust:
        for method, key in (("chipjev", "Chip"), ("tpe8", "Tpe"), ("random8", "Random"),
                            ("chipjev-v2", "NoPrior"), ("acpro-llm", "Acpro")):
            if method in robust:
                r = robust[method]
                m[f"PtmCorner{key}"] = f"{r['corners_pass']}/{r['designs']}"
                m[f"PtmYield{key}"] = f"{100 * r['mean_yield']:.0f}"
                m[f"PtmFullYield{key}"] = f"{r['full_yield']}/{r['designs']}"
    return m, outcomes


def latency_macros():
    """Separate microbenchmarks on the idle host: typed decisions and the acquisition kernel."""
    out = {}
    typed = ARCHIVE / "typed-latency.json"
    if typed.exists():
        t = json.loads(typed.read_text())
        out["PtmTypedOneMs"] = f"{t['one_pass_ms']['median']:.1f}"
        out["PtmTypedTwoMs"] = f"{t['two_pass_ms']['median']:.1f}"
    kernel = ARCHIVE / "latency.json"
    if kernel.exists():
        k = json.loads(kernel.read_text())
        rows = k["rows"]

        def med(device, dtype, fused):
            values = [statistics.median(r["seconds"]) for r in rows
                      if r["device"].startswith(device) and r["dtype"] == dtype
                      and (fused is None or bool(r.get("fused", r.get("wide"))) == fused)]
            return values

        gpu = [statistics.median(r["seconds"]) for r in rows if r["device"].startswith("cuda")]
        fused, eager = min(gpu), max(gpu)
        cpu32 = [statistics.median(r["seconds"]) for r in rows
                 if r["device"] == "cpu" and r["dtype"] == "float32"]
        out["PtmKernelMs"] = f"{1e3 * fused:.1f}"
        out["PtmKernelEager"] = f"{eager / fused:.1f}" + r"$\times$"
        out["PtmKernelCpu"] = f"{min(cpu32) / fused:.0f}" + r"$\times$"
        out["PtmKernelParity"] = f"{max(p['relative_to_std'] for p in k['parity']):.1e}"
    return out


def write_macros(values, path):
    lines = ["% Generated by reproduce/report_ptm45.py from the frozen PTM 45 nm archive (topo-v3)."]
    lines += [rf"\newcommand{{\{k}}}{{{v}}}" for k, v in sorted(values.items())]
    path.write_text("\n".join(lines) + "\n")


def results_markdown(groups, ablation_groups, speed_time, speed_eval, typed_speed, llm, typed,
                     robust, values, outcomes, second=None):
    """Human-readable summary of the complete archive (generated; do not edit)."""
    lines = ["# PTM 45 nm study results (protocol topo-v3; generated by reproduce/report_ptm45.py)",
             ""]
    lines += [f"Qualified runs: ChipJev {values['PtmPass']}/60, without typed decisions "
              f"{values['PtmNoPriorPass']}/60, joint TPE {values['PtmTpePass']}/60, random "
              f"{values['PtmRandomPass']}/60. Median run time: ChipJev {values['PtmWall']}, "
              f"TPE {values['PtmTpeWall']}.",
              f"Against TPE's task medians: {outcomes['numeric_win']} numeric wins, "
              f"{outcomes['feasibility_win']} feasibility wins, {outcomes['tie']} ties, "
              f"{outcomes['loss']} losses.", ""]
    for name, s in (("time to TPE's final quality", speed_time),
                    ("simulations to TPE's final quality", speed_eval),
                    ("typed prior (time, versus no typed decisions)", typed_speed)):
        lo, hi = (f"{x:.2f}" if x is not None else "--" for x in s["ci"])
        lines.append(f"- Geometric-mean ratio, {name}: {s['geomean']:.2f}x "
                     f"(95% CI {lo}-{hi}) over {len(s['tasks'])} tasks; only ours: "
                     f"{s['only_ours']}; only baseline: {s['only_baseline']}.")
    lines += ["", "## Per task", "",
              "| Task | ChipJev median [IQR] | pass | time (s) | speedup | TPE median | pass | "
              "time (s) | random median | pass | AnalogCoder-Pro best | qualified | "
              "protocol |", "|" + "---|" * 13]
    for cls in CLASSES:
        for target in TARGETS:
            task = f"{cls}-{target}"
            gain = target == "gain"
            c, t, r = (summarize(groups[(task, m)]) for m in ("chipjev", "tpe8", "random8"))
            a, sp = llm[task], speed_time["per_task"][task]["ratio"]
            lines.append(
                f"| {task} | {number(c['median'], gain)} [{number(c['q1'], gain)}, "
                f"{number(c['q3'], gain)}] | {c['success']}/5 | {number(c['time'])} | "
                f"{'--' if sp is None else f'{sp:.2f}x'} | {number(t['median'], gain)} | "
                f"{t['success']}/5 | {number(t['time'])} | {number(r['median'], gain)} | "
                f"{r['success']}/5 | {number(a['best'], gain)} | {a['qualified']}/{a['attempts']} | "
                f"{duration(a['protocol_seconds'], ' ')} |")
    lines += ["", "## AnalogCoder-Pro flow", "",
              f"Attempts {values['PtmAcproAttempts']}, functional netlists (its own checks) "
              f"{values['PtmAcproFunctional']}, qualified sized designs "
              f"{values['PtmAcproQualified']}, tasks with a qualified design "
              f"{values['PtmAcproTasks']}, tasks reaching TPE's median "
              f"{values['PtmAcproReached']}. Median protocol time per task "
              f"{values['PtmAcproHours']} (total {values['PtmAcproTotalHours']}); "
              f"median attempt {values['PtmAcproAttemptTime']}, LLM share "
              f"{values['PtmAcproLlmShare']}%; {values['PtmAcproCalls']} calls, "
              f"{values['PtmAcproTokens']} tokens, ${values['PtmAcproCost']}.", ""]
    if second:
        lines += ["## AnalogCoder-Pro flow with GPT-5-mini (supplementary, after the freeze)", "",
                  f"Attempts {second['attempts']}, functional netlists {second['functional']}, "
                  f"unusable extracted code {second['unusable']} (multi-block answers "
                  f"{second['multiblock']}), qualified sized designs {second['qualified']} for "
                  f"tasks {second['tasks']} ({second['opamps']} op-amp designs); with all code "
                  f"blocks joined: {second['lenient_qualified']} for tasks "
                  f"{second['lenient_tasks']} ({second['lenient_opamps']} op-amp designs). Median "
                  f"attempt {duration(second['median_attempt_seconds'], ' ')}, LLM share "
                  f"{100 * second['llm_share']:.0f}%, ${second['cost_usd']:.2f}.", ""]
    if typed:
        lines += ["## Typed decisions", "",
                  f"AnalogCoder-Pro statements: fine-tuned {typed['statements']['fine-tuned']}, "
                  f"zero-shot {typed['statements']['zero-shot']}; held-out requests: fine-tuned "
                  f"{typed['heldout']['fine-tuned']}, zero-shot {typed['heldout']['zero-shot']}; "
                  f"{typed['llm_model']}: statements {typed['llm_statements']}, held-out "
                  f"{typed['llm_heldout']}, valid {typed['llm_valid']}, median "
                  f"{typed['llm_median_seconds']:.2f} s per parse. Typed latency in the main stage "
                  f"(one pass, median): {values['PtmTypedMs']} ms.", ""]
    lines += ["## Ablations (multi-stage gain/FoM tasks)", ""]
    for method in ("scrambled-roles", "cpu-acquisition"):
        rows = [r for (t, m), g in ablation_groups.items() if m == method for r in g]
        s = summarize(rows)
        lines.append(f"- {method}: {s['success']}/{s['n']} qualified, median time "
                     f"{number(s['time'])} s.")
    if robust:
        lines += ["", "## Robustness of delivered designs", ""]
        for method, r in robust.items():
            lines.append(f"- {method}: {r['designs']} designs, all corners {r['corners_pass']}, "
                         f"per corner {r['corner_rates']}, mean mismatch yield "
                         f"{100 * r['mean_yield']:.1f}%, full yield {r['full_yield']}; "
                         f"failed checks {dict(r['failed_checks'].most_common(5))}.")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------- main


def main():
    global ARCHIVE, PAPER, LLM_DIR
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--study", type=Path, default=ARCHIVE,
                        help="study directory (default experiments/ptm45)")
    parser.add_argument("--runs", type=Path, default=None,
                        help="search runs (default: the study's results/)")
    parser.add_argument("--llm", type=Path, default=None,
                        help="AnalogCoder-Pro DeepSeek-V3 flow (default: the study's results/"
                             "acpro-llm/deepseek-deepseek-chat-v3-0324)")
    parser.add_argument("--output", "--paper", dest="paper", type=Path, default=PAPER,
                        help="report directory (default: runs/reports)")
    parser.add_argument("--preview", action="store_true")
    args = parser.parse_args()
    ARCHIVE, PAPER = args.study.resolve(), args.paper.resolve()
    LLM_DIR = ARCHIVE / "results/acpro-llm/deepseek-deepseek-chat-v3-0324"
    args.runs = args.runs or ARCHIVE / "results"
    frozen = json.loads((ARCHIVE / "protocol.json").read_text())
    main_rows, missing_main = load_search(args.runs, "main", frozen["jobs"]["main"], args.preview)
    abl_rows, missing_abl = load_search(args.runs, "ablation", frozen["jobs"]["ablation"],
                                        args.preview)
    llm_rows, missing_llm = load_llm(args.preview, args.llm)
    groups, ablation_groups = defaultdict(list), defaultdict(list)
    for row in main_rows:
        groups[(row["task"], row["method"])].append(row)
    for row in abl_rows:
        ablation_groups[(row["task"], row["method"])].append(row)
    out = (ROOT / "runs/preview/ptm45") if args.preview else ARCHIVE / "report"
    out.mkdir(parents=True, exist_ok=True)
    if not args.preview:
        required = ("typed-results.json", "typed-latency.json", "latency.json",
                    "corner-selection.jsonl")
        absent = [n for n in required if not (ARCHIVE / n).exists()]
        if absent:
            raise ValueError(f"missing macro sources in {ARCHIVE}: {absent}")
    startups = sorted((args.runs / "main").glob("startup-*.json"))
    # The stage start (a resumed stage adds later records).
    startup = json.loads(startups[0].read_text())["warmup_seconds"] if startups else None
    speed_time = speedups(groups, field=0)
    speed_eval = speedups(groups, field=1)
    typed_speed = speedups(groups, method="chipjev", baseline="chipjev-v2", field=0)
    llm = llm_summary(llm_rows, groups)
    typed = typed_summary()
    robust = robustness_summary(args.runs)
    beat = beat_llm(groups, llm_rows)
    second = second_llm((args.llm or LLM_DIR).parent / "openai-gpt-5-mini")
    values, outcomes = macros(groups, ablation_groups, speed_time, speed_eval, typed_speed, llm,
                              typed, robust, startup)
    typed_effect = {}
    for target in ("gain", "gbw", "fom"):
        a = summarize(groups[(f"opampN-{target}", "chipjev")])
        b = summarize(groups[(f"opampN-{target}", "chipjev-v2")])
        typed_effect[target] = {"typed": a, "v2": b}
    values["PtmTypedGbwRatio"] = ratio(typed_effect["gbw"]["typed"]["median"]
                                          / typed_effect["gbw"]["v2"]["median"]) + r"$\times$"
    values["PtmTypedFomRatio"] = ratio(typed_effect["fom"]["typed"]["median"]
                                          / typed_effect["fom"]["v2"]["median"]) + r"$\times$"
    values["PtmTypedGbwFirst"] = ratio(typed_effect["gbw"]["v2"]["first"]
                                          / typed_effect["gbw"]["typed"]["first"]) + r"$\times$"
    values["PtmTypedFomFirst"] = ratio(typed_effect["fom"]["v2"]["first"]
                                          / typed_effect["fom"]["typed"]["first"]) + r"$\times$"
    values["PtmTypedGainDelta"] = f"{typed_effect['gain']['v2']['median'] - typed_effect['gain']['typed']['median']:.0f}"
    if beat["tasks"]:
        spans = [v["acpro_seconds"] / 60 for v in beat["tasks"].values()]
        values["PtmBeatMinMin"] = f"{min(spans):.0f}"
        values["PtmBeatMaxMin"] = f"{max(spans):.0f}"
    selection = ARCHIVE / "corner-selection.jsonl"
    if selection.exists():
        picked = [json.loads(line) for line in selection.read_text().splitlines()]
        for method, key in (("chipjev", "Chip"), ("tpe8", "Tpe")):
            chosen = [r for r in picked if r["method"] == method]
            values[f"PtmCornerSel{key}"] = (
                f"{sum(r['robust'] is not None for r in chosen)} of {len(chosen)}")
    if second:
        values["PtmGptAttempts"] = str(second["attempts"])
        values["PtmGptFunctional"] = str(second["functional"])
        values["PtmGptQualified"] = str(second["qualified"])
        values["PtmGptTasks"] = str(len(second["tasks"]))
        values["PtmGptOpamps"] = str(second["opamps"])
        values["PtmGptAttemptTime"] = duration(second["median_attempt_seconds"])
        values["PtmGptCost"] = f"{second['cost_usd']:.2f}"
        values["PtmGptUnusable"] = str(second["unusable"])
        values["PtmGptMultiblock"] = str(second["multiblock"])
        values["PtmGptLenientQualified"] = str(second["lenient_qualified"])
        values["PtmGptLenientTasks"] = str(len(second["lenient_tasks"]))
        values["PtmGptLenientOpamps"] = str(second["lenient_opamps"])
        values["PtmGptLlmShare"] = f"{100 * second['llm_share']:.0f}"
    if beat["geomean"]:
        rounded = float(f"{beat['geomean']:.2g}")
        values["PtmBeatRatio"] = f"{rounded:,.0f}" + r"$\times$"
        values["PtmBeatTasks"] = str(len(beat["tasks"]))
        values["PtmBeatSlowest"] = duration(beat["slowest_chipjev"])
        values["PtmBeatAll"] = "all" if beat["all_runs_reached"] else "not all"
    values.update(latency_macros())
    stats = {f"{t}|{m}": summarize(g) for (t, m), g in groups.items()}
    stats.update({f"{t}|{m}": summarize(g) for (t, m), g in ablation_groups.items()})
    summary = {
        "missing": {"main": len(missing_main), "ablation": len(missing_abl),
                    "llm": len(missing_llm)},
        "stats": stats, "outcomes_vs_tpe8": dict(outcomes),
        "speedup_time_vs_tpe8": speed_time, "speedup_evaluations_vs_tpe8": speed_eval,
        "typed_prior_time_vs_v2": typed_speed, "llm": llm, "typed": typed,
        "robustness": robust, "beat_llm": beat, "second_llm": second, "macros": values,
    }
    (out / "summary.json").write_text(json.dumps(clean(summary), indent=1))
    (out / "RESULTS.md").write_text(results_markdown(
        groups, ablation_groups, speed_time, speed_eval, typed_speed, llm, typed, robust, values,
        outcomes, second))
    target_dir = out if args.preview else PAPER / "generated"
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "ptm45-table.tex").write_text(main_table(groups, llm, speed_time))
    write_macros(values, target_dir / "ptm45-summary.tex")
    figure_dir = out if args.preview else PAPER / "figures"
    figure_dir.mkdir(parents=True, exist_ok=True)
    anytime_figure(groups, llm_rows, figure_dir)
    print(json.dumps(clean({k: summary[k] for k in ("missing", "outcomes_vs_tpe8")}), indent=1))
    for key in ("speedup_time_vs_tpe8", "speedup_evaluations_vs_tpe8", "typed_prior_time_vs_v2"):
        s = summary[key]
        print(key, s["geomean"], s["ci"], len(s["tasks"]), "only ours", s["only_ours"],
              "only baseline", s["only_baseline"])


if __name__ == "__main__":
    main()
