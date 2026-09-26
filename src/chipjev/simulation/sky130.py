"""The qualified amplifier/op-amp testbench on the open SkyWater SKY130 PDK (TT, 1.8 V).

Everything that defines a measurement is shared with the PTM 45 nm testbench (analysis.py):
the three-level input-bias search of AnalogCoder-Pro's dc_sweep_template, the
operating-point, current, function, bandwidth, stability, saturation, settling,
minimum-gain and CMRR checks, the metric definitions (gain, GBW = min(A0 f-3dB, fu),
FoM = GBW CL / P) and the constraint margins (``analyze``). This module only writes the
deck for SKY130 devices (circuits/sky130_devices.py), runs the PDK's standard ngspice mode
(``ngbehavior=hsa``) and repeats the strict unity-buffer qualification of op-amps with the
same devices (online as well as strict).
"""

import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import numpy as np

from ..circuits.sky130_devices import VDD, build, include_text, probe
from ..paths import ngspice
from .analysis import (
    BUFFER_DC_ERROR_V,
    BUFFER_GAIN_ERROR,
    BUFFER_RINGING,
    LOAD_PF,
    ONLINE,
    SETTLE_WINDOW,
    BenchError,
    _search_script,
    analyze,
    objective,
    reported,
)

__all__ = ["VDD", "LOAD_PF", "deck", "evaluate", "objective", "reported", "qualify_buffer"]

SPICEINIT = "set ngbehavior=hsa\nset ng_nomodcheck\nset num_threads=1\n"
STEP_V = 0.01
# Simulation time limits. SKY130's binned BSIM4 cards make some nonsensical designs (mostly
# random multi-stage op-amps) spend seconds in the bias-search DC sweeps; an online
# simulation that exceeds ONLINE_LIMIT_S fails like any unconvergent design. The limit is
# the same for every method; strict re-simulation keeps a generous limit.
ONLINE_LIMIT_S = 2.0
STRICT_LIMIT_S = 60.0
# Strict tolerances: the PTM testbench's reltol and vntol (100x tighter than online) with
# the online abstol of 1e-12 A instead of 1e-14 A. The ideal gate-bias sources of SKY130 devices carry
# only femtoampere gate leakage, so at abstol 1e-14 (and often 1e-13) the buffer transients
# abort with "timestep too small" for numerical, not circuit, reasons.
STRICT = "reltol=1e-6 abstol=1e-12 vntol=1e-9"


