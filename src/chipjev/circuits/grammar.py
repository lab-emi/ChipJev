"""Typed building-block grammar for amplifier and op-amp topologies.

A topology is a sequence of stages drawn from a small library of textbook blocks plus
a compensation choice. Every block is written for one polarity and mirrored for the
other by swapping device types and supply rails, so NMOS- and PMOS-input variants share
one description. Sizes live in *role slots* (for example "2.in", the input transistor of
stage 2) that keep their meaning across topologies; the search moves sizes between
topologies through these slots.

The electrical conventions follow AnalogCoder-Pro's unified generation-and-optimization
tasks: 1.2 V supply, W between 1x and 500x L, ideal bias voltages, bulk tied to source.
"""

import itertools
import math
from dataclasses import dataclass, field

VDD = 1.2


def _geometric(low, high, count):
    """`count` geometrically spaced values from `low` to `high` (3 significant digits)."""
    return tuple(float(f"{low * (high / low) ** (k / (count - 1)):.3g}") for k in range(count))


# Levels per slot kind: the search grid, fine enough that rounding to it costs little
# against continuous sizing (about 16 levels per decade, 4 per octave of L, 10 mV biases).
# Baselines size on the same ranges with continuous values.
LEVELS = {
    "ratio": _geometric(1, 500, 44),  # W/L
    "length": _geometric(45, 720, 17),  # nm
    "bias": tuple(round(0.20 + 0.01 * i, 2) for i in range(81)),  # V, gate strength
    "res": _geometric(1, 200, 38),  # kOhm
    "cap": _geometric(0.1, 20, 38),  # pF
    "rz": _geometric(0.05, 5, 33),  # kOhm
}

# Slot suffix -> kind. Ratios: in(put), ld (load), cn/cp (NMOS/PMOS-side cascode),
# src/snk (current source/sink), tail, mir (mirror). Biases are gate strengths |Vgs|
# measured from each device's own rail (NMOS: V; PMOS: VDD - V).
SLOT_KIND = {
    "in": "ratio",
    "ld": "ratio",
    "cn": "ratio",
    "cp": "ratio",
    "src": "ratio",
    "snk": "ratio",
    "tail": "ratio",
    "L": "length",
    "vld": "bias",
    "vcn": "bias",
    "vcp": "bias",
    "vs": "bias",
    "vk": "bias",
    "vt": "bias",
    "R": "res",
    "cc": "cap",
    "cc2": "cap",
    "rz": "rz",
}

# Single-ended gain/buffer stages and the slots each uses (stage prefix added later).
SE_STAGES = {
    "r": ("in", "L", "R"),
    "diode": ("in", "ld", "L"),
    "cs": ("in", "ld", "L", "vld"),
    "cas": ("in", "cn", "ld", "L", "vcn", "vld"),
    "tele": ("in", "cn", "cp", "ld", "L", "vcn", "vcp", "vld"),
    "inv": ("in", "ld", "L"),
    "inv_cas": ("in", "cn", "cp", "ld", "L", "vcn", "vcp"),
    "fold": ("in", "src", "cp", "cn", "snk", "L", "vs", "vcp", "vcn", "vk"),
    "sf": ("in", "snk", "L", "vk"),
}
SYMMETRIC = {"inv", "inv_cas"}  # contain both device types driven by the input

# Differential-input, single-ended-output first stages.
DIFF_STAGES = {
    "ota5": ("in", "ld", "tail", "L", "vt"),
    "tele": ("in", "cn", "cp", "ld", "tail", "L", "vt", "vcn", "vcp"),
    "fc": ("in", "tail", "src", "cp", "cn", "snk", "L", "vt", "vs", "vcp", "vcn"),
    "cmota": ("in", "ld", "src", "snk", "tail", "L", "vt"),
    "rload": ("in", "tail", "L", "R", "vt"),
}

# Stage choices allowed after the first stage of multi-stage designs.
GAIN_STAGES = ("cs_n", "cs_p", "cas_n", "cas_p", "inv", "inv_cas")
BUFFERS = ("none", "sf_n", "sf_p")

CLASSES = {
    "amp1": "single-stage amplifier",
    "opamp1": "single-stage op-amp",
    "ampN": "multi-stage amplifier",
    "opampN": "multi-stage op-amp",
}


def _variants(names):
    out = []
    for name in names:
        out += [name] if name in SYMMETRIC else [f"{name}_n", f"{name}_p"]
    return tuple(out)


