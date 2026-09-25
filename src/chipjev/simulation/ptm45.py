"""The testbench on PTM 45 nm models (1.2 V): deck, evaluation, and the strict
unity-buffer qualification of op-amps.

AnalogCoder-Pro's model file and optimizer helper are not released; the PTM 45 nm
high-performance card (models/ptm45hp.pm) is this testbench's choice. Everything runs in one
ngspice process per design. Strict re-simulation repeats the whole evaluation, bias search
included, at tighter tolerances. The measurement itself (bias search, checks, metrics and
margins) is shared with the SKY130 testbench (analysis.py).

The unity-buffer qualification is a nominal, local test at the searched input bias, not a
claim about the complete input/output range, mismatch, all closed-loop configurations, or
production sign-off.
"""

import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import numpy as np

from ..circuits.grammar import VDD, build
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

__all__ = ["LOAD_PF", "MODEL", "VDD", "deck", "evaluate", "objective", "qualify_buffer",
           "reported"]

MODEL = Path(__file__).resolve().parent / "models" / "ptm45hp.pm"


STRICT = "reltol=1e-6 abstol=1e-14 vntol=1e-9"


SPICEINIT = "set num_threads=1\n"


def deck(
    topology,
    values,
    *,
    strict=False,
    load_pf=LOAD_PF,
    vdd=VDD,
    model=MODEL,
    rules="qualified",
    temperature=27.0,
):
    """Return (deck text, Builder)."""
    target = vdd / 2
    b = build(topology, values, vdd)
    lines = [f"* ChipJev-Topo {topology.id}", f'.include "{model}"']
    lines.append(f".options {STRICT if strict else ONLINE}")
    lines.append(f".temp {temperature:.6g}")
    lines.append(f"vdd vdd 0 DC {vdd}")
    if topology.differential:
        source = "vcm"
        lines += [
            f"vcm cm 0 DC {target}",
            "vinp inp cm DC 0 AC 0.5",
            "vinn inn cm DC 0 AC 0.5 180",
        ]
    else:
        source = "vin"
        lines.append(f"vin in 0 DC {target} AC 1")
    for node, volts in sorted(b.bias.items()):
        lines.append(f"v_{node} {node} 0 DC {volts:.6f}")
    lines += b.lines
    driven = {"vdd", "in", "inp", "inn", "cm", *b.bias}
    internal = sorted(n for n in b.nodes | {"out"} if n not in driven)
    if rules in ("physical", "qualified"):
        # Perturbation sources for the open-loop stability run (zero in DC and AC).
        lines += [f"iprt_{n} 0 {n} PULSE(0 1p 10n 1n 1n 1n 1)" for n in internal]
    lines.append(f"cload out 0 {load_pf * 1e-12:.6g}")
    control = ["set noaskquit", "set wr_singlescale", "set wr_vecnames", "set numdgt=10"]
    control += _search_script(source, vdd)
    control += [f"alter {source} dc = $vbest", "op"]
    nodes = sorted(b.nodes | ({"inp", "inn"} if topology.differential else {"in"}) | {"out"})
    for node in nodes:
        control.append(f'echo "@@V {node} $&v({node})"')
    for name, *_ in b.mos:
        control += [
            f"let i_{name} = @{name}[id]",
            f'echo "@@I {name} $&i_{name}"',
            f"let d_{name} = @{name}[vds] - @{name}[vdsat]",
            f'echo "@@D {name} $&d_{name}"',
        ]
    for node in ["vdd", *(f"v_{n}" for n in sorted(b.bias))]:
        sourcename = node if node == "vdd" else node
        control += [f"let s_{node} = i({sourcename})", f'echo "@@P {node} $&s_{node}"']
    control += [
        "ac dec 20 1 100g",
        "let mag = abs(v(out))",
        "let pha = cph(v(out)) * 180 / pi",
        "wrdata ac.tsv mag pha",
    ]
    if topology.differential:
        control += [
            "alter @vinn[acphase] = 0",
            "ac lin 1 100 100",
            "let cmg = abs(v(out)) / 0.5",
            'echo "@@C $&cmg"',
        ]
    if rules in ("physical", "qualified"):
        step, stop = SETTLE_WINDOW
        control += [
            f"tran {step} {stop}",
            "let dev = vecmax(abs(v(out) - v(out)[0]))",
            'echo "@@T $&dev"',
        ]
    control.append("quit")
    text = "\n".join(lines) + "\n.control\n" + "\n".join(control) + "\n.endc\n.end\n"
    return text, b


