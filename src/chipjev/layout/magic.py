"""Deterministic SKY130 primitive placement and channel routing in Magic.

The layout is actual PDK material, including contacts, wells and guard rings.
Every net has one label on a physically connected M3 trunk.  No repeated labels
are used to substitute for wires.  Ideal supply/bias sources and the test load
remain outside the cell.  Dimensions are quantized before LVS.
"""

import json
import math
import re
import shutil
import subprocess
import time
from collections import defaultdict
from pathlib import Path

from ..circuits.sky130_devices import DEVICE, build
from ..paths import magic
from ..simulation.pdk import model_root

GRID = 0.005


def readiness():
    missing = [name for name in (magic(), "netgen") if not shutil.which(name)]
    if shutil.which(magic()):
        try:
            version = subprocess.check_output([magic(), "--version"], text=True, timeout=5)
            if tuple(map(int, re.findall(r"\d+", version)[:3])) < (8, 3, 684):
                missing.append("Magic >= 8.3.684 (scripts/setup-layout.sh)")
        except (subprocess.SubprocessError, ValueError):
            missing.append("working Magic version check")
    for name in ("magic/sky130A.tech", "magic/sky130A.tcl", "netgen/sky130A_setup.tcl"):
        if not (model_root() / "libs.tech" / name).is_file():
            missing.append(name)
    return missing


def run_magic(directory, script, name):
    """Keep the exact input and complete log; Tcl errors are fatal, even on exit 0."""
    root = model_root() / "libs.tech/magic"
    prefix = (
        f"tech load {{{root / 'sky130A.tech'}}}\n"
        f"source {{{root / 'sky130A.tcl'}}}\n"
        "scalegrid 1 2\nunits internal\nsnap internal\ndrc off\n"
        "crashbackups stop\n"
    )
    text = (
        prefix
        + "if {[catch {\n"
        + script
        + (
            "\n} problem]} {puts stderr $::errorInfo; exit 1}\n"
            'puts "@@CHIPJEV_DONE"\nquit -noprompt\n'
        )
    )
    path = directory / f"{name}.tcl"
    path.write_text(text)
    proc = subprocess.run(
        [magic(), "-dnull", "-noconsole", "-rcfile", "/dev/null", path.name],
        cwd=directory,
        capture_output=True,
        text=True,
        timeout=120,
    )
    output = proc.stdout + proc.stderr
    (directory / f"{name}.log").write_text(output)
    if (
        proc.returncode
        or "@@CHIPJEV_DONE" not in output
        or "Unknown option:" in output
        or "Unrecognized layer" in output
    ):
        raise RuntimeError(f"Magic {name} failed; inspect {name}.log")
    return output


def rectangles(path):
    result = defaultdict(list)
    layer = None
    # Magic may save an individual cell on its coarser native grid even when the
    # active editor uses scalegrid 1 2. Normalize every file to our 5 nm grid.
    scale = 2.0
    for line in path.read_text().splitlines():
        if line.startswith("magscale "):
            _, numerator, denominator = line.split()
            scale = 2 * int(numerator) / int(denominator)
        elif line.startswith("<< "):
            layer = line[3:-3]
        elif line.startswith("rect "):
            coords = [int(v) * scale for v in line.split()[1:]]
            if any(abs(v-round(v)) > 1e-8 for v in coords):
                raise ValueError("Geometry finer than the supported 5 nm grid")
            result[layer].append(tuple(round(v) for v in coords))
    return dict(result)


def bounds(shapes):
    rects = [r for group in shapes.values() for r in group]
    return (
        min(r[0] for r in rects),
        min(r[1] for r in rects),
        max(r[2] for r in rects),
        max(r[3] for r in rects),
    )


