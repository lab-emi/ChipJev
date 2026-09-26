"""MIM capacitor arrays: equal unit tiles on one metal3 bottom plate.

Unit tiles (the lecture's matched R/C practice) are arranged as a near-square
grid. Their metal4 top plates are stitched into one mesh; the shared metal3
bottom plate carries a via3 tab for its terminal. By convention the bottom
plate, with its larger parasitic to the substrate, goes on the low-impedance
node of a Miller capacitor (the stage output), the top plate on the
high-impedance node.
"""

import math

from . import tech as T
from .canvas import Canvas

TAB = 480  # bottom-plate tab length (2.4 um)
LINK = 200  # top-plate stitch width


class MimArray:
    def __init__(self, name, top_net, bottom_net, count, side):
        self.name, self.top, self.bottom = name, top_net, bottom_net
        self.count, self.side = count, side
        self.cols = math.ceil(math.sqrt(count))
        self.rows = math.ceil(count / self.cols)
        self.canvas = Canvas()
        self.tiles = []
        self._draw()

    def _draw(self):
        c, s = self.canvas, self.side
        pitch = s + T.MIM_SP
        for k in range(self.count):
            i, j = divmod(k, self.cols)
            x, y = j * pitch, i * pitch
            c.rect("mimcap", x, y, x + s, y + s)
            c.rect("mimcapcontact", x + T.MIMCC_SURR, y + T.MIMCC_SURR, x + s - T.MIMCC_SURR,
                   y + s - T.MIMCC_SURR)
            c.rect("metal4", x + 12, y + 12, x + s - 12, y + s - 12)
            self.tiles.append((x, y))
        width = self.cols * pitch - T.MIM_SP
        height = self.rows * pitch - T.MIM_SP
        # One continuous metal4 top plate over the whole tile array: no notches
        # (wide-metal rules) and a low-resistance top terminal.
        full_rows = self.count // self.cols
        c.rect("metal4", 12, 12, width - 12, full_rows * pitch - T.MIM_SP - 12)
        if self.count % self.cols:
            last = full_rows * pitch
            c.rect("metal4", 12, last - T.MIM_SP - 12, (self.count % self.cols) * pitch - T.MIM_SP - 12,
                   last + s - 12)
        m = T.MIM_M3_SURR
        c.rect("metal3", -m, -m, width + m, height + m)
        # Bottom-plate tab: a metal3 strip along the whole left edge. The bus of
        # the bottom net lands wherever its track is; tap() drops the via3 there.
        self.tab = (-m - TAB, -m, -m, height + m)
        c.rect("metal3", *self.tab)
        self.bottom_pin = (-m - TAB // 2, height // 2)
        # Top plate: one sheet over the whole array; a bus reaching x > 12 at any
        # height inside the sheet connects.
        self.top_pin = (12, height // 2)
        self.width, self.height = width, height

    def tap(self, canvas, dx, dy, y):
        """Via3 stack from the bottom-plate tab up to a metal4 bus at height ``y``."""
        x = self.bottom_pin[0] + dx
        for offset in (-80, 80):
            canvas.via3(x + offset, y, m3="h")
        canvas.rect("metal4", x - 150, y - 40, x + 150, y + 40)

    def reference(self):
        um = T.um(self.side)
        return [
            f"X{self.name}_t{k} {self.top} {self.bottom} sky130_fd_pr__cap_mim_m3_1 w={um:.6g} l={um:.6g}"
            for k in range(self.count)
        ]

    def value_f(self):
        um = T.um(self.side)
        return self.count * (T.MIM_FF_PER_UM2 * um * um + 0.76 * um) * 1e-15


# ------------------------------------------------------------------------ resistors

RHO = 48.2  # generic poly sheet resistance used by the PDK PCell (ohm/square)
SEGMENT_UM = 20.0  # longest unit segment; longer resistors fold into a serpentine
SEG_GAP = 120  # 0.6 um between segment bodies
TAB_W = 120  # metal3 terminal tabs


def resistor_segments(value_ohm):
    """(count, width um, length um) of equal unit segments for a resistance."""
    width = max(0.5, math.ceil(1.65 * RHO / value_ohm * 100) / 100)
    total = value_ohm * width / RHO
    count = max(1, math.ceil(total / SEGMENT_UM))
    length = max(1.65, round(total / count * 100) / 100)
    return count, width, length


class ResistorArray:
    """Series chain of equal generic-poly unit segments (a serpentine), with
    metal3 terminal tabs on both sides so buses can land at any height."""

    def __init__(self, name, a, b, value, segment):
        self.name, self.a, self.b, self.value = name, a, b, value
        self.count, self.w_um, self.l_um = resistor_segments(value)
        self.canvas = Canvas()
        self.nodes = [a] + [f"{name}_n{k}" for k in range(1, self.count)] + [b]
        self._draw(segment)

    def _draw(self, segment):
        c = self.canvas
        x0, y0, x1, y1 = segment["bounds"]
        width = x1 - x0
        pitch = width + SEG_GAP
        pads = segment["pads"]  # (bottom pad, top pad) metal1 rectangles, local
        self.pads = []
        for k in range(self.count):
            dx = k * pitch - x0
            for layer, rects in segment["shapes"].items():
                for r in rects:
                    c.rect(layer, r[0] + dx, r[1], r[2] + dx, r[3])
            self.pads.append([tuple(v + (dx if i % 2 == 0 else 0) for i, v in enumerate(p)) for p in pads])
        # Serpentine: join top pads of segments (0,1), bottom pads of (1,2), ...
        # Each jumper carries the label of its internal chain node.
        for k in range(self.count - 1):
            side = 1 if k % 2 == 0 else 0
            p, q = self.pads[k][side], self.pads[k + 1][side]
            c.rect("metal1", p[0], p[1], q[2], p[3])
            c.label("metal1", (p[0] + q[2]) // 2, (p[1] + p[3]) // 2, self.nodes[k + 1])
        first = self.pads[0][0]
        last = self.pads[-1][0 if (self.count - 1) % 2 == 1 else 1]
        # Terminal tabs: metal3 strips left and right, joined by via1/via2 at the pads.
        self.tabs = []
        span0, span1 = y0 - 200, y1 + 200
        for pad, x in ((first, -TAB_W - 300), (last, self.count * pitch - SEG_GAP + 300)):
            px, py = (pad[0] + pad[2]) // 2, (pad[1] + pad[3]) // 2
            c.via1(px, py, m1="v", m2="h")
            c.hwire(2, min(px, x), max(px, x), py, 60)
            c.via2(x, py)
            tab = c.rect("metal3", x - TAB_W // 2, span0, x + TAB_W // 2, span1)
            self.tabs.append((x, tab))
        self.width = self.count * pitch - SEG_GAP
        self.height = y1 - y0

    def tap(self, canvas, dx, dy, index, y):
        x, _ = self.tabs[index]
        canvas.via3(x + dx, y, m3="v")

    def reference(self):
        # Magic extracts the generic poly resistor as a primitive R with a model.
        return [f"R{self.name}_s{k} {self.nodes[k]} {self.nodes[k + 1]} sky130_fd_pr__res_generic_po "
                f"w={self.w_um:.6g} l={self.l_um:.6g}" for k in range(self.count)]
