"""Fixed-condition noise, PSRR and finite-impedance supply measurements.

These measured metrics are only acceptance constraints when requested. The PDN
is an explicit lumped test fixture, not an inferred package or substrate model.
"""

import json
import math
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from ..circuits.sky130_devices import include_text
from ..paths import ngspice
from .sky130 import SPICEINIT, STRICT


@dataclass(frozen=True)
class AnalogConditions:
    noise_low_hz: float = 10.0
    noise_high_hz: float = 1e6
    supply_resistance_ohm: float = 20.0
    load_step_a: float = 50e-6
    pulse_rise_s: float = 1e-10
    temperature_c: float = 27.0

    def __post_init__(self):
        positive = (
            self.noise_low_hz,
            self.noise_high_hz,
            self.supply_resistance_ohm,
            self.load_step_a,
            self.pulse_rise_s,
        )
        if not all(math.isfinite(v) and v > 0 for v in positive):
            raise ValueError("Analog test conditions must be positive and finite")
        if self.noise_high_hz <= self.noise_low_hz or not math.isfinite(self.temperature_c):
            raise ValueError("Invalid noise band or temperature")


def measure(
    topology,
    circuit,
    directory,
    *,
    input_bias,
    vdd=1.8,
    load_pf=100,
    conditions=None,
    corner="tt",
    mismatch_seed=None,
):
    start = time.perf_counter()
    if mismatch_seed is not None and (type(mismatch_seed) is not int or mismatch_seed < 0):
        raise ValueError("Mismatch seed must be a nonnegative integer")
    if not all(math.isfinite(v) and v > 0 for v in (vdd, load_pf)) or not math.isfinite(input_bias):
        raise ValueError("Invalid fixed electrical conditions")
    directory = Path(directory)
    conditions = conditions or AnalogConditions()
    directory.mkdir(parents=True, exist_ok=True)
    result = {
        "status": "fail",
        "conditions": {
            **asdict(conditions),
            "input_bias_v": input_bias,
            "vdd_v": vdd,
            "load_pf": load_pf,
            "corner": corner,
            "rc_corner": "nominal",
            "mismatch_seed": mismatch_seed,
            "offset_output_target_v": vdd / 2,
        },
        "metrics": {},
        "error": None,
    }
    source = "vdiff" if topology.differential else "vin"
    seed_options = f" seed={mismatch_seed + 1} seedinfo" if mismatch_seed is not None else ""
    lines = [
        "* ChipJev explicit analog fixture",
        include_text(corner, mismatch=mismatch_seed is not None),
        f".options {STRICT}{seed_options}",
        f".temp {conditions.temperature_c}",
        f"vsupply vpin 0 DC {vdd} AC 0",
        f"rpdn vpin vdd {conditions.supply_resistance_ohm}",
    ]
    if topology.differential:
        lines += [
            f"vcm cm 0 DC {input_bias}",
            "vdiff differential 0 DC 0 AC 1",
            "eplus inp cm differential 0 0.5",
            "eminus inn cm differential 0 -0.5",
        ]
    else:
        lines += [f"vin in 0 DC {input_bias} AC 1"]
    lines += getattr(circuit, "model_lines", [])
    lines += [f"v_{n} {n} 0 DC {v:.12g}" for n, v in sorted(circuit.bias.items())]
    lines += circuit.lines
    lines += [
        f"cload out 0 {load_pf * 1e-12}",
        f"iload vdd 0 PULSE(0 {conditions.load_step_a} 10n "
        f"{conditions.pulse_rise_s} {conditions.pulse_rise_s} 5n 40n)",
    ]
    sweep = f"dec 20 {conditions.noise_low_hz} {conditions.noise_high_hz}"
    control = ["set noaskquit", "set wr_singlescale", "set wr_vecnames", "set numdgt=12", "op"]
    supply_nodes = sorted(
        n for n, root in circuit.node_roots.items() if root in ("vdd", "vss") and n != "vss"
    )

    def node(n):
        return ("0" if n == "vss" else n) if n in circuit.ports else f"xdut.{n}"

    if supply_nodes:
        control += ["wrdata rail-op.tsv " + " ".join(f"v({node(n)})" for n in supply_nodes)]
    control += [
        f"ac {sweep}",
        "let gain = mag(v(out))",
        "wrdata signal-ac.tsv gain",
        f"noise v(out) {source} {sweep}",
        "setplot noise1",
        "wrdata noise.tsv inoise_spectrum onoise_spectrum",
        f"alter @{source}[acmag] = 0",
        "alter @vsupply[acmag] = 1",
        f"ac {sweep}",
        "let transfer = mag(v(out))",
        "wrdata supply-ac.tsv transfer",
        "alter @vsupply[acmag] = 0",
        f"tran {conditions.pulse_rise_s / 5:.12g} 30n 0 {conditions.pulse_rise_s / 5:.12g}",
        "wrdata supply-step.tsv v(vdd) v(out)",
    ]
    if topology.differential:
        control += ["dc vdiff -0.01 0.01 0.0001", "wrdata offset.tsv v(out)"]
    control += ['echo "@@ANALOG_DONE"', "quit"]
    text = "\n".join(lines + [".control", *control, ".endc", ".end"]) + "\n"
    (directory / "analog.cir").write_text(text)
    (directory / ".spiceinit").write_text(
        SPICEINIT
        + (
            f"option seed={mismatch_seed + 1}\nsetseed {mismatch_seed + 1}\n"
            if mismatch_seed is not None
            else ""
        )
    )
    try:
        proc = subprocess.run(
            [ngspice(), "-b", "analog.cir"],
            cwd=directory,
            capture_output=True,
            text=True,
            timeout=45,
        )
        output = proc.stdout + proc.stderr
        (directory / "analog.log").write_text(output)
        if proc.returncode or "@@ANALOG_DONE" not in output:
            raise ValueError("Analog simulation did not complete")

        def read(name, columns):
            data = np.atleast_2d(np.loadtxt(directory / name, skiprows=1))
            if data.shape[1] != columns or not np.isfinite(data).all():
                raise ValueError(f"Incomplete {name}")
            return data

        noise = read("noise.tsv", 3)
        gain = read("signal-ac.tsv", 2)
        psrr = read("supply-ac.tsv", 2)
        step = read("supply-step.tsv", 3)
        if not np.allclose(noise[:, 0], gain[:, 0]) or not np.allclose(gain[:, 0], psrr[:, 0]):
            raise ValueError("Mismatched frequency grids")
        if (
            len(noise) < 10
            or np.any(noise[:, 1:] < 0)
            or not np.any(noise[:, 1] > 0)
            or noise[-1, 0] < 0.999 * conditions.noise_high_hz
        ):
            raise ValueError("Incomplete noise band")
        rejection = 20 * np.log10(np.maximum(gain[:, 1], 1e-30) / np.maximum(psrr[:, 1], 1e-30))
        baseline = np.median(step[step[:, 0] < 9e-9, 1])
        metrics = {
            "input_noise_rms_v": float(np.sqrt(np.trapezoid(noise[:, 1] ** 2, noise[:, 0]))),
            "output_noise_rms_v": float(np.sqrt(np.trapezoid(noise[:, 2] ** 2, noise[:, 0]))),
            "psrr_min_db": float(np.min(rejection)),
            "supply_droop_v": float(max(0, baseline - np.min(step[:, 1]))),
            "supply_early_droop_v": float(
                max(0, baseline - np.interp(10.2e-9, step[:, 0], step[:, 1]))
            ),
            "supply_dc_drop_v": float(vdd - baseline),
        }
        if topology.differential:
            offset = read("offset.tsv", 2)
            crossed = np.flatnonzero((offset[:-1, 1] - vdd / 2) * (offset[1:, 1] - vdd / 2) <= 0)
            offsets = []
            for k in crossed:
                a, b = offset[k : k + 2]
                if a[1] != b[1]:
                    offsets.append(float(a[0] + (b[0] - a[0]) * (vdd / 2 - a[1]) / (b[1] - a[1])))
            metrics["input_offset_v"] = min(offsets, key=abs) if offsets else None
            metrics["input_offset_abs_v"] = abs(metrics["input_offset_v"]) if offsets else None
        if supply_nodes:
            op = read("rail-op.tsv", len(supply_nodes) + 1)[0, 1:]
            rail = {n: float(v) for n, v in zip(supply_nodes, op)}
            vp = [v for n, v in rail.items() if circuit.node_roots[n] == "vdd"]
            vn = [0.0, *(v for n, v in rail.items() if circuit.node_roots[n] == "vss")]
            metrics["internal_supply_drop_v"] = max(vp) - min(vp) if vp else 0.0
            metrics["internal_ground_rise_v"] = max(vn) - min(vn) if vn else 0.0
        sample = np.unique(np.linspace(0, len(step) - 1, 200).astype(int))
        result.update(
            status="measured",
            metrics=metrics,
            waveforms={
                "frequency_hz": noise[:, 0].tolist(),
                "input_noise_v_sqrt_hz": noise[:, 1].tolist(),
                "psrr_db": rejection.tolist(),
                "step_ns": (step[sample, 0] * 1e9).tolist(),
                "supply_v": step[sample, 1].tolist(),
            },
        )
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired) as exc:
        result["error"] = str(exc)
    result["seconds"] = time.perf_counter() - start
    (directory / "analog.json").write_text(json.dumps(result, indent=2, allow_nan=False))
    return result
