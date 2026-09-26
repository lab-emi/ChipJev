"""Archive and report the goal-driven loop, separately from the v1/frozen studies."""

import argparse
import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IDS = ("opamp-gain", "opamp-speed", "ota-efficient")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def capture(runs, destination):
    if destination.exists():
        raise FileExistsError("Use a fresh evidence directory")
    sources = {json.loads((p / "result.json").read_text())["example"]["id"]: p for p in runs}
    if set(sources) != set(IDS):
        raise ValueError("Exactly one completed run per prompt is required")
    for ident, source in sources.items():
        record = json.loads((source / "result.json").read_text())
        if not record["valid"]:
            raise ValueError(f"{ident} failed qualification")
        for name, expected in record["source_sha256"].items():
            if digest(ROOT / name) != expected:
                raise ValueError(f"Source changed after the run: {name}")
    destination.mkdir(parents=True)
    for ident, source in sources.items():
        target = destination / ident
        target.mkdir()
        for name in (
            "result.json",
            "physical.json",
            "optimization.json",
            "layout.mag",
            "layout.gds",
            "layout.svg",
            "layout-intent.svg",
            "pex.spice",
            "drc.txt",
            "lvs.log",
            "circuit.sch",
            "circuit.spice",
            "physical-evidence.zip",
        ):
            shutil.copy2(source / name, target / name)
        for name in ("layout.mag", "layout.json"):
            shutil.copy2(source / "physical/candidate-00" / name, target / f"initial-{name}")
    (destination / "MANIFEST.json").write_text(
        json.dumps(
            {
                "scope": "Three public development prompts; not held-out success-rate evidence",
                "files": {
                    str(p.relative_to(destination)): digest(p)
                    for p in sorted(destination.rglob("*"))
                    if p.is_file()
                },
                "report_script_sha256": digest(Path(__file__)),
            },
            indent=2,
        )
    )


