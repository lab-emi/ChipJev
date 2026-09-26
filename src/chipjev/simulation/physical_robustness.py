"""Optional device-corner and seeded local-mismatch verification at fixed bias."""

import json
from pathlib import Path

import numpy as np

from .analog import AnalogConditions, measure
from .sky130 import evaluate


def qualify(
    topology,
    values,
    circuit,
    directory,
    *,
    input_bias,
    vdd=1.8,
    load_pf=100,
    corners=("tt", "ss", "ff"),
    temperatures=(27.0,),
    mismatch_seeds=(),
    conditions=None,
):
    directory = Path(directory)
    conditions = conditions or AnalogConditions()
    directory.mkdir(parents=True, exist_ok=True)
    cases = []
    for corner in corners:
        for temperature in temperatures:
            name = f"{corner}-{temperature:g}C"
            r = evaluate(
                topology,
                values,
                directory / name,
                strict=True,
                keep=True,
                circuit=circuit,
                vdd=vdd,
                load_pf=load_pf,
                input_bias=input_bias,
                corner=corner,
                temperature=temperature,
            )
            cases.append(
                {"name": name, "valid": r["valid"], "checks": r["checks"], "metrics": r["metrics"]}
            )
    mismatch = []
    for seed in mismatch_seeds:
        name = f"mismatch-{seed}"
        r = evaluate(
            topology,
            values,
            directory / name,
            strict=True,
            keep=True,
            circuit=circuit,
            vdd=vdd,
            load_pf=load_pf,
            input_bias=input_bias,
            mismatch_seed=seed,
            temperature=conditions.temperature_c,
        )
        a = measure(
            topology,
            circuit,
            directory / name / "analog",
            input_bias=input_bias,
            vdd=vdd,
            load_pf=load_pf,
            conditions=conditions,
            mismatch_seed=seed,
        )
        mismatch.append(
            {
                "seed": seed,
                "valid": r["valid"] and a["status"] == "measured",
                "checks": r["checks"],
                "metrics": {**r["metrics"], **a["metrics"]},
            }
        )
    offsets = [
        r["metrics"]["input_offset_v"]
        for r in mismatch
        if r["metrics"].get("input_offset_v") is not None
    ]
    result = {
        "status": "pass" if all(r["valid"] for r in cases + mismatch) else "fail",
        "corners": cases,
        "mismatch": mismatch,
        "fixed_input_bias_v": input_bias,
        "offset_std_v": float(np.std(offsets, ddof=1)) if len(offsets) > 1 else None,
        "scope": "Device corners and PDK local mismatch; nominal interconnect/passive models. "
        "No spatial gradient, substrate-noise, thermal or manufacturing yield claim.",
    }
    if not cases and not mismatch:
        result["status"] = "not_run"
    (directory / "robustness.json").write_text(json.dumps(result, indent=2, allow_nan=False))
    return result
