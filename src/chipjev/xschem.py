"""xschem schematics of SKY130 designs: open-source schematic capture for ChipJev results.

Each transistor of a design becomes the PDK's own xschem symbol (sky130_fd_pr/nfet_01v8.sym,
pfet_01v8.sym) with the simulated W, L, fingers and diffusion geometry; resistors, capacitors
and the supply and bias sources become xschem devices. Nets are named labels on the pins, so
xschem's netlister must reproduce the simulated netlist; ``check`` verifies exactly that.
"""

import os
import re
import shlex
import subprocess
import tempfile
from pathlib import Path

SYMBOL = {"n": "sky130_fd_pr/nfet_01v8.sym", "p": "sky130_fd_pr/pfet_01v8.sym"}
MODEL = {"n": "nfet_01v8", "p": "pfet_01v8"}
# Pin offsets of the symbols at rotation 0 (from the symbol files).
MOS_PINS = {"n": {"D": (20, -30), "G": (-20, 0), "S": (20, 30), "B": (20, 0)},
            "p": {"D": (20, 30), "G": (-20, 0), "S": (20, -30), "B": (20, 0)}}
TWO_PINS = ((0, -30), (0, 30))
PITCH = (240, 200)
COLUMNS = 6


def library():
    """The PDK's xschem library (open_pdks/volare sky130A)."""
    path = os.environ.get("CHIPJEV_SKY130_XSCHEM",
                          Path.home() / ".volare/sky130A/libs.tech/xschem")
    return Path(path)


def _label(x, y, net, index):
    return f"C {{devices/lab_pin.sym}} {x} {y} 0 0 {{name=l{index} sig_type=std_logic lab={net}}}"


def _parse(line):
    """(kind, name, nodes, params) of a builder device line."""
    tokens = line.split()
    params = dict(t.split("=", 1) for t in tokens if "=" in t)
    plain = [t for t in tokens if "=" not in t]
    if line.startswith("x"):
        kind = "n" if "nfet" in plain[5] else "p"
        return kind, plain[0][1:], plain[1:5], params
    return plain[0][0], plain[0], plain[1:3], {"value": plain[3]}


