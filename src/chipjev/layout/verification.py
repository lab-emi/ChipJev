"""LVS, extracted RC integrity and strict ngspice post-layout qualification."""

import hashlib
import json
import math
import re
import subprocess
import time
from collections import Counter, defaultdict
from pathlib import Path

from ..circuits.sky130_devices import DEVICE, build
from ..paths import magic
from ..simulation.pdk import model_root
from ..simulation.sky130 import evaluate
from .magic import run_magic, synthesize


def spice_lines(text):
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("*"):
            continue
        if line.startswith("+"):
            if not lines:
                raise ValueError("SPICE continuation without a statement")
            lines[-1] += " " + line[1:].strip()
        else:
            lines.append(line)
    return lines


def spice_number(value):
    match = re.fullmatch(r"([+-]?[\d.]+(?:e[+-]?\d+)?)(meg|[tgkmunpf])?(?:[a-z]*)", value.lower())
    if not match:
        raise ValueError(f"Invalid SPICE number {value!r}")
    scales = {
        None: 1,
        "t": 1e12,
        "g": 1e9,
        "meg": 1e6,
        "k": 1e3,
        "m": 1e-3,
        "u": 1e-6,
        "n": 1e-9,
        "p": 1e-12,
        "f": 1e-15,
    }
    return float(match[1]) * scales[match[2]]


def lvs(directory):
    start = time.perf_counter()
    setup = model_root() / "libs.tech/netgen/sky130A_setup.tcl"
    proc = subprocess.run(
        [
            "netgen",
            "-batch",
            "lvs",
            "lvs.spice layout",
            "reference.spice layout",
            str(setup),
            "lvs.log",
            "-json",
        ],
        cwd=directory,
        capture_output=True,
        text=True,
        timeout=60,
    )
    (directory / "netgen.log").write_text(proc.stdout + proc.stderr)
    report = (directory / "lvs.log").read_text()
    # A topology match with property errors is explicitly NOT an LVS pass.
    passed = (
        proc.returncode == 0
        and "Circuits match uniquely." in report
        and "Property errors were found" not in report
        and "do not match" not in report.lower()
    )
    return {"passed": passed, "seconds": time.perf_counter() - start}


def extract_rc(directory):
    start = time.perf_counter()
    # Modern Magic folds extresist into extract; require its recorded version.
    version = subprocess.check_output([magic(), "--version"], text=True).strip()
    numbers = tuple(map(int, re.findall(r"\d+", version)[:3]))
    if numbers < (8, 3, 684):
        raise RuntimeError("This flow requires Magic >= 8.3.684; run scripts/setup-layout.sh")
    run_magic(
        directory,
        """load layout
select top cell
extract unique
extract do resistance
extresist threshold 0
extresist mindelay 0
extresist minresist 100
extract all
ext2spice lvs
ext2spice scale off
ext2spice cthresh 0
ext2spice extresist on
ext2spice -o pex.spice
""",
        "extraction",
    )
    lines = spice_lines((directory / "pex.spice").read_text())
    resistors = [
        line.split() for line in lines if line.lower().startswith("r") and len(line.split()) == 4
    ]
    caps = [line.split() for line in lines if line.lower().startswith("c")]
    if not resistors or not caps or not (directory / "layout.res.ext").is_file():
        raise RuntimeError("Magic did not produce a nonempty RC extraction")
    return {
        "mode": "distributed RC",
        "magic_version": version,
        "resistors": len(resistors),
        "capacitors": len(caps),
        "capacitance_ff": sum(spice_number(c[3]) for c in caps) * 1e15,
        "seconds": time.perf_counter() - start,
    }


