"""Compile a ChipJev SKY130 circuit into a professional-style analog layout.

Pipeline: circuit structure -> finger arrays (planner) -> rows, rails, guard
rings and decap fill (floorplan) -> trunk/bus routing (router) -> MIM blocks
-> Magic cell, declared reference netlist and logical-to-physical manifest.
Magic's full DRC, extraction and GDS writer run on the result; Netgen LVS and
RC extraction follow in chipjev.layout.verification.
"""

import json
import math
import re
import time
from pathlib import Path

from ...circuits.sky130_devices import DEVICE, build
from ..magic import readiness, run_magic
from ..technology import provenance
from . import tech as T
from .analysis import analyse
from .canvas import Canvas
from .floorplan import Floorplan
from .passives import MimArray, ResistorArray, resistor_segments
from .pcell import resistor_segment
from .planner import ProPlan, mim_tiles, plan_units
from .router import Router, RoutingSpace

GENERATOR = "pro-rows-v1"
MAGIC = """load layout
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
"""


def synthesize(topology, values, directory, *, vdd=1.8, plan=None, current_a=1e-3, run=True,
               finger_max_um=None, observer=None):
    """``observer("drc", {"status": "running"})`` fires once the cell is written and
    Magic starts the full DRC deck (verification.verify reports the verdict)."""
    start = time.perf_counter()
    plan = plan or ProPlan()
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    if any(directory.glob("*.mag")):
        raise FileExistsError("Use a fresh physical directory")
    if run and (missing := readiness()):
        raise RuntimeError(str(missing))
    builder = build(topology, values, vdd, finger_max=finger_max_um)
    circuit = analyse(builder, topology)
    side = _passive_size(circuit) if plan.passives == "right" else (0, 0)
    # Fold count of the large blocks is chosen by the floorplan's area/aspect score.
    options = []
    for fold in (1, 2, 4):
        try:
            candidate = plan_units(circuit, plan, fold=fold)
        except ValueError:
            continue
        options.append((Floorplan(candidate, plan, circuit, side=side).score, fold, candidate))
    failures = []
    for _, fold, units in sorted(options, key=lambda o: o[:2]):
        routed = False
        for extra in range(0, 8):
            # Routing channels grow until every trunk has a legal position.
            fp = Floorplan(units, plan, circuit, extra_tracks=extra, side=side)
            canvas = Canvas()
            canvas.merge(fp.canvas)
            router = Router(canvas, circuit, fp, axis=0)
            # Metal3 power straps on the ring sides are obstacles for signal trunks.
            router.blocked += [s["rect"] for s in fp.power_straps]
            mims = _place_passives(circuit, fp, plan, canvas, router)
            try:
                router.route()
                _connect_passives(router, mims)  # passive buses retry with the channels too
                routed = True
                break
            except RoutingSpace as exc:
                failure = f"fold {fold}, {extra} extra tracks: {exc}"
        if routed:
            break
        failures.append(failure)  # the next-best fold is tried before giving up
    else:
        raise RoutingSpace("layout", {"x0": 0, "x1": 0}) from ValueError("; ".join(failures))
    result_notes = failures
    router.draw_trunks()
    ports = _label(canvas, circuit, router, fp)
    reference, manifest = _declare(circuit, fp, mims, units, plan)
    placements, groups = _placements(fp, circuit)
    canvas.write_mag(directory / "layout.mag", ports)
    (directory / "reference.spice").write_text(
        "* Declared physical implementation before extraction\n.subckt layout "
        + " ".join(ports) + "\n" + "\n".join(reference) + "\n.ends layout\n")
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2))
    x0, y0, x1, y1 = canvas.bounds()
    result = {
        "technology": "sky130A",
        "generator": GENERATOR,
        "topology": topology.id,
        "ports": ports,
        "width_um": T.um(x1 - x0),
        "height_um": T.um(y1 - y0),
        "area_um2": T.um(x1 - x0) * T.um(y1 - y0),
        "placements": placements,
        "groups": groups,
        "routes": [{k: v for k, v in r.items() if k != "rect"} for r in canvas.routes],
        "trunks": router.trunks,
        "buses": router.buses,
        "rows": _rows(fp),
        "rails": [{"net": r["net"], "y_um": T.um(r["y"]), "width_um": plan.rail_um} for r in fp.rails],
        "plan": plan.to_dict(),
        "plan_id": plan.id,
        "physical_devices": sum(1 for d in manifest["devices"].values()),
        "logical_mosfets": len(circuit.devices),
        "pairs": circuit.pairs,
        "symmetric_nets": {k: v for k, v in circuit.mirror.items() if k != v},
        "technology_rules": provenance(),
        "fold": fold,
        "arrangement": fp.arrangement,
        "regions": {pol: [x0, x1, fp.axes.get(pol, 0)] for pol, (x0, x1) in fp.region_x.items()},
        "foreign_over_matched": router.foreign_crossings(),
        "routing_retries": result_notes,
    }
    if run:
        if observer:
            observer("drc", {"status": "running", "area_um2": result["area_um2"]})
        output = run_magic(directory, MAGIC, "layout")
        match = re.search(r"@@DRC (\d+)", output)
        if not match:
            raise RuntimeError("Missing DRC result")
        result["drc_errors"] = int(match[1])
    result["layout_seconds"] = time.perf_counter() - start
    (directory / "layout.json").write_text(json.dumps(result, indent=2))
    if run:
        from ..render import render_svg

        render_svg(directory, result)
    return result