def schematic(builder, title, vdd, sources=True):
    """xschem schematic text of a Sky130Builder design (optionally with its DC sources)."""
    lines = ["v {xschem version=3.4.5 file_version=1.2}", "G {}", "K {}", "V {}", "S {}", "E {}",
             f"T {{{title}}} 0 -140 0 0 0.5 0.5 {{}}",
             f"T {{ChipJev design on SKY130 (TT), VDD = {vdd:g} V}} 0 -100 0 0 0.3 0.3 {{}}"]
    items = [_parse(line) for line in builder.lines]
    if sources:
        items.append(("v", "vdd", ["vdd", "0"], {"value": f"{vdd:g}"}))
        items += [("v", f"v_{node}", [node, "0"], {"value": f"{volts:.6g}"})
                  for node, volts in sorted(builder.bias.items())]
    labels = 0
    for index, (kind, name, nodes, params) in enumerate(items):
        x = (index % COLUMNS) * PITCH[0]
        y = (index // COLUMNS) * PITCH[1]
        if kind in ("n", "p"):
            props = (f"name={name.upper()} L={params['l']} W={params['w']} nf={params['nf']} "
                     f"mult={params.get('mult', '1')} ad={params['ad']} as={params['as']} "
                     f"pd={params['pd']} ps={params['ps']} nrd={params['nrd']} "
                     f"nrs={params['nrs']} sa=0 sb=0 sd=0 model={MODEL[kind]} spiceprefix=X")
            lines.append(f"C {{{SYMBOL[kind]}}} {x} {y} 0 0 {{{props}}}")
            for pin, net in zip(("D", "G", "S", "B"), nodes, strict=True):
                dx, dy = MOS_PINS[kind][pin]
                labels += 1
                lines.append(_label(x + dx, y + dy, net, labels))
        else:
            symbol = {"r": "res", "c": "capa", "v": "vsource"}[kind]
            lines.append(f"C {{devices/{symbol}.sym}} {x} {y} 0 0 "
                         f"{{name={name.upper()} value={params['value']} m=1}}")
            for (dx, dy), net in zip(TWO_PINS, nodes, strict=True):
                labels += 1
                lines.append(_label(x + dx, y + dy, net, labels))
    return "\n".join(lines) + "\n"


def netlist(path, workdir=None, timeout=60):
    """Netlist a schematic with xschem in batch mode; returns the SPICE text."""
    path = Path(path).resolve()
    work = Path(workdir or tempfile.mkdtemp(prefix="chipjev-xschem-"))
    work.mkdir(parents=True, exist_ok=True)
    rc = work / "xschemrc"
    rc.write_text("set XSCHEM_LIBRARY_PATH {}\n"
                  "append XSCHEM_LIBRARY_PATH ${XSCHEM_SHAREDIR}/xschem_library\n"
                  f"append XSCHEM_LIBRARY_PATH :{library()}\n"
                  "set netlist_type spice\nset lvs_netlist 0\n")
    command = ["xschem", "-n", "-s", "-x", "-q", "--rcfile", str(rc), "-o", str(work), str(path)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    output = work / (path.stem + ".spice")
    # xschem exits nonzero for "undriven node" notices: the inputs are driven by the testbench.
    notices = [line for line in result.stderr.splitlines() if line.startswith("Error:")]
    if not output.exists() or any("undriven node" not in line for line in notices):
        raise RuntimeError(f"xschem netlisting failed ({shlex.join(command)}): "
                           f"{result.stderr[-500:]}")
    text = output.read_text()
    if "IS MISSING" in text:
        raise RuntimeError("xschem could not resolve a symbol; set CHIPJEV_SKY130_XSCHEM")
    return text


def _devices(text):
    """{name: (model, nodes, {param: float})} of transistor, R, C and V lines in a netlist."""
    joined = re.sub(r"\n\+", " ", text)
    out = {}
    for line in joined.splitlines():
        tokens = line.split()
        if not tokens or tokens[0][0].lower() not in "xrcv" or tokens[0].startswith("."):
            continue
        name = tokens[0].lower()
        if name.startswith("x"):
            model = next((t for t in tokens if t.startswith("sky130_fd_pr__")), None)
            if model is None:
                continue
            nodes = tokens[1:tokens.index(model)]
            params = {}
            for t in tokens[tokens.index(model) + 1:]:
                if "=" in t:
                    k, v = t.split("=", 1)
                    try:
                        params[k.lower()] = float(v)
                    except ValueError:
                        params[k.lower()] = v
            out[name] = (model, tuple(n.lower() for n in nodes), params)
        else:
            out[name] = (name[0], tuple(n.lower() for n in tokens[1:3]), {"value": tokens[3]})
    return out


def check(builder, text, vdd):
    """True when xschem's netlist has the design's devices, nodes, transistor geometry and the
    values of its resistors, capacitors and sources."""
    ours = _devices("\n".join(builder.lines) + f"\nvdd vdd 0 {vdd:g}\n" + "".join(
        f"v_{n} {n} 0 {v:.6g}\n" for n, v in sorted(builder.bias.items())))
    theirs = _devices(text)
    problems = []
    for name, (model, nodes, params) in ours.items():
        other = theirs.get(name)
        if other is None:
            problems.append(f"{name} missing")
            continue
        if other[0] != model or other[1] != tuple(n if n != "0" else "0" for n in nodes):
            problems.append(f"{name} connectivity {other[:2]} != {(model, nodes)}")
            continue
        for key in ("w", "l", "nf", "ad", "as", "pd", "ps", "value"):
            if key in params:
                try:
                    a, b = float(params[key]), float(other[2].get(key, "nan"))
                except ValueError:
                    a, b = params[key], other[2].get(key)
                    if a != b:
                        problems.append(f"{name} {key} {b} != {a}")
                    continue
                if not abs(a - b) <= 1e-6 * max(1.0, abs(a)):
                    problems.append(f"{name} {key} {b} != {a}")
    extra = sorted(set(theirs) - set(ours))
    if extra:
        problems.append(f"unexpected devices {extra}")
    return not problems, problems