@dataclass(frozen=True)
class Topology:
    """One member of a class: ordered stages, optional buffer and a compensation."""

    cls: str
    stages: tuple  # e.g. ("ota5_n", "cs_p")
    buffer: str = "none"
    comp: str = "none"  # none | miller | miller_rz | miller2
    name: str = field(default="", compare=False)

    @property
    def id(self):
        parts = list(self.stages)
        if self.buffer != "none":
            parts.append(self.buffer)
        if self.comp != "none":
            parts.append(self.comp)
        return "+".join(parts)

    @property
    def differential(self):
        return self.cls.startswith("opamp")

    def slots(self):
        """Ordered role slots used by this topology."""
        names = []
        for k, stage in enumerate(self.stages, 1):
            kind = stage.rsplit("_", 1)[0] if stage not in SYMMETRIC else stage
            table = DIFF_STAGES if (k == 1 and self.differential) else SE_STAGES
            names += [f"{k}.{s}" for s in table[kind]]
        if self.buffer != "none":
            names += [f"b.{s}" for s in SE_STAGES["sf"]]
        if self.comp in ("miller", "miller_rz", "miller2"):
            names.append("c.cc")
        if self.comp == "miller_rz":
            names.append("c.rz")
        if self.comp == "miller2":
            names.append("c.cc2")
        return tuple(names)


def slot_kind(slot):
    return SLOT_KIND[slot.split(".", 1)[1]]


def library(cls):
    """All topologies of a class, in a fixed order."""
    if cls == "amp1":
        return tuple(
            Topology(cls, (s,))
            for s in _variants(("r", "diode", "cs", "cas", "tele", "inv", "inv_cas", "fold", "sf"))
        )
    if cls == "opamp1":
        return tuple(Topology(cls, (s,)) for s in _variants(DIFF_STAGES))
    result = []
    firsts = GAIN_STAGES if cls == "ampN" else _variants(DIFF_STAGES)
    for count in (2, 3):
        for rest in itertools.product(GAIN_STAGES, repeat=count - 1):
            comps = ("none", "miller", "miller_rz") + (("miller2",) if count == 3 else ())
            buffers = BUFFERS if cls == "ampN" else ("none",)
            for first in firsts:
                for buffer in buffers:
                    for comp in comps:
                        result.append(Topology(cls, (first, *rest), buffer, comp))
    return tuple(result)


# ---------------------------------------------------------------------------------------
# Netlist construction


class Builder:
    """Accumulates devices, bias sources and nodes of one design."""

    def __init__(self, vdd=VDD):
        self.vdd = vdd
        self.lines = []
        self.mos = []  # (name, drain, gate, source, type)
        self.bias = {}  # node -> volts
        self.nodes = {"vdd"}

    def mos_(self, kind, d, g, s, ratio, length_nm):
        name = f"m{len(self.mos) + 1}"
        length = length_nm * 1e-9
        width = ratio * length
        model = "nmos" if kind == "n" else "pmos"
        self.lines.append(f"{name} {d} {g} {s} {s} {model} W={width:.6g} L={length:.6g}")
        self.mos.append((name, d, g, s, kind))
        self.nodes.update(n for n in (d, g, s) if n != "0")

    def res(self, a, b, kohm):
        self.lines.append(f"r{len(self.lines) + 1} {a} {b} {kohm * 1e3:.6g}")
        self.nodes.update(n for n in (a, b) if n != "0")

    def cap(self, a, b, pf):
        self.lines.append(f"c{len(self.lines) + 1} {a} {b} {pf * 1e-12:.6g}")
        self.nodes.update(n for n in (a, b) if n != "0")

    def gate(self, node, kind, strength):
        """Bias node for a device of `kind` with gate strength |Vgs| from its rail."""
        volts = strength if kind == "n" else self.vdd - strength
        self.bias[node] = min(max(volts, 0.0), self.vdd)
        self.nodes.add(node)
        return node


def _rails(polarity):
    """(same kind, opposite kind, low rail, high rail) for an input device polarity."""
    return ("n", "p", "0", "vdd") if polarity == "n" else ("p", "n", "vdd", "0")


