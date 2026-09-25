"""Topologies published by AnalogCoder-Pro (IEEE TCAD 2026, arXiv 2508.02518v2, Fig. 10),
reconstructed from the figure so that they can be re-sized on this testbench with
AnalogCoder-Pro's own optimizer (baselines.tpe).

acpro_a  Fig. 10(a), the op-amp with its highest FoM (73.9 reported): NMOS differential
         pair with a PMOS mirror load and an NMOS tail; a common-source NMOS second stage
         with a PMOS current-source load and a Miller capacitor across it; a
         common-source NMOS output stage with a resistor load.
acpro_b  Fig. 10(b), a target-guided amplifier: a common-source NMOS input stage with a
         PMOS load; a cascoded NMOS common-source stage (PMOS cascode load, and a PMOS
         current source into its cascode node) bridged from input to output by a resistor;
         a CMOS-inverter output stage; capacitors from the output to the first- and
         second-stage outputs.
acpro_c  Fig. 10(c), a target-guided amplifier: a cascoded common-source input stage (PMOS
         load and cascode, NMOS cascode, NMOS input above an NMOS source device); a
         common-source NMOS stage with a PMOS current-source load; a CMOS-inverter output
         stage; Miller capacitors across the second and third stages.

The figure's shared bias nets (Vbias1..3) stay shared. The bias generator of (a)
(current source and mirrors) is replaced by ideal gate-bias sources, as everywhere in the
grammar, which only removes its bias-branch power. Device sizes are free parameters; the
paper gives none. Slot names follow the grammar's roles, so the same value ranges apply.
"""

from dataclasses import dataclass, field

from .grammar import VDD, Builder, library

__all__ = ["PUBLISHED", "Published", "lookup"]


@dataclass(frozen=True)
class Published:
    id: str
    cls: str
    slot_names: tuple
    construct: object = field(compare=False, repr=False)
    figure: str = ""

    @property
    def differential(self):
        return self.cls.startswith("opamp")

    def slots(self):
        return self.slot_names

    def build(self, values, vdd=VDD):
        missing = [s for s in self.slot_names if s not in values]
        if missing:
            raise KeyError(f"{self.id}: missing slots {missing}")
        b = Builder(vdd)
        self.construct(b, lambda slot: float(values[slot]))
        return b


def _acpro_a(b, v):
    l1, l2, l3 = v("1.L"), v("2.L"), v("3.L")
    b.mos_("n", "t1", b.gate("vb1", "n", v("1.vt")), "0", v("1.tail"), l1)  # M5
    b.mos_("n", "x1", "inp", "t1", v("1.in"), l1)  # M1
    b.mos_("n", "o1", "inn", "t1", v("1.in"), l1)  # M2
    b.mos_("p", "x1", "x1", "vdd", v("1.ld"), l1)  # M3 (diode)
    b.mos_("p", "o1", "x1", "vdd", v("1.ld"), l1)  # M4
    b.mos_("n", "o2", "o1", "0", v("2.in"), l2)  # M6
    b.mos_("p", "o2", b.gate("vb2", "p", v("2.vld")), "vdd", v("2.ld"), l2)  # M7
    b.cap("o1", "o2", v("c.cc"))  # Cc
    b.mos_("n", "out", "o2", "0", v("3.in"), l3)  # M8
    b.res("out", "vdd", v("3.R"))  # RL


def _acpro_b(b, v):
    l1, l2, l3 = v("1.L"), v("2.L"), v("3.L")
    vb1 = b.gate("vb1", "p", v("1.vld"))  # gates of M2, M4, M9
    b.mos_("n", "o1", "in", "0", v("1.in"), l1)  # M1
    b.mos_("p", "o1", vb1, "vdd", v("1.ld"), l1)  # M2
    b.res("o1", "o2", v("2.R"))  # R
    b.mos_("n", "s5", "o1", "0", v("2.in"), l2)  # M3
    b.mos_("p", "s5", vb1, "vdd", v("2.src"), l2)  # M4
    b.mos_("n", "o2", b.gate("vb2", "n", v("2.vcn")), "s5", v("2.cn"), l2)  # M5
    b.mos_("p", "o2", b.gate("vb3", "p", v("2.vcp")), "p6", v("2.cp"), l2)  # M6
    b.mos_("p", "p6", vb1, "vdd", v("2.ld"), l2)  # M9
    b.mos_("n", "out", "o2", "0", v("3.in"), l3)  # M7
    b.mos_("p", "out", "o2", "vdd", v("3.ld"), l3)  # M8
    b.cap("o1", "out", v("c.cc2"))  # C1
    b.cap("o2", "out", v("c.cc"))  # C2


def _acpro_c(b, v):
    l1, l2, l3 = v("1.L"), v("2.L"), v("3.L")
    vb1 = b.gate("vb1", "n", v("1.vcn"))  # gates of M9, M3 (NMOS) and M4 (PMOS)
    vb2 = b.gate("vb2", "p", v("1.vld"))  # gates of M2 and M6
    b.mos_("n", "s9", vb1, "0", v("1.snk"), l1)  # M9
    b.mos_("n", "s3", "in", "s9", v("1.in"), l1)  # M1
    b.mos_("n", "o1", vb1, "s3", v("1.cn"), l1)  # M3
    b.mos_("p", "o1", vb1, "p4", v("1.cp"), l1)  # M4
    b.mos_("p", "p4", vb2, "vdd", v("1.ld"), l1)  # M2
    b.mos_("n", "o2", "o1", "0", v("2.in"), l2)  # M5
    b.mos_("p", "o2", vb2, "vdd", v("2.ld"), l2)  # M6
    b.cap("o1", "o2", v("c.cc"))  # C1
    b.mos_("n", "out", "o2", "0", v("3.in"), l3)  # M7
    b.mos_("p", "out", "o2", "vdd", v("3.ld"), l3)  # M8
    b.cap("o2", "out", v("c.cc2"))  # C2


PUBLISHED = {
    t.id: t
    for t in (
        Published(
            "acpro_a",
            "opampN",
            ("1.in", "1.ld", "1.tail", "1.L", "1.vt", "2.in", "2.ld", "2.L", "2.vld")
            + ("3.in", "3.L", "3.R", "c.cc"),
            _acpro_a,
            "Fig. 10(a)",
        ),
        Published(
            "acpro_b",
            "ampN",
            ("1.in", "1.ld", "1.L", "1.vld", "2.in", "2.src", "2.cn", "2.cp", "2.ld", "2.L")
            + ("2.vcn", "2.vcp", "2.R", "3.in", "3.ld", "3.L", "c.cc", "c.cc2"),
            _acpro_b,
            "Fig. 10(b)",
        ),
        Published(
            "acpro_c",
            "ampN",
            ("1.in", "1.snk", "1.cn", "1.cp", "1.ld", "1.L", "1.vcn", "1.vld", "2.in", "2.ld")
            + ("2.L", "3.in", "3.ld", "3.L", "c.cc", "c.cc2"),
            _acpro_c,
            "Fig. 10(c)",
        ),
    )
}


def lookup(cls, topology_id):
    """A grammar topology of `cls` or a published one, by id."""
    if topology_id in PUBLISHED:
        topology = PUBLISHED[topology_id]
        if topology.cls != cls:
            raise ValueError(f"{topology_id} is a {topology.cls} topology, not {cls}")
        return topology
    return {t.id: t for t in library(cls)}[topology_id]
