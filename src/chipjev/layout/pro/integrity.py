"""Logical-to-physical integrity of a pro-generator layout, checked before simulation.

The generator may re-finger a device (for the row height it chose) and adds
end dummies and MOS decoupling capacitors. Every such transformation is
declared in manifest.json before extraction; this check proves the declared
implementation is the schematic circuit plus harmless, explicitly typed
auxiliaries, and returns what the extracted-device mapping must find.
"""

import math
from collections import Counter

from ...circuits.sky130_devices import DEVICE

OFF = {"n": "vss", "p": "vdd"}
OPPOSITE = {"n": "vdd", "p": "vss"}
RAIL = {"n": "vss", "p": "vdd"}


def _norm(net):
    return "vss" if net == "0" else net


def validate(builder, manifest):
    """Return (expected finger count per logical MOS, Counter of auxiliary devices)."""
    logical = {name: (_norm(d), _norm(g), _norm(s), kind) for name, d, g, s, kind in builder.mos}
    widths = Counter()
    counts = Counter()
    auxiliaries = Counter()
    caps = Counter()
    resistors = {}
    for ident, entry in manifest["devices"].items():
        kind = entry["kind"]
        if kind == "c":
            _cap(builder, entry, caps)
            continue
        if kind == "r":
            resistors.setdefault(entry["logical"], []).append(entry)
            continue
        if kind not in ("n", "p") or entry["model"] != DEVICE[kind]:
            raise ValueError(f"Unsupported declared device {ident}")
        a, gate, b, bulk = entry["nets"]
        if bulk != RAIL[kind]:
            raise ValueError(f"{ident}: bulk is not on its rail")
        role = entry.get("role", "active")
        if entry["auxiliary"]:
            if a != b:
                raise ValueError(f"{ident}: an auxiliary finger must short its source and drain")
            if role == "dummy" and gate != OFF[kind]:
                raise ValueError(f"{ident}: dummy gate must hold the finger off")
            if role == "decap" and not (gate == OPPOSITE[kind] and a == RAIL[kind]):
                raise ValueError(f"{ident}: decap must sit between the two rails")
            if role not in ("dummy", "decap"):
                raise ValueError(f"{ident}: unknown auxiliary role {role}")
            auxiliaries[(entry["model"], (a, gate, b, bulk))] += 1
            continue
        name = entry["logical"]
        if name not in logical:
            raise ValueError("Manifest changed the logical circuit")
        d, g, s, lkind = logical[name]
        if lkind != kind or gate != g or {a, b} != {d, s}:
            raise ValueError(f"{ident}: finger terminals differ from {name}")
        width, length, _ = builder.geometry[name]
        if not math.isclose(entry["params"]["l"], max(0.15, round(length / 0.01) * 0.01), abs_tol=1e-7):
            raise ValueError(f"{ident}: gate length is not the quantized schematic length")
        widths[name] += entry["params"]["w"]
        counts[name] += 1
    if set(counts) != set(logical):
        raise ValueError("Manifest omits a logical MOS")
    for name, total in widths.items():
        width = builder.geometry[name][0]
        # Each finger is rounded to the 10 nm symmetric quantum (at most 5 nm per finger).
        if abs(total - width) > 0.005 * counts[name] + 1e-6 and not (width < 0.42 and total <= 0.42 + 1e-9):
            raise ValueError(f"{name}: physical width {total:.4f} um differs from {width:.4f} um")
    _check_caps(builder, caps)
    _check_resistors(builder, resistors)
    return dict(counts), auxiliaries


def _check_resistors(builder, resistors):
    """Each schematic resistor is one series chain of unit segments from a to b."""
    declared = {}
    for line in builder.lines:
        head = line.split()
        if head[0][0].lower() == "r":
            declared[head[0]] = (_norm(head[1]), _norm(head[2]), float(head[3]))
    if set(declared) != set(resistors):
        raise ValueError("Manifest resistors differ from the schematic")
    for name, (a, b, value) in declared.items():
        segments = resistors[name]
        degree = Counter(n for s in segments for n in s["nets"])
        ends = {n for n, d in degree.items() if d == 1}
        if ends != {a, b} or any(d > 2 for d in degree.values()) or len(degree) != len(segments) + 1:
            raise ValueError(f"{name}: segments are not one series chain from {a} to {b}")
        squares = sum(s["params"]["l"] / s["params"]["w"] for s in segments)
        if not math.isclose(squares * 48.2, value, rel_tol=0.03):
            raise ValueError(f"{name}: {squares * 48.2:.1f} ohm drawn for {value:.1f} ohm")


def _cap(builder, entry, caps):
    name = entry["logical"]
    w, length = entry["params"]["w"], entry["params"]["l"]
    caps[(name, tuple(sorted(entry["nets"])))] += (2.0 * w * length + 0.38 * (w + length)) * 1e-15


def _check_caps(builder, caps):
    declared = {}
    for line in builder.lines:
        head = line.split()
        if head[0][0].lower() == "c":
            declared[head[0]] = (tuple(sorted(_norm(n) for n in head[1:3])), float(head[3]))
    found = {name: (nets, value) for (name, nets), value in caps.items()}
    if set(found) != set(declared):
        raise ValueError("Manifest capacitors differ from the schematic")
    for name, (nets, value) in declared.items():
        if found[name][0] != nets:
            raise ValueError(f"{name}: capacitor terminals changed")
        if not math.isclose(found[name][1], value, rel_tol=0.02):
            raise ValueError(f"{name}: tiled capacitance {found[name][1]:.3e} F is not {value:.3e} F")
