"""Archive three live runs, or regenerate the v4 physical demonstration report.

Capture once: python reproduce/report_layout.py --runs DIR DIR DIR
Rebuild:      python reproduce/report_layout.py [--paper ChipJev_arXiv]
This is a development demonstration, separate from the frozen benchmark studies.
"""

import argparse
import gzip
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IDS = ("opamp-gain", "opamp-speed", "ota-efficient")
LABELS = ("High-gain op-amp", "Wideband op-amp", "Efficient OTA")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def capture(runs, archive):
    import subprocess

    from chipjev.paths import magic
    from chipjev.simulation.pdk import REVISION, SHA256

    destination = archive / "results"
    if destination.exists():
        raise FileExistsError("Evidence exists; choose a fresh --archive instead of overwriting it")
    records = {json.loads((p / "result.json").read_text())["example"]["id"]: p for p in runs}
    if set(records) != set(IDS):
        raise ValueError("Supply exactly one completed run for each public prompt")
    for ident in IDS:
        source, target = records[ident], destination / ident
        record = json.loads((source / "result.json").read_text())
        if not record.get("source_sha256"):
            raise ValueError("Each final run must record its executed source hashes")
        for name, expected in record["source_sha256"].items():
            if digest(ROOT / name) != expected:
                raise ValueError(
                    f"Source changed after this run: {name}; capture a consistent release"
                )
        if not record["valid"]:
            raise ValueError(f"{ident} did not qualify; retain the failure and fix the flow first")
        target.mkdir(parents=True)
        for name in (
            "result.json",
            "physical.json",
            "decisions.json",
            "circuit.sch",
            "circuit.spice",
            "layout.mag",
            "layout.gds",
            "layout.svg",
            "pex.spice",
            "drc.txt",
            "lvs.log",
            "physical-evidence.zip",
            "ac.tsv",
            "buffer-1.tsv",
            "buffer--1.tsv",
        ):
            shutil.copy2(source / name, target / name)
        with gzip.GzipFile(filename=str(target / "search.json.gz"), mode="wb", mtime=0) as stream:
            stream.write((source / "search.json").read_bytes())
    source_paths = [
        *ROOT.glob("src/chipjev/**/*.py"),
        *ROOT.glob("demo/*.py"),
        ROOT / "scripts/setup-layout.sh",
        ROOT / "reproduce/report_layout.py",
    ]
    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "study": "Three development demonstrations after implementation tuning; not held-out or preregistered",
        "timing": "Worker monotonic wall time; includes model startup, search, schematic, physical verification; excludes network/browser latency",
        "magic": subprocess.check_output([magic(), "--version"], text=True).strip(),
        "magic_commit": subprocess.check_output([magic(), "--commit"], text=True).strip(),
        "sky130_archive_sha256": SHA256,
        "sky130_source_revision": REVISION,
        "source_sha256": {str(p.relative_to(ROOT)): digest(p) for p in sorted(source_paths)},
        "files": {
            str(p.relative_to(archive)): digest(p)
            for p in sorted(destination.rglob("*"))
            if p.is_file()
        },
    }
    (archive / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n")


def report(archive, paper):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import PatchCollection
    from matplotlib.patches import Rectangle

    from chipjev.layout.magic import GRID, bounds, rectangles

    manifest = json.loads((archive / "MANIFEST.json").read_text())
    for name, expected in manifest["files"].items():
        if digest(archive / name) != expected:
            raise ValueError(f"Evidence checksum mismatch: {name}")
    records = [
        json.loads((archive / "results" / ident / "result.json").read_text()) for ident in IDS
    ]
    output = archive / "report"
    output.mkdir(exist_ok=True)
    summary, timing_rows, metric_rows = [], [], []
    for label, record in zip(LABELS, records, strict=True):
        physical = record["physical"]
        layout, pex = physical["layout"], physical["pex"]
        pre, post = record["prelayout"]["metrics"], record["metrics"]
        assert record["valid"] and physical["valid"] and layout["drc_errors"] == 0
        assert physical["lvs"]["passed"] and all(physical["postlayout"]["checks"].values())
        row = {
            "prompt": record["example"]["id"],
            "topology": record["topology"],
            "mosfets": record["mosfets"],
            "fingers": sum(g["drawn"][2] for g in layout["geometry"].values()),
            "layout_seconds": layout["layout_seconds"],
            "physical_seconds": physical.get("all_physical_seconds", physical["total_seconds"]),
            "search_screening": physical.get("search_screening", {}),
            "total_seconds": record["demo_seconds"],
            "area_um2": layout["area_um2"],
            "resistors": pex["resistors"],
            "capacitors": pex["capacitors"],
            "prelayout": pre,
            "postlayout": post,
            "attempts": len(physical["recovery"]["attempts"]),
            "valid": True,
        }
        summary.append(row)
        timing_rows.append(
            f"{label} & {row['mosfets']}/{row['fingers']} & {row['area_um2']:.0f} & "
            f"{row['layout_seconds']:.2f} & {row['physical_seconds']:.2f} & "
            f"{row['total_seconds']:.2f} & {row['resistors']}/{row['capacitors']} & Pass \\"
        )

        def pair(key, scale=1):
            return f"{pre[key] * scale:.2f}/{post[key] * scale:.2f}"

        metric_rows.append(
            f"{label} & {pair('gain_db')} & {pair('gbw_mhz')} & {pair('pm_deg')} & "
            f"{pair('power_uw', 0.001)} & {pair('cmrr_db')} & "
            f"{pair('buffer_gain_error', 100)} \\"
        )
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    # Each table contains data only, so its surrounding caption describes scope.
    for name, rows in (("layout-timing.tex", timing_rows), ("layout-metrics.tex", metric_rows)):
        (output / name).write_text(
            "\n".join(row.rstrip(chr(92)) + chr(92) * 2 for row in rows) + "\n\\bottomrule\n"
        )
    macros = []
    for macro, key in (
        ("LayoutTime", "layout_seconds"),
        ("PhysicalTime", "physical_seconds"),
        ("DemoTime", "total_seconds"),
    ):
        values = [r[key] for r in summary]
        macros.append(
            f"\\newcommand{{\\{macro}}}{{{min(values):.2f}--{max(values):.2f}~s\\xspace}}"
        )
    (output / "layout-summary.tex").write_text("\n".join(macros) + "\n")
    markdown = [
        "# Physical demonstration measurements",
        "",
        "One fresh run per public prompt after development tuning. All three pass full Magic DRC, Netgen LVS and strict extracted ngspice checks.",
        "",
        "| Prompt | MOS/fingers | Area (µm²) | Layout + DRC (s) | Physical flow (s) | Whole worker (s) | R/C |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for label, row in zip(LABELS, summary, strict=True):
        markdown.append(
            f"| {label} | {row['mosfets']}/{row['fingers']} | {row['area_um2']:.0f} | {row['layout_seconds']:.2f} | {row['physical_seconds']:.2f} | {row['total_seconds']:.2f} | {row['resistors']}/{row['capacitors']} |"
        )
    markdown += [
        "",
        "Layout time includes PCell generation, placement, routing, full DRC, initial connectivity/capacitance extraction and GDS writing. Physical flow sums SVG, LVS, distributed RC extraction and strict ngspice for all early candidate screens and final sizing attempts. Candidate screens can overlap ongoing search; this cumulative time is not an extra term to add to whole-worker wall time. Total includes model loading and the live schematic workflow, but excludes browser/network time.",
        "",
        "Pre/post measurements use the same qualification rules and independent input-bias searches. Their differences include PDK grid quantization, physical passive models, diffusion geometry and extracted RC; they are not a parasitic-only ablation. Supply, ideal gate biases and 100 pF load are external. These nominal TT checks do not establish matching, PVT yield, or fabrication signoff.",
    ]
    (output / "README.md").write_text("\n".join(markdown) + "\n")
    plt.rcParams.update({"font.size": 8, "pdf.fonttype": 42})
    fig, axes = plt.subplots(1, 3, figsize=(7.15, 2.05), layout="constrained")
    colors = {
        "nwell": "#d9e8e3",
        "pwell": "#eadde9",
        "ndiff": "#84a753",
        "pdiff": "#c9b754",
        "poly": "#bd4b4b",
        "nmos": "#bd4b4b",
        "pmos": "#bd4b4b",
        "locali": "#999999",
        "metal1": "#6c83b4",
        "metal2": "#9469a6",
        "metal3": "#007bad",
        "metal4": "#be9141",
        "mimcap": "#42a5a5",
        "via": "#172a48",
        "via2": "#172a48",
        "via3": "#172a48",
    }
    for ax, ident, label, row in zip(axes, IDS, LABELS, summary, strict=True):
        shapes = rectangles(archive / "results" / ident / "layout.mag")
        for layer, color in colors.items():
            patches = [
                Rectangle((x * GRID, y * GRID), (u - x) * GRID, (v - y) * GRID)
                for x, y, u, v in shapes.get(layer, [])
            ]
            ax.add_collection(
                PatchCollection(patches, facecolor=color, edgecolor="none", alpha=0.75)
            )
        x0, y0, x1, y1 = bounds(shapes)
        ax.set_xlim((x0 - 150) * GRID, (x1 + 150) * GRID)
        ax.set_ylim((y0 - 150) * GRID, (y1 + 150) * GRID)
        ax.set_aspect("equal")
        ax.axis("off")
        ax.set_title(f"{label}\n{(x1 - x0) * GRID:.1f} × {(y1 - y0) * GRID:.1f} µm", fontsize=8)
        ax.text(
            0.5,
            -0.12,
            f"{row['layout_seconds']:.2f} s layout + DRC",
            transform=ax.transAxes,
            ha="center",
            va="top",
            fontsize=8,
        )
    fig.savefig(output / "physical-layouts.pdf", bbox_inches="tight")
    plt.close(fig)
    if paper:
        for name in ("layout-summary.tex", "layout-timing.tex", "layout-metrics.tex"):
            shutil.copy2(output / name, paper / "generated" / name)
        shutil.copy2(output / "physical-layouts.pdf", paper / "figures" / "physical-layouts.pdf")
    print(
        json.dumps(
            [{k: v for k, v in r.items() if k not in ("prelayout", "postlayout")} for r in summary],
            indent=2,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path, nargs=3)
    parser.add_argument("--archive", type=Path, default=ROOT / "experiments/layout")
    parser.add_argument("--paper", type=Path)
    args = parser.parse_args()
    if args.runs:
        capture(args.runs, args.archive)
    report(args.archive, args.paper)