def deck(topology, values, *, quantize_geometry=False, strict=False, load_pf=LOAD_PF, vdd=VDD, rules="qualified",
         temperature=27.0, corner="tt", circuit=None, input_bias=None, mismatch_seed=None):
    """Return (deck text, Builder): ptm45.deck with SKY130 devices."""
    target = vdd / 2
    from ..circuits.sky130_devices import build_on_grid
    make = build_on_grid if quantize_geometry else build
    b = circuit if circuit is not None else make(topology, values, vdd)
    lines = [f"* ChipJev-Topo SKY130 {topology.id}", include_text(corner, mismatch=mismatch_seed is not None)]
    lines += getattr(b, "model_lines", [])
    lines.append(f".options {STRICT if strict else ONLINE}")
    if mismatch_seed is not None:
        # Set after startup: ngspice's Gaussian initializer can reseed after
        # .spiceinit. A deck option is evaluated before PDK random parameters.
        lines.append(f".options seed={mismatch_seed + 1} seedinfo")
    lines.append(f".temp {temperature:.6g}")
    lines.append(f"vdd vdd 0 DC {vdd}")
    if topology.differential:
        source = "vcm"
        lines += [f"vcm cm 0 DC {target}", "vinp inp cm DC 0 AC 0.5",
                  "vinn inn cm DC 0 AC 0.5 180"]
    else:
        source = "vin"
        lines.append(f"vin in 0 DC {target} AC 1")
    for node, volts in sorted(b.bias.items()):
        lines.append(f"v_{node} {node} 0 DC {volts:.6f}")
    lines += b.lines
    driven = {"vdd", "in", "inp", "inn", "cm", *b.bias}
    internal = sorted(n for n in b.nodes | {"out"} if n not in driven)
    if rules in ("physical", "qualified"):
        lines += [f"iprt_{n} 0 {n} PULSE(0 1p 10n 1n 1n 1n 1)" for n in internal]
    lines.append(f"cload out 0 {load_pf * 1e-12:.6g}")
    control = ["set noaskquit", "set wr_singlescale", "set wr_vecnames", "set numdgt=10"]
    if input_bias is None:
        control += _search_script(source, vdd)
    else:
        if not np.isfinite(input_bias) or not 0 < input_bias < vdd:
            raise ValueError("Fixed input bias must be finite and inside the supply rails")
        control += [f"set vbest = {input_bias:.12g}"]
    control += [f"alter {source} dc = $vbest", "op"]
    if input_bias is not None:
        control += [f"let biaserror = abs(v(out) - {target:.12g})",
                    f'echo "@@B {input_bias:.12g} $&biaserror"']
    nodes = sorted(b.nodes | ({"inp", "inn"} if topology.differential else {"in"}) | {"out"})
    for node in nodes:
        control.append(f'echo "@@V {node} $&v({node})"')
    for name, _d, _g, _s, kind in b.mos:
        if circuit is not None:
            control += b.probe_commands(name, kind)
            control += [f'echo "@@I {name} $&i_{name}"', f'echo "@@D {name} $&d_{name}"']
        else:
            control += [f"let i_{name} = {probe(name, kind, 'id')}",
                        f'echo "@@I {name} $&i_{name}"',
                        f"let d_{name} = {probe(name, kind, 'vds')} - "
                        f"{probe(name, kind, 'vdsat')}",
                        f'echo "@@D {name} $&d_{name}"']
    for node in ["vdd", *(f"v_{n}" for n in sorted(b.bias))]:
        control += [f"let s_{node} = i({node})", f'echo "@@P {node} $&s_{node}"']
    control += ["ac dec 20 1 100g", "let mag = abs(v(out))", "let pha = cph(v(out)) * 180 / pi",
                "wrdata ac.tsv mag pha"]
    if topology.differential:
        control += ["alter @vinn[acphase] = 0", "ac lin 1 100 100",
                    "let cmg = abs(v(out)) / 0.5", 'echo "@@C $&cmg"']
    if rules in ("physical", "qualified"):
        step, stop = SETTLE_WINDOW
        control += [f"tran {step} {stop}", "let dev = vecmax(abs(v(out) - v(out)[0]))",
                    'echo "@@T $&dev"']
    control.append("quit")
    text = "\n".join(lines) + "\n.control\n" + "\n".join(control) + "\n.endc\n.end\n"
    return text, b


def buffer_deck(topology, values, metrics, direction, load_pf, vdd, temperature, corner="tt",
                 options=None, circuit=None, mismatch_seed=None, quantize_geometry=False):
    """ptm45.buffer_deck with SKY130 devices."""
    vin = metrics["vin_dc"]
    ugf = metrics.get("ugf_mhz")
    stop = 100e-6 if not ugf else min(max(40 / (ugf * 1e6), 2e-6), 200e-6)
    delay = stop / 20
    inverted = abs(metrics["dc_phase_deg"]) >= 90
    feedback, signal = ("inp", "inn") if inverted else ("inn", "inp")
    from ..circuits.sky130_devices import build_on_grid
    make = build_on_grid if quantize_geometry else build
    builder = circuit if circuit is not None else make(topology, values, vdd)
    lines = [
        f"* Qualified buffer (SKY130): {topology.id}, direction {direction}",
        include_text(corner, mismatch=mismatch_seed is not None),
        f".options {options or STRICT}" + (f" seed={mismatch_seed + 1} seedinfo" if mismatch_seed is not None else ""),
        f".temp {temperature:.6g}",
        f"vdd vdd 0 DC {vdd}",
        f"vsig {signal} 0 DC {vin:.9g} PULSE({vin:.9g} "
        f"{vin + direction * STEP_V:.9g} {delay:.9g} 1n 1n 1 2)",
        f"vfb {feedback} out DC 0",
    ]
    lines += getattr(builder, "model_lines", [])
    lines += [f"v_{n} {n} 0 DC {v:.9g}" for n, v in sorted(builder.bias.items())]
    lines += builder.lines + [
        f"cload out 0 {load_pf * 1e-12:.9g}",
        ".control", "set noaskquit", "set wr_singlescale", "set numdgt=12",
        f"tran {stop / 4000:.9g} {stop:.9g} 0 {stop / 4000:.9g}",
        f"wrdata buffer-{direction}.tsv v(out)", "quit", ".endc", ".end",
    ]
    return "\n".join(lines) + "\n", stop, delay


