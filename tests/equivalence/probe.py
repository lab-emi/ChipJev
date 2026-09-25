"""Differential probe: the same deterministic inputs through the frozen code and the live package.

  # frozen side (the code that produced the paper), inside the frozen tree:
  .venv/bin/python reproduce/frozen.py exec -- $PWD/.venv/bin/python $PWD/tests/equivalence/probe.py \
      --side frozen --out $PWD/tests/equivalence/golden.json.gz \
      --weights $PWD/experiments/ptm45/typed-decisions.pt
  # live side:
  PYTHONPATH=src .venv/bin/python tests/equivalence/probe.py --side live --out /tmp/live.json.gz \
      --weights experiments/ptm45/typed-decisions.pt

tests/test_equivalence.py compares the live side with the committed golden output of the
frozen side, section by section. Every section is deterministic: CPU tensors with fixed
seeds, synchronous executors in place of the worker and refit pools, and ngspice (which is
deterministic for a given deck). Timing fields, process ids and absolute model paths are
removed before the comparison.

This is the only live file that names the frozen modules (chipjev_topo, chipjev_topo_v2,
chipjev_topo_v3, chipjev_topo_v4, chipjev.rt, chipjev.topo_system2, ...).
"""

import argparse
import gzip
import hashlib
import json
import math
import os
import re
import sys
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace

import numpy as np

CLASSES = ("amp1", "opamp1", "ampN", "opampN")
TARGETS = ("gain", "gbw", "fom")
DROP = re.compile(r"(seconds|^pid$|^elapsed|^timing$|^time$|^wall|^device$|^threads$)")
SECTIONS = ("grammar", "sky130_devices", "space", "surrogate", "decisions", "decks",
            "evaluate", "evaluator", "search", "baselines", "analogcoder_pro", "robustness",
            "xschem", "typed")


# ----------------------------------------------------------------------------- the two APIs


def frozen_api():
    import chipjev.rt.surrogate as surrogate
    import chipjev.topo_system2 as llm
    import chipjev.topo_xschem as xschem
    import chipjev_topo.gp as gp
    import chipjev_topo.grammar as grammar
    import chipjev_topo.published as published
    import chipjev_topo_v2.baselines as baselines
    import chipjev_topo_v2.bench as ptm45
    import chipjev_topo_v2.search as loop2
    import chipjev_topo_v3.acpro as helper
    import chipjev_topo_v3.netlist as netlist
    import chipjev_topo_v3.robustness as robustness
    import chipjev_topo_v3.search as loop3
    import chipjev_topo_v3.typed as typed
    import chipjev_topo_v4.bench as sky130
    import chipjev_topo_v4.search as search4
    import chipjev_topo_v4.sky130 as devices
    from chipjev_topo.space import ClassSpace as Space1
    from chipjev_topo_v2.space import ClassSpace as Space2
    from chipjev_topo_v3.space import ClassSpace as Space3

    def space(cls, carry_sizes=True, prior=None, roles=True, layer=None):
        if layer == 3 or prior is not None or not roles:
            return Space3(cls, carry_sizes=carry_sizes, prior=prior, roles=roles)
        if layer == 2 or not carry_sizes:
            return Space2(cls, carry_sizes=carry_sizes)
        return Space1(cls)

    def search(prior, **settings):
        if prior is None and "roles" not in settings and "dtype" not in settings:
            return lambda *a, **k: loop2.ChipJevTopo(loop2.Settings(**settings)).run(*a, **k)
        s = loop3.Settings(**settings)
        return lambda *a, **k: loop3.ChipJevTopo(s).run(*a, prior=prior, **k)

    def evaluator(workers, technology):
        if technology == "sky130":
            return search4.Evaluator(workers, technology="sky130")
        return loop2.Evaluator(workers)

    return SimpleNamespace(
        side="frozen", grammar=grammar, published=published, space=space, devices=devices,
        ptm45=ptm45, sky130=sky130, surrogate=surrogate, gp=gp, typed=typed, llm=llm,
        search=search, loop_modules=(loop2, loop3), measure=loop2._measure,
        evaluator_class=loop2.Evaluator, evaluator=evaluator, baselines=baselines,
        helper=helper, netlist=netlist, robustness=robustness, xschem=xschem,
        canonical=loop2.CANONICAL)


