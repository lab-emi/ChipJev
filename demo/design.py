"""A bounded, fresh Laya + ChipJev search for a selected public prompt."""

from chipjev.circuits.grammar import default_values, library
from chipjev.circuits.sky130_devices import build
from chipjev.circuits.space import ClassSpace
from chipjev.decisions.typed import TypedDecisions
from chipjev.paths import ROOT
from chipjev.search.evaluator import Evaluator
from chipjev.search.loop import ChipJevSearch, Settings, _outputs, _score_numpy

WEIGHTS = ROOT / "experiments/ptm45/typed-decisions.pt"
ROUNDS = 96
SEARCH_SECONDS = 180
SEEDS = {"opamp-gain": 0, "opamp-speed": 2, "ota-efficient": 2}


def load_model(device=None):
    import torch

    torch.set_num_threads(8)
    return TypedDecisions(weights=WEIGHTS, device=device, offline=True)


def decide(model, example):
    answer = model.ask(example["prompt"], cls=example["cls"], objective=example["objective"],
                       vdd=example["vdd"], load_pf=example["load_pf"])
    # The prompt's explicit stage count is a hard design constraint. Preserve the
    # model's complete answers, and condition its prior on the allowed grammar.
    topologies = [t for t in library(example["cls"])
                  if len(t.stages) == example["stages"]
                  and len(build(t, default_values(t), example["vdd"]).mos) >= example.get("min_mosfets", 0)]
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


def search(answer, example, device, observer):
    evaluator = Evaluator(8, technology="sky130")
    # Interactive profile: same grammar, priors, GP and strict qualification;
    # smaller acquisition pools and stop at the first strictly verified design.
    # No archived circuit, sizing or measurement is used as a starting point.
    options = Settings(seed=SEEDS[example["id"]], rounds=ROUNDS, features=256, random_pool=1024,
                       local_pool=2048, device=str(device), threads=8)
    topologies = [t for t in library(example["cls"]) if t.id in answer["search_topologies"]]
    try:
        result = ChipJevSearch(options).run(example["cls"], example["objective"], evaluator,
                   prior=answer["search_prior"], vdd=example["vdd"], load_pf=example["load_pf"],
                   topologies=topologies, deadline=SEARCH_SECONDS, observer=observer,
                   stop_after_verified=True, wait_for_refit=True)
    finally:
        evaluator.close()
    if result["best"] is not None:
        selected = result["best"]
    else:
        record = least_violating(result)
        selected = {"topology": record["topology"],
                    "values": ClassSpace(example["cls"], topologies=topologies).values(record["design"])}
    result["demo_stop_rule"] = "first strictly verified design or budget exhausted"
    # Consume each refit before the next acquisition so capture/network latency
    # cannot change which model supplies the following search round.
    result["wait_for_refit"] = True
    result["prior"] = answer["search_prior"]
    result["topology_ids"] = answer["search_topologies"]
    return selected, result
