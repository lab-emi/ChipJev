"""Versioned SKY130 routing policy; Magic's full deck remains the geometry oracle.

Values are in um and ohm/square. Conservative generator clearances are distinct
from foundry minima. EM, substrate noise and whole-die density are not inferred
from a clean local DRC report.
"""

import hashlib
import math
from functools import lru_cache

from ..simulation.pdk import model_root

GRID = 0.005
POLICY = "sky130-analog-1"
SOURCE = "https://skywater-pdk.readthedocs.io/en/main/rules/periphery.html"
WIDTH = {1: 0.14, 2: 0.14, 3: 0.30, 4: 0.30, 5: 1.60}
SPACE = {1: 0.28, 2: 0.28, 3: 0.60, 4: 0.60, 5: 1.60}
# sky130A.tech extract resist (allmN), converted from milliohm/square.
SHEET = {1: 0.105, 2: 0.105, 3: 0.038, 4: 0.038, 5: 0.021}


def units(um):
    return int(math.ceil(float(um) / (2 * GRID) - 1e-9)) * 2


def rail_width(current_a, length_um, drop_v=0.002, multiplier=1):
    if not all(math.isfinite(x) and x > 0 for x in (current_a, length_um, drop_v)):
        raise ValueError("Rail sizing requires positive finite current, length and IR budget")
    return units(max(1.2, SHEET[4] * current_a * length_um / drop_v) * multiplier)


@lru_cache(maxsize=1)
def provenance():
    root = model_root()
    files = ("magic/sky130A.tech", "magic/sky130A.tcl", "netgen/sky130A_setup.tcl")
    return {
        "policy": POLICY,
        "grid_um": GRID,
        "source": SOURCE,
        "files": {
            p: hashlib.sha256((root / "libs.tech" / p).read_bytes()).hexdigest() for p in files
        },
        "coverage": {
            "geometry": "Magic drc(full), checked after compilation",
            "connectivity": "Netgen LVS and RC device inventory",
            "electromigration": "unsupported: no qualified current-density limits",
            "whole_die_density": "not_run: requires integration context",
            "substrate_noise": "unsupported",
            "thermal_gradient": "unsupported",
        },
        "routing_policy": {
            "min_width_um": WIDTH,
            "clearance_um": SPACE,
            "sheet_ohm_per_square": SHEET,
        },
    }
