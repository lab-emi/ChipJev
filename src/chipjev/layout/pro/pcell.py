"""PDK PCells drawn once by Magic and cached (poly resistor segments)."""

import hashlib
import json
import shutil
import tempfile
import uuid
from pathlib import Path

from ...paths import ROOT
from ..magic import rectangles, run_magic
from ..technology import provenance


def pcell(model, params):
    """Rectangles of a PDK PCell, drawn by Magic once per parameter set."""
    tech = provenance()
    cache = ROOT / "runs/pcell-cache" / tech["files"]["magic/sky130A.tcl"][:16]
    cache.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(json.dumps([model, params, tech], sort_keys=True).encode()).hexdigest()
    saved = cache / f"{key}.mag"
    if not saved.exists():
        with tempfile.TemporaryDirectory(prefix="chipjev-pcell-") as tmp:
            text = " ".join(f"{k} {v:.9g}" for k, v in params.items())
            run_magic(Path(tmp), f"load cell\nbox values 0 0 0 0\n"
                                 f"set p [dict merge [sky130::{model}_defaults] {{{text}}}]\n"
                                 f"sky130::{model}_draw $p\nsave cell", "pcell")
            temporary = cache / f"{key}.{uuid.uuid4().hex}.tmp"
            shutil.copyfile(Path(tmp) / "cell.mag", temporary)
            temporary.replace(saved)
    return rectangles(saved)


def resistor_segment(w_um, l_um):
    """Generic poly resistor unit: shapes, bounds and its two metal1 end pads."""
    shapes = pcell("sky130_fd_pr__res_generic_po", {"w": w_um, "l": l_um, "guard": 0, "vias": 1})
    shapes.pop("checkpaint", None)
    rects = [r for group in shapes.values() for r in group]
    bounds = (min(r[0] for r in rects), min(r[1] for r in rects),
              max(r[2] for r in rects), max(r[3] for r in rects))
    metal = sorted(shapes["metal1"], key=lambda r: r[1])
    bottom = (min(r[0] for r in metal), metal[0][1], max(r[2] for r in metal),
              max(r[3] for r in metal if r[1] < 0))
    top = (min(r[0] for r in metal), min(r[1] for r in metal if r[1] > 0), max(r[2] for r in metal),
           metal[-1][3])
    return {"shapes": shapes, "bounds": bounds, "pads": (bottom, top)}