def _passive_size(circuit):
    """Footprint of the passive column (for the floorplan's aspect choice)."""
    width = height = 0
    for name, kind, a, b, value in circuit.passives:
        if kind == "c":
            count, side = mim_tiles(value)
            cols = math.ceil(math.sqrt(count))
            rows = math.ceil(count / cols)
            width += cols * (side + T.MIM_SP) + 700
            height = max(height, rows * (side + T.MIM_SP) + 800)
        else:
            count, w, length = resistor_segments(value)
            width += count * T.u(w + 0.6) + 1200
            height = max(height, T.u(length + 5))
    return width, height


def _place_passives(circuit, fp, plan, canvas, router):
    """Passive column right of (or above) the wells: resistors first, then MIMs.

    Every terminal is a metal3 tab (resistors, MIM bottom plate) or the MIM's
    metal4 top plate; tabs span the whole column so a bus lands at any height.
    """
    placed = []
    bx0, by0, bx1, by1 = fp.bounds()
    items = []
    for name, kind, a, b, value in circuit.passives:
        if kind == "r":
            count, w, length = resistor_segments(value)
            items.append(ResistorArray(name, a, b, value, resistor_segment(w, length)))
        else:
            count, side = mim_tiles(value)
            top, bottom = _plates(circuit, a, b)
            items.append(MimArray(name, top, bottom, count, side))
    if not items:
        return []
    height = max(i.height for i in items)
    if plan.passives == "right":
        x = bx1 + 700
        y = max(by0, (by0 + by1) // 2 - height // 2)
    else:
        x = (bx0 + bx1) // 2 - sum(i.width + 1400 for i in items) // 2
        y = by1 + 800
    for item in items:
        if isinstance(item, ResistorArray):
            ox, oy = x + 600, y + (height - item.height) // 2
            canvas.merge(item.canvas, ox, oy)
            # Extend the terminal tabs over the whole column height.
            for tx, _ in item.tabs:
                canvas.rect("metal3", tx + ox - 60, y - 200, tx + ox + 60, y + height + 200)
            item.span = (y - 100, y + height + 100)
            router.blocked.append((ox - 600, y - 400, ox + item.width + 600, y + height + 400))
            x = ox + item.width + 700
        else:
            ox, oy = x + 28 + 480 + 200, y + (height - item.height) // 2
            canvas.merge(item.canvas, ox, oy)
            router.blocked.append((ox - 28 - 480 - 200, oy - 400, ox + item.width + 200, oy + item.height + 400))
            x = ox + item.width + 700
        placed.append((item, (ox, oy)))
    return placed


def _plates(circuit, a, b):
    """Bottom plate on the lower-impedance node: a stage output or a rail."""
    rank = {"vss": 0, "vdd": 0, "out": 1}
    if rank.get(a, 2) <= rank.get(b, 2):
        return b, a
    return a, b


def _terminals(items):
    """Every passive terminal: (net, landing x, y span, tap callable)."""
    out = []
    for item, (x, y) in items:
        if isinstance(item, MimArray):
            out.append((item.top, x + item.top_pin[0] + 200, (y + 100, y + item.height - 100), None))
            out.append((item.bottom, x + item.bottom_pin[0], (y + item.tab[1] + 60, y + item.tab[3] - 60),
                        lambda canvas, landed, item=item, x=x, y=y: item.tap(canvas, x, y, landed)))
        else:
            for index, net in ((0, item.a), (1, item.b)):
                tx = item.tabs[index][0] + x
                out.append((net, tx, item.span,
                            lambda canvas, landed, item=item, x=x, index=index:
                            item.tap(canvas, x, 0, index, landed)))
    return out


def _connect_passives(router, items):
    """Buses from each net's nearest trunk to its passive terminals, or between
    terminals directly when the net touches no transistor (e.g. Rz-Cc midpoint)."""
    by_net = {}
    for net, x, span, tap in _terminals(items):
        by_net.setdefault(net, []).append((x, span, tap))
    for net, terms in by_net.items():
        if any(t["net"] == net for t in router.trunks):
            for x, span, tap in terms:
                landed = router.add_bus(net, x, x, (span[0] + span[1]) // 2, span=span)
                if tap:
                    tap(router.c, landed)
            continue
        lo = max(span[0] for _, span, _ in terms)
        hi = min(span[1] for _, span, _ in terms)
        xs = [x for x, _, _ in terms]
        y = router._bus_track((lo + hi) // 2, min(xs), max(xs),
                              lambda y: lo <= y <= hi)
        router.c.hwire(4, min(xs) - 40, max(xs) + 40, y, 80, net)
        router.c.label("metal4", (min(xs) + max(xs)) // 2, y, net)  # a pin for the extracted netlist
        router.buses.append({"net": net, "y": y, "x0": min(xs) - 40, "x1": max(xs) + 40})
        for _, _, tap in terms:
            if tap:
                tap(router.c, y)


def _label(canvas, circuit, router, fp):
    ports = []
    # Nets that touch only passives already carry their pin (bus or resistor jumper).
    labelled = {net for _, _, _, net in canvas.labels}
    nets = sorted(set(circuit.ports) - labelled)
    ports += sorted(labelled)
    for net in nets:
        trunks = [t for t in router.trunks if t["net"] == net and not t.get("shield")]
        if net in ("vdd", "vss") and any(s["net"] == net for s in fp.power_straps):
            trunks = []  # supply pins go on the power straps
        if trunks:
            t = trunks[0]
            canvas.label("metal3", t["x"], (t["y0"] + t["y1"]) // 2, net)
        elif net in ("vdd", "vss"):
            strap = next(s for s in fp.power_straps if s["net"] == net)
            canvas.label("metal3", strap["x"], (strap["y0"] + strap["y1"]) // 2, net)
        else:
            continue
        ports.append(net)
    return ports


def _declare(circuit, fp, mims, units, plan):
    reference, devices = [], {}
    for p in fp.placed:
        spec = p.array.spec
        model = DEVICE[spec.polarity]
        bulk = "vss" if spec.polarity == "n" else "vdd"
        w, length = T.um(spec.w), T.um(spec.length)
        for i, f in enumerate(spec.fingers):
            ident = f"{spec.name}_f{i}"
            a, b = spec.regions[i], spec.regions[i + 1]
            reference.append(f"X{ident} {a} {f.gate} {b} {bulk} {model} w={w:.6g} l={length:.6g} nf=1 mult=1")
            devices[ident] = {
                "logical": f.device if f.kind == "active" else ident,
                "kind": spec.polarity,
                "role": f.kind,
                "nets": [a, f.gate, b, bulk],
                "model": model,
                "params": {"w": w, "l": length},
                "auxiliary": f.kind != "active",
                "array": spec.name,
            }
    for mim, _ in mims:
        reference += mim.reference()
        if isinstance(mim, ResistorArray):
            for k in range(mim.count):
                devices[f"{mim.name}_s{k}"] = {
                    "logical": mim.name, "kind": "r", "role": "active",
                    "nets": [mim.nodes[k], mim.nodes[k + 1]], "model": "sky130_fd_pr__res_generic_po",
                    "params": {"w": mim.w_um, "l": mim.l_um}, "auxiliary": False,
                }
            continue
        for k in range(mim.count):
            devices[f"{mim.name}_t{k}"] = {
                "logical": mim.name, "kind": "c", "role": "active",
                "nets": [mim.top, mim.bottom], "model": "sky130_fd_pr__cap_mim_m3_1",
                "params": {"w": T.um(mim.side), "l": T.um(mim.side)}, "auxiliary": False,
            }
    logical = {}
    for unit in units:
        for name, (count, w, length) in unit.fingers.items():
            m = circuit.devices[name]
            logical[name] = {
                "schematic": {"w": m.w, "l": m.length, "nf": m.nf},
                "physical": {"fingers": count, "w_finger": T.um(w), "l": T.um(length),
                             "w_total": count * T.um(w)},
                "pattern": unit.pattern,
                "refingered": bool(getattr(unit, "refingered", False)),
            }
    for mim, _ in mims:
        value = next(p[4] for p in circuit.passives if p[0] == mim.name)
        if isinstance(mim, ResistorArray):
            logical[mim.name] = {"schematic": {"r": value},
                                 "physical": {"segments": mim.count, "w": mim.w_um, "l": mim.l_um,
                                              "r_nominal": mim.count * mim.l_um / mim.w_um * 48.2}}
            continue
        logical[mim.name] = {"schematic": {"c": value},
                             "physical": {"tiles": mim.count, "side": T.um(mim.side),
                                          "c_nominal": mim.value_f()}}
    manifest = {
        "generator": GENERATOR,
        "requalify": sorted(n for n, v in logical.items() if v.get("refingered")),
        "plan": plan.to_dict(),
        "plan_id": plan.id,
        "devices": devices,
        "logical": logical,
        "technology": provenance(),
    }
    return reference, manifest


def _placements(fp, circuit):
    placements = []
    for p in fp.placed:
        spec, arr = p.array.spec, p.array
        for i, f in enumerate(spec.fingers):
            x = arr.gate_x(i) + p.x
            placements.append({
                "id": f"{spec.name}_f{i}",
                "logical": f.device if f.kind == "active" else f"{spec.name}_f{i}",
                "bbox": (x, p.y, x + spec.length, p.y + spec.w),
                "auxiliary": f.kind != "active",
                "role": f.kind,
                "array": spec.name,
            })
    groups = []
    for i, (a, b) in enumerate(circuit.pairs):
        role = "input_pair" if {circuit.devices[a].g, circuit.devices[b].g} == {"inp", "inn"} else "matched"
        boxes = [p["bbox"] for p in placements if p["logical"] in (a, b)]
        bbox = (min(r[0] for r in boxes), min(r[1] for r in boxes),
                max(r[2] for r in boxes), max(r[3] for r in boxes))
        groups.append({"id": f"g{i}", "members": [a, b], "kind": circuit.devices[a].kind,
                       "role": role, "bbox": bbox})
    return placements, groups


def _rows(fp):
    rows = []
    for polarity, table in fp.rows.items():
        for level, row in sorted(table.items()):
            rows.append({
                "polarity": polarity, "level": level, "height_um": T.um(row.height),
                "arrays": [p.array.spec.name for p in row.items],
            })
    return rows