def evaluate(
    topology,
    values,
    directory=None,
    *,
    strict=False,
    load_pf=LOAD_PF,
    vdd=VDD,
    keep=False,
    rules="qualified",
    temperature=27.0,
):
    """Measure one design; returns a JSON-serializable record (never raises for a bad
    design: simulator failures become invalid records with an error message)."""
    start = time.perf_counter()
    own = directory is None
    directory = Path(directory or tempfile.mkdtemp(prefix="chipjev-ptm45-"))
    directory.mkdir(parents=True, exist_ok=True)
    (directory / ".spiceinit").write_text(SPICEINIT)
    record = {
        "topology": topology.id,
        "cls": topology.cls,
        "values": {k: float(v) for k, v in values.items()},
        "strict": strict,
        "load_pf": load_pf,
        "vdd": vdd,
        "rules": rules,
        "temperature_c": temperature,
        "valid": False,
        "checks": {},
        "metrics": {},
        "margins": {},
        "error": None,
    }
    sim_seconds = 0.0
    try:
        text, b = deck(
            topology,
            values,
            strict=strict,
            load_pf=load_pf,
            vdd=vdd,
            rules=rules,
            temperature=temperature,
        )
        record["devices"] = len(b.mos)
        (directory / "design.cir").write_text(text)
        sim_start = time.perf_counter()
        try:
            proc = subprocess.run(
                [ngspice(), "-b", "design.cir"],
                cwd=directory,
                capture_output=True,
                text=True,
                timeout=120,
            )
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
            output, directory / "ac.tsv", b, topology, load_pf, vdd, rules
        )
        record.update(valid=valid, checks=checks, metrics=metrics, margins=margins)
        if rules == "qualified" and strict and valid and topology.differential:
            checked = qualify_buffer(
                topology,
                values,
                metrics,
                directory,
                load_pf=load_pf,
                vdd=vdd,
                temperature=temperature,
            )
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
                if path.name not in (".spiceinit",):
                    path.unlink(missing_ok=True)
    return record


STEP_V = 0.01


def buffer_deck(topology, values, metrics, direction, load_pf, vdd, temperature):
    vin = metrics["vin_dc"]
    ugf = metrics.get("ugf_mhz")
    stop = 100e-6 if not ugf else min(max(40 / (ugf * 1e6), 2e-6), 200e-6)
    delay = stop / 20
    inverted = abs(metrics["dc_phase_deg"]) >= 90
    feedback, signal = ("inp", "inn") if inverted else ("inn", "inp")
    builder = build(topology, values, vdd)
    lines = [
        f"* Qualified buffer: {topology.id}, direction {direction}",
        f'.include "{MODEL}"',
        f".options {STRICT}",
        f".temp {temperature:.6g}",
        f"vdd vdd 0 DC {vdd}",
        f"vsig {signal} 0 DC {vin:.9g} PULSE({vin:.9g} "
        f"{vin + direction * STEP_V:.9g} {delay:.9g} 1n 1n 1 2)",
        f"vfb {feedback} out DC 0",
    ]
    lines += [f"v_{n} {n} 0 DC {v:.9g}" for n, v in sorted(builder.bias.items())]
    lines += builder.lines + [
        f"cload out 0 {load_pf * 1e-12:.9g}",
        ".control",
        "set noaskquit",
        "set wr_singlescale",
        "set numdgt=12",
        f"tran {stop / 4000:.9g} {stop:.9g} 0 {stop / 4000:.9g}",
        f"wrdata buffer-{direction}.tsv v(out)",
        "quit",
        ".endc",
        ".end",
    ]
    return "\n".join(lines) + "\n", stop, delay


def qualify_buffer(
    topology, values, metrics, directory, *, load_pf=100.0, vdd=1.2, temperature=27.0
):
    steps = []
    for direction in (1, -1):
        try:
            text, stop, delay = buffer_deck(
                topology, values, metrics, direction, load_pf, vdd, temperature
            )
            path = directory / f"buffer-{direction}.cir"
            path.write_text(text)
            proc = subprocess.run(
                [ngspice(), "-b", path.name],
                cwd=directory,
                capture_output=True,
                text=True,
                timeout=20,
            )
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
            error = None
            passed = (
                gain_error <= BUFFER_GAIN_ERROR
                and ringing <= BUFFER_RINGING
                and dc_error <= BUFFER_DC_ERROR_V
            )
            indices = np.unique(np.linspace(0, len(t) - 1, 240).astype(int))
            steps.append(
                {
                    "direction": direction,
                    "gain": gain,
                    "gain_error": gain_error,
                    "ringing": ringing,
                    "dc_error_v": dc_error,
                    "passed": bool(passed),
                    "error": error,
                    "window_s": stop,
                    "waveform": {
                        "t_us": ((t[indices] - delay) * 1e6).tolist(),
                        "delta_mv": ((v[indices] - v0) * 1e3).tolist(),
                    },
                }
            )
        except (OSError, ValueError, IndexError, subprocess.TimeoutExpired) as exc:
            steps.append({"direction": direction, "passed": False, "error": str(exc)})

    def worst(key):
        values = [s[key] for s in steps if key in s]
        return max(values) if len(values) == 2 else None

    return {
        "passed": all(s["passed"] for s in steps),
        "steps": steps,
        "max_gain_error": worst("gain_error"),
        "max_ringing": worst("ringing"),
        "max_dc_error_v": worst("dc_error_v"),
    }
