"""Rows, rails, guard rings and decoupling fill around placed finger arrays.

Floorplan conventions (the way an analog layout engineer draws an op-amp):
* one well region per polarity: PMOS on top in an N-well, NMOS below;
* inside a region, rows follow the DC current path from the rail inward
  (level 0 next to the rail), so sources strap straight into their rail;
* every row owns a contacted tap strip on its rail side carrying a wide
  metal1 + metal2 rail; left/right tap strips close each region into a guard
  ring, and the two rings face each other as a double guard bar;
* the first stage is centred on one vertical symmetry axis; later stages sit
  in a column to its right; idle row area becomes MOS decoupling capacitance.
"""

import math
from dataclasses import dataclass, field

from . import tech as T
from .canvas import Canvas
from .mos import MosArray
from .planner import LU_FINGER_UM, SEG_UM, decap_spec

ARRAY_GAP = 120  # between arrays in a row (bounds to bounds)
RING_MARGIN = 60  # array bounds to ring tap diffusion
CORE_GAP = 360  # between the first-stage column and the output column
DECAP_L = 200  # 1.0 um decoupling fingers
DECAP_MIN_GAP = 400  # smallest idle gap worth filling (2 um)
ROW_UM = 2.6  # rails, taps and gate zones per shelf (estimate for the packing score)
SIDE_GAP = 400  # between side-by-side wells: P-tap ring, N-well spacing, N-tap ring


TRUNK_PITCH = 150  # must match router.TRUNK_PITCH
TAP_CLEAR = 60  # array bounds (incl. dummy heads) to a tap column
TAP_COLUMN = TAP_CLEAR + T.TAP_W  # one side's tap column envelope


@dataclass
class Placed:
    array: MosArray
    x: int  # translation of the array's local frame
    y: int = 0
    column: str = "core"
    unit: object = None
    pad: int = 0  # routing channel on each side (small arrays need room for trunks)

    def __post_init__(self):
        spec = self.array.spec
        nets = [n for n in dict.fromkeys(spec.strap_nets)]
        nets += [g for g in (spec.top_gate, spec.bottom_gate) if g and g not in nets]
        x0, _, x1, _ = self.array.extent()
        demand = (len(nets) + 1) * TRUNK_PITCH
        self.pad = max(0, demand - (x1 - x0)) // 2

    @property
    def taps(self):
        return TAP_COLUMN if self.array.spec.tap_ends else 0

    def extent(self):
        x0, y0, x1, y1 = self.array.extent()
        return x0 - self.pad - self.taps, y0, x1 + self.pad + self.taps, y1

    def bounds(self):
        x0, y0, x1, y1 = self.extent()
        return x0 + self.x, y0 + self.y, x1 + self.x, y1 + self.y


@dataclass
class Row:
    polarity: str
    level: int
    items: list = field(default_factory=list)
    diff_y: int = 0  # global y of the rail-side diffusion edge
    height: int = 0  # max finger width in the row

    @property
    def rail_side(self):
        return "bottom" if self.polarity == "n" else "top"


def side_needs(array, side, rail_net, tap_polarity):
    """Clearances from a diffusion edge to a tap strip / rail metal on ``side``.

    Returns (tap, metal): distances from the diffusion edge to the tap diffusion
    edge and to the rail metal edge that satisfy poly, contact, li, metal1 and
    metal2 rules for everything the array draws on that side.
    """
    spec = array.spec
    bar = spec.top_gate if side == "top" else spec.bottom_gate
    used = array.zone(side) > T.ENDCAP
    poly = array.zone(side)
    tap = max(T.DIFF_SP, poly + T.POLY_TAP)
    metal = T.M1_SP
    if used:
        g0 = array.bar_offset(side) if bar else 31
        # Poly contacts keep 0.235 um from P+ (a P tap counts, licon.9 + psdm.5a).
        pc = T.PC_PDIFF if tap_polarity == "n" else T.PC_DIFF
        tap = max(tap, g0 + 50 + pc, g0 + 50 + 10)
        if bar is not None and bar != rail_net:
            metal = max(metal, g0 + 60 + T.M1_SP, g0 + 61 + T.M2_SP)
    return tap, metal