def _se_stage(b, k, stage, inp, out, v):
    """Single-ended stage k from node inp to node out; v(slot) gives physical values."""
    if stage in SYMMETRIC:
        kind, pol = stage, "n"
    else:
        kind, pol = stage.rsplit("_", 1)
    same, opp, low, high = _rails(pol)
    L = v(f"{k}.L")
    p = f"s{k}"
    if kind == "r":
        b.mos_(same, out, inp, low, v(f"{k}.in"), L)
        b.res(out, high, v(f"{k}.R"))
    elif kind == "diode":
        b.mos_(same, out, inp, low, v(f"{k}.in"), L)
        b.mos_(opp, out, out, high, v(f"{k}.ld"), L)
    elif kind == "cs":
        b.mos_(same, out, inp, low, v(f"{k}.in"), L)
        b.mos_(opp, out, b.gate(f"{p}ld", opp, v(f"{k}.vld")), high, v(f"{k}.ld"), L)
    elif kind == "cas":
        b.mos_(same, f"{p}a", inp, low, v(f"{k}.in"), L)
        b.mos_(same, out, b.gate(f"{p}cn", same, v(f"{k}.vcn")), f"{p}a", v(f"{k}.cn"), L)
        b.mos_(opp, out, b.gate(f"{p}ld", opp, v(f"{k}.vld")), high, v(f"{k}.ld"), L)
    elif kind == "tele":
        b.mos_(same, f"{p}a", inp, low, v(f"{k}.in"), L)
        b.mos_(same, out, b.gate(f"{p}cn", same, v(f"{k}.vcn")), f"{p}a", v(f"{k}.cn"), L)
        b.mos_(opp, out, b.gate(f"{p}cp", opp, v(f"{k}.vcp")), f"{p}c", v(f"{k}.cp"), L)
        b.mos_(opp, f"{p}c", b.gate(f"{p}ld", opp, v(f"{k}.vld")), high, v(f"{k}.ld"), L)
    elif kind == "inv":
        b.mos_("n", out, inp, "0", v(f"{k}.in"), L)
        b.mos_("p", out, inp, "vdd", v(f"{k}.ld"), L)
    elif kind == "inv_cas":
        b.mos_("n", f"{p}a", inp, "0", v(f"{k}.in"), L)
        b.mos_("n", out, b.gate(f"{p}cn", "n", v(f"{k}.vcn")), f"{p}a", v(f"{k}.cn"), L)
        b.mos_("p", out, b.gate(f"{p}cp", "p", v(f"{k}.vcp")), f"{p}c", v(f"{k}.cp"), L)
        b.mos_("p", f"{p}c", inp, "vdd", v(f"{k}.ld"), L)
    elif kind == "fold":
        b.mos_(same, f"{p}f", inp, low, v(f"{k}.in"), L)
        b.mos_(opp, f"{p}f", b.gate(f"{p}s", opp, v(f"{k}.vs")), high, v(f"{k}.src"), L)
        b.mos_(opp, out, b.gate(f"{p}cp", opp, v(f"{k}.vcp")), f"{p}f", v(f"{k}.cp"), L)
        b.mos_(same, out, b.gate(f"{p}cn", same, v(f"{k}.vcn")), f"{p}e", v(f"{k}.cn"), L)
        b.mos_(same, f"{p}e", b.gate(f"{p}k", same, v(f"{k}.vk")), low, v(f"{k}.snk"), L)
    elif kind == "sf":
        b.mos_(same, high, inp, out, v(f"{k}.in"), L)
        b.mos_(same, out, b.gate(f"{p}k", same, v(f"{k}.vk")), low, v(f"{k}.snk"), L)
    else:
        raise ValueError(stage)


