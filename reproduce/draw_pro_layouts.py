"""Render Magic layouts (layout.mag) as PNG panels with one consistent palette.

    python reproduce/draw_pro_layouts.py OUT.png "title=path/to/layout.mag" ...

Layers are drawn bottom-up with fixed colours, so layouts from different
generators compare like for like. The geometry is the exact cell Magic
checked; nothing is simplified except that contacts are drawn as squares.
"""

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.collections import PatchCollection  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

GRID = 0.005
STYLE = [  # (layers, face, edge, alpha)
    (("nwell",), "#2e4a2e", "#5c8a5c", 0.35),
    (("pwell",), "#4a2e4a", None, 0.0),
    (("psubdiff", "nsubdiff", "psubdiffcont", "nsubdiffcont"), "#c8a032", None, 0.85),
    (("ndiff", "pdiff", "ndiffc", "pdiffc"), "#3fa34d", None, 0.85),
    (("nmos", "pmos"), "#3fa34d", None, 0.85),
    (("poly", "polycont", "npolyres", "rpoly"), "#d64545", None, 0.9),
    (("locali",), "#8c6cc4", None, 0.35),
    (("metal1", "viali"), "#4a7fd6", None, 0.55),
    (("metal2", "via"), "#d670c7", None, 0.5),
    (("metal3", "via2"), "#35c4c4", None, 0.45),
    (("mimcap", "mimcapcontact"), "#2a9d8f", None, 0.6),
    (("metal4", "via3"), "#f2a541", None, 0.45),
    (("metal5", "via4"), "#e9e9e9", None, 0.3),
]


def rectangles(path):
    """Rectangles in 5 nm units: 'magscale 1 2' files already are; 'magscale 1 1' use 10 nm."""
    shapes, layer, factor = {}, None, 2
    for line in Path(path).read_text().splitlines():
        if line.startswith("magscale"):
            a, b = map(int, line.split()[1:3])
            factor = 2 * a // b
        elif line.startswith("<< "):
            layer = line[3:-3]
        elif line.startswith("rect "):
            x0, y0, x1, y1 = (int(v) * factor for v in line.split()[1:])
            shapes.setdefault(layer, []).append((x0, y0, x1, y1))
    return shapes


def draw(ax, path, title):
    shapes = rectangles(path)
    rects = [r for group in shapes.values() for r in group]
    x0, y0 = min(r[0] for r in rects), min(r[1] for r in rects)
    x1, y1 = max(r[2] for r in rects), max(r[3] for r in rects)
    for layers, face, edge, alpha in STYLE:
        patches = [Rectangle(((a - x0) * GRID, (b - y0) * GRID), (c - a) * GRID, (d - b) * GRID)
                   for layer in layers for a, b, c, d in shapes.get(layer, [])]
        if patches and alpha:
            ax.add_collection(PatchCollection(patches, facecolor=face, edgecolor=edge or "none",
                                              linewidth=0.3 if edge else 0, alpha=alpha))
    w, h = (x1 - x0) * GRID, (y1 - y0) * GRID
    ax.set_xlim(-0.02 * w, 1.02 * w)
    ax.set_ylim(-0.02 * h, 1.02 * h)
    ax.set_aspect("equal")
    ax.set_facecolor("#0d1117")
    ax.set_title(f"{title}\n{w:.1f} x {h:.1f} um = {w * h:,.0f} um$^2$", color="#e6edf3", fontsize=10)
    ax.tick_params(colors="#8b949e", labelsize=7)
    for spine in ax.spines.values():
        spine.set_color("#30363d")


def main(out, panels, columns=None):
    columns = columns or min(3, len(panels))
    rows = -(-len(panels) // columns)
    fig, axes = plt.subplots(rows, columns, figsize=(6 * columns, 5.2 * rows), facecolor="#0d1117",
                             squeeze=False)
    for ax, (title, path) in zip(axes.flat, panels):
        draw(ax, path, title)
    for ax in list(axes.flat)[len(panels):]:
        ax.axis("off")
    fig.tight_layout()
    fig.savefig(out, dpi=150, facecolor=fig.get_facecolor())


if __name__ == "__main__":
    items = [a.split("=", 1) for a in sys.argv[2:] if "=" in a]
    cols = next((int(a.split(":")[1]) for a in sys.argv[2:] if a.startswith("cols:")), None)
    main(sys.argv[1], items, cols)
