"""Optional, explicitly separated adjacent sizing × layout refinement."""

import json
import shutil
import time
from pathlib import Path

from ..circuits.grammar import LEVELS, slot_kind
from ..layout.plan import LayoutPlan
from ..layout.quality import objective_value
from .layout import LayoutGoal, optimize


def refine(
    topology,
    initial,
    directory,
    *,
    max_evaluations=4,
    budget_seconds=30,
    vdd=1.8,
    load_pf=100,
    observer=None,
):
    """Retain the incumbent unless a fixed-bias, fully qualified sizing move wins.

    Kept separate from fixed-circuit area results so circuit changes cannot be
    reported as placement-only gains. Each move uses the incumbent physical plan.
    """
    if type(max_evaluations) is not int or max_evaluations < 0 or budget_seconds <= 0:
        raise ValueError("Invalid joint-refinement budget")
    directory = Path(directory).resolve()
    start = time.perf_counter()
    baseline = dict(initial["values"])
    goal_data = dict(initial["optimization"]["goal"])
    from ..simulation.analog import AnalogConditions

    goal_data["analog"] = AnalogConditions(**goal_data["analog"])
    goal = LayoutGoal(**goal_data)
    plan = LayoutPlan(**initial["layout"]["plan"])
    bias = initial["optimization"]["fixed_input_bias_v"]
    best, source = initial, None
    trials = []
    slots = sorted(baseline, key=lambda s: (slot_kind(s) != "length", s))
    for slot in slots:
        grid = LEVELS[slot_kind(slot)]
        index = min(range(len(grid)), key=lambda i: abs(grid[i] - baseline[slot]))
        for step in (1, -1):
            if len(trials) >= max_evaluations or time.perf_counter() - start >= budget_seconds:
                break
            if not 0 <= index + step < len(grid):
                continue
            values = {**baseline, slot: grid[index + step]}
            target = directory / f"joint-{len(trials):02d}"
            record = {
                "values": values,
                "slot": slot,
                "parent_plan_id": initial["layout"]["plan_id"],
                "valid": False,
                "accepted": False,
                "error": None,
            }
            try:
                result = optimize(
                    topology,
                    values,
                    target,
                    goal=goal,
                    vdd=vdd,
                    load_pf=load_pf,
                    input_bias=bias,
                    max_evaluations=1,
                    budget_seconds=budget_seconds,
                    initial_plan=plan,
                    observer=observer,
                )
                record.update(
                    valid=result["valid"],
                    metrics=result["postlayout"]["metrics"],
                    area_um2=result["layout"]["area_um2"],
                )
                if result["valid"] and objective_value(result, goal.objective) > objective_value(
                    best, goal.objective
                ):
                    best, source = result, target
                    record["accepted"] = True
            except (ValueError, RuntimeError, OSError) as exc:
                record["error"] = str(exc)
            trials.append(record)
    if source:
        for path in source.iterdir():
            if path.is_file():
                shutil.copy2(path, directory / path.name)
            elif path.name in ("prelayout", "postlayout", "analog", "schematic"):
                shutil.copytree(path, directory / path.name, dirs_exist_ok=True)
    best["joint_refinement"] = {
        "history": trials,
        "seconds": time.perf_counter() - start,
        "initial_values": baseline,
        "fixed_input_bias_v": bias,
        "scope": "Adjacent electrical sizing moves, reported separately from fixed-circuit layout search",
    }
    best["fixed_circuit_optimization"] = initial["optimization"]
    best["recovery"]["changed"] = best["values"] != baseline
    best["total_seconds"] = initial["total_seconds"] + best["joint_refinement"]["seconds"]
    (directory / "joint-refinement.json").write_text(
        json.dumps(best["joint_refinement"], indent=2, allow_nan=False)
    )
    (directory / "physical.json").write_text(json.dumps(best, indent=2, allow_nan=False))
    return best
