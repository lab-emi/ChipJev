"""Report of the SKY130 and System Two study (protocol topo-v4 and its system2b addendum):
Table III, the paper's Sky*, SysTwo* and AnalogCoder-Pro wall-time macros,
report/summary.json and report/RESULTS.md, from the archived evidence.

  .venv/bin/python reproduce/report_sky130_system_two.py      # from experiments/sky130-system-two
  .venv/bin/python reproduce/report_sky130_system_two.py --study DIR [--runs DIR] \
      [--ptm45-summary FILE] [--llm-runs DIR] [--paper DIR]

The statistics are those of the PTM 45 nm report (report_ptm45.py, imported unchanged):
failure-aware medians, wins/ties/losses within 0.5 dB or 5%, time and simulations to TPE's
median final quality with a percentile bootstrap over seeds. AnalogCoder-Pro ratios come from
the PTM 45 nm summary (experiments/ptm45/report/summary.json, written by report_ptm45.py
first). Refuses missing or duplicate runs of the frozen job lists unless --preview (then
writes only to runs/preview/sky130-system-two).
"""

import argparse
import gzip
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import report_ptm45 as ptm  # noqa: E402

ARCHIVE = ROOT / "experiments/sky130-system-two"
PTM45 = ROOT / "experiments/ptm45"
PAPER = ROOT / "runs/reports"
CLASSES, TARGETS, NAMES = ptm.CLASSES, ptm.TARGETS, ptm.NAMES
SHORT = {"amp1": "A1", "opamp1": "O1", "ampN": "AN", "opampN": "ON"}
GOAL = {"gain": "gain", "gbw": "GBW", "fom": "FoM"}
LLM_METHODS = {"chipjev-deepseek": "DeepSeek-V3", "chipjev-gpt5mini": "GPT-5-mini"}
PARALLEL = 8  # AnalogCoder-Pro attempts ran eight at a time (acpro-llm-run.py --parallel 8)


def load_stage(runs_dir, stage, jobs, preview):
    rows = []
    for path in sorted((runs_dir / stage).glob("results*.jsonl")):
        rows += [json.loads(line) for line in path.read_text().splitlines()]
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
        if raw["verified"] != bool(raw["best"]) or raw["verified"] != row["verified"]:
            raise ValueError(f"inconsistent incumbent: {row['run_file']}")
        if row["cls"].startswith("opamp") and raw["best"]:
            qualification = raw["best"].get("qualification")
            if qualification is not None and not qualification["passed"]:
                raise ValueError(f"unqualified reported op-amp: {row['run_file']}")
        if stage == "sky130" and raw.get("technology") != "sky130":
            raise ValueError(f"not a SKY130 run: {row['run_file']}")
        offset = row.get("typed_seconds") or 0.0
        row["time"] = raw["wall_seconds"] + offset
        row["events"] = ptm.incumbent_events(raw, offset)
        row["decision"] = raw.get("decision")
        row["tally"] = raw.get("tally") or {}
        row["key"] = f"{row['cls']}-{row['target']}"
        if row["verified"] and row["best"] is None:
            raise ValueError(f"verified run without objective: {row['run_file']}")
    return rows, missing