def report(directory):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import PatchCollection
    from matplotlib.patches import Rectangle

    from chipjev.layout.magic import GRID, bounds, rectangles

    manifest = json.loads((directory / "MANIFEST.json").read_text())
    for name, expected in manifest["files"].items():
        if digest(directory / name) != expected:
            raise ValueError(f"Changed evidence: {name}")
    output = directory / "report"
    output.mkdir(exist_ok=True)
    rows = []
    for ident in IDS:
        record = json.loads((directory / ident / "result.json").read_text())
        physical = record["physical"]
        trace = physical["optimization"]
        layout = physical["layout"]
        initial = trace["history"][0]
        rows.append(
            {
                "prompt": ident,
                "valid": physical["valid"],
                "initial_valid": initial["valid"],
                "initial_area_um2": initial["quality"]["area_um2"],
                "final_area_um2": layout["area_um2"],
                "area_reduction_percent": 100
                * (1 - layout["area_um2"] / initial["quality"]["area_um2"]),
                "first_feasible_seconds": trace["first_feasible_seconds"],
                "optimization_seconds": trace["wall_seconds"],
                "layout_drc_seconds": layout["layout_seconds"],
                "worker_seconds": record["demo_seconds"],
                "evaluations": trace["evaluations"],
                "rejected": sum(not h["valid"] for h in trace["history"]),
                "laya_seconds": trace["decision_seconds"],
                "prelayout_metrics": physical["prelayout"]["metrics"],
                "postlayout_metrics": physical["postlayout"]["metrics"],
                "logical_mosfets": layout["logical_mosfets"],
                "physical_devices": layout["physical_devices"],
                "pex": physical["pex"],
                "analog_metrics": physical["analog"]["metrics"],
                "plan": layout["plan"],
                "fixed_input_bias_v": trace["fixed_input_bias_v"],
            }
        )
    (output / "summary.json").write_text(json.dumps(rows, indent=2))
    lines = [
        "# Goal-driven analog layout: measured development runs",
        "",
        "Same circuit sizing and fixed input bias within each layout search; real Magic/Netgen/ngspice. PCell cache is warm, Laya is resident on an RTX 4090. Wall times are host measurements and exclude network/browser latency.",
        "",
        "| Prompt | Initial → final area (µm²) | Reduction | First feasible (s) | Layout loop (s) | Whole demo (s) | Rejected / evaluated |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    tex = []
    for r in rows:
        lines.append(
            f"| {r['prompt']} | {r['initial_area_um2']:.0f} → {r['final_area_um2']:.0f} | {r['area_reduction_percent']:.1f}% | {r['first_feasible_seconds']:.2f} | {r['optimization_seconds']:.2f} | {r['worker_seconds']:.2f} | {r['rejected']} / {r['evaluations']} |"
        )
        tex.append(
            f"{r['prompt']} & {r['initial_area_um2']:.0f} & {r['final_area_um2']:.0f} & {r['area_reduction_percent']:.1f} & {r['first_feasible_seconds']:.2f} & {r['optimization_seconds']:.2f} "
            + chr(92) * 2
        )
    lines += [
        "",
        "All delivered layouts pass full available Magic DRC, unique LVS, declared-device/PEX integrity, and strict fixed-bias nominal OP/AC/transient checks. Noise/PSRR and finite-impedance supply metrics are measurements, with no invented acceptance limits. Failed candidates are retained in the evidence ZIP.",
        "",
        "This comparison starts from the new grouped generator; it does not claim area or speed superiority over the archived row generator or competing layout tools. The three prompts informed development. No expert-layout-trained checkpoint or cross-topology generalization result is claimed. EM, density/antenna closure, spatial mismatch, thermal and substrate-noise signoff are outside the implemented coverage.",
    ]
    (output / "README.md").write_text("\n".join(lines) + "\n")
    (output / "analog-layout-results.tex").write_text("\n".join(tex) + "\n")
    # Direct manuscript inputs: derived only from this checked evidence archive.
    summaries = []
    for macro, key in (("LayoutTime", "layout_drc_seconds"),
                       ("LayoutLoopTime", "optimization_seconds"),
                       ("DemoTime", "worker_seconds")):
        values = [r[key] for r in rows]
        summaries.append("\\newcommand{\\" + macro + "}{"
                         + f"{min(values):.2f}--{max(values):.2f}" + r"~s\xspace}")
    for macro, row in (("LayoutGainAreaReduction", rows[0]), ("LayoutOtaAreaReduction", rows[2])):
        summaries.append("\\newcommand{\\" + macro + "}{"
                         + f"{row['area_reduction_percent']:.1f}" + "}")
    (output / "layout-summary.tex").write_text("\n".join(summaries) + "\n")
    titles = ("High-gain op-amp", "Wideband op-amp", "Efficient OTA")
    timing, performance = [], []
    keys = (("gain_db", 1), ("gbw_mhz", 1), ("pm_deg", 1), ("power_uw", .001),
            ("cmrr_db", 1), ("buffer_gain_error", 100))
    for title, r in zip(titles, rows, strict=True):
        timing.append(f"{title} & {r['logical_mosfets']}/{r['physical_devices']} & "
                      f"{r['final_area_um2']:.0f} & {r['layout_drc_seconds']:.2f} & "
                      f"{r['optimization_seconds']:.2f} & {r['worker_seconds']:.2f} & "
                      f"{r['pex']['resistors']}/{r['pex']['capacitors']} & Pass " + chr(92)*2)
        cells = [f"{r['prelayout_metrics'][k]*scale:.2f}/{r['postlayout_metrics'][k]*scale:.2f}"
                 for k, scale in keys]
        performance.append(title + " & " + " & ".join(cells) + " " + chr(92)*2)
    for name, body in (("layout-timing.tex", timing), ("layout-metrics.tex", performance)):
        (output / name).write_text("\n".join([*body, r"\bottomrule"]) + "\n")
    colors = {
        "nwell": "#d3e5db",
        "pwell": "#ecd9e8",
        "ndiff": "#9aa557",
        "pdiff": "#dfbd66",
        "nmos": "#d06767",
        "pmos": "#d06767",
        "poly": "#d06767",
        "locali": "#ad998f",
        "metal1": "#8c9eba",
        "metal2": "#ac92bd",
        "metal3": "#5b9cbe",
        "metal4": "#b3975a",
        "metal5": "#cc8045",
    }
    plt.rcParams.update({"font.size": 8, "pdf.fonttype": 42})
    fig, axes = plt.subplots(2, 3, figsize=(11, 6), layout="constrained")
    for col, (ident, row) in enumerate(zip(IDS, rows, strict=True)):
        for ridx, name in enumerate(("initial-layout.mag", "layout.mag")):
            axis = axes[ridx, col]
            shapes = rectangles(directory / ident / name)
            x0, y0, x1, y1 = bounds(shapes)
            for layer, color in colors.items():
                rects = [
                    Rectangle((a * GRID, b * GRID), (c - a) * GRID, (d - b) * GRID)
                    for a, b, c, d in shapes.get(layer, [])
                ]
                axis.add_collection(
                    PatchCollection(
                        rects,
                        facecolor=color,
                        edgecolor="none",
                        alpha=0.45 if "well" in layer else 0.85,
                    )
                )
            axis.set(
                xlim=(x0 * GRID - 2, x1 * GRID + 2),
                ylim=(y0 * GRID - 2, y1 * GRID + 2),
                aspect="equal",
                xlabel="µm",
                ylabel="µm",
                title=f"{ident} · {'initial' if ridx == 0 else 'selected'}\n{row['initial_area_um2' if ridx == 0 else 'final_area_um2']:.0f} µm²",
            )
            axis.spines[["top", "right"]].set_visible(False)
    fig.savefig(output / "layout-comparison.png", dpi=180)
    fig.savefig(output / "layout-comparison.pdf")
    plt.close(fig)
    print("\n".join(lines))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path, nargs=3)
    parser.add_argument("--archive", type=Path, default=ROOT / "experiments/analog-layout")
    args = parser.parse_args()
    if args.runs:
        capture(args.runs, args.archive)
    report(args.archive)


if __name__ == "__main__":
    main()
