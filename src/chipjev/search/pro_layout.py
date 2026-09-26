"""Goal-driven layout search over professional templates, with Laya and the knowledge base.

Every candidate is a ProPlan: a one-knob change of the incumbent inside the
template space, so each one is a structurally professional layout. Batches of
candidates run in parallel through Magic DRC/extraction, Netgen LVS, the
declared physical netlist and post-layout ngspice, then the rule-card critic.
Acceptance is by measurement only: qualification first, then the goal.

Proposals: knowledge cards retrieved for the measured symptoms say which knobs
are relevant (e.g. phase-margin loss -> compensation placement, pair
pattern); Laya ranks the annotated options; one slot per batch explores.
Each decision and the measured outcome of every evaluated option is logged to
trajectory.jsonl, the training data for Laya's layout policy.
"""

import json
import math
import multiprocessing
import queue
import random
import shutil
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from ..circuits.published import lookup
from ..decisions.pro_layout import ProLayoutDecisions, option_text, state_text
from ..layout.pro.knowledge import BY_ID, retrieve, symptoms_of
from ..layout.pro.planner import ProPlan
from ..simulation.sky130 import evaluate

GOALS = ("quality", "area", "gbw", "gain", "pm")
STEPS = ("layout", "drc", "lvs", "extracting", "postsimulating")
_PROGRESS = None  # per-process queue for live verification steps (pool initializer)


def _progress_channel(channel):
    global _PROGRESS
    _PROGRESS = channel


def _evaluate(job, index=None):
    """Worker: full physical verification and critic for one plan (own process)."""
    import traceback

    from ..circuits.sky130_devices import build
    from ..layout.pro.knowledge import review
    from ..layout.quality import assess
    from ..layout.verification import ExtractedCircuit, verify

    cls, topo, values, directory, plan, vdd, load, bias, pre, fmax = job
    directory = Path(directory)
    topology = lookup(cls, topo)
    start = time.perf_counter()

    def report(name, data):
        # Only small, path-free facts cross the process boundary.
        if _PROGRESS is not None and index is not None and name in STEPS + ("done",):
            facts = {k: data[k] for k in ("status", "errors", "devices", "nets", "area_um2") if k in data}
            _PROGRESS.put((index, name, {**facts, "at": time.monotonic()}))

    try:
        result = verify(topology, values, directory, vdd=vdd, load_pf=load, plan=ProPlan(**plan),
                        prelayout=pre, input_bias=bias, finger_max_um=fmax, observer=report)
        circuit = ExtractedCircuit(build(topology, values, vdd, finger_max=fmax), directory / "pex.spice")
        quality = assess(result["layout"], directory, circuit)
        manifest = json.loads((directory / "manifest.json").read_text())
        critic = review(result["layout"], manifest, quality, result["postlayout"],
                        result["layout"]["drc_errors"])
        result["quality"] = {k: v for k, v in quality.items() if k != "routes"}
        result["critic"] = critic
        (directory / "physical.json").write_text(json.dumps(result, indent=2, allow_nan=False))
        post = result["postlayout"]
        report("done", {"status": "passed" if result["valid"] else "failed"})
        return {
            "valid": result["valid"], "drc": result["layout"]["drc_errors"], "lvs": result["lvs"]["passed"],
            "lvs_devices": result["lvs"].get("devices"), "lvs_nets": result["lvs"].get("nets"),
            "metrics": post["metrics"], "checks": post["checks"],
            "physical_schematic_valid": (result.get("physical_schematic") or {}).get("valid"),
            "area_um2": result["layout"]["area_um2"], "width_um": result["layout"]["width_um"],
            "height_um": result["layout"]["height_um"], "critic": critic["score"],
            "findings": critic["findings"], "symptoms": symptoms_of(result),
            "performance_delta": result["performance_delta"],
            "layout_seconds": result["layout"]["layout_seconds"],
            "seconds": time.perf_counter() - start,
        }
    except Exception as exc:  # a failed candidate is feedback, never a crash of the loop
        report("done", {"status": "failed"})
        return {"valid": False, "error": f"{type(exc).__name__}: {exc}",
                "trace": traceback.format_exc()[-2000:], "seconds": time.perf_counter() - start,
                "symptoms": ["error"]}


