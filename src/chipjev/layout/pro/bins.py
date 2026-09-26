"""SKY130 model-bin boundaries: re-fingering must keep W/NF inside the simulated bin.

The 1.8 V FET models are binned by W and L, and ``wnflag=1`` selects the bin
by W/NF. A layout that re-fingers a device into another W bin silently swaps
its parameter set (threshold, mobility), which moves the bias point of any
fixed-gate current source. Keeping each finger in the bin of the schematic
W/NF preserves the simulated device; only intra-bin geometry and layout
parasitics then differ, and the post-layout simulation measures both.
"""

import re
from functools import lru_cache

from ...simulation.pdk import model_root

MODELS = {"n": "sky130_fd_pr__nfet_01v8__tt.pm3.spice", "p": "sky130_fd_pr__pfet_01v8__tt.pm3.spice"}


@lru_cache(maxsize=None)
def edges(kind):
    """Sorted W bin edges (um) of the TT model file for this polarity."""
    text = (model_root() / "libs.ref/sky130_fd_pr/spice" / MODELS[kind]).read_text().lower()
    values = set()
    for key in ("wmin", "wmax"):
        for match in re.finditer(rf"\b{key}\s*=\s*([0-9.]+e[+-]?[0-9]+|[0-9.]+)", text):
            values.add(round(float(match[1]) * 1e6, 4))
    return tuple(sorted(v for v in values if v > 0))


def bin_range(kind, w_finger_um):
    """[low, high) bin containing a finger width."""
    low, high = 0.0, float("inf")
    for edge in edges(kind):
        if edge <= w_finger_um + 1e-9:
            low = edge
        elif edge < high:
            high = edge
            break
    return low, high
