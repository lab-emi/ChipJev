"""Compile analog groups into real SKY130 geometry and layered channel routing.

M1 accesses devices, M2 accesses row buses, M3 connects each row to M4 column
spines. Only nets crossing columns use M5. PDK guard rings enclose whole groups.
The declaration manifest and LVS reference are generated before extraction.
"""

import copy
import hashlib
import json
import math
import re
import shutil
import time
import uuid
from collections import defaultdict
from pathlib import Path

from ..circuits.sky130_devices import build
from ..paths import ROOT
from .intent import derive
from .magic import bounds, center, primitive_specs, readiness, rectangles, run_magic
from .plan import LayoutPlan, arrangement
from .technology import GRID, SPACE, provenance, rail_width, units


class Drawing:
    def __init__(self):
        self.shapes = defaultdict(list)
        self.routes = []

    def paint(self, layer, rect):
        self.shapes[layer].append(tuple(round(x) for x in rect))

    def merge(self, shapes, dx=0, dy=0):
        for layer, rects in shapes.items():
            self.shapes[layer].extend((a + dx, b + dy, c + dx, d + dy) for a, b, c, d in rects)

    def wire(self, layer, p, q, width, net):
        x, y = p
        u, v = q
        if x != u and y != v:
            raise ValueError("Non-Manhattan route")
        h = width // 2
        self.paint(f"metal{layer}", (min(x, u) - h, min(y, v) - h, max(x, u) + h, max(y, v) + h))
        self.routes.append(
            {
                "layer": layer,
                "net": net,
                "p": p,
                "q": q,
                "width_um": width * GRID,
                "length_um": (abs(x - u) + abs(y - v)) * GRID,
            }
        )

    def via(self, point, lower=1, count=1):
        x, y = point
        cut = {1: 52, 2: 56, 3: 64, 4: 236}[lower]
        pitch = {1: 100, 2: 112, 3: 128, 4: 400}[lower]
        for i in range(count):
            u = x + (i - (count - 1) / 2) * pitch
            for metal in (lower, lower + 1):
                hx, hy = (cut // 2, cut // 2 + 10) if metal <= 2 else (50, 50)
                if lower == 4:
                    hx = hy = 180
                self.paint(f"metal{metal}", (u - hx, y - hy, u + hx, y + hy))
            self.paint(
                "via" if lower == 1 else f"via{lower}",
                (u - cut // 2, y - cut // 2, u + cut // 2, y + cut // 2),
            )


def _primitives(builder, plan, intent, directory):
    physical = copy.deepcopy(builder)
    matched = {n for g in intent["groups"] if len(g["members"]) == 2 for n in g["members"]}
    for name in matched:
        w, length, nf = physical.geometry[name]
        physical.geometry[name] = (w, length, nf * plan.split)
    if plan.decap_pf:
        physical.lines.append(f"cdecap vdd 0 {plan.decap_pf * 1e-12}")
    specs, reference, geometries = primitive_specs(physical)
    for spec in specs:
        if spec["kind"] in ("n", "p"):
            spec["params"]["guard"] = 0
    manifest = {
        s["id"]: {
            "logical": s["logical"],
            "kind": s["kind"],
            "nets": s["nets"],
            "model": s["model"],
            "params": s["params"],
            "auxiliary": False,
        }
        for s in specs
    }
    # Identical, rail-tied dummy MOS: extracted and included in the expected LVS circuit.
    if plan.dummies:
        for g in intent["groups"]:
            if len(g["members"]) != 2:
                continue
            source = next(s for s in specs if s["logical"] == g["members"][0])
            count = sum(s["logical"] in g["members"] for s in specs)
            rows = (
                2 * math.ceil((count // 2) / plan.fingers_per_row)
                if plan.pattern == "centroid"
                else math.ceil(count / plan.fingers_per_row)
            )
            for row in range(rows):
                for side in ("left", "right"):
                    spec = copy.deepcopy(source)
                    spec["id"] = spec["logical"] = f"dummy_{g['id']}_{row}_{side}"
                    rail = "vss" if g["kind"] == "n" else "vdd"
                    spec["nets"] = [rail] * 4
                    specs.append(spec)
                    p = spec["params"]
                    reference.append(
                        f"X{spec['id']} {' '.join(spec['nets'])} {spec['model']} "
                        f"w={p['w']:.6g} l={p['l']:.6g} nf=1 mult=1"
                    )
                    manifest[spec["id"]] = {
                        "logical": spec["logical"],
                        "kind": spec["kind"],
                        "nets": spec["nets"],
                        "model": spec["model"],
                        "params": p,
                        "auxiliary": True,
                    }
    tech = provenance()
    cache = ROOT / "runs/pcell-cache" / tech["files"]["magic/sky130A.tcl"][:16]
    cache.mkdir(parents=True, exist_ok=True)
    script, misses, hits = [], {}, 0
    for spec in specs:
        key = hashlib.sha256(
            json.dumps([spec["model"], spec["params"], tech], sort_keys=True).encode()
        ).hexdigest()
        saved = cache / f"{key}.mag"
        if saved.exists():
            shutil.copy2(saved, directory / f"{spec['id']}.mag")
            hits += 1
        elif key not in misses:
            misses[key] = spec["id"]
            params = " ".join(f"{k} {v:.9g}" for k, v in spec["params"].items())
            script += [
                f"load {spec['id']}",
                "box values 0 0 0 0",
                f"set p [dict merge [sky130::{spec['model']}_defaults] {{{params}}}]",
                f"sky130::{spec['model']}_draw $p",
                f"save {spec['id']}",
            ]
        spec["cache_key"] = key
    if script:
        run_magic(directory, "\n".join(script), "primitives")
    for key, ident in misses.items():
        # Each local file is complete before publishing its bytes atomically.
        temporary = cache / f"{key}.{uuid.uuid4().hex}.tmp"
        shutil.copyfile(directory / f"{ident}.mag", temporary)
        temporary.replace(cache / f"{key}.mag")
    for spec in specs:
        target = directory / f"{spec['id']}.mag"
        if not target.exists():
            shutil.copy2(cache / f"{spec['cache_key']}.mag", target)
    return specs, reference, geometries, manifest, hits


def synthesize(topology, values, directory, *, vdd=1.8, plan=None, current_a=0.001):
    start = time.perf_counter()
    plan = plan or LayoutPlan()
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    if any(directory.glob("*.mag")):
        raise FileExistsError("Use a fresh physical directory")
    if missing := readiness():
        raise RuntimeError(str(missing))
    builder = build(topology, values, vdd)
    intent = derive(builder)
    plan.validate(builder, intent)
    specs, reference, geometries, manifest, hits = _primitives(builder, plan, intent, directory)
    by_id = {s["id"]: s for s in specs}
    local = {s["id"]: rectangles(directory / f"{s['id']}.mag") for s in specs}
    # Pack complete intent groups into shared, same-polarity guard domains.
    # Matched units and their edge dummies remain an indivisible row chunk.
    groups = []
    logical_group = {n: g["id"] for g in intent["groups"] for n in g["members"]}
    for kind in ("n", "p"):
        domain = [g for g in intent["groups"] if g["kind"] == kind]
        packed, current = [], []
        for g in domain:
            ids = [[s["id"] for s in specs if s["logical"] == n] for n in g["members"]]
            if len(ids) == 2:
                chunks = arrangement(*ids, plan.pattern, plan.fingers_per_row)
            else:
                chunks = [
                    ids[0][i : i + plan.fingers_per_row]
                    for i in range(0, len(ids[0]), plan.fingers_per_row)
                ]
            if len(ids) == 2 and plan.dummies:
                chunks = [
                    [f"dummy_{g['id']}_{i}_left", *row, f"dummy_{g['id']}_{i}_right"]
                    for i, row in enumerate(chunks)
                ]
            for row in chunks:
                if plan.pattern == "centroid" or len(current) + len(row) > plan.fingers_per_row:
                    if current:
                        packed.append(current)
                        current = []
                current += row
                if plan.pattern == "centroid":
                    packed.append(current)
                    current = []
        if current:
            packed.append(current)
        if packed:
            groups.append(
                {
                    "id": f"domain_{kind}",
                    "members": [n for g in domain for n in g["members"]],
                    "kind": kind,
                    "role": "domain",
                    "rows": packed,
                    "source_groups": domain,
                }
            )
    for s in specs:
        if s["kind"] not in ("n", "p"):
            groups.append(
                {
                    "id": s["id"],
                    "members": [s["logical"]],
                    "kind": s["kind"],
                    "role": "decap" if s["logical"] == "cdecap" else "passive",
                }
            )
    blocks = []
    placed_passives = set()
    for group in groups:
        members = group["members"]
        if group["kind"] not in ("n", "p"):
            if members[0] in placed_passives:
                continue
            placed_passives.add(members[0])
        ids = [[s["id"] for s in specs if s["logical"] == name] for name in members]
        if "rows" in group:
            rows = group["rows"]
        elif len(ids) == 2:
            rows = arrangement(*ids, plan.pattern, plan.fingers_per_row)
        else:
            rows = [
                ids[0][i : i + plan.fingers_per_row]
                for i in range(0, len(ids[0]), plan.fingers_per_row)
            ]
        if "rows" not in group and len(ids) == 2 and plan.dummies:
            rows = [
                [f"dummy_{group['id']}_{i}_left", *row, f"dummy_{group['id']}_{i}_right"]
                for i, row in enumerate(rows)
            ]
        draw = Drawing()
        placements, buses = [], []
        y = units(2)
        maxx = 0
        for row_index, row in enumerate(rows):
            sizes = [bounds(local[ident]) for ident in row]
            pitch = max(r[2] - r[0] for r in sizes) + units(4 if group["kind"] == "c" else 2)
            height = max(r[3] - r[1] for r in sizes)
            terminals = defaultdict(list)
            for col, ident in enumerate(row):
                spec = by_id[ident]
                x0, y0, x1, y1 = bounds(local[ident])
                dx, dy = units(2) + col * pitch - x0, y - y0
                draw.merge(local[ident], dx, dy)
                bbox = (x0 + dx, y0 + dy, x1 + dx, y1 + dy)
                placements.append(
                    {
                        "id": ident,
                        "logical": spec["logical"],
                        "bbox": bbox,
                        "group": logical_group.get(spec["logical"], group["id"]),
                        "row": row_index,
                        "auxiliary": manifest[ident]["auxiliary"],
                    }
                )
                if spec["kind"] in ("n", "p"):
                    ds = sorted(local[ident]["ndiffc" if spec["kind"] == "n" else "pdiffc"])
                    points = [
                        center(ds[-1]),
                        center(max(local[ident]["polycont"], key=lambda r: r[1])),
                        center(ds[0]),
                    ]
                    for index, ((x, z), net) in enumerate(zip(points, spec["nets"][:3])):
                        p = (x + dx, z + dy)
                        if index == 1:
                            q = (bbox[2] + units(0.8), p[1])
                            draw.wire(1, p, q, 46, net)
                            p = q
                        draw.via(p)
                        terminals[net].append(p)
                    # Distributed taps keep every diffusion within the PDK LU
                    # distance even inside a wide, shared guard-ring domain.
                    tap_x = bbox[2] + units(1.4)
                    tap_y = bbox[1]
                    diff, contact = (
                        ("psubdiff", "psubdiffcont")
                        if spec["kind"] == "n"
                        else ("nsubdiff", "nsubdiffcont")
                    )
                    draw.paint(diff, (tap_x - 27, tap_y - 24, tap_x + 27, bbox[3] + 24))
                    draw.paint(contact, (tap_x - 17, tap_y, tap_x + 17, bbox[3]))
                    draw.paint("locali", (tap_x - 17, tap_y - 16, tap_x + 17, bbox[3] + 16))
                    draw.paint("viali", (tap_x - 17, tap_y - 17, tap_x + 17, tap_y + 17))
                    draw.paint("locali", (tap_x - 33, tap_y - 33, tap_x + 33, tap_y + 33))
                    draw.paint("metal1", (tap_x - 33, tap_y - 33, tap_x + 33, tap_y + 33))
                    draw.via((tap_x, tap_y))
                    terminals[spec["nets"][3]].append((tap_x, tap_y))
                elif spec["kind"] == "r":
                    contacts = sorted(local[ident]["polycont"], key=lambda r: r[1])
                    for index, (r, net) in enumerate(
                        zip((contacts[0], contacts[-1]), spec["nets"])
                    ):
                        x, z = center(r)
                        p = (x + dx, z + dy)
                        q = (bbox[0] - units(0.8) if index == 0 else bbox[2] + units(0.8), p[1])
                        draw.wire(1, p, q, 60, net)
                        draw.via(q)
                        terminals[net].append(q)
                else:
                    top = center(
                        max(
                            local[ident]["mimcapcontact"],
                            key=lambda r: (r[2] - r[0]) * (r[3] - r[1]),
                        )
                    )
                    bot = center(local[ident]["via3"][0])
                    for index, ((x, z), net) in enumerate(zip((top, bot), spec["nets"])):
                        p = (x + dx, z + dy)
                        q = (bbox[0] - units(1) if index == 0 else bbox[2] + units(1), p[1])
                        draw.wire(4, p, q, 100, net)
                        draw.via(q, 3)
                        draw.via(q, 2)
                        terminals[net].append(q)
                maxx = max(maxx, bbox[2] + units(2))
            track = y + height + units(1.5)
            # Neighboring terminal columns and Via2 landing envelopes bound
            # access widening, even when the global rail can be much wider.
            power_access = units(0.26 + 0.16 * (plan.rail_multiplier - 1))
            for net, points in terminals.items():
                if net not in ("vdd", "vss"):
                    continue
                for other, other_points in terminals.items():
                    if other == net:
                        continue
                    for p in points:
                        for q in other_points:
                            gap = abs(p[0] - q[0]) - units(SPACE[2])
                            limit = gap if other in ("vdd", "vss") else 2 * gap - 56
                            power_access = min(power_access, max(52, int(limit) // 2 * 2))
            for net in sorted(terminals):
                power = net in ("vdd", "vss")
                width = (
                    rail_width(current_a, 100, multiplier=plan.rail_multiplier)
                    if power
                    else units(0.5)
                )
                track += width // 2
                ps = terminals[net]
                left, right = min(p[0] for p in ps), max(p[0] for p in ps)
                draw.wire(3, (left, track), (right, track), width, net)
                for p in ps:
                    access_width = power_access if power else 52
                    draw.wire(2, p, (p[0], track), access_width, net)
                    draw.via((p[0], track), 2)
                buses.append({"net": net, "point": (right, track), "width": width})
                track += width // 2 + units(0.8)
            y = track + units(2)
        # One contacted, continuous PDK guard ring per MOS group.
        if group["kind"] in ("n", "p"):
            gw, gh = maxx + units(2), y + units(2)
            cx, cy = gw // 2, gh // 2
            typ, ct, sub = (
                ("psd", "psc", "psub") if group["kind"] == "n" else ("nsd", "nsc", "nwell")
            )
            script = (
                f"load ring_{group['id']}\nbox values {cx} {cy} {cx} {cy}\n"
                f"set p [dict merge $sky130::ruleset {{plus_diff_type {typ} "
                f"plus_contact_type {ct} sub_type {sub} full_metal 1 viagb 100 viagt 100}}]\n"
                f"sky130::guard_ring {gw * GRID:.6g} {gh * GRID:.6g} $p\n"
                f"save ring_{group['id']}"
            )
            run_magic(directory, script, f"guard_{group['id']}")
            ring = rectangles(directory / f"ring_{group['id']}.mag")
            draw.merge(ring)
            bulk = "vss" if group["kind"] == "n" else "vdd"
            p = (cx, 0)
            draw.via(p)
            track = -units(1.5)
            draw.wire(2, p, (cx, track), 60, bulk)
            draw.via((cx, track), 2)
            buses.append(
                {
                    "net": bulk,
                    "point": (cx, track),
                    "width": rail_width(current_a, 100, multiplier=plan.rail_multiplier),
                }
            )
        blocks.append({"group": group, "drawing": draw, "placements": placements, "buses": buses})

    allnets = sorted({b["net"] for block in blocks for b in block["buses"]})
    # Stable rail locations. Inputs use a neighboring grounded spine when shielding.
    ordered = [n for n in allnets if n not in ("vdd", "vss")] + [
        n for n in ("vss", "vdd") if n in allnets
    ]
    if plan.shield_inputs:
        ordered = [n for n in ordered if n != "vss"]
        at = max((ordered.index(n) for n in ("inp", "inn", "in") if n in ordered), default=-1) + 1
        ordered.insert(at, "vss")
    columns = [[] for _ in range(plan.columns)]
    for block in blocks:
        role = block["group"]["role"]
        if role == "decap":
            c = 0 if plan.decap_location == "supply" else plan.columns - 1
        else:
            c = 0 if block["group"]["kind"] == "n" else plan.columns - 1
        columns[c].append(block)
    final = Drawing()
    placements, groups_out, spine_points = [], [], defaultdict(list)
    cursor = 0
    maxy = 0
    for column in columns:
        if not column:
            continue
        body_width = max(
            bounds(b["drawing"].shapes)[2] - bounds(b["drawing"].shapes)[0] for b in column
        )
        sx = cursor + body_width + units(3)
        spine_x, widths = {}, {}
        for net in ordered:
            width = (
                rail_width(current_a, 200, multiplier=plan.rail_multiplier)
                if net in ("vdd", "vss")
                else units(0.5)
            )
            # M4 spine pitch must accommodate the larger M4/M5 landing pads.
            envelope = max(width, units(1.8))
            sx += envelope // 2
            spine_x[net], widths[net] = sx, width
            sx += envelope // 2 + units(SPACE[4])
        y = 0
        endpoints = defaultdict(list)
        for block in column:
            x0, y0, x1, y1 = bounds(block["drawing"].shapes)
            dx, dy = cursor - x0, y - y0 + units(2)
            final.merge(block["drawing"].shapes, dx, dy)
            for route in block["drawing"].routes:
                final.routes.append(
                    {
                        **route,
                        "p": (route["p"][0] + dx, route["p"][1] + dy),
                        "q": (route["q"][0] + dx, route["q"][1] + dy),
                    }
                )
            for p in block["placements"]:
                a, b, c, d = p["bbox"]
                placements.append({**p, "bbox": (a + dx, b + dy, c + dx, d + dy)})
            for g in block["group"].get("source_groups", [block["group"]]):
                rects = [p["bbox"] for p in placements if p["logical"] in g["members"]]
                gb = (
                    min(r[0] for r in rects),
                    min(r[1] for r in rects),
                    max(r[2] for r in rects),
                    max(r[3] for r in rects),
                )
                groups_out.append({**g, "bbox": gb, "guard_domain": block["group"]["id"]})
            for bus in block["buses"]:
                net = bus["net"]
                p = (bus["point"][0] + dx, bus["point"][1] + dy)
                q = (spine_x[net], p[1])
                final.wire(3, p, q, bus["width"], net)
                final.via(q, 3, 2 if net in ("vdd", "vss") else 1)
                endpoints[net].append(q)
            y = dy + y1 + units(3)
        for net, points in endpoints.items():
            low = min(p[1] for p in points)
            high = max(p[1] for p in points)
            final.wire(4, (spine_x[net], low), (spine_x[net], high), widths[net], net)
            spine_points[net].append((spine_x[net], high))
        maxy = max(maxy, y)
        cursor = sx + units(4)
    labels = []
    top = maxy + units(3)
    for i, net in enumerate(allnets):
        points = spine_points[net]
        if len(points) > 1:
            width = (
                max(units(1.8), rail_width(current_a, 200, multiplier=plan.rail_multiplier))
                if net in ("vdd", "vss")
                else units(1.8)
            )
            top += width // 2 + units(2)
            left, right = min(p[0] for p in points), max(p[0] for p in points)
            final.wire(5, (left, top), (right, top), width, net)
            for p in points:
                w = (
                    rail_width(current_a, 200, multiplier=plan.rail_multiplier)
                    if net in ("vdd", "vss")
                    else units(0.5)
                )
                final.wire(4, p, (p[0], top), w, net)
                final.via((p[0], top), 4)
            point, layer = (left, top), 5
            top += width // 2
        else:
            point, layer = points[0], 4
        x, y = point
        labels += [f"rlabel metal{layer} s {x} {y} {x} {y} 0 {net}", f"port {i + 1} nsew"]
    lines = ["magic", "tech sky130A", "magscale 1 2", "timestamp 0"]
    for layer, rects in final.shapes.items():
        lines += [f"<< {layer} >>", *("rect " + " ".join(map(str, r)) for r in rects)]
    lines += ["<< labels >>", *labels, "<< end >>"]
    (directory / "layout.mag").write_text("\n".join(lines) + "\n")
    (directory / "reference.spice").write_text(
        "* Declared physical implementation before extraction\n.subckt layout "
        + " ".join(allnets)
        + "\n"
        + "\n".join(reference)
        + "\n.ends layout\n"
    )
    (directory / "manifest.json").write_text(
        json.dumps(
            {
                "plan": plan.to_dict(),
                "plan_id": plan.id,
                "devices": manifest,
                "geometry": geometries,
                "technology": provenance(),
            },
            indent=2,
        )
    )
    output = run_magic(
        directory,
        """load layout
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
gds write layout.gds
save layout
""",
        "layout",
    )
    match = re.search(r"@@DRC (\d+)", output)
    if not match:
        raise RuntimeError("Missing DRC result")
    x0, y0, x1, y1 = bounds(final.shapes)
    result = {
        "technology": "sky130A",
        "generator": "analog-groups-v1",
        "topology": topology.id,
        "drc_errors": int(match[1]),
        "ports": allnets,
        "width_um": (x1 - x0) * GRID,
        "height_um": (y1 - y0) * GRID,
        "area_um2": (x1 - x0) * (y1 - y0) * GRID**2,
        "geometry": geometries,
        "placements": placements,
        "groups": groups_out,
        "intent": intent,
        "routes": final.routes,
        "plan": plan.to_dict(),
        "plan_id": plan.id,
        "physical_devices": len(specs),
        "logical_mosfets": len(builder.mos),
        "pcell_cache_hits": hits,
        "layout_seconds": time.perf_counter() - start,
        "technology_rules": provenance(),
    }
    (directory / "layout.json").write_text(json.dumps(result, indent=2))
    from .render import render_svg

    render_svg(directory, result)
    return result
