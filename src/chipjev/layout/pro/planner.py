"""From circuit structure to finger arrays: decomposition, patterns and orientation.

The plan knobs are the actions the goal-driven loop (and Laya) may take. Each
knob selects among professional templates, so every choice yields a
structurally sound layout; the EDA measurements decide which one is best.
"""

import hashlib
import json
import math
from dataclasses import asdict, dataclass, replace

from . import tech as T
from .analysis import OFF, RAIL
from .mos import ArraySpec, Finger, straps_fit

PATTERNS = ("abba", "mirror")


@dataclass(frozen=True)
class ProPlan:
    aspect: float = 1.0  # target block width / height; rows get finger widths to match
    max_finger_um: float = 12.0  # tallest finger (row height) the planner may use
    pair_pattern: str = "abba"  # abba: 1-D common centroid; mirror: two arrays about the axis
    dummies: bool = True  # end dummies on matched arrays
    single_dummies: bool = True  # end dummies on unmatched multi-finger arrays
    rail_um: float = 1.0  # horizontal power rail width (metal1 + metal2)
    decap: bool = True  # MOS decoupling capacitors in idle row area
    passives: str = "right"  # MIM/resistor block: right of the core or on top
    shield_inputs: bool = False  # grounded metal3 shields beside the input trunks
    pair_even: bool = True  # even finger counts on matched devices (balanced current direction)
    refinger: bool = False  # re-finger devices for the target aspect (requires re-qualification)

    def __post_init__(self):
        if self.pair_pattern not in PATTERNS:
            raise ValueError("Unknown pair pattern")
        if not 0.2 <= self.aspect <= 5:
            raise ValueError("Aspect ratio outside 0.2-5")
        if not 0.84 <= self.max_finger_um <= 25:
            raise ValueError("Finger width must stay within 0.84-25 um (latch-up tap distance)")
        if not 0.5 <= self.rail_um <= 3.0:
            raise ValueError("Rail width outside 0.5-3.0 um")
        if self.passives not in ("right", "top"):
            raise ValueError("Unknown passive placement")

    def to_dict(self):
        return asdict(self)

    @property
    def id(self):
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()[:16]

    def neighbors(self):
        """One-knob moves (the typed action space)."""
        moves = {
            "aspect": [v for v in (0.5, 0.75, 1.0, 1.5, 2.0) if v != self.aspect],
            "max_finger_um": [v for v in (3.0, 6.0, 12.0, 20.0) if v != self.max_finger_um],
            "pair_pattern": [p for p in PATTERNS if p != self.pair_pattern],
            "dummies": [not self.dummies],
            "single_dummies": [not self.single_dummies],
            "rail_um": [v for v in (0.6, 1.0, 2.0) if v != self.rail_um],
            "decap": [not self.decap],
            "passives": [p for p in ("right", "top") if p != self.passives],
            "shield_inputs": [not self.shield_inputs],
            "refinger": [not self.refinger],
        }
        for field, values in moves.items():
            for value in values:
                yield field, replace(self, **{field: value})


@dataclass
class Unit:
    """A placement unit: one matched pair or one single device, and its arrays.

    ``rows`` lists the sub-rows of the unit (more than one when a large device
    is folded into a 2-D array), each a left-to-right list of ArraySpec.
    """

    kind: str  # pair | single
    devices: tuple
    polarity: str
    level: int
    stage: int
    rows: list
    pattern: str
    fingers: dict  # device -> (count, finger width units, length units)


def quantize_length(l_um):
    return T.u(max(0.15, round(l_um / 0.01) * 0.01))


def decompose(w_um, target_um, even=False, window=(0.42, float("inf"))):
    """Finger count and width (units) near a target finger width.

    The finger width must stay inside ``window`` (the model bin of the
    schematic W/NF, so re-fingering never swaps the device's parameter set).
    """
    low, high = max(0.42, window[0]), window[1]
    feasible = [n for n in range(1, int(w_um / low) + 2)
                if low - 1e-9 <= round(w_um / n / 0.01) * 0.01 < high - 1e-9]
    if not feasible:
        feasible = [1]
    if even:
        feasible = [n for n in feasible if n % 2 == 0] or feasible
    count = min(feasible, key=lambda n: (abs(w_um / n - target_um), n))
    width = T.u(max(0.42, round(w_um / count / 0.01) * 0.01))
    return count, width


LU_FINGER_UM = 25.0  # taps on both row edges keep every point within 15 um (LU.2, LU.3)


def faithful(m, fold=1):
    """Schematic finger width and count per fold row (the simulated device, unchanged).

    Returns (count per row, width units, refingered=False) or None when the
    finger count does not divide into the requested fold rows. Fingers taller
    than the latch-up-safe height stay as simulated; their arrays are cut into
    short segments with tap columns instead (see segments()).
    """
    if m.nf % fold:
        return None
    width = round(m.w / m.nf / 0.01) * 0.01
    return m.nf // fold, T.u(max(0.42, width)), False