def _diff_stage(b, stage, out, v):
    """Differential first stage from (inp, inn) to single-ended `out`, non-inverting
    from inp."""
    kind, pol = stage.rsplit("_", 1)
    same, opp, low, high = _rails(pol)
    L = v("1.L")
    tail = b.gate("s1t", same, v("1.vt"))
    b.mos_(same, "t1", tail, low, v("1.tail"), L)
    if kind == "ota5":
        b.mos_(same, "x1", "inp", "t1", v("1.in"), L)
        b.mos_(same, out, "inn", "t1", v("1.in"), L)
        b.mos_(opp, "x1", "x1", high, v("1.ld"), L)
        b.mos_(opp, out, "x1", high, v("1.ld"), L)
    elif kind == "tele":
        cn = b.gate("s1cn", same, v("1.vcn"))
        cp = b.gate("s1cp", opp, v("1.vcp"))
        b.mos_(same, "a1", "inp", "t1", v("1.in"), L)
        b.mos_(same, "a2", "inn", "t1", v("1.in"), L)
        b.mos_(same, "x1", cn, "a1", v("1.cn"), L)
        b.mos_(same, out, cn, "a2", v("1.cn"), L)
        b.mos_(opp, "x1", cp, "c1", v("1.cp"), L)
        b.mos_(opp, out, cp, "c2", v("1.cp"), L)
        b.mos_(opp, "c1", "x1", high, v("1.ld"), L)
        b.mos_(opp, "c2", "x1", high, v("1.ld"), L)
    elif kind == "fc":
        src = b.gate("s1s", opp, v("1.vs"))
        cp = b.gate("s1cp", opp, v("1.vcp"))
        cn = b.gate("s1cn", same, v("1.vcn"))
        b.mos_(same, "f1", "inp", "t1", v("1.in"), L)
        b.mos_(same, "f2", "inn", "t1", v("1.in"), L)
        b.mos_(opp, "f1", src, high, v("1.src"), L)
        b.mos_(opp, "f2", src, high, v("1.src"), L)
        b.mos_(opp, "x1", cp, "f1", v("1.cp"), L)
        b.mos_(opp, out, cp, "f2", v("1.cp"), L)
        b.mos_(same, "x1", cn, "e1", v("1.cn"), L)
        b.mos_(same, out, cn, "e2", v("1.cn"), L)
        b.mos_(same, "e1", "x1", low, v("1.snk"), L)
        b.mos_(same, "e2", "x1", low, v("1.snk"), L)
    elif kind == "cmota":
        b.mos_(same, "x1", "inp", "t1", v("1.in"), L)
        b.mos_(same, "x2", "inn", "t1", v("1.in"), L)
        b.mos_(opp, "x1", "x1", high, v("1.ld"), L)
        b.mos_(opp, "x2", "x2", high, v("1.ld"), L)
        b.mos_(opp, "y1", "x2", high, v("1.src"), L)
        b.mos_(opp, out, "x1", high, v("1.src"), L)
        b.mos_(same, "y1", "y1", low, v("1.snk"), L)
        b.mos_(same, out, "y1", low, v("1.snk"), L)
    elif kind == "rload":
        b.mos_(same, "x1", "inp", "t1", v("1.in"), L)
        b.mos_(same, out, "inn", "t1", v("1.in"), L)
        b.res("x1", high, v("1.R"))
        b.res(out, high, v("1.R"))
    else:
        raise ValueError(stage)


def build(topology, values, vdd=VDD):
    """Devices of a design. `values` maps every slot of the topology to a physical value
    (W/L ratio, L in nm, gate strength in V, kOhm, pF). Returns the Builder; the output
    node is always "out" and the input nodes are "in" or ("inp", "inn")."""
    if hasattr(topology, "construct"):  # a published topology (published.py)
        return topology.build(values, vdd)
    missing = [s for s in topology.slots() if s not in values]
    if missing:
        raise KeyError(f"{topology.id}: missing slots {missing}")

    def v(slot):
        return float(values[slot])

    b = Builder(vdd)
    count = len(topology.stages)
    gain_out = [f"o{k}" for k in range(1, count + 1)]
    if topology.buffer == "none":
        gain_out[-1] = "out"
    for k, stage in enumerate(topology.stages, 1):
        target = gain_out[k - 1]
        if k == 1 and topology.differential:
            _diff_stage(b, stage, target, v)
        else:
            source = "in" if k == 1 else gain_out[k - 2]
            _se_stage(b, k, stage, source, target, v)
    if topology.buffer != "none":
        _se_stage(b, "b", topology.buffer, gain_out[-1], "out", v)
    # Miller compensation across the last gain stage (and stage 2 for miller2).
    last_in = gain_out[-2] if count >= 2 else None
    last_out = gain_out[-1]
    if topology.comp == "miller":
        b.cap(last_out, last_in, v("c.cc"))
    elif topology.comp == "miller_rz":
        b.res(last_out, "cz", v("c.rz"))
        b.cap("cz", last_in, v("c.cc"))
    elif topology.comp == "miller2":
        b.cap(last_out, last_in, v("c.cc2"))
        b.cap(gain_out[-2], gain_out[-3], v("c.cc"))
    return b


def default_values(topology):
    """Mid-grid values for every slot (a neutral starting design)."""
    out = {}
    for slot in topology.slots():
        levels = LEVELS[slot_kind(slot)]
        out[slot] = levels[len(levels) // 2]
    return out


def level_count(slot):
    return len(LEVELS[slot_kind(slot)])


def value_of(slot, index):
    return LEVELS[slot_kind(slot)][int(index)]


def space_size(topology):
    return math.prod(level_count(s) for s in topology.slots())