def objective(entry, goal, reference_area):
    """Higher is better. Qualification dominates through the key below."""
    if not entry.get("metrics"):
        return -math.inf
    area = max(entry["area_um2"], 1.0)
    if goal == "quality":
        # Professional quality (critic) with a mild pressure toward compact blocks.
        return entry["critic"] - 10 * math.log10(area / reference_area)
    if goal == "area":
        return -area
    key = {"gbw": "gbw_mhz", "gain": "gain_db", "pm": "pm_deg"}[goal]
    value = entry["metrics"].get(key)
    return value if isinstance(value, (int, float)) and math.isfinite(value) else -math.inf


def stored_objective(value):
    """JSON-safe record: a candidate that produced no measurement (e.g. a routing
    failure) has no objective, instead of -inf, which the trace cannot serialize."""
    return value if math.isfinite(value) else None


def _key(entry, goal, reference_area):
    return (bool(entry.get("valid")), objective(entry, goal, reference_area))


def _prior(field, value, entry, goal):
    """Knowledge-guided relevance of a one-knob move under the incumbent's symptoms."""
    symptoms = entry.get("symptoms", []) if entry else []
    cards = retrieve(field, symptoms)
    score = sum(1.0 for c in cards if any(s in m for s in c.symptoms for m in symptoms))
    if goal == "area" and field in ("aspect", "max_finger_um", "decap", "refinger"):
        score += 0.5
    if goal == "quality" and field in ("pair_pattern", "dummies", "shield_inputs", "rail_um"):
        score += 0.3
    for finding in (entry or {}).get("findings", []):
        if finding["status"] != "pass" and field in BY_ID[finding["card"]].actions:
            score += 0.5
    return score