def center(rect):
    return ((rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2)


def primitive_specs(builder):
    specs, reference, geometries = [], [], {}
    for name, drain, gate, source, kind in builder.mos:
        width, length, nf = builder.geometry[name]
        # Symmetric PCells use a 10 nm dimension quantum on the 5 nm grid.
        wf = max(0.42, round(width / nf / 0.01) * 0.01)
        length = max(0.15, round(length / 0.01) * 0.01)
        geometries[name] = {
            "requested": list(builder.geometry[name]),
            "drawn": [wf * nf, length, nf],
        }
        bulk = "vss" if kind == "n" else "vdd"
        for finger in range(nf):
            ident = f"{name}_f{finger}"
            params = {"w": wf, "l": length, "nf": 1, "guard": 1, "topc": 1, "botc": 0, "viagb": 100}
            nets = ["vss" if n == "0" else n for n in (drain, gate, source)] + [bulk]
            specs.append(
                {
                    "id": ident,
                    "model": DEVICE[kind],
                    "params": params,
                    "nets": nets,
                    "kind": kind,
                    "logical": name,
                }
            )
            reference.append(
                f"X{ident} {' '.join(nets)} {DEVICE[kind]} w={wf:.6g} l={length:.6g} nf=1 mult=1"
            )
    for line in builder.lines:
        if line[0].lower() not in "rc":
            continue
        name, a, b, value = line.split()
        value = float(value)
        nets = ["vss" if n == "0" else n for n in (a, b)]
        if name[0] == "r":
            # A poly resistor has 48.2 ohms/square at the nominal corner.
            width = max(0.5, 1.65 * 48.2 / value)
            width = math.ceil(width * 100) / 100
            length = round(value * width / 48.2 * 100) / 100
            model = "sky130_fd_pr__res_generic_po"
            params = {"w": width, "l": length, "guard": 0, "vias": 1}
            specs.append(
                {
                    "id": name,
                    "model": model,
                    "params": params,
                    "nets": nets,
                    "kind": "r",
                    "logical": name,
                }
            )
            reference.append(f"R{name} {' '.join(nets)} {model} w={width} l={length}")
        else:
            # MIM: 2 fF/um² plus 0.19 fF/um edge, split into <=30 um tiles.
            count = max(1, math.ceil(value / (2e-15 * 30**2 + 0.76e-15 * 30)))
            side = (-0.76 + math.sqrt(0.76**2 + 8 * value / count / 1e-15)) / 4
            side = max(2.0, round(side * 100) / 100)
            model = "sky130_fd_pr__cap_mim_m3_1"
            for tile in range(count):
                ident = f"{name}_t{tile}"
                params = {"w": side, "l": side}
                specs.append(
                    {
                        "id": ident,
                        "model": model,
                        "params": params,
                        "nets": nets,
                        "kind": "c",
                        "logical": name,
                    }
                )
                reference.append(f"X{ident} {' '.join(nets)} {model} w={side} l={side}")
    return specs, reference, geometries


def synthesize(topology, values, directory, *, vdd=1.8):
    start = time.perf_counter()
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    if any(directory.glob("*.mag")):
        raise FileExistsError("Use a fresh layout directory; existing geometry must not be reused")
    if missing := readiness():
        raise RuntimeError("Physical design tools missing: " + ", ".join(missing))
    builder = build(topology, values, vdd)
    specs, reference, geometries = primitive_specs(builder)
    script = []
    for spec in specs:
        params = " ".join(f"{k} {v:.9g}" for k, v in spec["params"].items())
        model, ident = spec["model"], spec["id"]
        script += [
            f"load {ident}",
            "box values 0 0 0 0",
            f"set p [dict merge [sky130::{model}_defaults] {{{params}}}]",
            f"sky130::{model}_draw $p",
            f"save {ident}",
        ]
    run_magic(directory, "\n".join(script), "primitives")
    shapes = defaultdict(list)
    terminals = defaultdict(list)
    placements = []
    cursor = 400
    maxy = 0

    def paint(layer, rect):
        shapes[layer].append(tuple(round(v) for v in rect))

    def wire(layer, p, q, width=60):
        x, y = p
        u, v = q
        if x != u and y != v:
            raise ValueError("Non-Manhattan wire")
        half = width // 2
        paint(layer, (min(x, u) - half, min(y, v) - half, max(x, u) + half, max(y, v) + half))

    def via(p, lower=1):
        x, y = p
        # Magic paints the contact plus its mandatory metal enclosure.
        cut = {1: 52, 2: 56, 3: 64}[lower]
        for metal in (lower, lower + 1):
            hx, hy = (cut // 2, cut // 2 + 10) if metal <= 2 else (50, 50)
            paint(f"metal{metal}", (x - hx, y - hy, x + hx, y + hy))
        paint(
            "via" if lower == 1 else f"via{lower}",
            (x - cut // 2, y - cut // 2, x + cut // 2, y + cut // 2),
        )

    for spec in specs:
        local = rectangles(directory / f"{spec['id']}.mag")
        x0, y0, x1, y1 = bounds(local)
        dx, dy = cursor - x0, 400 - y0
        for layer, group in local.items():
            shapes[layer].extend((a + dx, b + dy, c + dx, d + dy) for a, b, c, d in group)
        bbox = (x0 + dx, y0 + dy, x1 + dx, y1 + dy)
        placements.append({"id": spec["id"], "logical": spec["logical"], "bbox": bbox})
        maxy = max(maxy, bbox[3])
        kind = spec["kind"]
        if kind in ("n", "p"):
            contact = "ndiffc" if kind == "n" else "pdiffc"
            ds = sorted(local[contact], key=lambda r: r[0])
            d, s = center(ds[-1]), center(ds[0])
            gate = center(max(local["polycont"], key=lambda r: r[1]))
            taps = local["psubdiffcont" if kind == "n" else "nsubdiffcont"]
            bulk = center(min(taps, key=lambda r: r[1]))
            points = [d, gate, s, bulk]
            for index, ((x, y), net) in enumerate(zip(points, spec["nets"], strict=True)):
                point = (x + dx, y + dy)
                if index in (1, 3):
                    escape = (bbox[2] + 160 if index == 1 else bbox[0] - 160, point[1])
                    wire("metal1", point, escape, 46 if index == 1 else 60)
                    point = escape
                via(point)
                terminals[net].append(point)
        elif kind == "r":
            contacts = sorted(local["polycont"], key=lambda r: r[1])
            for index, (r, net) in enumerate(
                zip((contacts[0], contacts[-1]), spec["nets"], strict=True)
            ):
                x, y = center(r)
                p = (x + dx, y + dy)
                q = (bbox[0] - 160 if index == 0 else bbox[2] + 160, p[1])
                wire("metal1", p, q)
                via(q)
                terminals[net].append(q)
        else:
            # Top plate is M4 (mimcc); bottom plate contact is Via3 outside it.
            top = center(max(local["mimcapcontact"], key=lambda r: (r[2] - r[0]) * (r[3] - r[1])))
            bot = center(local["via3"][0])
            for index, ((x, y), net) in enumerate(zip((top, bot), spec["nets"], strict=True)):
                p = (x + dx, y + dy)
                q = (bbox[0] - 200 if index == 0 else bbox[2] + 200, p[1])
                wire("metal4", p, q, 100)
                via(q, 3)
                via(q, 2)
                terminals[net].append(q)
        cursor = bbox[2] + 800

    ports = sorted(terminals)
    labels = []
    for i, net in enumerate(ports):
        track = maxy + 600 + 200 * i
        points = terminals[net]
        left, right = min(p[0] for p in points), max(p[0] for p in points)
        wire("metal3", (left, track), (right, track), 100)
        for p in points:
            wire("metal2", p, (p[0], track), 52)
            via((p[0], track), 2)
        labels += [f"rlabel metal3 s {left} {track} {left} {track} 0 {net}", f"port {i + 1} nsew"]
    lines = ["magic", "tech sky130A", "magscale 1 2", "timestamp 0"]
    for layer, group in shapes.items():
        lines.append(f"<< {layer} >>")
        lines += ["rect " + " ".join(map(str, rect)) for rect in group]
    lines += ["<< labels >>", *labels, "<< end >>"]
    (directory / "layout.mag").write_text("\n".join(lines) + "\n")
    (directory / "reference.spice").write_text(
        "* Grid-quantized schematic with physical passives\n.subckt layout "
        + " ".join(ports)
        + "\n"
        + "\n".join(reference)
        + "\n.ends layout\n"
    )
    script = """load layout
select top cell
drc euclidean on
drc style drc(full)
drc on
drc check
drc catchup
set fd [open drc.txt w]
puts $fd [drc listall why]
close $fd
puts "@@DRC [drc list count total]"
extract unique
extract all
ext2spice lvs
ext2spice scale off
ext2spice -o lvs.spice
ext2spice cthresh 0
ext2spice -o capacitance.spice
gds write layout.gds
save layout
"""
    output = run_magic(directory, script, "layout")
    match = re.search(r"@@DRC (\d+)", output)
    if not match:
        raise RuntimeError("Magic did not report DRC completion")
    x0, y0, x1, y1 = bounds(shapes)
    result = {
        "technology": "sky130A",
        "topology": topology.id,
        "drc_errors": int(match[1]),
        "ports": ports,
        "width_um": (x1 - x0) * GRID,
        "height_um": (y1 - y0) * GRID,
        "area_um2": (x1 - x0) * (y1 - y0) * GRID**2,
        "geometry": geometries,
        "placements": placements,
        "physical_devices": len(specs),
        "logical_mosfets": len(builder.mos),
        "layout_seconds": time.perf_counter() - start,
    }
    (directory / "layout.json").write_text(json.dumps(result, indent=2))
    from .render import render_svg

    render_svg(directory, result)
    return result