class Item:
    """One unit sub-row: arrays that stay together, side by side (segments, mirror halves)."""

    def __init__(self, unit, placed):
        self.unit = unit
        self.placed = placed
        self.height = max(p.array.spec.w for p in placed)
        self.level = unit.level
        widths = [p.extent()[2] - p.extent()[0] for p in placed]
        self.width = sum(widths) + ARRAY_GAP * (len(placed) - 1)

    @property
    def priority(self):
        # Centre of the shelf: matched first-stage pairs, then first-stage singles.
        return (self.unit.stage != 1, self.unit.kind != "pair", -self.width)

    def place(self, x0):
        x = x0
        for p in self.placed:
            e0, _, e1, _ = p.extent()
            p.x = x - e0
            x += e1 - e0 + ARRAY_GAP


class Shelf:
    def __init__(self, first):
        self.items = [first]
        self.height = first.height

    @property
    def width(self):
        return sum(i.width for i in self.items) + ARRAY_GAP * (len(self.items) - 1)

    def place(self):
        """Centre-out about the symmetry axis x = 0."""
        order = sorted(self.items, key=lambda i: i.priority)
        centre = order[0]
        centre.place(-centre.width // 2)
        right = centre.width - centre.width // 2 + ARRAY_GAP
        left = -(centre.width // 2) - ARRAY_GAP
        for k, item in enumerate(order[1:]):
            if k % 2 == 0:
                item.place(right)
                right += item.width + ARRAY_GAP
            else:
                item.place(left - item.width)
                left -= item.width + ARRAY_GAP


def pack(items, target, mix=0.5):
    """Shelf packing: tallest first; an item joins a shelf if it fits and its
    height is at least ``mix`` times the shelf height (0 allows any height)."""
    shelves = []
    for item in sorted(items, key=lambda i: (-i.height, i.level, i.unit.stage)):
        for shelf in shelves:
            if shelf.width + ARRAY_GAP + item.width <= target and item.height >= mix * shelf.height:
                shelf.items.append(item)
                break
        else:
            shelves.append(Shelf(item))
    return shelves


class Floorplan:
    def __init__(self, units, plan, circuit, extra_tracks=0, side=(0, 0)):
        self.extra_tracks = extra_tracks
        self.plan = plan
        self.circuit = circuit
        self.canvas = Canvas()
        self.rows = {"n": {}, "p": {}}
        self.rails = []  # {"net", "rect" (metal2), "y"}
        self.placed = []
        self.decaps = []
        self.symmetric_axis = 0
        items = {"n": [], "p": []}
        for unit in units:
            column = "core" if unit.stage == 1 else "out"
            for specs in unit.rows:
                placed = []
                for spec in specs:
                    p = Placed(MosArray(spec), 0, 0, column, unit)
                    p.pad += extra_tracks * TRUNK_PITCH // 2
                    placed.append(p)
                items[unit.polarity].append(Item(unit, placed))
        shelves, self.arrangement = self._choose(items, side)
        for polarity, table in shelves.items():
            for index, shelf in enumerate(table):
                shelf.place()
                key = (min(i.level for i in shelf.items), index)
                row = Row(polarity, key)
                row.items = [p for item in shelf.items for p in item.placed]
                self.rows[polarity][key] = row
        self._arrange()
        self._fill_decap()
        self._place_y()
        self._draw()

    def _choose(self, items, side):
        """Scan shelf widths; keep the packing whose block (with the passive
        block of size ``side`` to its right) best matches the target aspect."""
        widest = max(i.width for group in items.values() for i in group)
        total = sum(i.width for group in items.values() for i in group)
        best = None
        for mix, k in ((m, k) for m in (0.5, 0.25, 0.0) for k in range(40)):
            target = widest * (1 + 0.12 * k)
            if k and target > total * 1.2:
                continue
            packed = {pol: pack(group, target, mix) for pol, group in items.items() if group}
            dims = {pol: (max(sh.width for sh in table) + 2 * RING_MARGIN + 2 * T.TAP_W,
                          sum(sh.height + T.u(ROW_UM) for sh in table))
                    for pol, table in packed.items()}
            # Mixed-height shelves waste area inside the shelf: charge for it.
            waste = sum(sh.width * sh.height - sum(i.width * i.height for i in sh.items)
                        for table in packed.values() for sh in table)
            layouts = [("stack", max(w for w, _ in dims.values()), sum(h for _, h in dims.values()))]
            if len(dims) == 2:
                layouts.append(("side", sum(w for w, _ in dims.values()) + SIDE_GAP,
                                max(h for _, h in dims.values())))
            for arrangement, width, height in layouts:
                span_w = width + (side[0] + 800 if side[0] else 0)
                span_h = max(height, side[1])
                ratio = span_w / span_h
                score = (span_w * span_h + 0.5 * waste) * (1 + 0.6 * abs(math.log(ratio / self.plan.aspect)))
                if best is None or score < best[0]:
                    best = (score, packed, arrangement)
        self.score = best[0]
        return best[1], best[2]

    def _arrange(self):
        """Place the two well regions (stacked or side by side); record their axes."""
        extent = {}
        for pol, rows in self.rows.items():
            placed = [p for r in rows.values() for p in r.items]
            if placed:
                extent[pol] = (min(p.bounds()[0] for p in placed), max(p.bounds()[2] for p in placed))
        shift = {pol: 0 for pol in extent}
        if self.arrangement == "side" and len(extent) == 2:
            # NMOS well on the left, N-well on the right, a vertical double guard between.
            shift["n"] = -extent["n"][1] - SIDE_GAP // 2 - RING_MARGIN - T.TAP_W
            shift["p"] = -extent["p"][0] + SIDE_GAP // 2 + RING_MARGIN + T.TAP_W
            for pol, rows in self.rows.items():
                for r in rows.values():
                    for p in r.items:
                        p.x += shift[pol]
            self.region_x = {pol: (e[0] + shift[pol], e[1] + shift[pol]) for pol, e in extent.items()}
        else:
            self.arrangement = "stack"
            x0 = min(e[0] for e in extent.values())
            x1 = max(e[1] for e in extent.values())
            self.region_x = {pol: (x0, x1) for pol in extent}
        self.axes = {pol: shift[pol] for pol in extent}

    # --------------------------------------------------------------- decaps
    def _fill_decap(self):
        if not self.plan.decap:
            return
        count = 0
        for polarity in ("n", "p"):
            for row in self.rows[polarity].values():
                items = sorted(row.items, key=lambda p: p.bounds()[0])
                w = max(p.array.spec.w for p in items)
                rx0, rx1 = self.region_x[polarity]
                edges = [rx0] + [v for p in items for v in (p.bounds()[0], p.bounds()[2])] + [rx1]
                gaps = [(edges[i], edges[i + 1]) for i in range(0, len(edges), 2)]
                tall = T.um(w) > LU_FINGER_UM
                for a, b in gaps:
                    x = a + ARRAY_GAP
                    while True:
                        room = b - ARRAY_GAP - x
                        if room < DECAP_MIN_GAP:
                            break
                        pitch = DECAP_L + T.REGION
                        span = min(room, T.u(SEG_UM)) if tall else room
                        fingers = (span - T.REGION - 2 * 40 - (2 * TAP_COLUMN if tall else 0)) // pitch
                        if fingers < 2:
                            break
                        spec = decap_spec(polarity, w, DECAP_L, fingers, f"decap{count}")
                        spec.tap_ends = tall
                        placed = Placed(MosArray(spec), 0, 0, "decap", None)
                        x0, _, x1, _ = placed.extent()
                        if x1 - x0 > room:
                            break
                        count += 1
                        placed.x = x - x0 if tall else (a + b) // 2 - (x0 + x1) // 2
                        row.items.append(placed)
                        self.decaps.append(placed)
                        if not tall:
                            break
                        x += x1 - x0 + ARRAY_GAP

    # --------------------------------------------------------------- y placement
    def _row_needs(self, row, side):
        """Clearance from this row's diffusion edges on ``side`` (max over items)."""
        rail = "vss" if row.polarity == "n" else "vdd"
        tap = metal = 0
        for p in row.items:
            a, m = side_needs(p.array, side, rail, row.polarity)
            tap, metal = max(tap, a), max(metal, m)
        return tap, metal

    def _rail_half(self, tap_need, metal_need):
        """Distance from a diffusion edge to the centre of a rail/tap strip."""
        rw = T.u(self.plan.rail_um)
        return max(tap_need + T.TAP_W // 2, metal_need + rw // 2)

    def _place_y(self):
        rw = T.u(self.plan.rail_um)
        self.strips = []  # (net, y centre, polarity)
        # NMOS region: rows upward from the bottom ring rail.
        y = 0
        self.strips.append(("vss", y, "n"))
        rows = [self.rows["n"][k] for k in sorted(self.rows["n"])]
        for i, row in enumerate(rows):
            row.height = max(p.array.spec.w for p in row.items)
            tap, metal = self._row_needs(row, "bottom")
            row.diff_y = y + self._rail_half(tap, metal)
            top_tap, top_metal = self._row_needs(row, "top")
            y = row.diff_y + row.height + self._rail_half(top_tap, top_metal)
            self.strips.append(("vss", y, "n"))
        n_top = y
        # Double guard bar: P-tap ring (VSS) and N-well ring (VDD) face each other.
        # ... and the two wells' metal3 power straps end-to-end need metal3 spacing.
        gap = max(T.PTAP_NWELL + T.NWELL_SURR + T.TAP_W, rw + T.M3_SP + 20, T.TAP_W + 2 * T.NWELL_SURR)
        y = n_top + gap if self.arrangement == "stack" else 0
        self.strips.append(("vdd", y, "p"))
        self.p_bottom = y
        prows = [self.rows["p"][k] for k in sorted(self.rows["p"], reverse=True)]
        # PMOS rows are listed from the inner (highest level) row up to the rail row.
        for i, row in enumerate(prows):
            row.height = max(p.array.spec.w for p in row.items)
            tap, metal = self._row_needs(row, "bottom")
            bottom = y + self._rail_half(tap, metal)
            top_tap, top_metal = self._row_needs(row, "top")
            row.diff_y = bottom + row.height  # rail-side (top) diffusion edge
            y = row.diff_y + self._rail_half(top_tap, top_metal)
            self.strips.append(("vdd", y, "p"))
        self.p_top = y
        self.n_top = n_top
        for polarity, rows_ in (("n", rows), ("p", prows)):
            for row in rows_:
                for p in row.items:
                    # Align the rail-side diffusion edge of every array in the row.
                    p.y = row.diff_y if polarity == "n" else row.diff_y - p.array.spec.w

    # --------------------------------------------------------------- drawing
    def _draw(self):
        c = self.canvas
        rw = T.u(self.plan.rail_um)
        placed = [p for rows in self.rows.values() for r in rows.values() for p in r.items]
        self.placed = placed
        self.ring = {}
        for pol, (x0, x1) in self.region_x.items():
            # Vertical ring strip centres, just outside the region's arrays.
            self.ring[pol] = (x0 - RING_MARGIN - T.TAP_W // 2, x1 + RING_MARGIN + T.TAP_W // 2)
        self.ring_x = (min(r[0] for r in self.ring.values()), max(r[1] for r in self.ring.values()))
        for p in placed:
            c.merge(p.array.canvas, p.x, p.y)
        for net, y, polarity in self.strips:
            if polarity not in self.ring:
                continue
            a, b = self.ring[polarity]
            self._tap_strip(net, y, polarity, a - T.TAP_W // 2, b + T.TAP_W // 2, rw)
        for polarity, (ya, yb) in (("n", (0, self.n_top)), ("p", (self.p_bottom, self.p_top))):
            if polarity not in self.ring:
                continue
            net = "vss" if polarity == "n" else "vdd"
            for xc in self.ring[polarity]:
                self._vertical_strip(net, xc, ya, yb, polarity)
        # Tap columns: tall-finger segments get taps on both ends, strip to strip.
        for p in placed:
            if not p.array.spec.tap_ends:
                continue
            pol = p.array.spec.polarity
            net = "vss" if pol == "n" else "vdd"
            ys = sorted(y for n, y, q in self.strips if n == net and q == pol)
            lo = max(y for y in ys if y < p.y)
            hi = min(y for y in ys if y > p.y + p.array.spec.w)
            ax0, _, ax1, _ = p.array.extent()
            for xc in (ax0 + p.x - TAP_CLEAR - T.TAP_W // 2, ax1 + p.x + TAP_CLEAR + T.TAP_W // 2):
                self._vertical_strip(net, xc, lo, hi, pol)
        self._power_straps(rw)
        # N-well over the whole PMOS region, including its ring.
        if "p" in self.ring:
            a, b = self.ring["p"]
            c.rect("nwell", a - T.TAP_W // 2 - T.NWELL_SURR, self.p_bottom - T.TAP_W // 2 - T.NWELL_SURR,
                   b + T.TAP_W // 2 + T.NWELL_SURR, self.p_top + T.TAP_W // 2 + T.NWELL_SURR)
        self._rail_links(placed)

    def _power_straps(self, rw):
        """Vertical metal3 power straps over both ring sides tie every row rail of a
        well together (a small power grid): supply current no longer flows along
        one rail from a single pin, which is source degeneration for high-current
        devices. The supply ports sit on these straps."""
        c = self.canvas
        width = max(T.u(1.0), rw)
        self.power_straps = []
        for polarity, (a, b) in self.ring.items():
            net = "vss" if polarity == "n" else "vdd"
            rails = [r for r in self.rails if r["net"] == net and r["polarity"] == polarity]
            if not rails:
                continue
            y0, y1 = min(r["y"] for r in rails), max(r["y"] for r in rails)
            for x in (a, b):
                strap = c.vwire(3, x, y0 - rw // 2, y1 + rw // 2, width, net)
                for r in rails:
                    # via2 array where the strap crosses each rail's metal2.
                    for dx in range(-(width // 2) + 60, width // 2 - 59, 90):
                        for dy in range(-(rw // 2) + 60, rw // 2 - 59, 90):
                            c.via2(x + dx, r["y"] + dy)
                self.power_straps.append({"net": net, "x": x, "rect": strap, "y0": y0, "y1": y1})

    def _tap_strip(self, net, y, polarity, x0, x1, rw):
        c = self.canvas
        diff, cont = ("psubdiff", "psubdiffcont") if polarity == "n" else ("nsubdiff", "nsubdiffcont")
        h = T.TAP_W // 2
        c.rect(diff, x0, y - h, x1, y + h)
        c.rect(cont, x0 + T.TAP_SURR, y - 17, x1 - T.TAP_SURR, y + 17)
        c.rect("locali", x0 + T.TAP_SURR - T.LI_SURR, y - 17, x1 - T.TAP_SURR + T.LI_SURR, y + 17)
        c.rect("viali", x0 + T.TAP_SURR, y - 17, x1 - T.TAP_SURR, y + 17)
        m1 = c.rect("metal1", x0, y - rw // 2, x1, y - rw // 2 + rw)
        m2 = c.rect("metal2", x0, y - rw // 2, x1, y - rw // 2 + rw)
        # Via1 rows stitch the stacked rails (low resistance, the lecture's "stack metals").
        rows = max(1, (rw - 2 * T.V1_SURR) // (T.V1 + T.V1_SP + 8))
        pitch = T.V1 + T.V1_SP + 8
        start = y - (rows - 1) * pitch // 2
        for r in range(rows):
            c.via1_row(x0 + 40, x1 - 40, start + r * pitch)
        self.rails.append({"net": net, "rect": m2, "m1": m1, "y": y, "polarity": polarity})

    def _vertical_strip(self, net, x, y0, y1, polarity):
        c = self.canvas
        diff, cont = ("psubdiff", "psubdiffcont") if polarity == "n" else ("nsubdiff", "nsubdiffcont")
        h = T.TAP_W // 2
        c.rect(diff, x - h, y0, x + h, y1)
        # Contacts stop short of the horizontal strips' contacts (licon spacing).
        cy0, cy1 = y0 + h + T.CONT + 20, y1 - h - T.CONT - 20
        if cy1 - cy0 >= T.CONT:
            c.rect(cont, x - 17, cy0, x + 17, cy1)
            c.rect("locali", x - 17, cy0 - T.LI_SURR, x + 17, cy1 + T.LI_SURR)
            c.rect("viali", x - 17, cy0, x + 17, cy1)
        c.rect("metal1", x - h, y0, x + h, y1)

    def _rail_links(self, placed):
        """Rail-strapped source strips and dummy heads drop straight into their rail."""
        c = self.canvas
        for p in placed:
            arr = p.array
            rail_y = self._nearest_rail(p)
            for pin in arr.pins["rail_strips"]:
                x0, y0, x1, y1 = pin["rect"]
                x0, x1 = x0 + p.x, x1 + p.x
                y0, y1 = y0 + p.y, y1 + p.y
                if arr.rail_side == "bottom":
                    c.rect("metal1", x0, rail_y, x1, y0 + 1)
                else:
                    c.rect("metal1", x0, y1 - 1, x1, rail_y)
            for pin in arr.pins["dummy_heads"]:
                x0, y0, x1, y1 = pin["rect"]
                # Full pad width: a narrower link would leave sub-rule notches beside it.
                if arr.rail_side == "bottom":
                    c.rect("metal1", x0 + p.x, rail_y, x1 + p.x, y1 + p.y)
                else:
                    c.rect("metal1", x0 + p.x, y0 + p.y, x1 + p.x, rail_y)

    def _nearest_rail(self, p):
        net = p.array.spec.rail_net
        edge = p.y if p.array.rail_side == "bottom" else p.y + p.array.spec.w
        ys = [y for n, y, pol in self.strips if n == net and pol == p.array.spec.polarity]
        if p.array.rail_side == "bottom":
            return max(y for y in ys if y < edge)
        return min(y for y in ys if y > edge)

    def bounds(self):
        return self.canvas.bounds()