class ExtractedCircuit:
    """Use the extracted devices without substituting schematic MOS instances.

    Distributed resistance is contracted ONLY for mapping and integrity checks.
    The simulator receives the unmodified extracted RC network. Finger currents
    are summed per schematic MOS; saturation must hold for every physical finger.
    """

    def __init__(self, builder, path):
        self.mos, self.nodes, self.bias = builder.mos, builder.nodes, builder.bias
        text = path.read_text()
        statements = spice_lines(text)
        header = [line.split() for line in statements if line.lower().startswith(".subckt ")]
        if len(header) != 1 or header[0][1] != "layout":
            raise ValueError("Expected one flat extracted layout subcircuit")
        ports = header[0][2:]
        self.lines = [text, "Xdut " + " ".join("0" if n == "vss" else n for n in ports) + " layout"]
        root = model_root() / "libs.tech/ngspice"
        paths = [
            root / "r+c/res_typical__cap_typical.spice",
            root / "r+c/res_typical__cap_typical__lin.spice",
            root / "capacitors/sky130_fd_pr__model__cap_mim.model.spice",
        ]
        self.model_lines = [f'.include "{p}"' for p in paths]
        parents = {}

        def find(n):
            parents.setdefault(n, n)
            if parents[n] != n:
                parents[n] = find(parents[n])
            return parents[n]

        for line in statements:
            tok = line.split()
            if tok[0][0].lower() == "r" and len(tok) == 4:
                if spice_number(tok[3]) < 0:
                    raise ValueError("Negative extracted resistance")
                parents[find(tok[1])] = find(tok[2])
        canonical = {}
        for port in ports:
            root = find(port)
            if root in canonical:
                raise ValueError(f"PEX short between {port} and {canonical[root]}")
            canonical[root] = port

        def net(node):
            if find(node) not in canonical:
                raise ValueError(f"Unconnected extracted terminal {node}")
            return canonical[find(node)]

        self.ports = ports
        self.node_roots = {n: canonical.get(find(n)) for n in list(parents)}

        def inventory(statements, resolve):
            entries = []
            for line in statements:
                tok = line.lower().split()
                if tok[0][0] not in "xr" or (tok[0][0] == "r" and len(tok) == 4):
                    continue
                model_index = next((i for i, t in enumerate(tok) if t.startswith("sky130_")), None)
                if model_index is None:
                    raise ValueError(f"Unknown extracted device: {line}")
                nets = [resolve(n) for n in tok[1:model_index]]
                if model_index == 5:
                    nets = [*sorted((nets[0], nets[2])), nets[1], nets[3]]
                else:
                    nets = sorted(nets)
                props = dict(t.split("=", 1) for t in tok[model_index + 1 :] if "=" in t)
                entries.append(
                    (
                        tok[model_index],
                        tuple(nets),
                        tuple((k, spice_number(props[k])) for k in ("w", "l")),
                    )
                )
            return Counter(entries)

        original = spice_lines((path.parent / "lvs.spice").read_text())
        if inventory(original, lambda n: n) != inventory(statements, net):
            raise ValueError("PEX changed device connectivity, count or geometry relative to LVS")

        manifest_path = path.parent / "manifest.json"
        manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else None
        expected_counts = {n: g[2] for n, g in builder.geometry.items()}
        auxiliaries = Counter()
        if manifest is not None and manifest.get("generator", "").startswith("pro-rows"):
            from .pro.integrity import validate

            reference = spice_lines((path.parent / "reference.spice").read_text())
            if inventory(reference, lambda n: n) != inventory(original, lambda n: n):
                raise ValueError("Extracted device inventory disagrees with declared implementation")
            expected_counts, auxiliaries = validate(builder, manifest)
        elif manifest is not None:
            from .intent import derive
            from .plan import LayoutPlan

            declared_plan = LayoutPlan(**manifest["plan"])
            declared_intent = derive(builder)
            declared_plan.validate(builder, declared_intent)
            paired = {
                n for g in declared_intent["groups"] if len(g["members"]) == 2 for n in g["members"]
            }
            reference = spice_lines((path.parent / "reference.spice").read_text())
            if inventory(reference, lambda n: n) != inventory(original, lambda n: n):
                raise ValueError(
                    "Extracted device inventory disagrees with declared implementation"
                )
            expected_counts = Counter()
            for entry in manifest["devices"].values():
                if entry["kind"] not in ("n", "p"):
                    continue
                if entry["auxiliary"]:
                    if len(set(entry["nets"])) != 1 or entry["nets"][0] not in ("vdd", "vss"):
                        raise ValueError("Only explicitly rail-tied dummy MOS are supported")
                    auxiliaries[(entry["model"], tuple(entry["nets"]))] += 1
                else:
                    name = entry["logical"]
                    if name not in builder.geometry:
                        raise ValueError("Manifest changed the logical circuit")
                    width, length, nf = builder.geometry[name]
                    count = nf * (declared_plan.split if name in paired else 1)
                    expected_width = max(0.42, round(width / count / 0.01) * 0.01)
                    expected_length = max(0.15, round(length / 0.01) * 0.01)
                    if not (
                        math.isclose(entry["params"]["w"], expected_width, abs_tol=1e-7)
                        and math.isclose(entry["params"]["l"], expected_length, abs_tol=1e-7)
                    ):
                        raise ValueError(
                            "Manifest geometry is not the declared sizing transformation"
                        )
                    expected_counts[name] += 1
            if set(expected_counts) != set(builder.geometry):
                raise ValueError("Manifest changed the logical circuit")
            for name, (_, _, nf) in builder.geometry.items():
                if expected_counts[name] != nf * (declared_plan.split if name in paired else 1):
                    raise ValueError("Manifest finger count violates the declared plan")

        self.mapping = defaultdict(list)
        for line in statements:
            tok = line.split()
            if tok[0][0].lower() != "x" or len(tok) < 6 or tok[5] not in DEVICE.values():
                continue
            d, g, s, bulk = map(net, tok[1:5])
            aux_key = (tok[5], (d, g, s, bulk))
            if auxiliaries[aux_key]:
                auxiliaries[aux_key] -= 1
                continue
            options = []
            for name, dd, gg, ss, kind in builder.mos:
                dd, gg, ss = ("vss" if n == "0" else n for n in (dd, gg, ss))
                if (
                    tok[5] == DEVICE[kind]
                    and g == gg
                    and {d, s} == {dd, ss}
                    and bulk == ("vss" if kind == "n" else "vdd")
                ):
                    options.append(name)
            if len(options) != 1:
                raise ValueError(f"Cannot uniquely associate extracted MOS {tok[0]}: {options}")
            self.mapping[options[0]].append(tok[0].lower())
        for name in builder.geometry:
            if len(self.mapping[name]) != expected_counts[name]:
                raise ValueError(f"PEX changed the physical finger count of {name}")
        if any(auxiliaries.values()):
            raise ValueError("Missing declared dummy devices")

    def probe_commands(self, name, kind):
        lines = [f"let i_{name} = 0", f"let d_{name} = 1e99"]
        for instance in self.mapping[name]:
            device = f"@m.xdut.{instance}.m{DEVICE[kind]}"
            lines += [
                f"let i_{name} = i_{name} + abs({device}[id])",
                f"let satfinger = abs({device}[vds]) - abs({device}[vdsat])",
                f"if satfinger < d_{name}",
                f"let d_{name} = satfinger",
                "end",
            ]
        return lines


