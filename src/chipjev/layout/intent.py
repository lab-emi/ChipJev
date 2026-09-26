"""Conservative, explicit analog groups derived from the connected circuit graph."""

from collections import defaultdict
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Group:
    id: str
    members: tuple[str, ...]
    kind: str
    role: str
    reason: str


def derive(builder):
    mos = {m[0]: m for m in builder.mos}
    available = set(mos)
    groups = []

    def add(names, role, reason):
        names = tuple(n for n in names if n in available)
        if not names:
            return
        groups.append(Group(f"g{len(groups)}", names, mos[names[0]][4], role, reason))
        available.difference_update(names)

    inputs = [m for m in builder.mos if m[2] in ("inp", "inn")]
    if (
        len(inputs) == 2
        and inputs[0][3:] == inputs[1][3:]
        and builder.geometry[inputs[0][0]] == builder.geometry[inputs[1][0]]
    ):
        add(
            [m[0] for m in inputs],
            "input_pair",
            "Differential gates, common source, equal geometry",
        )
    mirrors = defaultdict(list)
    for name, d, g, s, kind in builder.mos:
        if name in available:
            mirrors[(g, s, kind, builder.geometry[name])].append(name)
    for (gate, _, _, _), names in mirrors.items():
        if len(names) == 2 and any(mos[n][1] == gate for n in names):
            add(names, "current_mirror", "Common gate/source with a diode-connected reference")
    # Matched mirror loads of a current-mirror OTA have two distinct diode gates.
    branch_nodes = {m[1] for m in inputs}
    paired = defaultdict(list)
    for name, d, g, s, kind in builder.mos:
        if name in available and g in branch_nodes and d == g:
            paired[(s, kind, builder.geometry[name])].append(name)
    for names in paired.values():
        if len(names) == 2:
            add(names, "balanced_load", "Equal diode loads on the differential branches")
    for name, d, g, s, _ in builder.mos:
        if name in available:
            role = "output" if d == "out" else "bias" if g in builder.bias else "gain"
            add([name], role, "Circuit connectivity; no inferred matching constraint")
    nets = {n for m in builder.mos for n in m[1:4]}
    classes = {
        ("vss" if n == "0" else n): "power"
        if n in ("0", "vdd")
        else "input"
        if n in ("in", "inp", "inn")
        else "bias"
        if n in builder.bias
        else "signal"
        for n in sorted(nets)
    }
    return {
        "groups": [asdict(g) for g in groups],
        "net_classes": classes,
        "inference": "connectivity rules; equal sizing alone never implies matching",
    }