def live_api():
    import chipjev.analogcoder_pro.helper as helper
    import chipjev.analogcoder_pro.netlist as netlist
    import chipjev.circuits.grammar as grammar
    import chipjev.circuits.published as published
    import chipjev.circuits.sky130_devices as devices
    import chipjev.decisions.llm as llm
    import chipjev.decisions.typed as typed
    import chipjev.search.baselines as baselines
    import chipjev.search.evaluator as evaluators
    import chipjev.search.loop as loop
    import chipjev.simulation.ptm45 as ptm45
    import chipjev.simulation.robustness as robustness
    import chipjev.simulation.sky130 as sky130
    import chipjev.surrogate.gp as gp
    import chipjev.xschem as xschem
    from chipjev.circuits.space import ClassSpace

    def space(cls, carry_sizes=True, prior=None, roles=True, layer=None):
        return ClassSpace(cls, carry_sizes=carry_sizes, prior=prior, roles=roles)

    def search(prior, **settings):
        s = loop.Settings(**settings)
        return lambda *a, **k: loop.ChipJevSearch(s).run(*a, prior=prior, **k)

    def evaluator(workers, technology):
        return evaluators.Evaluator(workers, technology=technology)

    return SimpleNamespace(
        side="live", grammar=grammar, published=published, space=space, devices=devices,
        ptm45=ptm45, sky130=sky130, surrogate=gp, gp=gp, typed=typed, llm=llm,
        search=search, loop_modules=(loop,), measure=evaluators._measure,
        evaluator_class=evaluators.Evaluator, evaluator=evaluator, baselines=baselines,
        helper=helper, netlist=netlist, robustness=robustness, xschem=xschem,
        canonical=loop.CANONICAL)


# ----------------------------------------------------------------------------- helpers


def clean(value, path_map=()):
    """JSON-safe, deterministic view: no timing, process ids or absolute model paths."""
    if isinstance(value, dict):
        return {str(k): clean(v, path_map) for k, v in sorted(value.items(), key=lambda i: str(i[0]))
                if not DROP.search(str(k))}
    if isinstance(value, (list, tuple)):
        return [clean(v, path_map) for v in value]
    if hasattr(value, "tolist"):
        return clean(value.tolist(), path_map)
    if isinstance(value, (np.floating, float)):
        value = float(value)
        return value if math.isfinite(value) else repr(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, str):
        for old, new in path_map:
            value = value.replace(old, new)
        return value
    return value