SEG_UM = 26.0  # longest array between tap columns for fingers taller than LU_FINGER_UM


def segments(count, w_um, l_um, pair):
    """Split one row's fingers into arrays short enough for end tap columns.

    Latch-up needs every diffusion point within 15 um of a tap. Rows carry
    taps above and below; fingers taller than ~25 um also need taps to the
    left and right, so the array is cut into segments of at most SEG_UM.
    Returns fingers per device for each segment (as equal as possible, even
    counts first so every segment stays a common-centroid ABBA).
    """
    if w_um <= LU_FINGER_UM:
        return [count]
    pitch = l_um + 0.29
    fit = max(1, int((SEG_UM - 0.29) / pitch) - 2)  # two end dummies
    per = max(1, fit // 2 if pair else fit)
    n = -(-count // per)
    base, extra = divmod(count, n)
    parts = [base + (1 if i < extra else 0) for i in range(n)]
    return parts


def bin_window(m, fold=1):
    """Allowed finger widths: the bin of the schematic W/NF (and each fold row keeps it)."""
    from .bins import bin_range

    return bin_range(m.kind, round(m.w / m.nf / 0.01) * 0.01)


def orient(sequence, terms, prefer):
    """Choose each finger's source/drain orientation so neighbours share a region.

    sequence: device names; terms: device -> (source net, drain net).
    Returns the len+1 region nets, or None when a diffusion break is required.
    Among valid paths prefer end regions in ``prefer`` (rail or source nets).
    """
    best = None
    for start in (0, 1):
        regions = []
        s, d = terms[sequence[0]]
        left, right = (s, d) if start == 0 else (d, s)
        regions += [left, right]
        ok = True
        for name in sequence[1:]:
            s, d = terms[name]
            if s == regions[-1]:
                regions.append(d)
            elif d == regions[-1]:
                regions.append(s)
            else:
                ok = False
                break
        if not ok:
            continue
        score = (regions[0] in prefer) + (regions[-1] in prefer)
        if best is None or score > best[0]:
            best = (score, regions)
    return None if best is None else best[1]


def _gate_sides(polarity, gates):
    """Single gate net: away from the rail. Two nets: first away, second on the rail side."""
    away, rail = ("top", "bottom") if polarity == "n" else ("bottom", "top")
    sides = {}
    for i, net in enumerate(gates):
        sides[net] = away if i == 0 else rail
    if len(gates) > 2:
        raise ValueError("An array can carry at most two gate nets")
    return sides


def build_array(name, polarity, w, length, sequence, circuit, dummies, prefer=(), tap_ends=False):
    devices = circuit.devices
    terms = {n: (devices[n].s, devices[n].d) for n in set(sequence)}
    rail = RAIL[polarity]
    regions = orient(sequence, terms, set(prefer) | {rail})
    if regions is None:
        return None
    fingers = [Finger(devices[n].g, n) for n in sequence]
    if dummies:
        fingers = [Finger(OFF[polarity], None, "dummy"), *fingers, Finger(OFF[polarity], None, "dummy")]
        regions = [regions[0], *regions, regions[-1]]
    gates = list(dict.fromkeys(devices[n].g for n in sequence))
    sides = _gate_sides(polarity, gates)
    top = next((g for g, s in sides.items() if s == "top"), None)
    bottom = next((g for g, s in sides.items() if s == "bottom"), None)
    rail_side = "bottom" if polarity == "n" else "top"
    rail_bar = bottom if rail_side == "bottom" else top
    rail_nets = {rail} if rail in regions and rail_bar is None else set()
    strap_nets = [n for n in dict.fromkeys(regions) if n not in rail_nets]
    spec = ArraySpec(polarity, w, length, fingers, regions, top_gate=top, bottom_gate=bottom,
                     rail_net=rail, strap_nets=strap_nets, rail_nets=rail_nets, name=name,
                     tap_ends=tap_ends)
    if not straps_fit(w, len(strap_nets)):
        # Too narrow for its straps (e.g. a 0.42 um cascode): stack them outside the
        # diffusion on a side without a gate bar, the rail side first.
        away = "top" if rail_side == "bottom" else "bottom"
        free = [side for side, bar in ((rail_side, rail_bar), (away, top if away == "top" else bottom))
                if bar is None]
        if not free:
            return None
        spec.strap_side = free[0]
    return spec


def pair_sequence(count, pattern):
    """Finger order (A/B) for a pair with ``count`` fingers per device."""
    if pattern == "abba":
        # An odd count cannot be exactly common-centroid in one row (the position
        # sums differ by an odd number); ABBA..AB reaches that one-pitch minimum and
        # keeps shared diffusion, and cross-coupled rows/segments cancel it. (A run
        # of three Bs cannot share diffusion, so A..AB..BA..A fell back to A|B.)
        return ["A", "B", "B", "A"] * (count // 2) + (["A", "B"] if count % 2 else [])
    raise ValueError(pattern)


ROW_OVERHEAD_UM = 2.4  # tap strip, rail and gate zones per row (height)
ARRAY_OVERHEAD_UM = 2.2  # dummies, heads and spacing per array (length)
FOLDS = (1, 2, 4)


def _blocks(circuit):
    """Pairs and singles with the row they belong to and their gate-pitch area."""
    blocks, done = [], set()
    for left, right in circuit.pairs:
        a = circuit.devices[left]
        pitch = T.um(quantize_length(a.length)) + 0.29
        blocks.append({"key": (left, right), "kind": a.kind, "level": _lvl(circuit, a, circuit.devices[right]),
                       "area": 2 * a.w * pitch, "wmax": a.w, "window": bin_window(a)})
        done.update((left, right))
    for name, m in circuit.devices.items():
        if name not in done:
            pitch = T.um(quantize_length(m.length)) + 0.29
            blocks.append({"key": (name,), "kind": m.kind, "level": circuit.level[name],
                           "area": m.w * pitch, "wmax": m.w, "window": bin_window(m)})
    return blocks


def row_targets(circuit, plan):
    """Finger width per row, and a fold count per large block, for one block width.

    Row length ~ sum(W * finger pitch) / finger width. For each fold choice the
    block width is scanned; the smallest area whose aspect ratio is closest to
    the plan's target wins. Folding splits a large block over 2 or 4 rows
    (a 2-D common-centroid array when it is a matched pair).
    """
    blocks = _blocks(circuit)
    total = sum(b["area"] for b in blocks)
    best = None
    for fold in FOLDS:
        folds = {}
        for b in blocks:
            f = fold if b["area"] >= 0.2 * total else 1
            if not plan.refinger and faithful(circuit.devices[b["key"][0]], f) is None:
                f = 1
            folds[b["key"]] = f
        if not plan.refinger:
            for b in blocks:
                count, w, _ = faithful(circuit.devices[b["key"][0]], folds[b["key"]])
                b["window"] = (T.um(w), T.um(w) + 0.01)  # the finger width is fixed
        rows = {}
        for b in blocks:
            f = folds[b["key"]]
            for sub in range(f):
                rows.setdefault((b["kind"], b["level"], sub), []).append((b, f))
        for k in range(80):
            width = 4.0 * 1.08**k
            height = longest = 0.0
            targets = {}
            for key, members in rows.items():
                area = sum(b["area"] / f for b, f in members)
                room = width - len(members) * ARRAY_OVERHEAD_UM
                wf = area / room if room > 1 else plan.max_finger_um
                wf = min(max(wf, 1.0), plan.max_finger_um)
                targets[key] = wf
                # Each block can only approach the row target inside its model bin.
                actual = [min(max(wf, b["window"][0]), b["window"][1] - 0.01, b["wmax"] / f)
                          for b, f in members]
                longest = max(longest, sum(b["area"] / f / w for (b, f), w in zip(members, actual))
                              + len(members) * ARRAY_OVERHEAD_UM)
                height += max(actual) + ROW_OVERHEAD_UM
            span = max(width, longest)
            score = span * height * (1 + 0.6 * abs(math.log(span / height / plan.aspect)))
            if best is None or score < best[0]:
                best = (score, targets, folds)
    return best[1], best[2]


def plan_units(circuit, plan, fold=None):
    """Placement units with finger arrays; wider fingers if straps do not fit.

    ``fold`` forces the fold count of the large blocks (the floorplan scores
    each choice); by default the row model picks it.
    """
    targets, folds = row_targets(circuit, plan)
    if fold is not None:
        total = sum(b["area"] for b in _blocks(circuit))
        for b in _blocks(circuit):
            f = fold if b["area"] >= 0.2 * total else 1
            if not plan.refinger and faithful(circuit.devices[b["key"][0]], f) is None:
                f = 1
            folds[b["key"]] = f
    units = []
    done = set()
    for left, right in circuit.pairs:
        a, b = circuit.devices[left], circuit.devices[right]
        fold = folds[(left, right)]
        key = (a.kind, _lvl(circuit, a, b), 0)
        units.append(_pair_unit(circuit, plan, a, b, targets[key], fold))
        done.update((left, right))
    for name, m in circuit.devices.items():
        if name not in done:
            fold = folds[(name,)]
            key = (m.kind, circuit.level[name], 0)
            units.append(_single_unit(circuit, plan, m, targets[key], fold))
    return units


def _pair_unit(circuit, plan, a, b, target, fold=1):
    length = quantize_length(a.length)
    for attempt in range(8):
        if plan.refinger:
            count, w = decompose(a.w / fold, target, even=plan.pair_even, window=bin_window(a))
            changed = True
        else:
            count, w, changed = faithful(a, fold)
        fingers = {a.name: (count * fold, w, length), b.name: (count * fold, w, length)}
        parts = segments(count, T.um(w), T.um(length), pair=True)
        tall = len(parts) > 1 or T.um(w) > LU_FINGER_UM
        if plan.pair_pattern == "abba":
            rows = []
            for sub in range(fold):
                row = []
                for k, n in enumerate(parts):
                    # Cross-coupled: ABBA and BAAB alternate over rows and segments.
                    first, second = (a, b) if (sub + k) % 2 == 0 else (b, a)
                    seq = [first.name if x == "A" else second.name for x in pair_sequence(n, "abba")]
                    tag = f"s{k}" if len(parts) > 1 else ""
                    spec = build_array(f"{a.name}{b.name}r{sub}{tag}", a.kind, w, length, seq, circuit,
                                       plan.dummies, tap_ends=tall)
                    if spec is None:
                        break
                    row.append(spec)
                if len(row) != len(parts):
                    break
                rows.append(row)
            if len(rows) == fold:
                return _unit("pair", (a, b), circuit, rows, "abba", fingers, changed)
        rows = []
        for sub in range(fold):
            order = (a, b) if sub % 2 == 0 else (b, a)
            row = []
            for m in order:
                for k, n in enumerate(parts):
                    tag = f"s{k}" if len(parts) > 1 else ""
                    row.append(build_array(f"{m.name}r{sub}{tag}", m.kind, w, length, [m.name] * n, circuit,
                                           plan.dummies, tap_ends=tall))
            if not all(row):
                break
            rows.append(row)
        if len(rows) == fold:
            return _unit("pair", (a, b), circuit, rows, "mirror", fingers, changed)
        if not plan.refinger:
            break
        target *= 1.6  # wider fingers leave room for the metal2 straps
    raise ValueError(f"No array template fits pair {a.name}/{b.name}")


def _single_unit(circuit, plan, m, target, fold=1):
    length = quantize_length(m.length)
    for attempt in range(8):
        if plan.refinger:
            count, w = decompose(m.w / fold, target, window=bin_window(m))
            changed = True
        else:
            count, w, changed = faithful(m, fold)
        parts = segments(count, T.um(w), T.um(length), pair=False)
        tall = len(parts) > 1 or T.um(w) > LU_FINGER_UM
        rows = []
        for sub in range(fold):
            row = []
            for k, n in enumerate(parts):
                dummies = plan.single_dummies and n > 1
                tag = (f"r{sub}" if fold > 1 else "") + (f"s{k}" if len(parts) > 1 else "")
                row.append(build_array(f"{m.name}{tag}", m.kind, w, length, [m.name] * n, circuit, dummies,
                                       tap_ends=tall))
            if not all(row):
                break
            rows.append(row)
        if len(rows) == fold:
            return _unit("single", (m,), circuit, rows, "single", {m.name: (count * fold, w, length)}, changed)
        if not plan.refinger:
            break
        target *= 1.6
    raise ValueError(f"No array template fits {m.name}")


def _unit(kind, devices, circuit, rows, pattern, fingers, changed):
    names = tuple(m.name for m in devices)
    level = max(circuit.level[n] for n in names)
    unit = Unit(kind, names, devices[0].kind, level, circuit.stage[names[0]], rows, pattern, fingers)
    unit.refingered = changed and any(
        fingers[m.name][0] != m.nf or abs(T.um(fingers[m.name][1]) - m.w / m.nf) > 0.006 for m in devices)
    return unit


def _lvl(circuit, a, b):
    return max(circuit.level[a.name], circuit.level[b.name])


def decap_spec(polarity, w, length, count, name):
    """MOS decoupling capacitor: gate on the opposite rail, all diffusion on the own rail."""
    rail = RAIL[polarity]
    gate = "vdd" if polarity == "n" else "vss"
    fingers = [Finger(gate, None, "decap") for _ in range(count)]
    regions = [rail] * (count + 1)
    top, bottom = (gate, None) if polarity == "n" else (None, gate)
    return ArraySpec(polarity, w, length, fingers, regions, top_gate=top, bottom_gate=bottom,
                     rail_net=rail, strap_nets=[], rail_nets={rail}, name=name)


def mim_tiles(value_f):
    """Equal unit tiles (<= 30 um) for a capacitor; returns (count, side units)."""
    tile_max = 2e-15 * 30**2 + 0.76e-15 * 30
    count = max(1, math.ceil(value_f / tile_max))
    side = (-0.76 + math.sqrt(0.76**2 + 8 * value_f / count / 1e-15)) / 4
    side = max(2.0, round(side * 100) / 100)
    return count, T.u(side)