def qualify_buffer(topology, values, metrics, directory, *, load_pf=LOAD_PF, vdd=VDD,
                   temperature=27.0, corner="tt", strict=True, circuit=None, mismatch_seed=None, quantize_geometry=False,
                   online_timeout_s=None):
    """ptm45.qualify_buffer with SKY130 devices (same criteria); an
    online check (strict=False) uses the online tolerances and time limit and keeps no
    waveforms."""
    steps = []
    for direction in (1, -1):
        try:
            text, stop, delay = buffer_deck(topology, values, metrics, direction, load_pf, vdd,
                                            temperature, corner,
                                            options=STRICT if strict else ONLINE, circuit=circuit,
                                            mismatch_seed=mismatch_seed, quantize_geometry=quantize_geometry)
            path = directory / f"buffer-{direction}.cir"
            path.write_text(text)
            proc = subprocess.run([ngspice(), "-b", path.name], cwd=directory,
                                  capture_output=True, text=True,
                                  timeout=30 if strict else (ONLINE_LIMIT_S if online_timeout_s is None else online_timeout_s))
            if proc.returncode:
                raise ValueError(f"buffer transient exited with code {proc.returncode}")
            data = np.atleast_2d(np.loadtxt(directory / f"buffer-{direction}.tsv"))
            if data.shape[1] < 2 or not np.isfinite(data).all() or data[-1, 0] < 0.999 * stop:
                raise ValueError("incomplete or nonfinite buffer transient")
            t, v = data[:, 0], data[:, 1]
            before, tail = v[t < 0.9 * delay], v[t >= 0.8 * stop]
            v0, final = float(np.median(before)), float(np.median(tail))
            gain = (final - v0) / (direction * STEP_V)
            gain_error = abs(gain - 1.0)
            ringing = float(np.ptp(tail)) / STEP_V
            dc_error = abs(v0 - metrics["vin_dc"])
            passed = (gain_error <= BUFFER_GAIN_ERROR and ringing <= BUFFER_RINGING
                      and dc_error <= BUFFER_DC_ERROR_V)
            step = {"direction": direction, "gain": gain, "gain_error": gain_error,
                    "ringing": ringing, "dc_error_v": dc_error, "passed": bool(passed),
                    "error": None, "window_s": stop}
            if strict:
                indices = np.unique(np.linspace(0, len(t) - 1, 240).astype(int))
                step["waveform"] = {"t_us": ((t[indices] - delay) * 1e6).tolist(),
                                    "delta_mv": ((v[indices] - v0) * 1e3).tolist()}
            steps.append(step)
        except (OSError, ValueError, IndexError, subprocess.TimeoutExpired) as exc:
            steps.append({"direction": direction, "passed": False, "error": str(exc)})

    def worst(key):
        found = [s[key] for s in steps if key in s]
        return max(found) if len(found) == 2 else None

    return {"passed": all(s["passed"] for s in steps), "steps": steps,
            "max_gain_error": worst("gain_error"), "max_ringing": worst("ringing"),
            "max_dc_error_v": worst("dc_error_v")}


