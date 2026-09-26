"""Shared-diffusion MOS finger arrays: the device template of the professional generator.

One array is one continuous diffusion strip. Fingers share every source/drain
region with their neighbours; each region is contacted over its full height
(licon + li + mcon + metal1 strip), as the SKY130 PCells draw it. Gates are
joined by a continuous poly bar on the top and/or bottom side (one gate net
per side), contacted at every finger and strapped in metal1. End dummies are
real transistors that share the diffusion, with the gate tied off to the rail
through a poly tab that turns outward, away from the matched fingers.

Source/drain nets leave the array in one of two ways:
* ``rail``: metal1 strips run straight into the rail on the rail side (only
  for the rail net, and only when that side carries no metal1 gate bar);
* ``strap``: horizontal metal2 straps over the diffusion, via1 on each strip;
  a finger too narrow for its straps stacks them just outside the diffusion on a
  side without a gate bar (``strap_side``), with the metal1 strips extended under
  them (metal2 crosses the other nets' strips without contact).

Local frame: diffusion from x = 0 to ``length``, y = 0 to ``w`` (units).
"""

from dataclasses import dataclass, field

from . import tech as T
from .canvas import Canvas

STRAP_W = 60  # 0.30 um metal2 strap: hosts via1 (0.26 um) and via2 (0.28 um)
STRAP_MARGIN = 12
HEAD_OFFSET = 60  # dummy poly head centre beyond the diffusion end


@dataclass(frozen=True)
class Finger:
    gate: str
    device: str | None  # logical MOS, or None for dummy/decap fingers
    kind: str = "active"  # active | dummy | decap


@dataclass
class ArraySpec:
    polarity: str  # "n" or "p"
    w: int  # finger width (units)
    length: int  # gate length (units)
    fingers: list
    regions: list  # len(fingers) + 1 source/drain nets
    top_gate: str | None = None
    bottom_gate: str | None = None
    rail_net: str = "vss"
    strap_nets: list = field(default_factory=list)  # bottom to top
    rail_nets: set = field(default_factory=set)  # regions connected straight to the rail
    strap_width: int = STRAP_W
    name: str = "array"
    tap_ends: bool = False  # tall fingers: vertical tap columns at both ends (latch-up)
    strap_side: str | None = None  # None: straps over the diffusion; else "top"/"bottom" outside


def region_width(length, count):
    if count > 1 and length < T.MIN_EFFL:
        return T.REGION + T.even(T.MIN_EFFL - length)
    return T.REGION


def straps_fit(w, count, width=STRAP_W):
    return count * width + max(0, count - 1) * T.M2_SP + 2 * STRAP_MARGIN <= w


