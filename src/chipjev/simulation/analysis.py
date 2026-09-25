"""Measurement of an amplifier or op-amp design from one ngspice run (any technology).

It reproduces the published parts of AnalogCoder-Pro's evaluation of its unified
topology-generation-and-optimization tasks: the multi-resolution input bias search of its
released ``dc_sweep_template.py`` (coarse, medium and fine DC sweeps that place the output
closest to VDD/2; op-amp inputs tied together), the operating-point checks of
``check_netlist`` in optimization mode, the ``problem_check`` rules (every transistor
conducts at least 10 uA; an op-amp's differential gain exceeds its common-mode gain) and
the metric definitions of its Table VII (gain at low frequency, GBW = gain x -3 dB
bandwidth, FoM = GBW x CL / power). A physically attached CL = 100 pF (AnalogGenie's load
for the same FoM), a 60-degree phase-margin requirement (PM_MIN) and a minimum DC gain per
class (MIN_GAIN_DB) are this testbench's choices.
The "physical" rules add what a circuit designer would require of an amplifier: every
transistor in saturation, open-loop stability (a perturbed operating point settles), a
phase margin of at least 60 degrees at every unity-gain crossing, a minimum DC gain, and
GBW = min(gain x bandwidth, unity-gain frequency), so that a pole-zero doublet or peaking
cannot inflate it. The "qualified" rules (the default) add CMRR and, for op-amps, a
closed-loop unity-buffer test. The "published" rules keep AnalogCoder-Pro's definitions and
checks only.

The technology-specific decks live in ptm45.py (PTM 45 nm) and sky130.py (SkyWater SKY130);
both write the same control script and are measured by ``analyze``.
"""

import math

import numpy as np

from ..circuits.grammar import VDD

ONLINE = "reltol=1e-4 abstol=1e-12 vntol=1e-7"


LOAD_PF = 100.0


MARGIN = 0.2  # dc_sweep_template.py sweeps the input over [0.2, VDD - 0.2]


MIN_CURRENT = 1e-5  # problem_check: every MOSFET conducts at least 10 uA


# Added requirement (not in AnalogCoder-Pro): with gain above 0 dB, a phase margin of at
# least 60 degrees at the unity-gain frequency, so that GBW = gain x bandwidth describes a
# usable, compensated amplifier rather than a peaking or unstable one.
PM_MIN = 60.0


PM_MAX = 180.0  # a phase lead at the unity-gain frequency is treated as an anomaly


# Added requirement: open-loop stability. After the AC analyses a transient run from the
# operating point injects a 1 pA, 1 ns current pulse into every internal node; the output
# of a stable amplifier stays within nanovolts, while a right-half-plane pole (a positive
# feedback loop) makes it run away or oscillate. SETTLE_V is the tolerated deviation.
SETTLE_WINDOW = ("1u", "100u")  # (step, stop)


SETTLE_V = 0.01


# Added requirement: a useful amplifier. Minimum DC gain per class (dB); AnalogCoder-Pro's
# GBW and FoM tasks set none, so a two-stage "op-amp" with 7 dB of gain would qualify.
MIN_GAIN_DB = {"amp1": 20.0, "opamp1": 40.0, "ampN": 40.0, "opampN": 60.0}


VTH_CHECK = 0.01  # check_netlist(optimize=True)


# Evaluation rules. "physical" (this work's benchmark): the phase-margin and minimum-gain
# requirements above, and GBW = min(gain x -3 dB bandwidth, unity-gain frequency), which
# never exceeds AnalogCoder-Pro's value for the same circuit. "published": AnalogCoder-Pro's
# published rules only (GBW = gain x bandwidth, no stability or minimum-gain requirement).
RULES = ("qualified", "physical", "published")


CMRR_MIN_DB = 40.0


BUFFER_GAIN_ERROR = 0.02


BUFFER_RINGING = 0.02


BUFFER_DC_ERROR_V = 0.01


