"""Baselines on ChipJev's testbench, rules, starts and worker pool.

tpe8     eight-worker joint TPE (Optuna, constant liar): topology and sizes as one
         define-by-run search space, batches of eight, the same first batch as ChipJev.
random8  random (topology, sizing) designs over the grammar's grid, eight at a time.

Every method verifies each new online incumbent by strict re-simulation and reports only
strictly valid designs, exactly like the ChipJev search.
"""

import time
import warnings

import numpy as np

from ..circuits.grammar import (
    BUFFERS,
    DIFF_STAGES,
    GAIN_STAGES,
    LEVELS,
    Topology,
    library,
    slot_kind,
)
from ..circuits.space import ClassSpace
from ..simulation.analysis import objective, reported
from .evaluator import _measure
from .loop import CANONICAL, _outputs, _score_numpy


def initial_designs(space, rng, batch=8):
    designs = [space.canonical(t) for t in CANONICAL[space.cls]][:batch]
    while len(designs) < batch:
        design = space.random(rng, 1)[0]
        if design not in designs:
            designs.append(design)
    return designs


def score(record, target):
    value = objective(record, target)
    if record["valid"] and value is not None:
        return 100.0 + value
    return min(float(_score_numpy([_outputs(dict(record, objective=value))])[0]), 0.0)


class Tracker:
    """Online trajectory, strict verification of new incumbents and the reported best."""

    def __init__(self, target, verify, start):
        self.target, self.verify, self.start = target, verify, start
        self.records, self.strict = [], []
        self.best = None
        self.first = None
        self.trajectory = []
        self.verify_seconds = 0.0

    def observe(self, measured, designs):
        at = time.perf_counter() - self.start
        threshold = -np.inf if self.best is None else self.best["objective"]
        contenders = []
        for record, design in zip(measured, designs, strict=True):
            record["objective"] = objective(record, self.target)
            record["elapsed_seconds"] = at
            self.records.append(record)
            if record["valid"] and record["objective"] is not None:
                if record["objective"] > threshold:
                    contenders.append((record["objective"], design))
        contenders.sort(key=lambda c: -c[0])
        if contenders:
            verify_start = time.perf_counter()
            checked = self.verify([d for _, d in contenders[:2]])
            self.verify_seconds += time.perf_counter() - verify_start
            at = time.perf_counter() - self.start
            for record in checked:
                record["objective"] = objective(record, self.target)
                record["elapsed_seconds"] = at
                self.strict.append(record)
                if record["valid"] and record["objective"] is not None:
                    if self.best is None or record["objective"] > self.best["objective"]:
                        self.best = record
                        if self.first is None:
                            self.first = {"seconds": at, "evaluations": len(self.records)}
        self.trajectory.append(
            (len(self.records), at, None if self.best is None else self.best["objective"])
        )

    def result(self, method, extra):
        best = self.best
        result = {
            "method": method,
            "verified": best is not None,
            "first_verified": self.first,
            "best": None
            if best is None
            else {
                "topology": best["topology"],
                "values": best["values"],
                "metrics": best["metrics"],
                "objective": best["objective"],
                "reported": reported(best, self.target),
                "seconds": best["elapsed_seconds"],
            },
            "evaluations": len(self.records),
            "verifications": len(self.strict),
            "false_passes": sum(1 for r in self.strict if not r["valid"]),
            "wall_seconds": time.perf_counter() - self.start,
            "verify_seconds": self.verify_seconds,
            "trajectory": self.trajectory,
            **extra,
        }
        result.update(records=self.records, strict=self.strict)
        if self.best:
            result["best"]["qualification"] = self.best.get("qualification")
        return result


def random_search(
    cls,
    target,
    evaluator,
    budget=1024,
    *,
    batch=8,
    seed=0,
    load_pf=100.0,
    vdd=1.2,
    rules="qualified",
):
    space = ClassSpace(cls)
    rng = np.random.default_rng(seed)
    env = {"load_pf": load_pf, "vdd": vdd, "rules": rules}
    start = time.perf_counter()
    tracker = Tracker(target, lambda ds: evaluator.map(space, ds, strict=True, **env), start)
    seen = set()
    while len(tracker.records) < budget:
        designs = initial_designs(space, rng, batch) if not tracker.records else []
        while len(designs) < min(batch, budget - len(tracker.records)):
            design = space.random(rng, 1)[0]
            if design not in seen and design not in designs:
                designs.append(design)
        seen.update(designs)
        tracker.observe(evaluator.map(space, designs, **env), designs)
    return tracker.result("random8", {"cls": cls, "target": target, "seed": seed, **env})