def verify(
    topology,
    values,
    directory,
    *,
    vdd=1.8,
    load_pf=100,
    observer=None,
    prelayout=None,
    plan=None,
    input_bias=None,
    temperature=27.0,
    finger_max_um=None,
):
    """Write reviewable evidence for every stage, including failures.

    ``finger_max_um``: the layout-aware device template the schematic was sized
    with (pro generator); the extracted devices are mapped to the same builder.
    """
    start = time.perf_counter()
    directory = Path(directory).resolve()

    def stage(name, data=None):
        if observer:
            observer(name, data or {})

    stage("layout")
    from .pro.planner import ProPlan

    if plan is None:
        layout = synthesize(topology, values, directory, vdd=vdd)
    elif isinstance(plan, ProPlan):
        from .pro.compiler import synthesize as compile_pro

        current = ((prelayout or {}).get("metrics", {}).get("power_uw") or 1800) * 1e-6 / vdd
        layout = compile_pro(topology, values, directory, vdd=vdd, plan=plan, current_a=current,
                             finger_max_um=finger_max_um)
    else:
        from .compiler import synthesize as compile_layout

        current = ((prelayout or {}).get("metrics", {}).get("power_uw") or 1800) * 1e-6 / vdd
        layout = compile_layout(topology, values, directory, vdd=vdd, plan=plan, current_a=current)
    stage("extracting", layout)
    matched = lvs(directory)
    extraction = extract_rc(directory)
    stage("postsimulating", {"layout": layout, "lvs": matched, "pex": extraction})
    builder = build(topology, values, vdd, finger_max=finger_max_um)
    circuit = ExtractedCircuit(builder, directory / "pex.spice")
    if prelayout is None:
        prelayout = evaluate(
            topology,
            values,
            directory=directory / "prelayout",
            strict=True,
            keep=True,
            vdd=vdd,
            load_pf=load_pf,
            input_bias=input_bias,
            temperature=temperature,
        )
    post = evaluate(
        topology,
        values,
        directory=directory / "postlayout",
        strict=True,
        keep=True,
        vdd=vdd,
        load_pf=load_pf,
        circuit=circuit,
        input_bias=input_bias,
        temperature=temperature,
    )
    post.pop("pid", None)
    physical_schematic = None
    if (directory / "manifest.json").exists() and json.loads(
            (directory / "manifest.json").read_text()).get("generator", "").startswith("pro-rows"):
        # The declared physical netlist without parasitics: separates what
        # re-fingering changed from what the layout parasitics changed.
        from .pro.physical import PhysicalSchematic

        physical_schematic = evaluate(
            topology, values, directory=directory / "physical-schematic", strict=True, keep=True,
            vdd=vdd, load_pf=load_pf, circuit=PhysicalSchematic(builder, directory),
            input_bias=input_bias, temperature=temperature)
        physical_schematic.pop("pid", None)
    result = {
        "physical_schematic": physical_schematic,
        "valid": bool(
            prelayout["valid"] and layout["drc_errors"] == 0 and matched["passed"] and post["valid"]
        ),
        "layout": layout,
        "lvs": matched,
        "pex": extraction,
        "postlayout": post,
        "prelayout": prelayout,
        "performance_delta": {
            k: post["metrics"][k] - v
            for k, v in prelayout["metrics"].items()
            if k in post["metrics"]
            and isinstance(v, (int, float))
            and isinstance(post["metrics"][k], (int, float))
        },
        "physical_seconds": time.perf_counter() - start,
        "scope": "SKY130 TT; external ideal bias sources and load; nominal qualification",
    }
    artifacts = (
        "layout.mag",
        "layout.gds",
        "reference.spice",
        "lvs.spice",
        "pex.spice",
        "drc.txt",
        "lvs.log",
        "extraction.tcl",
        "postlayout/design.cir",
    )
    result["sha256"] = {
        p: hashlib.sha256((directory / p).read_bytes()).hexdigest() for p in artifacts
    }
    (directory / "physical.json").write_text(json.dumps(result, indent=2, allow_nan=False))
    return result