class MosArray:
    """Draw an ArraySpec; expose connection geometry for the router."""

    def __init__(self, spec):
        self.spec = spec
        s = spec
        if s.polarity not in ("n", "p"):
            raise ValueError("polarity must be n or p")
        if len(s.regions) != len(s.fingers) + 1:
            raise ValueError("Every finger needs a region on both sides")
        if s.w < 84 or s.length < T.POLY_W or s.w % 2 or s.length % 2:
            raise ValueError("Finger W/L below the PDK minimum or off the 10 nm quantum")
        self.rail_side = "bottom" if s.polarity == "n" else "top"
        self.canvas = Canvas()
        self.s = region_width(s.length, len(s.fingers))
        self.pitch = s.length + self.s
        self.length = len(s.fingers) * self.pitch + self.s
        self.pins = {"straps": [], "bars": [], "rail_strips": [], "dummy_heads": []}
        self._validate_nets()
        self._draw()

    # ------------------------------------------------------------------
    def _validate_nets(self):
        s = self.spec
        for side, net in (("top", s.top_gate), ("bottom", s.bottom_gate)):
            if net is None:
                continue
            if not any(f.gate == net and f.kind != "dummy" for f in s.fingers):
                raise ValueError(f"{side} gate bar {net} has no finger")
        for f in s.fingers:
            if f.kind != "dummy" and f.gate not in (s.top_gate, s.bottom_gate):
                raise ValueError(f"Finger gate {f.gate} has no gate bar")
        rail_bar = s.bottom_gate if self.rail_side == "bottom" else s.top_gate
        if s.rail_nets and rail_bar is not None:
            raise ValueError("Rail-strapped regions cannot cross a metal1 gate bar")
        if any(n != s.rail_net for n in s.rail_nets):
            raise ValueError("Only the rail net may be strapped into the rail")
        needed = {n for n in s.regions if n not in s.rail_nets}
        if set(s.strap_nets) != needed:
            raise ValueError(f"Strap nets {s.strap_nets} do not cover regions {sorted(needed)}")
        if s.strap_side is None and not straps_fit(s.w, len(s.strap_nets), s.strap_width):
            raise ValueError("Finger width cannot host the requested metal2 straps")
        if s.strap_side is not None and (s.top_gate if s.strap_side == "top" else s.bottom_gate):
            raise ValueError("Outside straps need a side without a gate bar")

    def region_x(self, j):
        return j * self.pitch

    def gate_x(self, i):
        return i * self.pitch + self.s

    def contact_x(self, j):
        return self.region_x(j) + (self.s - T.CONT) // 2

    def zone(self, side):
        """Distance from the diffusion edge to the far edge of a gate zone (or outside straps)."""
        base = self.bar_offset(side) + 66 if self._side_used(side) else T.ENDCAP
        return max(base, self.outside(side))

    def outside(self, side):
        """Distance from the diffusion edge to the far edge of outside straps (0: none)."""
        n = len(self.spec.strap_nets)
        if self.spec.strap_side != side or not n:
            return 0
        # The via1 metal1 pad reaches 2 units past its strap.
        return STRAP_MARGIN + n * self.spec.strap_width + (n - 1) * T.M2_SP + 2

    def _side_used(self, side):
        s = self.spec
        bar = s.top_gate if side == "top" else s.bottom_gate
        dummies = any(f.kind == "dummy" for f in s.fingers) and side == self.rail_side
        return bar is not None or dummies

    def bar_offset(self, side):
        s = self.spec
        net = s.top_gate if side == "top" else s.bottom_gate
        if net is None:
            return 31
        on = [i for i, f in enumerate(s.fingers) if f.gate == net and f.kind != "dummy"]
        first, last = min(on), max(on)
        crossing = any(
            s.fingers[i].gate != net or s.fingers[i].kind == "dummy" for i in range(first, last + 1)
        )
        # Other fingers end in a 0.13 um cap under this bar: keep 0.21 um poly space.
        return T.ENDCAP + T.POLY_SP if crossing else 31

    # ------------------------------------------------------------------
    def _draw(self):
        s, c = self.spec, self.canvas
        diff, gate, cont = ("ndiff", "nmos", "ndiffc") if s.polarity == "n" else ("pdiff", "pmos", "pdiffc")
        w, length = s.w, s.length
        for j in range(len(s.regions)):
            x0 = self.region_x(j)
            c.rect(diff, x0, 0, x0 + self.s, w)
            cx = self.contact_x(j)
            c.rect(cont, cx, T.DIFF_SURR, cx + T.CONT, w - T.DIFF_SURR)
            c.rect("locali", cx, T.DIFF_SURR - T.LI_SURR, cx + T.CONT, w - T.DIFF_SURR + T.LI_SURR)
            c.rect("viali", cx, T.DIFF_SURR, cx + T.CONT, w - T.DIFF_SURR)
            net = s.regions[j]
            if net in s.rail_nets:
                # Runs through the rail-side gate zone into the rail (joined by the row).
                y0, y1 = (-self.zone("bottom"), w) if self.rail_side == "bottom" else (0, w + self.zone("top"))
                strip = c.rect("metal1", cx - T.M1_SURR_MCON, y0, cx + T.CONT + T.M1_SURR_MCON, y1)
                self.pins["rail_strips"].append({"net": net, "rect": strip})
            else:
                c.rect("metal1", cx - T.M1_SURR_MCON, 0, cx + T.CONT + T.M1_SURR_MCON, w)
        for i, f in enumerate(s.fingers):
            x0 = self.gate_x(i)
            c.rect(gate, x0, 0, x0 + length, w)
            top = self._finger_poly_end(i, "top")
            bottom = self._finger_poly_end(i, "bottom")
            c.rect("poly", x0, w, x0 + length, w + top)
            c.rect("poly", x0, -bottom, x0 + length, 0)
        for side in ("top", "bottom"):
            self._gate_bar(side)
        self._dummy_heads()
        self._straps()

    def _finger_poly_end(self, i, side):
        s = self.spec
        f = s.fingers[i]
        bar = s.top_gate if side == "top" else s.bottom_gate
        if f.kind == "dummy":
            return self.bar_offset(side) + 66 if side == self.rail_side else T.ENDCAP
        if f.gate == bar:
            return self.bar_offset(side) + 33  # joins the bar
        return T.ENDCAP

    def _y(self, side, offset):
        """Map an offset measured outward from a diffusion edge to local y."""
        return self.spec.w + offset if side == "top" else -offset

    def _span(self, side, a, b):
        y0, y1 = self._y(side, a), self._y(side, b)
        return min(y0, y1), max(y0, y1)

    def _gate_bar(self, side):
        s, c = self.spec, self.canvas
        net = s.top_gate if side == "top" else s.bottom_gate
        if net is None:
            return
        g0 = self.bar_offset(side)
        on = [i for i, f in enumerate(s.fingers) if f.gate == net and f.kind != "dummy"]
        ext = max(0, (T.CONT + 2 * T.PC_SURR_ALL - s.length + 1) // 2)
        x0 = self.gate_x(on[0]) - ext
        x1 = self.gate_x(on[-1]) + s.length + ext
        y0, y1 = self._span(side, g0, g0 + 66)
        c.rect("poly", x0, y0, x1, y1)
        cy0, cy1 = self._span(side, g0 + 16, g0 + 50)
        centers = [self.gate_x(i) + s.length // 2 for i in on]
        for xc in centers:
            c.rect("polycont", xc - 17, cy0, xc + 17, cy1)
            c.rect("viali", xc - 17, cy0, xc + 17, cy1)
        lx0, lx1 = centers[0] - 17 - T.LI_SURR, centers[-1] + 17 + T.LI_SURR
        c.rect("locali", lx0, cy0, lx1, cy1)
        mx0, mx1 = centers[0] - 17 - T.M1_SURR_MCON_DIR, centers[-1] + 17 + T.M1_SURR_MCON_DIR
        bar = c.rect("metal1", mx0, cy0 - T.M1_SURR_MCON, mx1, cy1 + T.M1_SURR_MCON)
        self.pins["bars"].append({"net": net, "side": side, "rect": bar, "y": (cy0 + cy1) // 2})

    def _dummy_heads(self):
        s, c = self.spec, self.canvas
        side = self.rail_side
        g0 = self.bar_offset(side) if (s.bottom_gate if side == "bottom" else s.top_gate) else 31
        for i, f in enumerate(s.fingers):
            if f.kind != "dummy":
                continue
            if i not in (0, len(s.fingers) - 1):
                raise ValueError("Dummy fingers must terminate the array")
            left = i == 0
            gx = self.gate_x(i)
            xh = -HEAD_OFFSET if left else self.length + HEAD_OFFSET
            y0, y1 = self._span(side, g0, g0 + 66)
            # Poly tab from the dummy gate outward to the head (outside the bars' span).
            tab = (xh - 27, y0, gx + s.length, y1) if left else (gx, y0, xh + 27, y1)
            c.rect("poly", *tab)
            cy0, cy1 = self._span(side, g0 + 16, g0 + 50)
            c.rect("polycont", xh - 17, cy0, xh + 17, cy1)
            c.rect("viali", xh - 17, cy0, xh + 17, cy1)
            c.rect("locali", xh - 17 - T.LI_SURR, cy0, xh + 17 + T.LI_SURR, cy1)
            pad = c.rect("metal1", xh - 17 - T.M1_SURR_MCON_DIR, cy0 - T.M1_SURR_MCON,
                         xh + 17 + T.M1_SURR_MCON_DIR, cy1 + T.M1_SURR_MCON)
            self.pins["dummy_heads"].append({"net": s.rail_net, "rect": pad, "x": xh})

    def _straps(self):
        s, c = self.spec, self.canvas
        n = len(s.strap_nets)
        if not n:
            return
        sw = s.strap_width
        used = n * sw + (n - 1) * T.M2_SP
        free = s.w - used
        for k, net in enumerate(s.strap_nets):
            regions = [j for j, r in enumerate(s.regions) if r == net]
            xs = [self.contact_x(j) + T.CONT // 2 for j in regions]
            if s.strap_side is None:
                y = free // 2 + sw // 2 + k * (sw + T.M2_SP)  # centred stack over the diffusion
            else:
                offset = STRAP_MARGIN + k * (sw + T.M2_SP) + sw // 2
                y = self._y(s.strap_side, offset)
                y0, y1 = self._span(s.strap_side, 0, offset + sw // 2 + 2)
                for j in regions:  # the strip continues under the nearer straps to its own
                    cx = self.contact_x(j)
                    c.rect("metal1", cx - T.M1_SURR_MCON, y0, cx + T.CONT + T.M1_SURR_MCON, y1)
            for x in xs:
                c.via1(x, y, m1="v", m2="h")
            x0, x1 = min(xs) - 32, max(xs) + 32
            rect = c.rect("metal2", x0, y - sw // 2, x1, y - sw // 2 + sw)
            self.pins["straps"].append({"net": net, "rect": rect, "y": y})

    # ------------------------------------------------------------------
    def extent(self):
        """Local bounding box including gate zones and dummy heads (no rail)."""
        x0, y0, x1, y1 = self.canvas.bounds()
        return x0, y0, x1, y1
