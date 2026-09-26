"""Budgeted, goal-driven physical search with immutable plans and real feedback."""

import hashlib
import json
import math
import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..circuits.sky130_devices import build
from ..decisions.layout import LayoutDecisions
from ..layout.intent import derive
from ..layout.plan import LayoutPlan
from ..layout.quality import assess, objective_value
from ..layout.technology import provenance
from ..layout.verification import ExtractedCircuit, verify
from ..provenance import code_fingerprint
from ..simulation.analog import AnalogConditions, measure
from ..simulation.pdk import SHA256 as PDK_SHA256
from ..simulation.sky130 import evaluate


@dataclass(frozen=True)
class LayoutGoal:
    objective: str = "area"
    minimum: dict = field(default_factory=dict)
    maximum: dict = field(default_factory=dict)
    analog: AnalogConditions = field(default_factory=AnalogConditions)
    require_dummies: bool = True

    def __post_init__(self):
        if self.objective not in ("area", "gain", "gbw", "fom", "noise", "matching"):
            raise ValueError("Unknown layout objective")
        allowed = {
            "area_um2",
            "gain_db",
            "gbw_mhz",
            "pm_deg",
            "cmrr_db",
            "power_uw",
            "input_noise_rms_v",
            "psrr_min_db",
            "supply_droop_v",
            "centroid_error_um",
            "internal_supply_drop_v",
            "internal_ground_rise_v",
            "input_cap_imbalance_ff",
            "input_offset_abs_v",
            "supply_early_droop_v",
        }
        if type(self.require_dummies) is not bool:
            raise ValueError("require_dummies must be a boolean")
        for limits in (self.minimum, self.maximum):
            if set(limits) - allowed or not all(math.isfinite(v) for v in limits.values()):
                raise ValueError("Unknown or nonfinite physical goal")
        for key in self.minimum.keys() & self.maximum.keys():
            if self.minimum[key] > self.maximum[key]:
                raise ValueError("Inconsistent physical bounds")

    def qualify(self, result):
        measured = {
            **result["postlayout"]["metrics"],
            **result["quality"],
            **result["analog"].get("metrics", {}),
        }
        checks = {
            "physical": result["valid"],
            "analog_measured": result["analog"]["status"] == "measured",
            "required_dummies": not self.require_dummies
            or result.get("layout", {}).get("plan", {}).get("dummies", False),
        }
        for mode, limits in (("min", self.minimum), ("max", self.maximum)):
            for key, limit in limits.items():
                value = measured.get(key)
                checks[f"{mode}:{key}"] = (
                    isinstance(value, (int, float))
                    and math.isfinite(value)
                    and (value >= limit if mode == "min" else value <= limit)
                )
        return checks


def _features(plan):
    return [
        plan.columns,
        plan.fingers_per_row / 32,
        plan.split,
        plan.rail_multiplier,
        int(plan.dummies),
        int(plan.shield_inputs),
        plan.decap_pf / 5,
        int(plan.decap_location == "output"),
        *[int(plan.pattern == p) for p in ("clustered", "interdigitated", "centroid")],
    ]


def _pareto(candidates):
    def vector(result):
        return (
            result["quality"]["area_um2"],
            -result["postlayout"]["metrics"].get("gbw_mhz", 0),
            result["analog"]["metrics"]["input_noise_rms_v"],
        )

    return [
        a
        for a in candidates
        if not any(
            all(x <= y for x, y in zip(vector(b[1]), vector(a[1])))
            and any(x < y for x, y in zip(vector(b[1]), vector(a[1])))
            for b in candidates
            if b is not a
        )
    ]


