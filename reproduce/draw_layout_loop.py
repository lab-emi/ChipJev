"""Vector manuscript diagram of the implemented physical feedback path."""

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402


def draw(output):
    plt.rcParams.update({"font.family": "DejaVu Sans", "pdf.fonttype": 42})
    fig, ax = plt.subplots(figsize=(10, 3.6))
    fig.subplots_adjust(left=.01, right=.99, bottom=.015, top=.985)
    ax.set(xlim=(0, 10), ylim=(0, 3.5))
    ax.axis("off")
    xs, width, height = (.12, 2.62, 5.12, 7.62), 2.25, .7

    def box(col, y, title, detail, color="#e5f0f8"):
        x = xs[col]
        ax.add_patch(FancyBboxPatch((x, y), width, height,
                                   boxstyle="round,pad=0.025,rounding_size=.06",
                                   linewidth=.8, edgecolor="#577184", facecolor=color))
        ax.text(x+width/2, y+.49, title, ha="center", va="center", fontsize=10, weight="bold")
        ax.text(x+width/2, y+.22, detail, ha="center", va="center", fontsize=8.5, linespacing=1.3)

    def arrow(start, end, dashed=False):
        ax.add_patch(FancyArrowPatch(start, end, arrowstyle="-|>", mutation_scale=10,
                                    linewidth=1, color="#3c5263",
                                    linestyle="--" if dashed else "-"))

    box(0, 2.7, "Request", "Circuit objective\nSupply and load")
    box(1, 2.7, "Circuit search", "Laya topology prior\nGPU sizing + ngspice")
    box(2, 2.7, "Strict circuit screen", "Grid schematic + reference PEX\nShared input common mode")
    box(3, 2.7, "Fixed circuit", "Topology, sizing and bias\nStart layout budget")
    for col in range(3):
        arrow((xs[col]+width, 3.05), (xs[col+1]-.04, 3.05))

    box(0, 1.4, "PDK + goal contract", "Legal dimensions and actions\nExplicit measured bounds", "#edf3e7")
    box(1, 1.4, "Layout proposals", "Laya action probabilities\nIndependent exploration", "#dbeee8")
    box(2, 1.4, "Geometry compiler", "Groups, taps, rails, decap\nImmutable plan + reference", "#dbeee8")
    box(3, 1.4, "Physical checks", "Full DRC + property LVS\nDistributed RC PEX", "#dbeee8")
    for col in range(3):
        arrow((xs[col]+width, 1.75), (xs[col+1]-.04, 1.75))
    ax.plot([8.745, 8.745, 3.745], [2.7, 2.4, 2.4], color="#3c5263", linewidth=1)
    arrow((3.745, 2.4), (3.745, 2.16))

    box(1, .1, "Feedback", "Failures, margins, parasitics\nCost and remaining budget", "#f3eee3")
    box(2, .1, "Accept or roll back", "Qualified incumbent\nArea / GBW / noise Pareto", "#f3eee3")
    box(3, .1, "Fixed-condition ngspice", "OP / AC / transient\nNoise / PSRR / supply", "#f3eee3")
    arrow((8.745, 1.4), (8.745, .86))
    arrow((7.62, .45), (7.41, .45))
    arrow((5.12, .45), (4.91, .45))
    arrow((3.745, .82), (3.745, 1.36))
    ax.text(1.245, .46, "Optional, separate budgets:\nelectrical sizing refinement\ndevice corners / local mismatch",
            ha="center", va="center", fontsize=8, color="#405461", linespacing=1.5)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output)
    fig.savefig(output.with_suffix(".png"), dpi=170)
    plt.close(fig)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    draw(parser.parse_args().output)
