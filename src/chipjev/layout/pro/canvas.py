"""Flat rectangle canvas that writes a Magic cell with a deterministic layer order."""

from collections import defaultdict

from . import tech as T

# Plain layers first, contacts after the layers they connect. Magic reads the
# file as a sequence of paints, so this order never lets a residue layer
# overwrite a contact.
ORDER = (
    "nwell",
    "ndiff",
    "pdiff",
    "psubdiff",
    "nsubdiff",
    "poly",
    "npolyres",
    "nmos",
    "pmos",
    "ndiffc",
    "pdiffc",
    "psubdiffcont",
    "nsubdiffcont",
    "polycont",
    "locali",
    "viali",
    "metal1",
    "metal2",
    "metal3",
    "metal4",
    "metal5",
    "via",
    "via2",
    "via3",
    "via4",
    "mimcap",
    "mimcapcontact",
)
METAL = {1: "metal1", 2: "metal2", 3: "metal3", 4: "metal4", 5: "metal5"}


class Canvas:
    def __init__(self):
        self.shapes = defaultdict(list)
        self.routes = []
        self.labels = []

    # Primitive painting -----------------------------------------------------
    def rect(self, layer, x0, y0, x1, y1):
        x0, x1 = sorted((int(x0), int(x1)))
        y0, y1 = sorted((int(y0), int(y1)))
        if x1 <= x0 or y1 <= y0:
            raise ValueError(f"Empty {layer} rectangle {(x0, y0, x1, y1)}")
        self.shapes[layer].append((x0, y0, x1, y1))
        return (x0, y0, x1, y1)

    def hwire(self, level, x0, x1, y, width, net=None):
        h = width // 2
        rect = self.rect(METAL[level], min(x0, x1), y - h, max(x0, x1), y - h + width)
        if net:
            self.routes.append(
                {"net": net, "layer": level, "length_um": T.um(abs(x1 - x0)),
                 "width_um": T.um(width), "direction": "h", "rect": rect}
            )
        return rect

    def vwire(self, level, x, y0, y1, width, net=None):
        h = width // 2
        rect = self.rect(METAL[level], x - h, min(y0, y1), x - h + width, max(y0, y1))
        if net:
            self.routes.append(
                {"net": net, "layer": level, "length_um": T.um(abs(y1 - y0)),
                 "width_um": T.um(width), "direction": "v", "rect": rect}
            )
        return rect

    # Vias -------------------------------------------------------------------
    def via1(self, x, y, m1="v", m2="h"):
        """Drawn via1 with the directional 0.03 um metal extensions."""
        h, e = T.V1 // 2, T.V1 // 2 + T.V1_SURR
        self.rect("via", x - h, y - h, x + h, y + h)
        self.rect("metal1", *((x - h, y - e, x + h, y + e) if m1 == "v" else (x - e, y - h, x + e, y + h)))
        self.rect("metal2", *((x - h, y - e, x + h, y + e) if m2 == "v" else (x - e, y - h, x + e, y + h)))

    def via2(self, x, y, m2="h"):
        h = T.V2 // 2
        e = h + T.V2_SURR_M2
        self.rect("via2", x - h, y - h, x + h, y + h)
        self.rect("metal2", *((x - e, y - h, x + e, y + h) if m2 == "h" else (x - h, y - e, x + h, y + e)))
        s = h + T.V2_SURR_M3
        self.rect("metal3", x - s, y - s, x + s, y + s)

    def via3(self, x, y, m3="v"):
        h = T.V3 // 2
        e = h + T.V3_SURR_M3
        self.rect("via3", x - h, y - h, x + h, y + h)
        self.rect("metal3", *((x - h, y - e, x + h, y + e) if m3 == "v" else (x - e, y - h, x + e, y + h)))
        s = h + T.V3_SURR_M4
        self.rect("metal4", x - s, y - s, x + s, y + s)

    def via1_row(self, x0, x1, y):
        """Evenly spaced via1 along a horizontal overlap [x0, x1]."""
        pitch = T.V1 + T.V1_SP + 4
        span = x1 - x0 - T.V1 - 2 * T.V1_SURR
        count = max(1, span // pitch + 1)
        start = (x0 + x1) // 2 - (count - 1) * pitch // 2
        for i in range(count):
            self.via1(start + i * pitch, y, m1="h", m2="h")

    def via2_row(self, x0, x1, y):
        pitch = T.V2 + T.V2_SP + 4
        span = x1 - x0 - T.V2 - 2 * T.V2_SURR_M2
        count = max(1, span // pitch + 1)
        start = (x0 + x1) // 2 - (count - 1) * pitch // 2
        for i in range(count):
            self.via2(start + i * pitch, y)

    # Composition ------------------------------------------------------------
    def merge(self, other, dx=0, dy=0):
        for layer, rects in other.shapes.items():
            self.shapes[layer].extend((a + dx, b + dy, c + dx, d + dy) for a, b, c, d in rects)
        for route in other.routes:
            a, b, c, d = route["rect"]
            self.routes.append({**route, "rect": (a + dx, b + dy, c + dx, d + dy)})
        for layer, x, y, net in other.labels:
            self.labels.append((layer, x + dx, y + dy, net))

    def bounds(self, layers=None):
        rects = [r for layer, group in self.shapes.items() if layers is None or layer in layers
                 for r in group]
        if not rects:
            return None
        return (min(r[0] for r in rects), min(r[1] for r in rects),
                max(r[2] for r in rects), max(r[3] for r in rects))

    def label(self, layer, x, y, net):
        self.labels.append((layer, int(x), int(y), net))

    def write_mag(self, path, ports):
        lines = ["magic", "tech sky130A", "magscale 1 2", "timestamp 0"]
        unknown = set(self.shapes) - set(ORDER)
        if unknown:
            raise ValueError(f"Unordered layers {sorted(unknown)}")
        for layer in ORDER:
            rects = self.shapes.get(layer)
            if rects:
                lines.append(f"<< {layer} >>")
                lines += ["rect " + " ".join(map(str, r)) for r in sorted(set(rects))]
        lines.append("<< labels >>")
        index = {net: i + 1 for i, net in enumerate(ports)}
        for layer, x, y, net in self.labels:
            lines.append(f"rlabel {layer} s {x} {y} {x} {y} 0 {net}")
            if net in index:
                lines.append(f"port {index[net]} nsew")
        lines.append("<< end >>")
        path.write_text("\n".join(lines) + "\n")