def _suggest(trial, slot):
    """A continuous size on the grid's range (biases linear, everything else log)."""
    kind = slot_kind(slot)
    levels = LEVELS[kind]
    return trial.suggest_float(slot, levels[0], levels[-1], log=kind != "bias")


def _suggest_topology(trial, cls):
    """A grammar topology from categorical choices (define-by-run, conditional)."""
    if cls in ("amp1", "opamp1"):
        stage = trial.suggest_categorical("stage1", [t.stages[0] for t in library(cls)])
        return Topology(cls, (stage,))
    if cls == "ampN":
        firsts = list(GAIN_STAGES)
    else:
        firsts = [f"{name}_{pol}" for name in DIFF_STAGES for pol in "np"]
    count = trial.suggest_categorical("count", [2, 3])
    first = trial.suggest_categorical("stage1", firsts)
    rest = tuple(
        trial.suggest_categorical(f"stage{k}", list(GAIN_STAGES)) for k in range(2, count + 1)
    )
    buffer = trial.suggest_categorical("buffer", list(BUFFERS)) if cls == "ampN" else "none"
    comps = ["none", "miller", "miller_rz"] + (["miller2"] if count == 3 else [])
    comp = trial.suggest_categorical(f"comp{count}", comps)
    return Topology(cls, (first, *rest), buffer, comp)


def parameters(topology, values):
    result = {"stage1": topology.stages[0], **values}
    if len(topology.stages) > 1:
        result.update(count=len(topology.stages))
        result.update({f"stage{k}": stage for k, stage in enumerate(topology.stages[1:], 2)})
        result[f"comp{len(topology.stages)}"] = topology.comp
        if topology.cls == "ampN":
            result["buffer"] = topology.buffer
    return result


def tpe_joint(
    cls,
    target,
    evaluator,
    budget=1024,
    *,
    batch=8,
    startup=256,
    seed=0,
    load_pf=100.0,
    vdd=1.2,
    rules="qualified",
):
    import optuna

    optuna.logging.set_verbosity(optuna.logging.ERROR)
    warnings.filterwarnings("ignore", category=optuna.exceptions.ExperimentalWarning)
    sampler = optuna.samplers.TPESampler(
        n_startup_trials=startup, multivariate=True, group=True, constant_liar=True, seed=seed
    )
    study = optuna.create_study(direction="maximize", sampler=sampler)
    space = ClassSpace(cls)
    for design in initial_designs(space, np.random.default_rng(seed), batch):
        study.enqueue_trial(parameters(space.topology(design), space.values(design)))
    start = time.perf_counter()

    def measure(designs, strict=False):
        return list(
            evaluator.pool.map(
                _measure, [(cls, t.id, v, strict, load_pf, vdd, rules) for t, v in designs]
            )
        )

    tracker = Tracker(target, lambda ds: measure(ds, True), start)
    for _ in range(0, budget, batch):
        trials, designs = [], []
        for _ in range(min(batch, budget - len(tracker.records))):
            trial = study.ask()
            topology = _suggest_topology(trial, cls)
            values = {s: _suggest(trial, s) for s in topology.slots()}
            trials.append(trial)
            designs.append((topology, values))
        records = measure(designs)
        previous = len(tracker.strict)
        tracker.observe(records, designs)
        verified = {
            (r["topology"], tuple(sorted(r["values"].items()))): r
            for r in tracker.strict[previous:]
        }
        for trial, record in zip(trials, records, strict=True):
            key = (record["topology"], tuple(sorted(record["values"].items())))
            study.tell(trial, score(verified.get(key, record), target))
    return tracker.result(
        "tpe8",
        {
            "cls": cls,
            "target": target,
            "seed": seed,
            "load_pf": load_pf,
            "vdd": vdd,
            "rules": rules,
            "startup": startup,
            "constant_liar": True,
        },
    )