def optimize_pro(topology, values, directory, *, goal="quality", vdd=1.8, load_pf=100.0,
                 input_bias=None, prelayout=None, model=None, max_evaluations=12, parallel=4,
                 budget_seconds=240.0, seed_plan=None, rng_seed=0, log=None,
                 candidate_observer=None, observer=None, finger_max_um=None):
    """Returns the selected candidate's physical result (search/layout.optimize's shape),
    with the search trace under ``optimization``; raises if nothing qualified.

    ``observer(step, data)`` receives each candidate's verification steps live from
    the worker processes: layout, drc and lvs ({"status": running|passed|failed} with
    the violation or device/net counts), extracting and postsimulating; ``data`` also
    names the candidate (index, action, plan_id) and the step's time.monotonic() "at";
    "done" ends each candidate. ``candidate_observer`` receives "batch" when an iteration
    submits its candidates, "rendered" once a candidate's cell is final (after Magic DRC),
    "evaluated" in candidate order, and finally "selected"."""
    if goal not in GOALS:
        raise ValueError(f"goal must be one of {GOALS}")
    if log is None:
        # Progress goes to stderr: stdout may be a JSON event stream (the demo worker).
        def log(message):
            print(message, file=sys.stderr, flush=True)
    start = time.perf_counter()
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    if any(directory.iterdir()):
        raise FileExistsError("Physical optimization requires a fresh directory")
    rng = random.Random(rng_seed)
    # The schematic's device template (layout-aware physical profile) travels with it.
    finger_max_um = finger_max_um or (prelayout or {}).get("finger_max_um")
    if input_bias is None:
        input_bias = (prelayout or {}).get("metrics", {}).get("vin_dc")
    if prelayout is None or input_bias is None or prelayout.get("metrics", {}).get("vin_dc") != input_bias:
        prelayout = evaluate(topology, values, directory=directory / "schematic", strict=True, keep=True,
                             vdd=vdd, load_pf=load_pf, input_bias=input_bias,
                             quantize_geometry=float(finger_max_um) if finger_max_um else True)
        input_bias = prelayout.get("metrics", {}).get("vin_dc", input_bias)
    if input_bias is None:
        raise ValueError("A valid fixed input operating point is required")
    planner = ProLayoutDecisions(model) if model is not None else None
    seed = seed_plan or ProPlan()
    history, decisions, visited = [], [], set()
    incumbent = None
    batch = [("seed", seed, None)]
    reference_area = None
    live = observer is not None or candidate_observer is not None
    progress = multiprocessing.get_context().Queue() if live else None
    known, rendered = {}, set()
    iteration = 0

    def rendered_event(index):
        field, plan, target = known[index]
        if index not in rendered and candidate_observer and (target / "layout.mag").exists():
            rendered.add(index)
            candidate_observer({"kind": "rendered", "directory": target, "index": index,
                                "action": field, "plan_id": plan.id})

    def drain():
        while progress is not None:
            try:
                index, step, data = progress.get_nowait()
            except queue.Empty:
                return
            if index not in known:
                continue
            field, plan, _ = known[index]
            if observer:
                observer(step, {"index": index, "action": field, "plan_id": plan.id, **data})
            # The cell on disk is final once Magic's DRC run has saved it.
            if step == "drc" and data.get("status") != "running":
                rendered_event(index)

    with ProcessPoolExecutor(max_workers=parallel, initializer=_progress_channel,
                             initargs=(progress,)) as pool:
        while batch and len(history) < max_evaluations and time.perf_counter() - start < budget_seconds:
            jobs = []
            for field, plan, decision in batch:
                visited.add(plan.id)
                index = len(history) + len(jobs)
                target = directory / f"candidate-{index:02d}"
                jobs.append((index, field, plan, decision, target))
                known[index] = (field, plan, target)
            iteration += 1
            if candidate_observer:
                candidate_observer({"kind": "batch", "iteration": iteration,
                                    "indices": [j[0] for j in jobs], "actions": [j[1] for j in jobs],
                                    "incumbent": incumbent["index"] if incumbent else None})
            futures = [pool.submit(_evaluate, (topology.cls, topology.id, values, str(t), p.to_dict(),
                                               vdd, load_pf, input_bias, prelayout, finger_max_um), i)
                       for i, _, p, _, t in jobs]
            for (index, field, plan, decision, target), future in zip(jobs, futures):
                while True:  # results stay in candidate order; live steps stream meanwhile
                    try:
                        entry = future.result(timeout=0.05)
                        break
                    except TimeoutError:
                        drain()
                drain()
                entry.update(index=index, action=field, plan=plan.to_dict(), plan_id=plan.id,
                             parent=incumbent["plan_id"] if incumbent else None, decision=decision,
                             directory=target.name)
                if reference_area is None and entry.get("area_um2"):
                    reference_area = entry["area_um2"]
                entry["objective"] = stored_objective(objective(entry, goal, reference_area or 1.0))
                history.append(entry)
                log(f"  {target.name} {field:14s} valid={entry.get('valid')} "
                    f"area={entry.get('area_um2', 0):7.0f} critic={entry.get('critic', 0):5.1f} "
                    f"{entry.get('error', '')[:80]}")
                accepted = incumbent is None or _key(entry, goal, reference_area) > _key(
                    incumbent, goal, reference_area)
                entry["accepted"] = bool(accepted and entry.get("valid"))
                if accepted:
                    incumbent = entry
                if candidate_observer and (target / "layout.mag").exists():
                    rendered_event(index)  # no-op when the live DRC step already showed it
                    candidate_observer({
                        "kind": "evaluated", "directory": target, "index": index, "action": field,
                        "plan_id": plan.id, "valid": entry.get("valid"),
                        "accepted": accepted and entry.get("valid"),
                        "drc_errors": entry.get("drc"), "lvs": entry.get("lvs"),
                        "quality": {"area_um2": entry.get("area_um2")},
                        "metrics": entry.get("metrics"), "critic": entry.get("critic")})
                known.pop(index)  # late progress messages of a finished candidate are stale
            batch = _propose(incumbent, goal, visited, parallel, planner, decisions, rng)
    if progress is not None:
        progress.close()
    trace = _finish(directory, history, decisions, incumbent, goal, input_bias, prelayout, start,
                    planner, max_evaluations, parallel)
    if not incumbent or not incumbent.get("valid"):
        raise RuntimeError("No professional layout qualified; inspect optimization.json")
    result = json.loads((directory / "physical.json").read_text())
    result.update(values=values, optimization=trace, total_seconds=trace["wall_seconds"],
                  recovery={"changed": False, "attempts": history, "max_candidates": max_evaluations})
    (directory / "physical.json").write_text(json.dumps(result, indent=2, allow_nan=False, default=str))
    if candidate_observer:
        candidate_observer({"kind": "selected", "directory": directory, **{
            k: incumbent.get(k) for k in ("index", "action", "plan_id", "valid", "critic", "drc", "lvs",
                                          "lvs_devices", "lvs_nets", "area_um2")}})
    return result