def groups_of(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[(row["key"], row["method"])].append(row)
    return groups


def outcomes(groups, method, baseline):
    counts = {"numeric_win": 0, "feasibility_win": 0, "tie": 0, "loss": 0, "both_failed": 0}
    per_task = {}
    for cls in CLASSES:
        for target in TARGETS:
            key = f"{cls}-{target}"
            ours = ptm.summarize(groups[(key, method)])["median"]
            base = ptm.summarize(groups[(key, baseline)])["median"]
            result = ptm.compare(ours, base, target)
            counts[result] += 1
            per_task[key] = result
    return counts, per_task


def median(values):
    values = [v for v in values if v is not None]
    return statistics.median(values) if values else None


def seconds(value):
    if value is None or not np.isfinite(value):
        return "--"
    if value < 1:
        return f"{1000 * value:.0f}~ms"
    if value < 100:
        return f"{value:.1f}~s" if value < 10 else f"{value:.0f}~s"
    if value < 3600:
        return f"{value / 60:.1f}~min" if value < 600 else f"{value / 60:.0f}~min"
    return f"{value / 3600:.1f}~h"


def times(value):
    """A ratio as n$\\times$ with sensible rounding."""
    if value is None or not np.isfinite(value):
        return "--"
    if value >= 100:
        return f"{float(f'{value:.2g}'):,.0f}$\\times$"
    return f"{value:.1f}$\\times$" if value < 10 else f"{value:.0f}$\\times$"


# ---------------------------------------------------------------------------- AnalogCoder-Pro


def acpro_ratios(ptm_summary):
    """Per-task time ratio of AnalogCoder-Pro's protocol to ChipJev's median run, and quality
    ratios on the tasks where AnalogCoder-Pro qualified a design (PTM 45 nm archive)."""
    stats, llm = ptm_summary["stats"], ptm_summary["llm"]
    time_ratios, wall_ratios, wall_per_task, quality = [], [], [], {}
    for cls in CLASSES:
        for target in TARGETS:
            key = f"{cls}-{target}"
            chip = stats[f"{key}|chipjev"]
            flow = llm[key]
            if flow["attempts"] and flow.get("protocol_seconds"):
                time_ratios.append(flow["protocol_seconds"] / chip["time"])
                # The attempts are independent and ran eight at a time on eight cores: the
                # wall time of the protocol at ChipJev's core budget is the attempt time / 8.
                wall_ratios.append(flow["protocol_seconds"] / PARALLEL / chip["time"])
                wall_per_task.append(flow["protocol_seconds"] / PARALLEL)
            if flow.get("best") is not None and chip["median"] is not None:
                if target == "gain":
                    quality[key] = {"delta_db": chip["median"] - flow["best"]}
                else:
                    quality[key] = {"ratio": chip["median"] / flow["best"]}
    gmean = math.exp(sum(math.log(r) for r in time_ratios) / len(time_ratios))
    wall = math.exp(sum(math.log(r) for r in wall_ratios) / len(wall_ratios))
    return {"time_ratio_gmean": gmean, "time_ratio_min": min(time_ratios),
            "time_ratio_max": max(time_ratios), "wall_ratio_gmean": wall,
            "wall_ratio_min": min(wall_ratios), "wall_ratio_max": max(wall_ratios),
            "wall_per_task_median": statistics.median(wall_per_task), "quality": quality,
            "max_ratio": max(q["ratio"] for q in quality.values() if "ratio" in q),
            "max_delta_db": max(q["delta_db"] for q in quality.values() if "delta_db" in q),
            "fom_ratio_max": max((q["ratio"] for k, q in quality.items()
                                  if k.endswith("fom") and "ratio" in q), default=None),
            "gbw_ratio_max": max((q["ratio"] for k, q in quality.items()
                                  if k.endswith("gbw") and "ratio" in q), default=None)}


# ---------------------------------------------------------------------------- System Two


def system2_summary(groups, rows):
    out = {}
    for method in ("chipjev", *LLM_METHODS):
        chosen = [r for r in rows if r["method"] == method]
        decisions = [r["decision"] for r in chosen if r["decision"]]
        latency = [d["seconds"] for d in decisions]
        calls = sum(len(d.get("calls", [])) or 1 for d in decisions)
        out[method] = {
            "runs": len(chosen), "qualified": sum(r["verified"] for r in chosen),
            "decision_median_s": median(latency), "decision_p90_s":
                float(np.quantile(latency, 0.9)) if latency else None,
            "calls": calls,
            "type_errors": sum(d.get("type_errors", 0) for d in decisions),
            "api_errors": sum(d.get("api_errors", 0) for d in decisions),
            "failed": sum(bool(d.get("failed")) for d in decisions),
            "time_median_s": median([r["time"] for r in chosen]),
            "first_median_s": median([r["first_seconds"] + (r.get("typed_seconds") or 0.0)
                                      if r["verified"] and r["first_seconds"] is not None
                                      else math.inf for r in chosen]),
            "cost_usd": sum(sum(float(c.get("cost") or 0.0) for c in d.get("calls", []))
                            for d in decisions),
            "parsed": sum(1 for r, d in zip(chosen, decisions, strict=False)
                          if d.get("class") == r["cls"] and d.get("objective") == r["target"]),
        }
        if method != "chipjev":
            counts, per_task = outcomes(groups, method, "chipjev")
            out[method]["vs_laya"] = counts
            out[method]["vs_laya_tasks"] = per_task
    laya = out["chipjev"]["decision_median_s"]
    for method in LLM_METHODS:
        out[method]["latency_ratio"] = out[method]["decision_median_s"] / laya
    return out


# ---------------------------------------------------------------------------- SKY130


def sky130_summary(groups, rows):
    speed_time = ptm.speedups(groups, field=0, seed=20270926)
    speed_eval = ptm.speedups(groups, field=1, seed=20270926)
    counts, per_task = outcomes(groups, "chipjev", "tpe8")
    methods = {}
    for method in ("chipjev", "tpe8", "random8"):
        chosen = [r for r in rows if r["method"] == method]
        online = sum(r["tally"].get("online_records", 0) for r in chosen)
        methods[method] = {
            "qualified": sum(r["verified"] for r in chosen), "runs": len(chosen),
            "time_median_s": median([r["time"] for r in chosen]),
            "first_median_s": median([r["first_seconds"] + (r.get("typed_seconds") or 0.0)
                                      if r["verified"] else math.inf for r in chosen]),
            "timeouts": sum(r["tally"].get("online_timeouts", 0) for r in chosen),
            "online_records": online,
            "false_passes": sum(r["false_passes"] for r in chosen),
        }
    return {"speed_time": speed_time, "speed_eval": speed_eval, "outcomes": counts,
            "outcome_tasks": per_task, "methods": methods}


def sky130_table(groups, speed):
    """Column table: per task the ChipJev, TPE and random medians (qualified seeds when
    fewer than five) and ChipJev's speedup to TPE's final quality."""
    lines = [r"\begin{tabular}{@{}l>{\columncolor{paperpale}}r>{\columncolor{paperpale}}r"
             r">{\columncolor{paperpale}}rrrr@{}}",
             r"\toprule",
             r"Task & \textbf{ChipJev} & Time & Sooner & TPE & Time & Random\\", r"\midrule"]
    for cls in CLASSES:
        for target in TARGETS:
            key = f"{cls}-{target}"
            cells = []
            best = max((ptm.summarize(groups[(key, m)])["median"] or -np.inf)
                       for m in ("chipjev", "tpe8", "random8"))
            for method in ("chipjev", "tpe8", "random8"):
                s = ptm.summarize(groups[(key, method)])
                value = s["median"]
                if value is None or not np.isfinite(value):
                    text = "--"
                else:
                    text = ptm.number(value, target == "gain")
                    if abs(value - best) <= 1e-12:
                        text = r"\textbf{" + text + "}"
                if s["success"] < s["n"]:
                    text += f" ({s['success']})"
                cells.append(text)
            ratio = speed["per_task"][key]["ratio"]
            if ratio is None:
                chip_ok = np.isfinite(speed["per_task"][key]["ours_median"])
                sooner = "feas." if chip_ok else "--"
            else:
                sooner = f"{ratio:.1f}$\\times$"
            unit = {"gain": "dB", "gbw": "MHz", "fom": ""}[target]
            t_chip = ptm.summarize(groups[(key, "chipjev")])["time"]
            t_tpe = ptm.summarize(groups[(key, "tpe8")])["time"]
            lines.append(f"{SHORT[cls]}-{GOAL[target]} {unit} & {cells[0]} & {_one(t_chip, '.0f')} & "
                         f"{sooner} & {cells[1]} & {_one(t_tpe, '.0f')} & {cells[2]}\\\\")
        if cls != CLASSES[-1]:
            lines.append(r"\addlinespace[1pt]")
    lines += [r"\bottomrule", r"\end{tabular}"]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------- output


def macros(sky, sys2, acpro, ptm_summary):
    m = {}
    if sky:
        s = sky["methods"]
        m.update(
            SkyPass=str(s["chipjev"]["qualified"]),
            SkyTpePass=str(s["tpe8"]["qualified"]),
            SkyRandomPass=str(s["random8"]["qualified"]),
            SkyWall=seconds(s["chipjev"]["time_median_s"]),
            SkyTpeWall=seconds(s["tpe8"]["time_median_s"]),
            SkyRandomWall=seconds(s["random8"]["time_median_s"]),
            SkyFirst=seconds(s["chipjev"]["first_median_s"]),
            SkyTpeFirst=seconds(s["tpe8"]["first_median_s"]),
            SkySpeedup=times(sky["speed_time"]["geomean"]),
            SkySpeedupCI="--".join(f"{x:.1f}" if x is not None else "?"
                                        for x in sky["speed_time"]["ci"]) + r"$\times$",
            SkySpeedupTasks=str(len(sky["speed_time"]["tasks"])),
            SkyEvalSpeedup=times(sky["speed_eval"]["geomean"]),
            SkyEvalSpeedupCI="--".join(f"{x:.1f}" if x is not None else "?"
                                            for x in sky["speed_eval"]["ci"]) + r"$\times$",
            SkyNumericWins=str(sky["outcomes"]["numeric_win"]),
            SkyFeasibleWins=str(sky["outcomes"]["feasibility_win"]),
            SkyTies=str(sky["outcomes"]["tie"]),
            SkyLosses=str(sky["outcomes"]["loss"]),
            SkyOnlyChip=str(len(sky["speed_time"]["only_ours"])),
            SkyTimeoutChip=f"{100 * s['chipjev']['timeouts'] / max(1, s['chipjev']['online_records']):.1f}",
            SkyTimeoutTpe=f"{100 * s['tpe8']['timeouts'] / max(1, s['tpe8']['online_records']):.1f}",
            SkyTimeoutRandom=f"{100 * s['random8']['timeouts'] / max(1, s['random8']['online_records']):.1f}",
        )
    if sys2:
        laya, ds, gpt = sys2["chipjev"], sys2["chipjev-deepseek"], sys2["chipjev-gpt5mini"]
        # One basis everywhere: LLM decision medians over Laya's in-run one-pass median.
        low = min(ds["latency_ratio"], gpt["latency_ratio"])
        high = max(ds["latency_ratio"], gpt["latency_ratio"])
        m.update(
            SysTwoLayaMs=f"{1000 * laya['decision_median_s']:.1f}",
            SysTwoDeepSeekS=seconds(ds["decision_median_s"]),
            SysTwoGptS=seconds(gpt["decision_median_s"]),
            SysTwoDeepSeekRatio=times(ds["latency_ratio"]),
            SysTwoGptRatio=times(gpt["latency_ratio"]),
            SysTwoLlmRatio=(f"{float(f'{low:.2g}'):,.0f}--{float(f'{high:.2g}'):,.0f}$\\times$"),
            SysTwoPassLaya=str(laya["qualified"]), SysTwoPassDeepSeek=str(ds["qualified"]),
            SysTwoPassGpt=str(gpt["qualified"]),
            SysTwoWallLaya=seconds(laya["time_median_s"]),
            SysTwoWallDeepSeek=seconds(ds["time_median_s"]),
            SysTwoWallGpt=seconds(gpt["time_median_s"]),
            SysTwoParsedLaya=str(laya["parsed"]), SysTwoParsedDeepSeek=str(ds["parsed"]),
            SysTwoParsedGpt=str(gpt["parsed"]),
            SysTwoFirstLaya=seconds(laya["first_median_s"]),
            SysTwoFirstDeepSeek=seconds(ds["first_median_s"]),
            SysTwoFirstGpt=seconds(gpt["first_median_s"]),
            SysTwoTypeErrorsDeepSeek=str(ds["type_errors"]),
            SysTwoTypeErrorsGpt=str(gpt["type_errors"]),
            SysTwoCallsDeepSeek=str(ds["calls"]), SysTwoCallsGpt=str(gpt["calls"]),
            SysTwoFailedDeepSeek=str(ds["failed"]), SysTwoFailedGpt=str(gpt["failed"]),
            SysTwoCost=f"{ds['cost_usd'] + gpt['cost_usd']:.2f}",
        )
        for method, key in (("chipjev-deepseek", "DeepSeek"), ("chipjev-gpt5mini", "Gpt")):
            c = sys2[method]["vs_laya"]
            m[f"SysTwoVsLaya{key}"] = (f"{c['numeric_win'] + c['feasibility_win']}/{c['tie']}/"
                                      f"{c['loss']}")
            m[f"SysTwoVsLaya{key}Wins"] = str(c["numeric_win"] + c["feasibility_win"])
            m[f"SysTwoVsLaya{key}Ties"] = str(c["tie"])
            m[f"SysTwoVsLaya{key}Losses"] = str(c["loss"])
    m.update(
        PtmAcproRatio=times(acpro["time_ratio_gmean"]),
        PtmAcproRatioMin=times(acpro["time_ratio_min"]),
        PtmAcproRatioMax=times(acpro["time_ratio_max"]),
        PtmAcproWallRatio=times(acpro["wall_ratio_gmean"]),
        PtmAcproWallRatioMin=times(acpro["wall_ratio_min"]),
        PtmAcproWallRatioMax=times(acpro["wall_ratio_max"]),
        PtmAcproWallPerTask=seconds(acpro["wall_per_task_median"]),
        PtmAcproFomRatio=times(acpro["fom_ratio_max"]),
        PtmAcproGbwRatio=times(acpro["gbw_ratio_max"]),
        PtmAcproGainDelta=f"{acpro['max_delta_db']:.0f}",
    )
    return m


def _one(value, spec=".1f"):
    return "--" if value is None or not np.isfinite(value) else format(value, spec)


def results_markdown(sky, sys2, acpro, flows, sky_groups, sys_groups, values):
    """Human-readable summary of the SKY130 and System Two study (generated; do not edit)."""
    lines = ["# SKY130 and System Two study results (protocol topo-v4; generated by "
             "reproduce/report_sky130_system_two.py)", ""]
    lines += ["## AnalogCoder-Pro ratios (PTM 45 nm archive)", "",
              f"ChipJev is {acpro['time_ratio_gmean']:.0f}x faster than AnalogCoder-Pro's "
              f"released flow per task (geometric mean; {acpro['time_ratio_min']:.0f}-"
              f"{acpro['time_ratio_max']:.0f}x). Quality where AnalogCoder-Pro qualified: "
              + ", ".join(f"{k}: " + (f"{q['ratio']:.2f}x" if "ratio" in q
                                      else f"+{q['delta_db']:.1f} dB")
                          for k, q in sorted(acpro["quality"].items())) + ".", ""]
    for name, f in sorted(flows.items()):
        lines.append(f"- AnalogCoder-Pro with {name}: {f['attempts']} attempts, mean LLM call "
                     f"{f['call_seconds_mean']:.1f} s, median protocol time per task "
                     f"{f['protocol_seconds_median'] / 60:.1f} min "
                     f"({f['attempts_per_task']:.0f} attempts per task).")
    if sys2:
        lines += ["", "## System One versus System Two (PTM 45 nm)", "",
                  "| Decisions | qualified | decision median | type errors / calls | failed | "
                  "run median | first qualified | vs Laya (W/T/L) |", "|" + "---|" * 8]
        for method, label in (("chipjev", "Laya"), *LLM_METHODS.items()):
            x = sys2[method]
            vs = x.get("vs_laya")
            wtl = "--" if vs is None else (f"{vs['numeric_win'] + vs['feasibility_win']}/"
                                           f"{vs['tie']}/{vs['loss']}")
            lines.append(f"| {label} | {x['qualified']}/{x['runs']} | "
                         f"{_one(x['decision_median_s'], '.4g')} s | {x['type_errors']}/{x['calls']} | "
                         f"{x['failed']} | {_one(x['time_median_s'])} s | "
                         f"{_one(x['first_median_s'])} s | {wtl} |")
        lines += ["", "| Task | Laya | DeepSeek-V3 | GPT-5-mini |", "|---|---|---|---|"]
        for cls in CLASSES:
            for target in TARGETS:
                key = f"{cls}-{target}"
                cells = []
                for method in ("chipjev", *LLM_METHODS):
                    st = ptm.summarize(sys_groups[(key, method)])
                    cells.append(f"{ptm.number(st['median'], target == 'gain')} "
                                 f"({st['success']}/5)")
                lines.append(f"| {key} | " + " | ".join(cells) + " |")
    if sky:
        lines += ["", "## SKY130", "",
                  f"Qualified: ChipJev {sky['methods']['chipjev']['qualified']}/60, TPE "
                  f"{sky['methods']['tpe8']['qualified']}/60, random "
                  f"{sky['methods']['random8']['qualified']}/60. Against TPE's medians: "
                  f"{sky['outcomes']}. Time to TPE's final quality: "
                  f"{sky['speed_time']['geomean']:.2f}x (CI {sky['speed_time']['ci']}) over "
                  f"{len(sky['speed_time']['tasks'])} tasks; simulations "
                  f"{sky['speed_eval']['geomean']:.2f}x; only ChipJev: "
                  f"{sky['speed_time']['only_ours']}; only TPE: "
                  f"{sky['speed_time']['only_baseline']}.", "",
                  "| Task | ChipJev | TPE | random | ChipJev time (s) | TPE time (s) |",
                  "|---|---|---|---|---|---|"]
        for cls in CLASSES:
            for target in TARGETS:
                key = f"{cls}-{target}"
                st = {m: ptm.summarize(sky_groups[(key, m)]) for m in ("chipjev", "tpe8",
                                                                        "random8")}
                lines.append(f"| {key} | " + " | ".join(
                    f"{ptm.number(st[m]['median'], target == 'gain')} ({st[m]['success']}/5)"
                    for m in ("chipjev", "tpe8", "random8"))
                    + f" | {_one(st['chipjev']['time'])} | {_one(st['tpe8']['time'])} |")
        lines += ["", "Simulator time-outs (online, share): " + ", ".join(
            f"{m} {100 * x['timeouts'] / max(1, x['online_records']):.1f}%"
            for m, x in sky["methods"].items()) + "."]
    return "\n".join(lines) + "\n"


def llm_flow_stats(llm_root):
    """Per-call LLM time and per-task protocol time of the AnalogCoder-Pro runs (journals)."""
    out = {}
    for name, folder in (("deepseek", "deepseek-deepseek-chat-v3-0324"),
                         ("gpt", "openai-gpt-5-mini")):
        journal = llm_root / folder / "results.jsonl"
        if not journal.exists():
            continue
        rows = [json.loads(line) for line in journal.read_text().splitlines()]
        per_task = defaultdict(float)
        for r in rows:
            per_task[r["task_id"]] += r["wall_seconds"]
        span = max(r["start"] + r["wall_seconds"] for r in rows) - min(r["start"] for r in rows)
        out[name] = {"attempts": len(rows), "wall_span_seconds": span,
                     "call_seconds_mean": sum(r["llm_seconds"] for r in rows)
                     / max(1, sum(r["llm_calls"] for r in rows)),
                     "protocol_seconds_median": statistics.median(per_task.values()),
                     "attempts_per_task": len(rows) / max(1, len(per_task))}
    return out


def main():
    global ARCHIVE, PAPER
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--study", type=Path, default=ARCHIVE,
                        help="study directory (default experiments/sky130-system-two)")
    parser.add_argument("--runs", type=Path, default=None,
                        help="search runs (default: the study's results/)")
    parser.add_argument("--ptm45-summary", type=Path, default=PTM45 / "report/summary.json")
    parser.add_argument("--llm-runs", type=Path, default=PTM45 / "results/acpro-llm",
                        help="AnalogCoder-Pro journals (runs or archive acpro-llm directory)")
    parser.add_argument("--output", "--paper", dest="paper", type=Path, default=PAPER,
                        help="report directory (default: runs/reports)")
    parser.add_argument("--preview", action="store_true")
    args = parser.parse_args()
    ARCHIVE, PAPER = args.study.resolve(), args.paper.resolve()
    args.runs = args.runs or ARCHIVE / "results"
    frozen = json.loads((ARCHIVE / "protocol.json").read_text())
    if not args.preview and not (ARCHIVE / "xschem/roundtrip.json").exists():
        raise ValueError(f"missing {ARCHIVE}/xschem/roundtrip.json (the frozen xschem export)")
    ptm_summary = json.loads(args.ptm45_summary.read_text())
    out = (ROOT / "runs/preview/sky130-system-two") if args.preview else ARCHIVE / "report"
    out.mkdir(parents=True, exist_ok=True)
    sky_rows, sky_missing = load_stage(args.runs, "sky130", frozen["jobs"]["sky130"], args.preview)
    sys_rows, sys_missing = load_stage(args.runs, "system2", frozen["jobs"]["system2"],
                                       args.preview)
    sky_groups, sys_groups = groups_of(sky_rows), groups_of(sys_rows)
    sky = sky130_summary(sky_groups, sky_rows) if sky_rows else None
    sys2 = system2_summary(sys_groups, sys_rows) if sys_rows else None
    acpro = acpro_ratios(ptm_summary)
    flows = llm_flow_stats(args.llm_runs)
    values = macros(sky, sys2, acpro, ptm_summary)
    if "deepseek" in flows:
        values["PtmAcproCallSeconds"] = seconds(flows["deepseek"]["call_seconds_mean"])
        values["PtmAcproWallSpan"] = seconds(flows["deepseek"]["wall_span_seconds"])
    if "gpt" in flows:
        values["PtmGptCallSeconds"] = seconds(flows["gpt"]["call_seconds_mean"])
        values["PtmGptHours"] = seconds(flows["gpt"]["protocol_seconds_median"])
    roundtrip = ARCHIVE / "xschem/roundtrip.json"
    if roundtrip.exists():
        trip = json.loads(roundtrip.read_text())
        values["SkyXschemOk"] = str(trip["equivalent"])
        values["SkyXschemAll"] = str(trip["checked"])
    if sys2:
        for method, key in (("chipjev-deepseek", "DeepSeek"), ("chipjev-gpt5mini", "Gpt"),
                            ("chipjev", "Laya")):
            tasks = {r["key"] for r in sys_rows if r["method"] == method and r["verified"]}
            values[f"SysTwoTasks{key}"] = str(len(tasks))
    summary = {"missing": {"sky130": len(sky_missing), "system2": len(sys_missing)},
               "sky130": sky, "system2": sys2, "acpro": acpro, "llm_flows": flows,
               "macros": values,
               "stats": {f"{stage}|{k}|{m}": ptm.summarize(g) for stage, groups in
                         (("sky130", sky_groups), ("system2", sys_groups))
                         for (k, m), g in groups.items()}}
    (out / "summary.json").write_text(json.dumps(ptm.clean(summary), indent=1))
    (out / "RESULTS.md").write_text(results_markdown(sky, sys2, acpro, flows, sky_groups,
                                                     sys_groups, values))
    target = out if args.preview else PAPER / "generated"
    target.mkdir(parents=True, exist_ok=True)
    if sky:
        (target / "sky130-table.tex").write_text(sky130_table(sky_groups, sky["speed_time"]))
    lines = ["% Generated by reproduce/report_sky130_system_two.py from the frozen SKY130 and "
             "System Two archive (topo-v4)."]
    lines += [rf"\newcommand{{\{k}}}{{{v}}}" for k, v in sorted(values.items())]
    (target / "sky130-system-two-summary.tex").write_text("\n".join(lines) + "\n")
    print(json.dumps(ptm.clean({"missing": summary["missing"], "macros": values}), indent=1))


if __name__ == "__main__":
    main()