class SyncExecutor:
    """Runs submitted work immediately: removes thread-timing nondeterminism."""

    def __init__(self, *args, **kwargs):
        pass

    def submit(self, fn, *args, **kwargs):
        future = Future()
        future.set_result(fn(*args, **kwargs))
        return future

    def map(self, fn, *iterables, **kwargs):
        return [fn(*args) for args in zip(*iterables, strict=False)]

    def shutdown(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def sync_evaluator(api):
    evaluator = api.evaluator_class.__new__(api.evaluator_class)
    evaluator.pool = SyncExecutor()
    if api.side == "live":
        from chipjev.search.evaluator import Tally

        evaluator.tally = Tally()
    return evaluator


def designs_for(api, cls, count, seed):
    """Deterministic designs: the canonical starts, then seeded random designs."""
    space = api.space(cls)
    designs = [space.canonical(t) for t in api.canonical[cls]]
    rng = np.random.default_rng(seed)
    designs += space.random(rng, count)
    return space, designs


def prior_for(n):
    weights = np.array([1.0 + (int(hashlib.sha256(str(i).encode()).hexdigest()[:6], 16) % 97)
                        for i in range(n)])
    return weights / weights.sum()


def path_map(api):
    pairs = [(str(api.ptm45.MODEL), "<PTM45>")]
    pairs.append((str(api.devices.model_root()), "<SKY130>"))
    return pairs


# ----------------------------------------------------------------------------- sections


def section_grammar(api):
    g = api.grammar
    out = {"ids": {c: [t.id for t in g.library(c)] for c in CLASSES}, "builds": {}}
    for cls in CLASSES:
        topologies = g.library(cls)
        for t in topologies[:: max(1, len(topologies) // 23)]:
            b = g.build(t, g.default_values(t))
            out["builds"][t.id] = {"lines": b.lines, "bias": b.bias, "mos": b.mos,
                                   "nodes": sorted(b.nodes)}
    out["levels"] = {k: list(v) for k, v in sorted(g.LEVELS.items())}
    published = {}
    for key, topology in sorted(api.published.PUBLISHED.items()):
        values = {s: g.value_of(s, g.level_count(s) // 2) for s in topology.slots()}
        b = g.build(topology, values)
        published[key] = {"slots": list(topology.slots()), "lines": b.lines, "bias": b.bias}
    out["published"] = published
    return out


def section_sky130_devices(api):
    g, d = api.grammar, api.devices
    out = {"include": d.include_text("tt").replace(str(d.model_root()), "<SKY130>"),
           "geometry": [d.geometry(r, length) for r in (1.0, 7.3, 64.0, 500.0)
                        for length in (45.0, 180.0, 720.0)],
           "strength": [d.strength(v) for v in (0.2, 0.47, 1.0)], "builds": {}}
    for cls in CLASSES:
        topologies = g.library(cls)
        for t in topologies[:: max(1, len(topologies) // 11)]:
            b = d.build(t, g.default_values(t), vdd=1.8)
            out["builds"][t.id] = {"lines": b.lines, "bias": b.bias}
    return out


def section_space(api):
    import torch

    out = {}
    for cls in CLASSES:
        base = api.space(cls)
        prior = prior_for(len(base.topologies))
        variants = {
            "default": {}, "no-carry": {"carry_sizes": False},
            "prior": {"prior": prior}, "scrambled": {"roles": False},
            "all": {"carry_sizes": False, "prior": prior, "roles": False},
        }
        for name, options in variants.items():
            space = api.space(cls, **options)
            designs = [space.canonical(t) for t in api.canonical[cls]]
            rng = np.random.default_rng(1)
            random = space.random(rng, 12)
            record = {
                "dimension": space.dimension, "slots": list(space.slots),
                "values": [space.values(d) for d in designs],
                "features": space.features(designs + random),
                "random": random,
                "neighbors": [space.neighbors(d, np.random.default_rng(2), 6, 2)
                              for d in designs[:2] + random[:2]],
                "mutations": [space.mutations(i) for i in (0, len(space.topologies) // 2)],
            }
            for dtype in (torch.float64, torch.float32):
                generator = torch.Generator().manual_seed(3)
                features, t, lv = space.random_on_device(48, generator, "cpu", dtype)
                record[f"random_on_device_{dtype}"] = [features, t, lv]
                topologies = torch.tensor([d[0] for d in designs])
                levels = torch.tensor([d[1] for d in designs], dtype=dtype)
                generator = torch.Generator().manual_seed(4)
                features, t, lv = space.perturb_on_device(topologies, levels, 16, generator,
                                                          "cpu", dtype, jump=0.25, changes=(4,))
                record[f"perturb_on_device_{dtype}"] = [features, t, lv]
            out[f"{cls}/{name}"] = record
        # The frozen v3 layer with default options must equal the v1 layer.
        layered = api.space(cls, layer=3)
        out[f"{cls}/layer3-default"] = {
            "features": layered.features([layered.canonical(t) for t in api.canonical[cls]]),
            "random": layered.random(np.random.default_rng(1), 12)}
    return out


def section_surrogate(api):
    import torch

    rng = np.random.default_rng(5)
    x, y = rng.random((40, 6)), rng.random((40, 3))
    y[4, 1] = np.nan
    out = {}
    gp = api.surrogate.BatchedGP("cpu", seed=0, fit_threads=1, fused=False).fit(x, y, steps=12)
    mean, std = gp.predict(rng.random((10, 6)))
    out["batched"] = {"raw": gp.state["raw"], "mean": mean, "std": std}
    topo = api.gp.TopoGP("cpu", seed=0, fit_threads=1, wide=False).fit(x, y, steps=12)
    candidates = torch.as_tensor(rng.random((200, 6)), dtype=topo.dtype)
    torch.manual_seed(0)
    index, values = topo.thompson(api.gp.Points(candidates), samples=4,
                                  score=lambda v: v[..., 0] - v[..., 1], top=3)
    out["topo"] = {"raw": topo.state["raw"], "mean": topo.predict_mean(candidates[:20]),
                   "index": index, "values": values}
    return out


def section_decisions(api):
    t = api.typed
    out = {"questions": {}, "priors": {}, "state": [
        t.state_text("Design an amplifier.", vdd=1.2, load_pf=100.0),
        t.state_text("Design an op-amp.")]}
    for cls in CLASSES:
        for objective in TARGETS:
            questions = t.topology_questions(cls, objective)
            out["questions"][f"{cls}-{objective}"] = questions
            probabilities = {}
            for key, q in questions.items():
                options = list(q["criteria"])
                weights = np.array([1.0 + k for k in range(len(options))])
                probabilities[key] = dict(zip(options, (weights / weights.sum()).tolist(),
                                              strict=True))
            ids, prior = t.topology_prior(cls, probabilities)
            out["priors"][f"{cls}-{objective}"] = [list(ids), prior]
    library = api.grammar.library("opampN")
    out["decisions"] = [t.decisions(x) for x in library[::97]]
    state = t.state_text("Design a two-stage op-amp with the highest GBW.", vdd=1.2,
                         load_pf=100.0)
    questions = {**t.PARSE_QUESTIONS, **t.topology_questions("opampN", "gbw")}
    out["llm_prompt"] = api.llm.prompt(state, questions)
    keys = list(questions)
    first = {k: list(q["criteria"])[0] for k, q in questions.items()}
    replies = [
        json.dumps({k: {first[k]: 1.0} for k in keys}),
        json.dumps({f"[{k}]": {f"[{first[k]}]": 0.7} for k in keys}),
        json.dumps({k: {"not-an-option": 1.0} for k in keys}),
        json.dumps({k: {first[k]: 1.0} for k in keys[:-1]}),
        "no json here",
        "```json\n" + json.dumps({k: {first[k]: 2.0} for k in keys}) + "\n```",
    ]
    validated = []
    for reply in replies:
        try:
            validated.append(["ok", api.llm.validate(reply, questions)])
        except Exception as exc:  # the type error is part of the behaviour
            validated.append([type(exc).__name__, str(exc)])
    out["llm_validate"] = validated
    return out


def section_decks(api):
    out = {}
    pm = path_map(api)
    for cls in CLASSES:
        space, designs = designs_for(api, cls, 2, seed=6)
        for k, d in enumerate(designs):
            topology, values = space.topology(d), space.values(d)
            for strict in (False, True):
                text, _ = api.ptm45.deck(topology, values, strict=strict, load_pf=100.0, vdd=1.2)
                out[f"ptm45/{cls}/{k}/{strict}"] = clean(text, pm)
                text, _ = api.sky130.deck(topology, values, strict=strict, load_pf=100.0, vdd=1.8)
                out[f"sky130/{cls}/{k}/{strict}"] = clean(text, pm)
            text, _ = api.ptm45.deck(topology, values, rules="physical")
            out[f"ptm45-physical/{cls}/{k}"] = clean(text, pm)
    return out


def section_evaluate(api):
    out = {}
    pm = path_map(api)
    for cls in CLASSES:
        space, designs = designs_for(api, cls, 1, seed=7)
        for k, d in enumerate(designs[:2] + designs[-1:]):
            topology, values = space.topology(d), space.values(d)
            for strict in (False, True):
                record = api.ptm45.evaluate(topology, values, strict=strict, load_pf=100.0,
                                            vdd=1.2)
                out[f"ptm45/{cls}/{k}/{strict}"] = clean(record, pm)
        d = designs[0]
        record = api.ptm45.evaluate(space.topology(d), space.values(d), rules="physical")
        out[f"ptm45-physical/{cls}"] = clean(record, pm)
        for strict in (False, True):
            record = api.sky130.evaluate(space.topology(d), space.values(d), strict=strict,
                                         load_pf=100.0, vdd=1.8)
            out[f"sky130/{cls}/{strict}"] = clean(record, pm)
    return out


def section_evaluator(api):
    out = {}
    pm = path_map(api)
    for technology, vdd in (("ptm45", 1.2), ("sky130", 1.8)):
        evaluator = api.evaluator(2, technology)
        try:
            for cls in ("amp1", "opamp1"):
                space, designs = designs_for(api, cls, 0, seed=8)
                records = evaluator.map(space, designs[:2], load_pf=100.0, vdd=vdd)
                out[f"{technology}/{cls}"] = clean(records, pm)
        finally:
            evaluator.close()
    return out


def section_search(api):
    for module in api.loop_modules:
        module.ThreadPoolExecutor = SyncExecutor
    common = dict(seed=0, rounds=3, device="cpu", threads=1, random_pool=256, local_pool=256,
                  features=128, gp_steps_first=8, gp_steps=4, refit_every=2)
    out = {}
    pm = path_map(api)
    for cls, target in (("amp1", "gain"), ("opampN", "fom")):
        n = len(api.space(cls).topologies)
        prior = prior_for(n)
        arms = {
            "no-prior": (None, {}),
            "prior": (prior, {"prior_mix": 0.5, "typed_starts": 4}),
            "scrambled": (prior, {"roles": False}),
            "cpu-fp32": (prior, {"dtype": "float32"}),
        }
        for name, (p, extra) in arms.items():
            run = api.search(p, **common, **extra)
            result = run(cls, target, sync_evaluator(api), load_pf=100.0, vdd=1.2,
                         rules="qualified")
            for key in ("method", "settings", "acquisition_dtype", "starts", "typed_prior",
                        "environment", "notes"):
                result.pop(key, None)
            out[f"{cls}-{target}/{name}"] = clean(result, pm)
    return out


def section_baselines(api):
    out = {}
    pm = path_map(api)
    for cls, target in (("amp1", "gain"), ("opamp1", "gbw")):
        for name in ("random_search", "tpe_joint"):
            engine = getattr(api.baselines, name)
            kwargs = {"startup": 8} if name == "tpe_joint" else {}
            result = engine(cls, target, sync_evaluator(api), 24, seed=0, load_pf=100.0,
                            vdd=1.2, rules="qualified", **kwargs)
            # Trajectory points are (evaluations, elapsed seconds, best): drop the time.
            result["trajectory"] = [[p[0], *p[2:]] for p in result.get("trajectory", [])]
            out[f"{cls}-{target}/{name}"] = clean(result, pm)
    return out


NETLIST = """
.title two-stage
M1 net1 inp tail 0 nmos W=2u L=180n
M2 net2 inn tail 0 nmos W=2u L=180n
M3 net1 net1 vdd vdd pmos W=4u L=180n
M4 net2 net1 vdd vdd pmos W=4u L=180n
M5 tail vbn 0 0 nmos W=4u L=360n
M6 out net2 vdd vdd pmos W=16u L=180n
M7 out vbn 0 0 nmos W=8u L=360n
Cc net2 out 1p
Vbn vbn 0 DC 0.55
VDD vdd 0 DC 1.2
Vinp inp 0 DC 0.6 AC 1
Vinn inn 0 DC 0.6
CL out 0 100p
.end
"""


def section_analogcoder_pro(api):
    out = {"tasks": {str(k): v for k, v in api.helper.TASKS.items()},
           "ptm": [api.helper.ptm_params(k) for k in ("nmos", "pmos")],
           "model_module": clean(api.helper.model_module(), path_map(api))}
    try:
        b = api.netlist.parse(NETLIST, True, 1.2)
        out["parse"] = {"lines": b.lines, "bias": b.bias, "mos": b.mos, "nodes": sorted(b.nodes)}
    except Exception as exc:
        out["parse"] = [type(exc).__name__, str(exc)]
    return out


def section_robustness(api):
    out = {}
    pm = path_map(api)
    space = api.space("opamp1")
    d = space.canonical("ota5_n")
    checked = api.robustness.check(space.topology(d), space.values(d), target="gain", vdd=1.2,
                                   load_pf=100.0, seed=0, samples=2)
    out["opamp1"] = clean(checked, pm)
    return out


def section_xschem(api):
    out = {}
    for cls in ("amp1", "opampN"):
        space, designs = designs_for(api, cls, 1, seed=9)
        for k, d in enumerate(designs[:1] + designs[-1:]):
            b = api.devices.build(space.topology(d), space.values(d), vdd=1.8)
            out[f"{cls}/{k}"] = api.xschem.schematic(b, f"{cls}-{k}", 1.8)
    return out


def section_typed(api, weights):
    out = {}
    model = api.typed.TypedDecisions(weights=weights, device="cpu", dtype="float32")
    requests = [
        ("Design a two-stage op-amp with the highest gain-bandwidth product", 1.2, 100.0, {}),
        ("Design a single-stage amplifier with maximum gain.", None, None, {}),
        ("Design a multi-stage opamp that maximizes FoM.", 1.2, 100.0,
         {"cls": "opampN", "objective": "fom"}),
    ]
    for k, (text, vdd, load, extra) in enumerate(requests):
        answer = model.ask(text, vdd=vdd, load_pf=load, **extra)
        out[str(k)] = clean({key: answer[key] for key in
                             ("state", "class", "objective", "answers", "topologies", "prior")})
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--side", choices=("frozen", "live"), required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--sections", nargs="*", default=list(SECTIONS))
    parser.add_argument("--weights", type=Path, default=None)
    args = parser.parse_args()
    os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")
    import torch

    torch.set_num_threads(1)
    api = frozen_api() if args.side == "frozen" else live_api()
    results = {}
    for name in args.sections:
        if name == "typed":
            if args.weights is None:
                continue
            results[name] = section_typed(api, args.weights)
        else:
            results[name] = clean(globals()[f"section_{name}"](api))
        print(f"{args.side}: {name} done", file=sys.stderr, flush=True)
    with gzip.open(args.out, "wt") as stream:
        json.dump(results, stream, sort_keys=True, allow_nan=False)


if __name__ == "__main__":
    main()
