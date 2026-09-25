"""The topology grammar on the open SkyWater SKY130 PDK (sky130_fd_pr, TT, 1.8 V).

The grammar's role slots keep their normalized levels (chipjev.circuits.grammar.LEVELS), so
the search, its features and every baseline are unchanged; this builder maps the physical
values of a design to SKY130 devices:

* devices are the PDK's 1.8-V transistors, sky130_fd_pr__nfet_01v8 and __pfet_01v8,
  instantiated as in xschem (``.option scale=1u``, W and L in micrometres), with xschem's
  default diffusion geometry (0.29-um contacted diffusion) and bulks at the rails
  (NMOS to ground, PMOS to VDD) instead of the PTM grammar's bulk-to-source convention;
* L is the grammar length scaled by 150/45: 150 nm to 2.4 um on the same 17 levels;
* W = (W/L) x L, at least 0.42 um, split into fingers of at most 50 um (``wnflag=1``
  selects the model bin by W/NF);
* gate strengths |V_GS|, measured from each device's rail, map linearly from the grammar's
  0.20-1.00 V to 0.35-1.75 V, since SKY130 thresholds at 100 nA x W/L are about 0.55 V
  (NMOS) and 0.55-1.0 V (PMOS, rising with L), against 0.24 V for PTM 45 nm.

Resistors, capacitors and bias sources stay ideal, as in AnalogCoder-Pro's testbench.
"""

import math

from ..simulation.pdk import model_root
from .grammar import Builder, _diff_stage, _se_stage

VDD = 1.8
LENGTH_SCALE = 150.0 / 45.0
W_MIN_UM = 0.42
FINGER_MAX_UM = 50.0
CONTACT_UM = 0.29
STRENGTH_IN = (0.20, 1.00)  # grammar gate-strength range (V)
STRENGTH_OUT = (0.35, 1.75)  # SKY130 gate-strength range (V)
DEVICE = {"n": "sky130_fd_pr__nfet_01v8", "p": "sky130_fd_pr__pfet_01v8"}
CORNERS = ("tt", "ss", "ff", "sf", "fs")


def include_text(corner="tt"):
    """Model includes for the two transistors at a process corner (unmodified PDK files,
    Monte Carlo switches off), with xschem's scale and bin-selection options."""
    if corner not in CORNERS:
        raise ValueError(f"unknown SKY130 corner {corner!r}")
    root = model_root()
    spice = root / "libs.ref/sky130_fd_pr/spice"
    nfet = spice / f"sky130_fd_pr__nfet_01v8__{corner}.pm3.spice"
    pfet = spice / f"sky130_fd_pr__pfet_01v8__{corner}.corner.spice"
    if not nfet.exists() or not pfet.exists():
        raise FileNotFoundError("SKY130 models are missing; run scripts/setup.sh")
    names = [nfet, spice / "sky130_fd_pr__nfet_01v8__mismatch.corner.spice",
             pfet, spice / "sky130_fd_pr__pfet_01v8__mismatch.corner.spice"]
    lines = [
        ".option scale=1u wnflag=1",
        ".param MC_MM_SWITCH=0 MC_PR_SWITCH=0",
        ".param sky130_fd_pr__nfet_01v8__dlc_rotweak=0 sky130_fd_pr__pfet_01v8__dlc_rotweak=0",
        f'.include "{root / "libs.tech/ngspice/parameters/lod.spice"}"',
    ]
    lines += [f'.include "{path}"' for path in names]
    return "\n".join(lines)


def strength(value):
    """SKY130 gate strength for a grammar gate strength (linear map, same level count)."""
    (a, b), (c, d) = STRENGTH_IN, STRENGTH_OUT
    return c + (float(value) - a) * (d - c) / (b - a)


def geometry(ratio, length_nm):
    """(W total um, L um, fingers) of a grammar device."""
    length = float(length_nm) * LENGTH_SCALE / 1000.0
    width = max(float(ratio) * length, W_MIN_UM)
    fingers = max(1, math.ceil(width / FINGER_MAX_UM - 1e-9))
    return width, length, fingers


def diffusion(width, fingers):
    """xschem's default drain/source areas and perimeters (um^2, um) for W and NF."""
    wf = width / fingers
    drains, sources = (fingers + 1) // 2, (fingers + 2) // 2
    return {
        "ad": drains * wf * CONTACT_UM,
        "as": sources * wf * CONTACT_UM,
        "pd": 2 * drains * (wf + CONTACT_UM),
        "ps": 2 * sources * (wf + CONTACT_UM),
        "nrd": CONTACT_UM / width,
        "nrs": CONTACT_UM / width,
    }


def probe(name, kind, quantity):
    """ngspice vector of an operating-point quantity of a SKY130 device instance."""
    return f"@m.x{name}.m{DEVICE[kind]}[{quantity}]"


class Sky130Builder(Builder):
    """Builder whose devices are SKY130 transistors (see the module notes)."""

    def __init__(self, vdd=VDD):
        super().__init__(vdd)
        self.geometry = {}  # device name -> (W um, L um, fingers)

    def mos_(self, kind, d, g, s, ratio, length_nm):
        name = f"m{len(self.mos) + 1}"
        width, length, fingers = geometry(ratio, length_nm)
        bulk = "0" if kind == "n" else "vdd"
        extra = " ".join(f"{k}={v:.6g}" for k, v in diffusion(width, fingers).items())
        self.lines.append(
            f"x{name} {d} {g} {s} {bulk} {DEVICE[kind]} w={width:.6g} l={length:.6g} "
            f"nf={fingers} {extra} sa=0 sb=0 sd=0 mult=1"
        )
        self.mos.append((name, d, g, s, kind))
        self.geometry[name] = (width, length, fingers)
        self.nodes.update(n for n in (d, g, s) if n != "0")

    def gate(self, node, kind, value):
        return super().gate(node, kind, strength(value))


def build(topology, values, vdd=VDD):
    """SKY130 devices of a grammar design (the grammar's build with Sky130Builder)."""
    if hasattr(topology, "construct"):  # a published topology (published.py)
        b = Sky130Builder(vdd)
        topology.construct(b, lambda slot: float(values[slot]))
        return b
    missing = [s for s in topology.slots() if s not in values]
    if missing:
        raise KeyError(f"{topology.id}: missing slots {missing}")

    def v(slot):
        return float(values[slot])

    b = Sky130Builder(vdd)
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