def evaluate(topology, values, directory=None, *, strict=False, load_pf=LOAD_PF, vdd=VDD,
             keep=False, rules="qualified", temperature=27.0, corner="tt", circuit=None,
             input_bias=None, mismatch_seed=None, quantize_geometry=False, online_timeout_s=None):
    """ptm45.evaluate on SKY130: one JSON-serializable record per design
    (never raises for a bad design)."""
    start = time.perf_counter()
    if online_timeout_s is not None and (not np.isfinite(online_timeout_s) or online_timeout_s <= 0):
        raise ValueError("Online simulation timeout must be positive and finite")
    own = directory is None
    directory = Path(directory or tempfile.mkdtemp(prefix="chipjev-sky130-"))
    directory.mkdir(parents=True, exist_ok=True)
    if mismatch_seed is not None and (not isinstance(mismatch_seed,int) or mismatch_seed<0):
        raise ValueError("Mismatch seed must be a nonnegative integer")
    (directory / ".spiceinit").write_text(SPICEINIT +
        (f"option seed={mismatch_seed + 1}\nsetseed {mismatch_seed + 1}\n" if mismatch_seed is not None else ""))
    record = {
        "topology": topology.id, "cls": topology.cls,
        "values": {k: float(v) for k, v in values.items()}, "strict": strict,
        "load_pf": load_pf, "vdd": vdd, "rules": rules, "temperature_c": temperature,
        "technology": f"sky130-{corner}", "valid": False, "checks": {}, "metrics": {},
        "margins": {}, "error": None,
    }
    if online_timeout_s is not None:
        record["online_timeout_s"] = online_timeout_s
    sim_seconds = 0.0
    try:
        text, b = deck(topology, values, strict=strict, load_pf=load_pf, vdd=vdd, rules=rules,
                       temperature=temperature, corner=corner, circuit=circuit,
                       input_bias=input_bias, mismatch_seed=mismatch_seed, quantize_geometry=quantize_geometry)
        if quantize_geometry:
            record["geometry_policy"] = "10 nm symmetric PCell grid"
        if mismatch_seed is not None:
            record["mismatch_seed"]=mismatch_seed
        if input_bias is not None:
            record["bias_policy"] = {"mode": "fixed", "input_v": input_bias}
        record["devices"] = len(b.mos)
        (directory / "design.cir").write_text(text)
        sim_start = time.perf_counter()
        try:
            proc = subprocess.run([ngspice(), "-b", "design.cir"], cwd=directory,
                                  capture_output=True, text=True,
                                  timeout=STRICT_LIMIT_S if strict else (ONLINE_LIMIT_S if online_timeout_s is None else online_timeout_s))
        except subprocess.TimeoutExpired as exc:
            raise BenchError("simulator timeout") from exc
        finally:
            sim_seconds = time.perf_counter() - sim_start
        output = proc.stdout + proc.stderr
        if keep:
            (directory / "design.log").write_text(output)
        if re.search(r"(?i)singular matrix|no convergence|timestep too small", output):
            if "@@B" not in output:
                raise BenchError("simulator did not converge")
        valid, checks, metrics, region, margins = analyze(
            output, directory / "ac.tsv", b, topology, load_pf, vdd, rules,
            fixed_bias=input_bias)
        record.update(valid=valid, checks=checks, metrics=metrics, margins=margins)
        # Unlike the PTM testbench (strict re-simulation only), the unity-buffer test also runs
        # online, so that online validity and qualification apply the same checks: on SKY130
        # many op-amps pass every open-loop check at the edge of the input-bias sweep but
        # cannot act as buffers there.
        if rules == "qualified" and valid and topology.differential:
            checked = qualify_buffer(topology, values, metrics, directory, load_pf=load_pf,
                                     vdd=vdd, temperature=temperature, corner=corner,
                                     strict=strict, circuit=circuit, mismatch_seed=mismatch_seed, quantize_geometry=quantize_geometry,
                                     online_timeout_s=online_timeout_s)
            record["qualification"] = checked
            record["checks"]["closed_loop"] = checked["passed"]
            record["valid"] = bool(checked["passed"])
            metrics["buffer_gain_error"] = checked.get("max_gain_error")
            metrics["buffer_ringing"] = checked.get("max_ringing")
            metrics["buffer_dc_error_v"] = checked.get("max_dc_error_v")
        if region:
            record["region_failures"] = region
    except (BenchError, OSError, ValueError, IndexError) as exc:
        record["error"] = str(exc)
    finally:
        record["simulator_seconds"] = sim_seconds
        record["wall_seconds"] = time.perf_counter() - start
        record["pid"] = os.getpid()
        if not keep and own:
            shutil.rmtree(directory, ignore_errors=True)
        elif not keep:
            for path in directory.glob("*"):
                if path.name != ".spiceinit":
                    path.unlink(missing_ok=True)
    return record
