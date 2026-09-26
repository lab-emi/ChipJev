"""The declared physical netlist (reference.spice) as a simulatable circuit.

It holds exactly the fingers, dummies, decoupling capacitors and MIM tiles the
generator drew, without parasitics. Simulating it separates what re-fingering
changed (model bin / W-dependent parameters, shared-diffusion junctions) from
what the layout parasitics changed, and lets electrical closure repair sizing
before any Magic run.
"""

import json
from collections import defaultdict

from ...circuits.sky130_devices import DEVICE
from ...simulation.pdk import model_root
from ..verification import spice_lines


class PhysicalSchematic:
    def __init__(self, builder, directory):
        self.mos, self.nodes, self.bias = builder.mos, builder.nodes, builder.bias
        text = (directory / "reference.spice").read_text()
        header = next(line.split() for line in spice_lines(text) if line.lower().startswith(".subckt"))
        ports = header[2:]
        self.lines = [text, "Xdut " + " ".join("0" if n == "vss" else n for n in ports) + " layout"]
        root = model_root() / "libs.tech/ngspice"
        # Same model set as the extracted netlist (the MIM model needs the r+c parameters).
        self.model_lines = [f'.include "{root / p}"' for p in (
            "r+c/res_typical__cap_typical.spice",
            "r+c/res_typical__cap_typical__lin.spice",
            "capacitors/sky130_fd_pr__model__cap_mim.model.spice",
        )]
        manifest = json.loads((directory / "manifest.json").read_text())
        self.mapping = defaultdict(list)
        for ident, entry in manifest["devices"].items():
            if entry["kind"] in ("n", "p") and not entry["auxiliary"]:
                self.mapping[entry["logical"]].append(f"x{ident}".lower())

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
