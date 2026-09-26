"""Measured geometric/RC features, with proxies explicitly separated from signoff."""

import math
from collections import defaultdict

import numpy as np

from .technology import GRID, SHEET
from .verification import spice_lines, spice_number


def assess(layout, directory, circuit):
    groups = []
    for group in layout.get("groups", []):
        if len(group["members"]) != 2:
            continue
        moments = []
        counts = []
        for name in group["members"]:
            points = [
                ((p["bbox"][0] + p["bbox"][2]) / 2, (p["bbox"][1] + p["bbox"][3]) / 2)
                for p in layout["placements"]
                if p["logical"] == name
            ]
            moments.append(np.mean(points, axis=0) * GRID)
            counts.append(len(points))
        groups.append(
            {
                "group": group["id"],
                "role": group["role"],
                "members": group["members"],
                "unit_counts": counts,
                "centroids_um": [p.tolist() for p in moments],
                "centroid_error_um": float(np.linalg.norm(moments[0] - moments[1])),
            }
        )
    caps = defaultdict(float)
    coupling = defaultdict(float)
    for line in spice_lines((directory / "pex.spice").read_text()):
        t = line.split()
        if t[0][0].lower() != "c":
            continue
        a, b = (circuit.node_roots.get(n, n) for n in t[1:3])
        value = spice_number(t[3]) * 1e15
        for node in set((a, b)):
            caps[node] += value
        if a != b:
            coupling["|".join(sorted((str(a), str(b))))] += value
    routes = defaultdict(lambda: {"length_um": 0.0, "series_sum_ohm_proxy": 0.0})
    for route in layout.get("routes", []):
        entry = routes[route["net"]]
        entry["length_um"] += route["length_um"]
        entry["series_sum_ohm_proxy"] += (
            SHEET[route["layer"]] * route["length_um"] / route["width_um"]
        )
    inputs = [n for n in ("inp", "inn") if n in caps]
    return {
        "area_um2": layout["area_um2"],
        "aspect_ratio": layout["width_um"] / layout["height_um"],
        "matching": groups,
        "centroid_error_um": max((g["centroid_error_um"] for g in groups), default=0),
        "input_cap_imbalance_ff": abs(caps[inputs[0]] - caps[inputs[1]])
        if len(inputs) == 2
        else None,
        "net_capacitance_ff": dict(caps),
        "coupling_ff": dict(coupling),
        "routes": dict(routes),
        "proxy_scope": "Centroid is a geometric first moment; route R sum is not effective resistance or EM.",
        "coverage": layout.get("technology_rules", {}).get("coverage", {}),
    }


def objective_value(result, objective):
    quality = result["quality"]
    metrics = result["postlayout"]["metrics"]
    bench = result.get("analog", {}).get("metrics", {})
    if objective == "area":
        return -math.log10(quality["area_um2"])
    if objective == "noise":
        noise = bench.get("input_noise_rms_v")
        return -math.log10(noise) if noise and noise > 0 else None
    if objective == "matching":
        return -quality["centroid_error_um"]
    key = {"gain": "gain_db", "gbw": "gbw_mhz", "fom": "fom"}[objective]
    value = metrics.get(key)
    if value is None or not math.isfinite(value):
        return None
    return value if objective == "gain" else math.log10(max(value, 1e-30))