class BenchError(RuntimeError):
    pass


def sweep_levels(vdd):
    """(low, high, [(step, half-width)] x 3) of dc_sweep_template.py for a supply."""
    low, high = MARGIN, vdd - MARGIN
    span = high - low
    return low, high, ((span / 20, None), (span / 200, span / 8), (span / 2000, span / 80))


def _search_script(source, vdd=VDD):
    """ngspice control code for the three-level bias search; leaves $vbest set."""
    low, high, levels = sweep_levels(vdd)
    target = vdd / 2
    lines = []
    for level, (step, half) in enumerate(levels, 1):
        if half is None:
            lines.append(f"set lo{level} = {low:.6f}")
            lines.append(f"set hi{level} = {high:.6f}")
        else:
            lines += [
                f"let lo = $v{level - 1} - {half:.6f}",
                f"let hi = $v{level - 1} + {half:.6f}",
                f"if lo < {low:.6f}",
                f"  let lo = {low:.6f}",
                "end",
                f"if hi > {high:.6f}",
                f"  let hi = {high:.6f}",
                "end",
                f'set lo{level} = "$&lo"',
                f'set hi{level} = "$&hi"',
            ]
        lines += [
            f"dc {source} $lo{level} $hi{level} {step:.6f}",
            f"let d = abs(v(out) - {target:.6f})",
            "let span = vecmax(v(out)) - vecmin(v(out))",
            f'set span{level} = "$&span"',
            "let dm = vecmin(d)",
            "let k = 0",
            "let bi = 0",
            "while k < length(d)",
            "  if d[k] = dm",
            "    let bi = k",
            "    break",
            "  end",
            "  let k = k + 1",
            "end",
            f"let vb = $lo{level} + bi * {step:.6f}",
            f'set v{level} = "$&vb"',
            f'set d{level} = "$&dm"',
            f'echo "@@S {level} $&vb $&dm $&span"',
        ]
    # Global choice over all levels: smallest distance, ties broken towards VDD/2.
    lines += [
        "let bv = $v1",
        "let bd = $d1",
        "let cv = $v2",
        "let cd = $d2",
        f"if (cd < bd) | ((cd = bd) & (abs(cv - {target:.6f}) < abs(bv - {target:.6f})))",
        "  let bv = cv",
        "  let bd = cd",
        "end",
        "let cv = $v3",
        "let cd = $d3",
        f"if (cd < bd) | ((cd = bd) & (abs(cv - {target:.6f}) < abs(bv - {target:.6f})))",
        "  let bv = cv",
        "  let bd = cd",
        "end",
        'set vbest = "$&bv"',
        'echo "@@B $&bv $&bd"',
    ]
    return lines


def _interp_log(f1, f2, y1, y2, target):
    """Frequency where y crosses target between (f1, y1) and (f2, y2), log-f interpolation."""
    if y1 == y2:
        return f2
    t = (y1 - target) / (y1 - y2)
    return 10 ** (math.log10(f1) + t * (math.log10(f2) - math.log10(f1)))