def _propose(incumbent, goal, visited, width, planner, decisions, rng):
    if incumbent is None or not incumbent.get("plan"):
        return []
    base = ProPlan(**incumbent["plan"])
    options = [(f, p) for f, p in base.neighbors() if p.id not in visited]
    if not options:
        return []
    symptoms = incumbent.get("symptoms", [])
    scored = []
    for field, plan in options:
        old, new = getattr(base, field), getattr(plan, field)
        text, cards = option_text(field, old, new, symptoms)
        scored.append({"field": field, "plan": plan, "text": text, "cards": cards,
                       "prior": _prior(field, new, incumbent, goal)})
    scored.sort(key=lambda o: -o["prior"])
    shortlist = scored[:6]
    record = {"state": None, "options": {f"a{i}": o["text"] for i, o in enumerate(shortlist)},
              "cards": {f"a{i}": o["cards"] for i, o in enumerate(shortlist)},
              "priors": {f"a{i}": o["prior"] for i, o in enumerate(shortlist)}, "laya": None}
    if planner is not None:
        state = state_text(goal, incumbent, symptoms, incumbent["plan"])
        probabilities, seconds, model_state = planner.rank(state, record["options"])
        record.update(state=model_state, laya=probabilities, laya_seconds=seconds)
        # Until Laya is fine-tuned on measured layout outcomes its vote is one
        # term next to the knowledge prior; a trained layout policy leads.
        weight = 8.0 if getattr(planner.model, "layout_policy", False) else 2.0
        for i, o in enumerate(shortlist):
            o["score"] = o["prior"] + weight * probabilities[f"a{i}"]
    else:
        record["state"] = state_text(goal, incumbent, symptoms, incumbent["plan"])
        for o in shortlist:
            o["score"] = o["prior"]
    ranked = sorted(shortlist, key=lambda o: -o["score"])
    chosen = ranked[: max(1, width - 1)]
    rest = [o for o in scored if o not in chosen]
    if rest:  # one exploration slot per batch
        chosen.append(rng.choice(rest))
    record["chosen"] = [f"a{shortlist.index(o)}" if o in shortlist else o["field"] for o in chosen]
    decisions.append(record)
    return [(o["field"], o["plan"], len(decisions) - 1) for o in chosen]


def _finish(directory, history, decisions, incumbent, goal, bias, prelayout, start, planner,
            max_evaluations, parallel):
    trace = {
        "goal": goal, "fixed_input_bias_v": bias, "history": history, "decisions": decisions,
        "evaluations": len(history), "max_evaluations": max_evaluations, "parallel": parallel,
        "wall_seconds": time.perf_counter() - start,
        "eda_seconds": sum(h.get("seconds", 0) for h in history),
        "policy": ("Laya + knowledge-card prior" if planner else "knowledge-card prior") + ", one exploration slot",
        "schematic": {"valid": prelayout.get("valid"), "metrics": prelayout.get("metrics")},
        "selected": incumbent.get("directory") if incumbent else None,
    }
    (directory / "optimization.json").write_text(json.dumps(trace, indent=2, allow_nan=False, default=str))
    # Fine-tuning data: one row per decision with the measured outcome of each evaluated option.
    rows = []
    for i, d in enumerate(decisions):
        evaluated = [h for h in history if h.get("decision") == i]
        rows.append({"schema": "chipjev-layout-decision-v1", "goal": goal, "state": d["state"],
                     "options": d["options"], "cards": d["cards"], "priors": d["priors"],
                     "laya": d["laya"], "chosen": d["chosen"],
                     "outcomes": [{"action": h["action"], "plan": h["plan"], "valid": h.get("valid"),
                                   "objective": h.get("objective"), "critic": h.get("critic"),
                                   "area_um2": h.get("area_um2")} for h in evaluated]})
    (directory / "trajectory.jsonl").write_text("".join(json.dumps(r, default=str) + "\n" for r in rows))
    if incumbent and incumbent.get("directory"):
        source = directory / incumbent["directory"]
        for path in source.iterdir():
            if path.is_dir():
                shutil.copytree(path, directory / path.name, dirs_exist_ok=True)
            else:
                shutil.copy2(path, directory / path.name)
    return trace
