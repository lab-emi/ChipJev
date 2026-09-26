"""Trunk-and-bus router over the placed arrays.

Every net rises from its metal2 straps / metal1 gate bars to vertical metal3
trunks; trunks of the same net that cannot share one x position are joined by
a horizontal metal4 bus. Symmetric nets get mirror-image trunk positions about
the first-stage axis (the lecture's "matched signals routed together, in the
same metal" and "dummy routes"), self-symmetric nets sit on the axis, and
unrelated nets avoid crossing matched arrays where they have a choice.
"""

from collections import defaultdict

TRUNK_W = 80  # 0.40 um metal3 trunk
TRUNK_PITCH = 150  # centre-to-centre clearance for metal3 trunks and via2 pads
BUS_W = 80
BUS_PITCH = 160
GRID = 10


class RoutingSpace(ValueError):
    """No free metal3 position: the caller widens routing channels and retries."""

    def __init__(self, net, item):
        super().__init__(f"No metal3 trunk position for {net} near x={item['x0']}..{item['x1']}")
        self.net, self.item = net, item


class Router:
    def __init__(self, canvas, circuit, floorplan, axis=0):
        self.c = canvas
        self.circuit = circuit
        self.fp = floorplan
        self.axis = axis
        self.trunks = []  # {"net", "x", "y0", "y1"}
        self.buses = []  # {"net", "y", "x0", "x1"}
        self.blocked = []  # (x0, y0, x1, y1) metal3 keep-outs (for example MIM plates)
        self.matched = []  # (x0, x1, y0, y1) of matched arrays
        self.attach = defaultdict(list)
        self.pins = {}

    # ------------------------------------------------------------ attachments
    def collect(self):
        for p in self.fp.placed:
            arr = p.array
            if p.unit is not None and p.unit.kind == "pair":
                b = p.bounds()
                self.matched.append((b[0], b[2], b[1], b[3], set(self._nets(p))))
            ex0, _, ex1, _ = p.bounds()
            # A trunk may land anywhere in the array's own envelope (array plus its
            # routing channels); straps and bars are extended in metal2 to reach it.
            lo, hi = ex0 + 60, ex1 - 60
            for pin in arr.pins["straps"]:
                x0, y0, x1, y1 = pin["rect"]
                self.attach[pin["net"]].append({
                    "kind": "strap", "x0": lo, "x1": hi, "y": pin["y"] + p.y,
                    "drawn": (x0 + p.x, x1 + p.x), "width": y1 - y0, "pol": arr.spec.polarity})
            for pin in arr.pins["bars"]:
                x0, y0, x1, y1 = pin["rect"]
                self.attach[pin["net"]].append({
                    "kind": "bar", "x0": lo, "x1": hi, "y": pin["y"] + p.y,
                    "drawn": (x0 + p.x, x1 + p.x), "width": y1 - y0, "pol": arr.spec.polarity})

    @staticmethod
    def _nets(p):
        s = p.array.spec
        return set(s.regions) | {f.gate for f in s.fingers}

    # ------------------------------------------------------------ placement
    def _free(self, x, y0, y1, net, ignore=None):
        for t in self.trunks:
            if t is ignore or t["net"] == net:
                continue  # metal of the same net may touch
            if abs(t["x"] - x) < TRUNK_PITCH and not (y1 + 130 < t["y0"] or t["y1"] + 130 < y0):
                return False
        for bx0, by0, bx1, by1 in self.blocked:
            if x + TRUNK_W // 2 + 120 > bx0 and x - TRUNK_W // 2 - 120 < bx1 and y1 > by0 and y0 < by1:
                return False
        return True

    def _crossing_cost(self, x, y0, y1, net):
        cost = 0
        for mx0, mx1, my0, my1, nets in self.matched:
            if mx0 <= x <= mx1 and y1 > my0 and y0 < my1 and net not in nets:
                cost += 1
        return cost

    def _choose(self, net, lo, hi, y0, y1, prefer=None):
        if y1 - y0 < 240:  # a short trunk is drawn at least 120 long (plus its margin)
            mid = (y0 + y1) // 2
            y0, y1 = mid - 120, mid + 120
        lo, hi = -(-lo // GRID) * GRID, hi // GRID * GRID
        if hi < lo:
            return None
        candidates = [x for x in range(lo, hi + 1, GRID) if self._free(x, y0, y1, net)]
        if not candidates:
            return None
        centre = (lo + hi) // 2 if prefer is None else prefer
        return min(candidates, key=lambda x: (self._crossing_cost(x, y0, y1, net), abs(x - centre)))

    @staticmethod
    def _stab(items):
        """Greedy interval stabbing: fewest trunk positions reaching every attachment."""
        groups = []
        for item in sorted(items, key=lambda a: a["x1"]):
            if groups and item["x0"] <= groups[-1]["hi"] and item["x1"] >= groups[-1]["lo"]:
                g = groups[-1]
                g["lo"], g["hi"] = max(g["lo"], item["x0"]), min(g["hi"], item["x1"])
                g["items"].append(item)
            else:
                groups.append({"lo": item["x0"], "hi": item["x1"], "items": [item]})
        return groups

    def _slack(self, net):
        groups = self._stab(self.attach[net])
        return min(g["hi"] - g["lo"] for g in groups) if groups else 0

    def route(self):
        self.collect()
        done = set()
        mirror = self.circuit.mirror

        def priority(net):
            partner = mirror.get(net)
            slack = self._slack(net)
            groups = len(self._stab(self.attach[net]))
            if partner and partner != net and partner in self.attach:
                slack = min(slack, self._slack(partner))
                groups = max(groups, len(self._stab(self.attach[partner])))
            # Supplies last (their rails are everywhere); multi-trunk nets, which
            # need long vertical spans to a bus, before single-trunk nets; then
            # the most constrained first.
            return (net in ("vdd", "vss"), -(groups > 1), slack, net)

        order = sorted(self.attach, key=priority)
        for net in order:
            if net in done:
                continue
            partner = mirror.get(net)
            if partner and partner != net and partner in self.attach and partner not in done:
                self._route_symmetric(net, partner)
                done.update((net, partner))
            else:
                self._route_net(net, axis=partner == net)
                done.add(net)
        if self.fp.plan.shield_inputs:
            self._shields()

    def _axis(self, items):
        return self.fp.axes.get(items[0].get("pol"), self.axis) if items else self.axis

    def _rail(self, net, lo, hi, y0, y1):
        """Nearest rail of a supply net that overlaps [lo, hi] in x, or None."""
        rails = [r for r in self.fp.rails if r["net"] == net
                 and r["rect"][0] + 40 <= hi and lo <= r["rect"][2] - 40]
        if not rails:
            return None
        return min(rails, key=lambda r: 0 if y0 <= r["y"] <= y1 else min(abs(r["y"] - y0), abs(r["y"] - y1)))

    def _plan_bus(self, net, groups):
        """Height of the metal4 bus joining several trunks: the median attachment height,
        moved to the nearest free track. Trunk spans are reserved down/up to it."""
        if len(groups) < 2 or net in ("vdd", "vss"):
            return None
        ys = sorted(a["y"] for g in groups for a in g["items"])
        x0 = min(g["lo"] for g in groups)
        x1 = max(g["hi"] for g in groups)
        return self._bus_track(ys[len(ys) // 2], x0, x1)

    def _route_net(self, net, axis=False, forced=None, bus_y=None):
        groups = self._stab(self.attach[net])
        placed = []
        if bus_y is None:
            bus_y = self._plan_bus(net, groups)
        for i, g in enumerate(groups):
            ys = [a["y"] for a in g["items"]] + ([bus_y] if bus_y is not None else [])
            y0, y1 = min(ys), max(ys)
            rail = None
            lo, hi = g["lo"], g["hi"]
            orphan = False
            if net in ("vdd", "vss"):
                # Reserve the span down/up to the rail before choosing x.
                r = self._rail(net, lo, hi, y0, y1)
                if r is None:
                    orphan = True  # this well has no such rail: bus to one later
                else:
                    lo, hi = max(lo, r["rect"][0] + 40), min(hi, r["rect"][2] - 40)
                    rail = r["y"]
                    y0, y1 = min(y0, rail), max(y1, rail)
            centre = self._axis(g["items"])
            prefer = forced[i] if forced else (centre if axis and lo <= centre <= hi else None)
            x = self._choose(net, lo, hi, y0 - 60, y1 + 60, prefer)
            if x is None and len(g["items"]) > 1:
                # One trunk cannot serve the group: one trunk per attachment, joined by a bus.
                for item in g["items"]:
                    iy0, iy1 = min(item["y"], bus_y if bus_y is not None else item["y"]), \
                        max(item["y"], bus_y if bus_y is not None else item["y"])
                    if rail is not None:
                        iy0, iy1 = min(iy0, rail), max(iy1, rail)
                    xi = self._choose(net, item["x0"], item["x1"], iy0 - 60, iy1 + 60)
                    if xi is None:
                        raise RoutingSpace(net, item)
                    placed.append(self._finish(net, xi, [item], rail, bus_y))
                continue
            if x is None:
                raise RoutingSpace(net, g["items"][0])
            placed.append(self._finish(net, x, g["items"], rail, bus_y))
            if orphan:
                placed[-1]["orphan"] = True
        if any(t.get("orphan") for t in placed) and not any(
                not t.get("orphan") for t in placed):
            placed.append(self._rail_trunk(net, placed))
        if len(placed) > 1:
            self._bus(net, placed, preferred=bus_y)
        return placed

    def _rail_trunk(self, net, trunks):
        """A short trunk standing on the nearest rail of ``net`` (other well), for a bus."""
        rails = [r for r in self.fp.rails if r["net"] == net]
        ty = sum(t["y0"] + t["y1"] for t in trunks) // (2 * len(trunks))
        tx = trunks[0]["x"]
        for r in sorted(rails, key=lambda r: (abs(r["y"] - ty), abs((r["rect"][0] + r["rect"][2]) // 2 - tx))):
            y0, y1 = sorted((r["y"], ty))
            lo, hi = r["rect"][0] + 40, r["rect"][2] - 40
            x = self._choose(net, lo, hi, y0 - 60, y1 + 60, prefer=lo if tx < lo else hi)
            if x is not None:
                self.c.via2(x, r["y"])
                trunk = {"net": net, "x": x, "y0": r["y"], "y1": r["y"]}
                self.trunks.append(trunk)
                return trunk
        raise RoutingSpace(net, {"x0": tx, "x1": tx})

    def _finish(self, net, x, items, rail, reach=None):
        trunk = self._trunk(net, x, items, reach)
        if rail is not None:
            self.c.via2(x, rail)
            trunk["y0"], trunk["y1"] = min(trunk["y0"], rail), max(trunk["y1"], rail)
        return trunk

    def _route_symmetric(self, a, b):
        """Mirror-image trunks about the axis when both nets allow it."""
        ga, gb = self._stab(self.attach[a]), self._stab(self.attach[b])
        bus_a = self._plan_bus(a, ga)
        bus_b = self._plan_bus(b, gb)
        self_axis = self._axis(self.attach[a])
        if len(ga) == len(gb) and self_axis == self._axis(self.attach[b]):
            saved, self.axis = self.axis, self_axis
            xs = []
            ok = True
            for g, h in zip(sorted(ga, key=lambda g: g["lo"]), sorted(gb, key=lambda g: -g["hi"])):
                lo = max(g["lo"], 2 * self.axis - h["hi"])
                hi = min(g["hi"], 2 * self.axis - h["lo"])
                ys = [i["y"] for i in g["items"] + h["items"]] + [y for y in (bus_a, bus_b) if y is not None]
                pick = None
                for x in sorted(range(-(-lo // GRID) * GRID, hi // GRID * GRID + 1, GRID),
                                key=lambda x: abs(x - (lo + hi) // 2)):
                    m = 2 * self.axis - x
                    if x != m and abs(x - m) >= TRUNK_PITCH and self._free(x, min(ys) - 60, max(ys) + 60, a) \
                            and self._free(m, min(ys) - 60, max(ys) + 60, b):
                        pick = x
                        break
                if pick is None:
                    ok = False
                    break
                xs.append(pick)
            if ok:
                ta = self._route_net(a, forced=xs, bus_y=bus_a)
                # b's groups run left to right, the mirror of a's right to left.
                tb = self._route_net(b, forced=[2 * self.axis - x for x in reversed(xs)], bus_y=bus_b)
                self.axis = saved
                return ta, tb
            self.axis = saved
        return self._route_net(a, bus_y=bus_a), self._route_net(b, bus_y=bus_b)

    def _trunk(self, net, x, items, reach=None):
        c = self.c
        ys = [a["y"] for a in items] + ([reach] if reach is not None else [])
        y0, y1 = min(ys), max(ys)
        for a in items:
            d0, d1 = a["drawn"]
            y = a["y"]
            if a["kind"] == "strap":
                if not d0 + 37 <= x <= d1 - 37:
                    # Run the strap out to the trunk inside the array's envelope.
                    end = d0 if x < d0 else d1
                    c.hwire(2, min(x, end) - 37, max(x, end) + 37, y, max(a["width"], 60), net)
                c.via2(x, y)
            else:
                if d0 + 32 <= x <= d1 - 32:
                    c.via1(x, y, m1="h", m2="h")
                else:
                    # Leave the metal1 bar at its end in metal2 (the bar ends are free
                    # of other metal2), then run to the trunk.
                    xv = d0 + 32 if x < d0 else d1 - 32
                    c.via1(xv, y, m1="h", m2="h")
                    # 0.26 um: inside the via pads' height, so the rail clearance holds.
                    c.hwire(2, min(x, xv) - 37, max(x, xv) + 37, y, 52, net)
                c.via2(x, y)
        if y1 - y0 < 120:
            # Metal3 minimum area: reserve the stretched extent now, so later
            # trunks at the same x keep their spacing from it.
            mid = (y0 + y1) // 2
            y0, y1 = mid - 60, mid + 60
        trunk = {"net": net, "x": x, "y0": y0, "y1": y1}
        self.trunks.append(trunk)
        return trunk

    def _bus(self, net, trunks, preferred=None):
        xs = [t["x"] for t in trunks]
        x0, x1 = min(xs), max(xs)
        lo = max(t["y0"] for t in trunks)
        hi = min(t["y1"] for t in trunks)
        centre = (lo + hi) // 2 if lo <= hi else (min(t["y1"] for t in trunks) + max(t["y0"] for t in trunks)) // 2
        if preferred is not None:
            centre = preferred

        def extensions_free(y):
            return all(self._free(t["x"], min(t["y0"], y) - 60, max(t["y1"], y) + 60, net, ignore=t)
                       for t in trunks)

        y = self._bus_track(centre, x0, x1, extensions_free)
        for t in trunks:
            t["y0"], t["y1"] = min(t["y0"], y), max(t["y1"], y)
            self.c.via3(t["x"], y)
        self.c.hwire(4, x0 - 40, x1 + 40, y, BUS_W, net)
        self.buses.append({"net": net, "y": y, "x0": x0 - 40, "x1": x1 + 40})

    def _bus_track(self, centre, x0, x1, extra=None):
        for k in range(0, 2000):
            for y in (centre + k * GRID, centre - k * GRID):
                if all(abs(b["y"] - y) >= BUS_PITCH or b["x1"] + 80 < x0 or x1 + 80 < b["x0"]
                       for b in self.buses) and (extra is None or extra(y)):
                    return y
        raise RoutingSpace("bus", {"x0": x0, "x1": x1})

    def add_bus(self, net, x_from, x_to, y, span=None):
        """A metal4 bus from the net's nearest trunk to an external terminal (passives).

        ``span`` bounds the heights at which the terminal can be reached; the
        chosen track height is returned so the caller can land on it.
        """
        trunks = [t for t in self.trunks if t["net"] == net]
        if not trunks:
            raise ValueError(f"No trunk to reach {net}")
        t = min(trunks, key=lambda t: abs(t["x"] - x_from))

        def ok(y):
            inside = span is None or span[0] <= y <= span[1]
            return inside and self._free(t["x"], min(t["y0"], y) - 60, max(t["y1"], y) + 60, net, ignore=t)

        y = self._bus_track(y, min(t["x"], x_to), max(t["x"], x_to), ok)
        t["y0"], t["y1"] = min(t["y0"], y), max(t["y1"], y)
        self.c.via3(t["x"], y)
        x0, x1 = sorted((t["x"], x_to))
        self.c.hwire(4, x0 - 40, x1, y, BUS_W, net)
        self.buses.append({"net": net, "y": y, "x0": x0 - 40, "x1": x1})
        return y

    def _shields(self):
        """Grounded metal3 lines on both sides of each input trunk, tied to a VSS rail."""
        rails = [r for r in self.fp.rails if r["net"] == "vss"]
        for t in [t for t in self.trunks if t["net"] in ("inp", "inn", "in")]:
            for side in (-1, 1):
                x = t["x"] + side * TRUNK_PITCH
                y0, y1 = t["y0"] - 100, t["y1"] + 100
                rail = min(rails, key=lambda r: min(abs(r["y"] - y0), abs(r["y"] - y1)))
                y0, y1 = min(y0, rail["y"]), max(y1, rail["y"])
                if not self._free(x, y0, y1, "vss"):
                    continue
                self.c.via2(x, rail["y"])
                self.trunks.append({"net": "vss", "x": x, "y0": y0, "y1": y1, "shield": t["net"]})

    def foreign_crossings(self):
        """Unrelated trunks that cross matched arrays (the lecture's 'no routing over matched gates')."""
        count = 0
        for t in self.trunks:
            for mx0, mx1, my0, my1, nets in self.matched:
                if mx0 <= t["x"] <= mx1 and t["y1"] > my0 and t["y0"] < my1 and t["net"] not in nets:
                    count += 1
        return count

    def draw_trunks(self):
        for t in self.trunks:
            # A single-attachment trunk still needs the metal3 minimum area (met3.6).
            if t["y1"] - t["y0"] < 120:
                mid = (t["y0"] + t["y1"]) // 2
                t["y0"], t["y1"] = mid - 60, mid + 60
            self.c.vwire(3, t["x"], t["y0"] - 33, t["y1"] + 33, TRUNK_W, t["net"])
