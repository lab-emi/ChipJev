"""Robustness of finished designs: PVT corners and local mismatch Monte Carlo.

Every check repeats the complete qualified PTM 45 nm testbench (ptm45.py) at strict
tolerances (input bias search, operating point, AC, CMRR, open-loop perturbation and, for
op-amps, both unity-buffer steps) on the unchanged circuit, i.e. the same device sizes and
gate-bias voltages. The testbench re-finds the input bias in every condition, like the
nominal qualification does; for op-amps the buffer's 10-mV DC tracking limit then bounds
the input offset.

Corners: -40 and 125 degC at the nominal supply; supply -10% and +10% at 27 degC. The PTM
card has no process corners, so process variation is represented by mismatch only.

Mismatch: each transistor receives an independent threshold shift
delvto ~ N(0, A_VT / sqrt(W L)) (Pelgrom), with A_VT = 3.5 mV um, applied through the BSIM4
instance parameter delvto. The coefficient is an assumption typical of 45-nm-class bulk
processes, because PTM provides no mismatch data. These checks describe the delivered
nominal designs; no method optimized for them.
"""

import re

import numpy as np

from ..circuits.grammar import Builder

CORNERS = (
    {"name": "cold", "temperature": -40.0, "supply": 1.0},
    {"name": "hot", "temperature": 125.0, "supply": 1.0},
    {"name": "low-supply", "temperature": 27.0, "supply": 0.9},
    {"name": "high-supply", "temperature": 27.0, "supply": 1.1},
)
A_VT = 3.5e-3 * 1e-6  # V m (3.5 mV um)
SAMPLES = 64


class Shifted:
    """A topology whose transistors carry fixed threshold shifts (delvto, volts)."""

    construct = True

    def __init__(self, base, shifts):
        self.base, self.shifts = base, shifts
        self.cls, self.id, self.stages = base.cls, base.id, getattr(base, "stages", ())

    @property
    def differential(self):
        return self.base.differential

    def slots(self):
        return self.base.slots()

    def build(self, values, vdd):
        from ..circuits.grammar import build

        b = build(self.base, values, vdd)
        out = Builder(vdd)
        out.bias, out.nodes, out.mos = dict(b.bias), set(b.nodes), list(b.mos)
        names = {m[0]: k for k, m in enumerate(b.mos)}
        for line in b.lines:
            name = line.split()[0]
            if name in names:
                line += f" delvto={self.shifts[names[name]]:.6g}"
            out.lines.append(line)
        return out


def device_areas(topology, values, vdd):
    """W*L (m^2) of every transistor, in Builder order."""
    from ..circuits.grammar import build

    b = build(topology, values, vdd)
    areas = []
    for line in b.lines:
        if line.split()[0] in {m[0] for m in b.mos}:
            w = float(re.search(r"\bW=([0-9.eE+-]+)", line).group(1))
            l_ = float(re.search(r"\bL=([0-9.eE+-]+)", line).group(1))
            areas.append(w * l_)
    return np.array(areas)


def check(topology, values, *, target, vdd, load_pf, seed=0, samples=SAMPLES):
    """Corner and mismatch results of one design (strict qualified testbench)."""
    from .analysis import reported
    from .ptm45 import evaluate

    rows = {"corners": [], "mismatch": []}
    for corner in CORNERS:
        record = evaluate(topology, values, strict=True, load_pf=load_pf,
                          vdd=vdd * corner["supply"], rules="qualified",
                          temperature=corner["temperature"])
        rows["corners"].append(_row(record, target, reported, corner["name"]))
    sigma = A_VT / np.sqrt(device_areas(topology, values, vdd))
    rng = np.random.default_rng(seed)
    for k in range(samples):
        shifts = rng.normal(0.0, sigma)
        record = evaluate(Shifted(topology, shifts), values, strict=True, load_pf=load_pf,
                          vdd=vdd, rules="qualified")
        rows["mismatch"].append(_row(record, target, reported, f"mc{k}"))
    rows["corners_pass"] = all(r["valid"] for r in rows["corners"])
    rows["mismatch_yield"] = float(np.mean([r["valid"] for r in rows["mismatch"]]))
    rows["sigma_vt_mv"] = (1e3 * sigma).tolist()
    return rows


def _row(record, target, reported, name):
    metrics = record.get("metrics") or {}
    failed = sorted(k for k, v in (record.get("checks") or {}).items() if not v)
    return {
        "name": name,
        "valid": bool(record.get("valid")),
        "value": reported(record, target) if record.get("valid") else None,
        "gain_db": metrics.get("gain_db"),
        "pm_deg": metrics.get("pm_deg"),
        "cmrr_db": metrics.get("cmrr_db"),
        "buffer_dc_error_v": metrics.get("buffer_dc_error_v"),
        "failed": failed,
        "error": record.get("error"),
    }