def analyze(stdout, ac_path, b, topology, load_pf=LOAD_PF, vdd=VDD, rules="qualified"):
    """Parse the echoed operating point and AC data; apply checks; compute metrics."""
    if rules not in RULES:
        raise ValueError(f"unknown rules {rules!r}")
    physical = rules in ("physical", "qualified")
    volts, currents, supplies, sweeps, saturation = {"0": 0.0}, {}, {}, [], {}
    best = cm_gain = settle = None
    for line in stdout.splitlines():
        if not line.startswith("@@"):
            continue
        parts = line.split()
        tag = parts[0]
        try:
            if tag == "@@V":
                volts[parts[1]] = float(parts[2])
            elif tag == "@@I":
                currents[parts[1]] = float(parts[2])
            elif tag == "@@P":
                supplies[parts[1]] = float(parts[2])
            elif tag == "@@S":
                sweeps.append(tuple(float(x) for x in parts[1:5]))
            elif tag == "@@B":
                best = (float(parts[1]), float(parts[2]))
            elif tag == "@@C":
                cm_gain = float(parts[1])
            elif tag == "@@D":
                saturation[parts[1]] = float(parts[2])
            elif tag == "@@T":
                settle = float(parts[1])
        except (IndexError, ValueError) as exc:
            raise BenchError(f"unparsable simulator line: {line!r}") from exc
    if best is None or len(sweeps) != 3:
        raise BenchError("bias search did not complete")
    if "out" not in volts or len(currents) != len(b.mos):
        raise BenchError("operating point did not complete")
    if not ac_path.exists():
        raise BenchError("AC analysis did not complete")
    data = np.atleast_2d(np.loadtxt(ac_path, skiprows=1))
    if data.shape[1] < 3 or not np.isfinite(data).all():
        raise BenchError("nonfinite AC data")
    frequency, magnitude, phase = data[:, 0], data[:, 1], data[:, 2]

    checks = {}
    # dc_sweep_template / get_best_voltage: a flat output cannot be biased.
    checks["bias_found"] = max(s[3] for s in sweeps) >= 1e-6
    # check_netlist(optimize=True) reads the operating point with six decimals.
    rounded = {k: round(v, 6) for k, v in volts.items()}
    supply = rounded.get("vdd", vdd)
    region = []
    region_margin = np.inf
    for name, d, g, s, kind in b.mos:
        vd, vg, vs = rounded[d], rounded[g], rounded[s]
        bad = False
        if kind == "n":
            bad |= (vd == 0.0) or (vd < vs)
            bad |= (vg == vs) or (vg < vs) or (vg <= vs + VTH_CHECK)
            region_margin = min(region_margin, vd - vs, vg - vs - VTH_CHECK)
        else:
            bad |= (vd == supply and d != "vdd") or (vd > vs)
            bad |= (vg == vs) or (vg > vs) or (vg >= vs - VTH_CHECK)
            region_margin = min(region_margin, vs - vd, vs - vg - VTH_CHECK)
        if bad:
            region.append(name)
    checks["operating_point"] = not region
    checks["currents"] = all(abs(i) >= MIN_CURRENT for i in currents.values())
    gain_100 = float(np.interp(2.0, np.log10(frequency), magnitude))
    if topology.differential:
        checks["function"] = (
            cm_gain is not None and cm_gain < 2 * gain_100 - 1e-5 and 2 * gain_100 > 1e-5
        )
    else:
        checks["function"] = gain_100 > 1e-5
    a0 = float(magnitude[0])
    below = np.nonzero(magnitude < a0 / math.sqrt(2))[0]
    checks["bandwidth"] = bool(len(below)) and below[0] > 0
    metrics = {
        "vin_dc": best[0],
        "vout_dc": volts["out"],
        "bias_error_v": best[1],
        "gain_db": 20 * math.log10(max(a0, 1e-30)),
        "cm_gain_db": 20 * math.log10(max(cm_gain, 1e-30)) if cm_gain is not None else None,
        "dc_phase_deg": float(phase[0]),
    }
    power = -vdd * supplies.get("vdd", 0.0)
    for node, current in supplies.items():
        if node != "vdd":
            power += max(0.0, -b.bias[node[2:]] * current)
    metrics["power_uw"] = power * 1e6
    checks["power"] = power > 0
    # Unity-gain crossings (from above to below one): the unity-gain frequency is the
    # first, and the phase margin is checked at every one of them.
    crossings = np.nonzero((magnitude[:-1] >= 1.0) != (magnitude[1:] >= 1.0))[0] + 1
    phase_margins = []
    if a0 > 1 and len(crossings):
        for j in crossings:
            f = _interp_log(frequency[j - 1], frequency[j], magnitude[j - 1], magnitude[j], 1.0)
            lag = phase[0] - float(np.interp(math.log10(f), np.log10(frequency), phase))
            phase_margins.append(180.0 - lag)
            if len(phase_margins) == 1:
                metrics["ugf_mhz"] = f / 1e6
        metrics["pm_deg"] = min(phase_margins)
    if checks["bandwidth"]:
        j = below[0]
        f3 = _interp_log(
            frequency[j - 1], frequency[j], magnitude[j - 1], magnitude[j], a0 / math.sqrt(2)
        )
        metrics["bw_mhz"] = f3 / 1e6
        metrics["gbw_def_mhz"] = a0 * f3 / 1e6  # AnalogCoder-Pro: gain x bandwidth
        metrics["gbw_mhz"] = metrics["gbw_def_mhz"]
        if physical and "ugf_mhz" in metrics:
            metrics["gbw_mhz"] = min(metrics["gbw_def_mhz"], metrics["ugf_mhz"])
        if checks["power"]:
            metrics["fom"] = metrics["gbw_mhz"] * load_pf / (metrics["power_uw"] / 1e3)
    min_gain = MIN_GAIN_DB.get(topology.cls, -np.inf)
    pm_margin = None
    if phase_margins:
        pm_margin = min(min(phase_margins) - PM_MIN, PM_MAX - max(phase_margins))
    if physical:
        checks["stability"] = a0 <= 1 or (pm_margin is not None and pm_margin >= 0)
        checks["gain"] = metrics["gain_db"] >= min_gain
        # Every transistor in saturation (V_DS >= V_DSAT, BSIM4, type-normalized).
        checks["saturation"] = len(saturation) == len(b.mos) and min(saturation.values()) >= 0
        checks["settles"] = settle is not None and settle < SETTLE_V
        if saturation:
            region_margin = min(region_margin, min(saturation.values()))
        if settle is not None:
            metrics["settle_v"] = settle
    # Continuous constraint margins (>= 0 means satisfied) for constraint-aware search;
    # requirements that the rules do not impose get a constant, satisfied margin.
    smallest = min(abs(i) for i in currents.values())
    margins = {
        "gain_db": metrics["gain_db"] - min_gain if physical else 10.0,
        "pm_deg": pm_margin if physical else 30.0,
        "current_decades": math.log10(max(smallest, 1e-15) / MIN_CURRENT),
        "region_v": float(region_margin),
    }
    if topology.differential:
        metrics["cmrr_db"] = (
            20 * math.log10(max(gain_100, 1e-30) / max(cm_gain, 1e-30))
            if cm_gain is not None
            else None
        )
    if rules == "qualified":
        cmrr = metrics.get("cmrr_db")
        checks["cmrr"] = not topology.differential or (cmrr is not None and cmrr >= CMRR_MIN_DB)
        margins["cmrr_db"] = (
            cmrr - CMRR_MIN_DB if topology.differential and cmrr is not None else 40.0
        )
    checks = {k: bool(v) for k, v in checks.items()}
    metrics = {k: (None if v is None else float(v)) for k, v in metrics.items()}
    margins = {k: (None if v is None else float(v)) for k, v in margins.items()}
    valid = all(checks.values())
    return valid, checks, metrics, region, margins


def objective(record, target):
    """Objective of a record in the search's modelling domain (higher is better):
    gain in dB, log10 GBW (MHz) or log10 FoM. None when unmeasured."""
    metrics = record.get("metrics") or {}
    if target == "gain":
        value = metrics.get("gain_db")
        return None if value is None else float(value)
    key = {"gbw": "gbw_mhz", "fom": "fom"}[target]
    value = metrics.get(key)
    if value is None or not value > 0:
        return None
    return math.log10(value)


def reported(record, target):
    """Objective in reported units (dB, MHz, MHz pF/mW)."""
    metrics = record.get("metrics") or {}
    return metrics.get({"gain": "gain_db", "gbw": "gbw_mhz", "fom": "fom"}[target])
