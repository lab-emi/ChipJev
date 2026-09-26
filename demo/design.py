"""A bounded, fresh Laya + ChipJev search for a selected public prompt."""

import json
import time
from concurrent.futures import Future
from pathlib import Path
from tempfile import mkdtemp

from chipjev.circuits.grammar import default_values, library
from chipjev.circuits.sky130_devices import build
from chipjev.circuits.space import ClassSpace
from chipjev.decisions.typed import TypedDecisions
from chipjev.paths import ROOT
from chipjev.search.evaluator import Evaluator
from chipjev.search.loop import ChipJevSearch, Settings, _outputs, _score_numpy
from chipjev.simulation.analysis import CMRR_MIN_DB, MIN_GAIN_DB, PM_MIN
from demo.examples import allows

WEIGHTS = ROOT / "experiments/ptm45/typed-decisions.pt"
ROUNDS = 96
SEARCH_SECONDS = 180


class LayoutEvaluator(Evaluator):
    """Reserve modest nominal headroom; actual PEX still determines acceptance."""

    def __init__(self, *args, headroom=None, physical_directory=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.headroom = headroom or {}
        self.physical_directory = Path(physical_directory) if physical_directory else None
        if self.physical_directory:
            self.physical_directory.mkdir(parents=True, exist_ok=True)

    def submit(self, *args, **kwargs):
        futures = super().submit(*args, **kwargs)
        result = []
        for source in futures:
            destination = Future()

            def complete(source, destination=destination):
                try:
                    record = source.result()
                    metrics = record["metrics"]
                    reserves = getattr(self, "headroom", {})
                    limits = {
                        "gain_db": MIN_GAIN_DB[record["cls"]],
                        "pm_deg": PM_MIN,
                        "cmrr_db": CMRR_MIN_DB,
                    }
                    passed = all(
                        (metrics.get(key) or -1e9) >= limits[key] + reserve
                        for key, reserve in reserves.items()
                    )
                    record["schematic_valid"] = record["valid"]
                    if record["checks"]:
                        record["checks"]["layout_headroom"] = passed
                    record["valid"] = bool(record["valid"] and passed)
                    for key, reserve in reserves.items():
                        if record["margins"].get(key) is not None:
                            record["margins"][key] -= reserve
                    if record.get("strict") and record["valid"] and self.physical_directory:
                        from chipjev.circuits.published import lookup
                        from chipjev.layout.pro.planner import ProPlan
                        from chipjev.layout.verification import verify

                        target = Path(mkdtemp(prefix="candidate-", dir=self.physical_directory))
                        started = time.perf_counter()
                        if not record.get("geometry_policy"):
                            from chipjev.simulation.sky130 import evaluate

                            # Continuous sizing is a cheap exploration profile.
                            # Acceptance always uses the manufacturable schematic
                            # at the *same* selected input common-mode point.
                            record = evaluate(
                                lookup(record["cls"], record["topology"]), record["values"],
                                target/"schematic-grid", strict=True, keep=True,
                                vdd=record["vdd"], load_pf=record["load_pf"],
                                quantize_geometry=True, input_bias=record["metrics"]["vin_dc"],
                            )
                            record["valid"] = bool(record["valid"] and all(
                                (record["metrics"].get(k) or -1e9) >= limits[k]+v
                                for k,v in reserves.items()))
                            if not record["valid"]:
                                (target/"schematic-grid/result.json").write_text(json.dumps(record,indent=2))
                                destination.set_result(record)
                                return
                        try:
                            physical = verify(
                                lookup(record["cls"], record["topology"]),
                                record["values"], target, prelayout=record,
                                vdd=record["vdd"], load_pf=record["load_pf"],
                                plan=ProPlan(),
                                input_bias=record["metrics"]["vin_dc"],
                            )
                            measured = physical["postlayout"]
                        except (RuntimeError, ValueError) as exc:
                            # Illegal geometry is search feedback, never a reason
                            # to accept a schematic-only substitute.
                            physical = {"valid": False, "error": str(exc),
                                        "physical_seconds": time.perf_counter()-started}
                            (target/"physical.json").write_text(json.dumps(physical, indent=2))
                            measured = dict(record)
                            measured["checks"] = {**record["checks"], "function": False}
                            measured["margins"] = {**record["margins"], "function": -1.}
                        measured["physical_screen"] = {
                            "path": str(target.relative_to(self.physical_directory.parent)),
                            "valid": physical["valid"],
                            "seconds": physical["physical_seconds"],
                            "schematic_metrics": record["metrics"],
                        }
                        measured["valid"] = physical["valid"]
                        if not physical["valid"]:
                            measured["checks"]["function"] = False
                        record = measured
                    destination.set_result(record)
                except Exception as exc:
                    destination.set_exception(exc)

            source.add_done_callback(complete)
            result.append(destination)
        return result


def load_model(device=None):
    import torch

    torch.set_num_threads(8)
    return TypedDecisions(weights=WEIGHTS, device=device, offline=True)


def decide(model, example):
    answer = model.ask(
        example["prompt"],
        cls=example["cls"],
        objective=example["objective"],
        vdd=example["vdd"],
        load_pf=example["load_pf"],
    )
    # The prompt's explicit stage count and circuit family are hard design constraints.
    # Preserve the model's complete answers, and condition its prior on the allowed grammar.
    topologies = [
        t
        for t in library(example["cls"])
        if len(t.stages) == example["stages"] and allows(example, t)
        and len(build(t, default_values(t), example["vdd"]).mos) >= example.get("min_mosfets", 0)
    ]
    full_prior = dict(zip(answer["topologies"], answer["prior"], strict=True))
    weights = [full_prior[t.id] for t in topologies]
    answer["search_topologies"] = [t.id for t in topologies]
    answer["search_prior"] = [p / sum(weights) for p in weights]
    return answer


def least_violating(result):
    # A loose-tolerance pass can fail strict re-simulation. Use the strict
    # measurement for that same design when ranking an exhausted search.
    measured = {}
    for record in [*result["records"], *result["strict"]]:
        topology, levels = record["design"]
        measured[(topology, tuple(levels))] = record
    records = list(measured.values())
    if not records:
        raise RuntimeError("The design search produced no measurements")
    index = _score_numpy([_outputs(record) for record in records]).argmax()
    return records[int(index)]


def search(answer, example, device, observer, physical_directory=None):
    evaluator = LayoutEvaluator(
        8,
        technology="sky130",
        headroom=example["headroom"],
        # The interactive host also captures video and serves requests. Leave
        # timing headroom for ~2 s convergent DC sweeps; retain the total budget.
        evaluate_options={"quantize_geometry": example["objective"] != "gain", "online_timeout_s": 2.5},
        physical_directory=physical_directory,
    )
    # Interactive profile: same grammar, priors, GP and strict qualification;
    # smaller acquisition pools and stop at the first strictly verified design.
    # No archived circuit, sizing or measurement is used as a starting point.
    options = Settings(
        seed=example["seed"],
        rounds=ROUNDS,
        features=256,
        random_pool=1024,
        local_pool=2048,
        device=str(device),
        threads=8,
    )
    topologies = [t for t in library(example["cls"]) if t.id in answer["search_topologies"]]
    try:
        result = ChipJevSearch(options).run(
            example["cls"],
            example["objective"],
            evaluator,
            prior=answer["search_prior"],
            vdd=example["vdd"],
            load_pf=example["load_pf"],
            topologies=topologies,
            deadline=SEARCH_SECONDS,
            observer=observer,
            stop_after_verified=True,
            wait_for_refit=True,
        )
    finally:
        evaluator.close()
    if result["best"] is not None:
        selected = result["best"]
    else:
        record = least_violating(result)
        selected = {
            "topology": record["topology"],
            "values": ClassSpace(example["cls"], topologies=topologies).values(record["design"]),
        }
    result["demo_stop_rule"] = "first strictly RC-qualified design or budget exhausted"
    result["physical_candidate_screening"] = physical_directory is not None
    result["layout_headroom"] = example["headroom"]
    result["exploration_geometry"] = ("continuous approximation" if example["objective"] == "gain"
                                      else "manufacturing grid")
    result["acceptance_geometry"] = "manufacturing grid, fixed shared input bias"
    result["online_timeout_s"] = 2.5
    # Consume each refit before the next acquisition so capture/network latency
    # cannot change which model supplies the following search round.
    result["wait_for_refit"] = True
    result["prior"] = answer["search_prior"]
    result["topology_ids"] = answer["search_topologies"]
    return selected, result
