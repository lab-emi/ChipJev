"""Circuit structure a layout engineer reads off the schematic before drawing.

* matched pairs and the symmetric net map, grown from the differential inputs;
* the current-path level of every MOS (0 = source on its rail), which sets
  the row order from each rail inward;
* the stage of every MOS (first/differential stage versus later stages).

Equal sizing alone never implies matching: a pair needs symmetric nets.
"""

from dataclasses import dataclass, field

RAIL = {"n": "vss", "p": "vdd"}
OFF = {"n": "vss", "p": "vdd"}  # dummy gate level that keeps a finger off


def norm(net):
    return "vss" if net == "0" else net


@dataclass(frozen=True)
class Mos:
    name: str
    d: str
    g: str
    s: str
    kind: str
    w: float
    length: float
    nf: int

    @property
    def rail(self):
        return RAIL[self.kind]


@dataclass
class Circuit:
    devices: dict
    pairs: list  # (left device, right device), left on the inp/x1 half
    mirror: dict  # net -> symmetric net (both directions); self-symmetric nets map to themselves
    level: dict
    stage: dict
    bias: set
    passives: list  # (name, kind, a, b, value)
    ports: list
    notes: list = field(default_factory=list)


def _first_stage_count(topology):
    from ...circuits.grammar import _diff_stage
    from ...circuits.sky130_devices import Sky130Builder

    if not topology.differential:
        return 0
    probe = Sky130Builder()
    _diff_stage(probe, topology.stages[0], "o", lambda slot: 1.0)
    return len(probe.mos)


def analyse(builder, topology):
    devices = {}
    for name, d, g, s, kind in builder.mos:
        w, length, nf = builder.geometry[name]
        devices[name] = Mos(name, norm(d), norm(g), norm(s), kind, w, length, nf)
    first = _first_stage_count(topology)
    order = [m[0] for m in builder.mos]
    stage = {name: 1 if i < first else 2 for i, name in enumerate(order)}

    # Symmetric nets, grown to a fixpoint from the differential inputs.
    mirror = {"inp": "inn", "inn": "inp", "vdd": "vdd", "vss": "vss"}
    pairs, paired = [], set()

    def sym(a, b):
        return mirror.get(a) == b

    changed = True
    while changed:
        changed = False
        names = [n for n in order if n not in paired]
        for i, a in enumerate(names):
            if a in paired:
                continue
            for b in names[i + 1 :]:
                if b in paired:
                    continue
                A, B = devices[a], devices[b]
                if A.kind != B.kind or (A.w, A.length, A.nf) != (B.w, B.length, B.nf) or A.d == B.d:
                    continue
                terms = [(A.g, B.g), (A.s, B.s), (A.d, B.d)]

                def compatible(x, y):
                    # Equal, already symmetric, or two nets not yet classified.
                    return x == y or sym(x, y) or (x not in mirror and y not in mirror)

                # An anchor: a terminal pair already known to be symmetric halves.
                anchored = any(x != y and sym(x, y) for x, y in terms)
                if not anchored or not all(compatible(x, y) for x, y in terms):
                    continue
                left, right = (A, B) if _is_left(A, B, mirror) else (B, A)
                pairs.append((left.name, right.name))
                paired.update((a, b))
                for x, y in ((left.d, right.d), (left.s, right.s), (left.g, right.g)):
                    if x != y and mirror.get(x) != y:
                        mirror[x], mirror[y] = y, x
                        changed = True
                    elif x == y and x not in mirror:
                        mirror[x] = x
                        changed = True
                break
    # A mirror's common gate net is self-symmetric (for example x1 in ota5).
    for a, b in pairs:
        if devices[a].g == devices[b].g:
            mirror.setdefault(devices[a].g, devices[a].g)

    level = _levels(devices)
    passives = []
    for line in builder.lines:
        head = line.split()
        if head[0][0].lower() in "rc":
            name, a, b, value = head[:4]
            passives.append((name, head[0][0].lower(), norm(a), norm(b), float(value)))
    nets = {n for m in devices.values() for n in (m.d, m.g, m.s)} | {p[2] for p in passives} | {
        p[3] for p in passives
    }
    ports = sorted(nets | {"vdd", "vss"})
    return Circuit(devices, pairs, mirror, level, stage, {norm(b) for b in builder.bias},
                   passives, ports)


def _branch(a, b, mirror):
    """Same gate and source but drains on the two halves (a current-mirror pair)."""
    return mirror.get(a.d) == b.d


def _is_left(a, b, mirror):
    left = ("inp", "x1", "a1", "c1", "f1", "e1", "y1")
    for net in (a.g, a.d, a.s):
        if net in left:
            return True
    for net in (b.g, b.d, b.s):
        if net in left:
            return False
    return a.name < b.name


def _levels(devices):
    """Distance from the device's own rail along source-to-drain current paths."""
    level = {}
    remaining = dict(devices)
    frontier = {n for n, m in devices.items() if m.s == m.rail}
    for n in frontier:
        level[n] = 0
    current = 0
    while True:
        drains = {devices[n].d: devices[n].kind for n in level if level[n] == current}
        nxt = [
            n for n, m in remaining.items()
            if n not in level and drains.get(m.s) == m.kind
        ]
        if not nxt:
            break
        current += 1
        for n in nxt:
            level[n] = current
    # Anything left (source on a signal net driven by the other polarity, e.g. a
    # source follower) sits one row in from the rail.
    for n in devices:
        level.setdefault(n, 1)
    return level