def optimize(
    topology,
    values,
    directory,
    *,
    goal=None,
    vdd=1.8,
    load_pf=100,
    input_bias=None,
    prelayout=None,
    model=None,
    max_evaluations=8,
    budget_seconds=60,
    observer=None,
    candidate_observer=None,
    initial_plan=None,
):
    """Each candidate changes only physical variables. Sizing stays fixed and traceable.

    Deadline is checked between bounded EDA stages; a running qualification is
    allowed to finish. No unmeasured surrogate prediction becomes an incumbent.
    candidate_observer receives rendered, evaluated and selected events with the
    actual candidate directory, plan identity and measured acceptance decision.
    """
    if max_evaluations < 1 or not math.isfinite(budget_seconds) or budget_seconds <= 0:
        raise ValueError("A positive layout evaluation/time budget is required")
    start = time.perf_counter()
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    if any(directory.iterdir()):
        raise FileExistsError("Physical optimization requires a fresh directory")
    goal = goal or LayoutGoal()
    builder = build(topology, values, vdd)
    intent = derive(builder)
    if prelayout is None:
        prelayout = evaluate(
            topology,
            values,
            directory=directory / "schematic",
            strict=True,
            keep=True,
            vdd=vdd,
            load_pf=load_pf,
            input_bias=input_bias,
            temperature=goal.analog.temperature_c,
            quantize_geometry=True,
        )
    if input_bias is None:
        input_bias = prelayout.get("metrics", {}).get("vin_dc")
    if input_bias is None:
        raise ValueError("A valid fixed input operating point is required")
    # The same bias, model, load and supply are used for every layout candidate.
    if (
        prelayout.get("metrics", {}).get("vin_dc") != input_bias
        or prelayout.get("temperature_c", 27.0) != goal.analog.temperature_c
    ):
        quantized = bool(prelayout.get("geometry_policy"))
        prelayout = evaluate(
            topology,
            values,
            directory=directory / "fixed-schematic",
            strict=True,
            keep=True,
            vdd=vdd,
            load_pf=load_pf,
            input_bias=input_bias,
            temperature=goal.analog.temperature_c,
            quantize_geometry=quantized,
        )
    seed = initial_plan or LayoutPlan(fingers_per_row=20)
    seed.validate(builder, intent)
    if goal.require_dummies and not seed.dummies:
        raise ValueError("Initial plan violates the dummy requirement")
    planner = LayoutDecisions(model) if model is not None else None
    pending = [("initial", seed)]
    parents = {seed.id: None}
    visited = set()
    history = []
    accepted = []
    best = None
    first = None
    decisions = []

    def add_neighbors(plan):
        for action, p in plan.neighbors():
            if goal.require_dummies and not p.dummies:
                continue
            if p.id in visited or any(q.id == p.id for _, q in pending):
                continue
            try:
                p.validate(builder, intent)
            except ValueError:
                continue
            pending.append((action, p))
            parents[p.id] = plan.id

    for index in range(max_evaluations):
        if not pending or (index and time.perf_counter() - start >= budget_seconds):
            break
        decision = None
        if index:
            # Small, deterministic kernel guide over measured plan features. It
            # only proposes evaluations; its estimates are never reported as facts.
            successful = [h for h in history if h.get("objective") is not None]

            def acquisition(item):
                action, p = item
                proxy = p.estimate(builder, intent)
                last = history[-1]
                failed = [k for k, v in last.get("checks", {}).items() if not v]
                repair = []
                if any("supply" in k or "ground" in k for k in failed):
                    repair = ["rail_multiplier", "decap_pf", "decap_location", "columns"]
                elif any("centroid" in k or "imbalance" in k for k in failed):
                    repair = ["split", "pattern", "shield_inputs"]
                elif any("noise" in k or "psrr" in k for k in failed):
                    repair = ["shield_inputs", "columns", "rail_multiplier", "decap_pf"]
                # A failed bound changes the proposal priority. It never lowers
                # the bound or converts an estimate into a measured success.
                if repair:
                    return (0 if action in repair else 1, proxy["area_um2_proxy"], p.id)
                if goal.objective == "area":
                    # Fast geometry prior ranks proposals. Even the smallest
                    # candidate must pass complete EDA qualification.
                    estimate = -math.log10(proxy["area_um2_proxy"])
                    return (-estimate, p.id)
                if goal.objective == "matching":
                    return (p.pattern != "centroid", p.split != 2, proxy["area_um2_proxy"], p.id)
                if not successful:
                    return (action not in ("fingers_per_row", "columns", "dummies"), p.id)
                x = _features(p)
                neighbors = []
                for h in successful:
                    distance = sum((a - b) ** 2 for a, b in zip(x, h["features"]))
                    neighbors.append((distance, h["objective"]))
                weights = [math.exp(-d) for d, _ in neighbors]
                mean = sum(w * v for w, (_, v) in zip(weights, neighbors)) / max(
                    sum(weights), 1e-12
                )
                # Deliberate exploration of different physical structures.
                return (-mean - 0.1 * min(d for d, _ in neighbors), p.id)

            pending.sort(key=acquisition)
            shortlist = pending[:16]
            if planner:
                state = {
                    "goal": asdict(goal),
                    "technology": provenance()["policy"],
                    "groups": intent["groups"],
                    "fixed_input_bias_v": input_bias,
                    "remaining_seconds": max(0, budget_seconds - (time.perf_counter() - start)),
                    "history": [
                        {k: h.get(k) for k in ("plan", "valid", "metrics", "quality", "error",
                                              "checks", "qualification_checks")}
                        for h in history[-4:]
                    ],
                }
                ranked, decision = planner.rank(state, shortlist)
                decisions.append(decision)
                # Every third evaluation retains the independent exploration arm.
                # Guaranteed independent proposals prevent a topology-trained
                # prior from suppressing physical exploration before retraining.
                chosen = ranked[0] if index % 3 == 2 else shortlist[0]
                pending.remove(chosen)
            else:
                chosen = pending.pop(0)
        else:
            chosen = pending.pop(0)
        action, plan = chosen
        visited.add(plan.id)
        candidate = directory / f"candidate-{index:02d}"
        before = time.perf_counter()
        entry = {
            "index": index,
            "action": action,
            "plan": plan.to_dict(),
            "plan_id": plan.id,
            "parent": parents[plan.id],
            "proxy": plan.estimate(builder, intent),
            "features": _features(plan),
            "valid": False,
            "error": None,
            "objective": None,
            "fidelity": "full RC + fixed-condition ngspice + analog fixture",
        }

        def candidate_stage(name, data):
            if name == "extracting" and candidate_observer:
                candidate_observer({"kind": "rendered", "directory": candidate,
                                    "index": index, "action": action, "plan_id": plan.id,
                                    "layout": data})
            if observer:
                observer(name, data)

        try:
            physical = verify(
                topology,
                values,
                candidate,
                vdd=vdd,
                load_pf=load_pf,
                plan=plan,
                input_bias=input_bias,
                prelayout=prelayout,
                temperature=goal.analog.temperature_c,
                observer=candidate_stage,
            )
            circuit = ExtractedCircuit(builder, candidate / "pex.spice")
            physical["quality"] = assess(physical["layout"], candidate, circuit)
            physical["analog"] = measure(
                topology,
                circuit,
                candidate / "analog",
                input_bias=input_bias,
                vdd=vdd,
                load_pf=load_pf,
                conditions=goal.analog,
            )
            physical["goal_checks"] = goal.qualify(physical)
            physical["valid"] = all(physical["goal_checks"].values())
            entry.update(
                valid=physical["valid"],
                checks=physical["goal_checks"],
                qualification_checks=physical["postlayout"]["checks"],
                metrics={**physical["postlayout"]["metrics"], **physical["analog"]["metrics"]},
                quality={
                    k: physical["quality"][k]
                    for k in ("area_um2", "centroid_error_um", "input_cap_imbalance_ff")
                },
            )
            if physical["valid"]:
                entry["objective"] = objective_value(physical, goal.objective)
                if entry["objective"] is None:
                    raise ValueError("Requested objective was not measured")
                accepted.append((candidate, physical, entry["objective"]))
                if best is None or entry["objective"] > best[2]:
                    best = accepted[-1]
                    entry["accepted"] = True
                if first is None:
                    first = time.perf_counter() - start
            (candidate / "physical.json").write_text(
                json.dumps(physical, indent=2, allow_nan=False)
            )
        except (RuntimeError, ValueError, OSError) as exc:
            entry["valid"] = False
            entry["error"] = str(exc)
        entry["seconds"] = time.perf_counter() - before
        history.append(entry)
        if candidate_observer:
            candidate_observer({"kind": "evaluated", "directory": candidate, **entry})
        add_neighbors(plan)
        (directory / "optimization.json").write_text(
            json.dumps(
                {
                    "goal": asdict(goal),
                    "history": history,
                    "decisions": decisions,
                    "fixed_input_bias_v": input_bias,
                },
                indent=2,
                allow_nan=False,
            )
        )
    trace = {
        "goal": asdict(goal),
        "history": history,
        "decisions": decisions,
        "fixed_input_bias_v": input_bias,
        "first_feasible_seconds": first,
        "evaluations": len(history),
        "max_evaluations": max_evaluations,
        "budget_seconds": budget_seconds,
        "wall_seconds": time.perf_counter() - start,
        "eda_seconds": sum(h["seconds"] for h in history),
        "pareto_plan_ids": [p[1]["layout"]["plan_id"] for p in _pareto(accepted)],
        "policy": ("Laya prior + " if planner else "No Laya: ")
        + (
            "geometry acquisition"
            if goal.objective in ("area", "matching")
            else "kernel acquisition"
        ),
        "decision_seconds": sum(d["seconds"] for d in decisions),
        "decision_model": getattr(model, "metadata", None),
        "identity_sha256": hashlib.sha256(
            json.dumps(
                {
                    "topology": topology.id,
                    "values": values,
                    "goal": asdict(goal),
                    "bias": input_bias,
                    "vdd": vdd,
                    "load_pf": load_pf,
                    "pdk": provenance(),
                    "pdk_archive": PDK_SHA256,
                    "code_sha256": code_fingerprint(),
                },
                sort_keys=True,
            ).encode()
        ).hexdigest(),
    }
    (directory / "optimization.json").write_text(json.dumps(trace, indent=2, allow_nan=False))
    if best is None:
        raise RuntimeError("No layout satisfied the physical goal; inspect optimization.json")
    source, result, _ = best
    for path in source.iterdir():
        if path.is_dir():
            shutil.copytree(path, directory / path.name, dirs_exist_ok=True)
        else:
            shutil.copy2(path, directory / path.name)
    result.update(
        values=values,
        optimization=trace,
        total_seconds=trace["wall_seconds"],
        recovery={"changed": False, "attempts": history, "max_candidates": max_evaluations},
    )
    (directory / "physical.json").write_text(json.dumps(result, indent=2, allow_nan=False))
    if candidate_observer:
        chosen = next(h for h in history if h["plan_id"] == result["layout"]["plan_id"])
        candidate_observer({"kind": "selected", "directory": directory, **chosen})
    return result
