"""The ChipJev search: real-time joint topology and sizing search on a typed prior.

Every round measures a batch of distinct (topology, sizing) designs concurrently with
real ngspice. One slot goes to the posterior-mean best local move around the incumbent
(exploitation); the others go to pathwise Thompson samples of a Gaussian process over
the joint space, each maximized over a large candidate pool generated on the GPU
(uniform designs over all topologies plus local and one-choice topology mutations of
the best design of each leading topology, which carry sizes across topologies through
shared role slots).
The surrogate never accepts a design: every new incumbent is re-simulated at strict
tolerances, and only strictly valid designs are reported.

Typed decisions enter through three explicit options:

* `prior` (run): a typed-decision distribution over the class's topologies. The first
  round adds the `typed_starts` most probable topologies (mid-grid sizes) after the
  textbook starts, and uniform candidates draw their topology from
  (1 - mix) * prior + mix * uniform. Without a prior the search is the paper's
  "ChipJev without typed decisions" arm (method id chipjev-v2 in the evidence).
* `Settings.roles=False`: the scrambled-role representation (circuits/space.py).
* `Settings.dtype`: acquisition precision, so that an eager CPU ablation can use FP32 like
  the GPU kernel (the default CPU path is FP64).
"""

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field

import numpy as np

from ..circuits.grammar import VDD
from ..circuits.space import ClassSpace
from ..simulation.analysis import LOAD_PF, objective, reported
from ..surrogate.gp import Points, TopoGP

__all__ = ["CANONICAL", "ChipJevSearch", "Settings", "mixture", "warm"]

# Canonical textbook starting topologies per class (mid-grid sizes).
CANONICAL = {
    "amp1": ("cs_n", "cas_n", "tele_n", "inv"),
    "opamp1": ("ota5_n", "tele_n", "fc_n", "cmota_n"),
    "ampN": ("cs_n+cs_n", "cas_n+cs_n", "inv+inv", "cs_n+cs_n+cs_n"),
    "opampN": (
        "ota5_n+cs_p+miller",
        "ota5_p+cs_n+miller",
        "tele_n+cs_p+miller_rz",
        "fc_n+cs_p+miller",
    ),
}


@dataclass
class Settings:
    batch: int = 8
    rounds: int = 128
    exploit: int = 1
    exploit_final: int | None = None
    random_pool: int = 1 << 11
    local_pool: int = 1 << 13
    top_k: int = 8
    per_topology: int = 1
    depth: int = 0
    perturb: int = 0
    mutations: int = 2
    jump: float = 0.25
    changes: tuple = (4,)
    gp_steps_first: int = 60
    gp_steps: int = 15
    refit_every: int = 4
    threads: int = 8
    fit_points: int = 256
    max_points: int = 512
    features: int = 1024
    verify_top: int = 2
    device: str | None = None
    dtype: str | None = None  # acquisition precision; None: FP32 on GPUs, FP64 on the CPU
    seed: int = 0
    surrogate: bool = True
    constraint_model: bool = True
    carry_sizes: bool = True
    roles: bool = True  # False: scrambled-role representation (ablation)
    typed_starts: int = 4  # prior-ranked topologies added to the first round
    prior_mix: float = 0.5  # uniform share of the topology distribution of random candidates
    notes: dict = field(default_factory=dict)


def mixture(prior, mix):
    prior = np.asarray(prior, dtype=float)
    prior = prior / prior.sum()
    return (1.0 - mix) * prior + mix / len(prior)


class ChipJevSearch:
    def __init__(self, settings=None):
        self.settings = settings or Settings()

    def run(
        self,
        cls,
        target,
        evaluator,
        *,
        load_pf=LOAD_PF,
        vdd=VDD,
        rules="qualified",
        prior=None,
        deadline=None,
        observer=None,
        topologies=None,
        stop_after_verified=False,
        wait_for_refit=False,
    ):
        import torch

        from ..surrogate.gp import device_info, synchronize

        s = self.settings
        start = time.perf_counter()
        space = ClassSpace(
            cls,
            topologies=topologies,
            carry_sizes=s.carry_sizes,
            prior=None if prior is None else mixture(prior, s.prior_mix),
            roles=s.roles,
        )
        rng = np.random.default_rng(s.seed)
        threads = torch.get_num_threads()
        torch.set_num_threads(s.threads)
        gp = TopoGP(s.device, features=s.features, seed=s.seed, fit_threads=s.threads,
                    dtype=s.dtype)
        refitter = ThreadPoolExecutor(1) if s.surrogate else None
        refit = None
        generator = torch.Generator(device=gp.device).manual_seed(s.seed)
        scales = torch.tensor(
            [scale for _, scale in MARGINS] + [1.0], device=gp.device, dtype=gp.dtype
        )

        def score_fn(values):
            return _score_torch(values, scales) if s.constraint_model else values[..., 0]

        def model_outputs(record):
            outputs = _outputs(record)
            return outputs if s.constraint_model else [float(_score_numpy([outputs])[0])]

        designs, records, strict_records = [], [], []
        outputs, scores = [], []
        visited = set()
        design_indices = {}
        state = {"best": None, "first": None}
        timing = {"gp_fit": 0.0, "gp_refit": 0.0, "acquisition": 0.0, "evaluate": 0.0}
        rounds = []
        pending = []
        starts = list(CANONICAL[cls])
        if prior is not None and s.typed_starts:
            order = np.argsort(-np.asarray(prior), kind="stable")
            typed = [space.topologies[int(j)].id for j in order if
                     space.topologies[int(j)].id not in starts][: s.typed_starts]
            starts += typed

        def data(cap):
            chosen = _training_indices(records, scores, cap)
            x = space.features([designs[k] for k in chosen])
            return x, np.array([outputs[k] for k in chosen])

        def settle(block):
            while pending and (block or all(f.done() for f in pending[0][2])):
                round_index, chosen, futures, stamps = pending.pop(0)
                for design, future in zip(chosen, futures, strict=True):
                    record = future.result()
                    at = stamps.get(id(future), time.perf_counter()) - start
                    record.update(
                        round=round_index,
                        elapsed_seconds=at,
                        objective=objective(record, target),
                        design=[design[0], list(design[1])],
                    )
                    strict_records.append(record)
                    if not record["valid"] and design in design_indices:
                        k = design_indices[design]
                        outputs[k] = model_outputs(record)
                        scores[k] = float(_score_numpy([_outputs(record)])[0])
                    best = state["best"]
                    if record["valid"] and record["objective"] is not None:
                        if best is None or record["objective"] > best["objective"]:
                            state["best"] = record
                            if state["first"] is None:
                                state["first"] = {
                                    "seconds": at,
                                    "evaluations": len(records),
                                    "round": round_index,
                                }

        for round_index in range(s.rounds):
            if deadline is not None and time.perf_counter() - start > deadline:
                break
            batch, sources = [], []

            def add(design, source):
                if design not in visited and design not in batch:
                    batch.append(design)
                    sources.append(source)
                    return True
                return False

            if round_index == 0:
                for k, tid in enumerate(starts):
                    if tid in space.index and (prior is None or len(batch) < s.batch):
                        add(space.canonical(tid), "canonical" if k < 4 else "typed")
            elif s.surrogate:
                ranked = sorted(range(len(records)), key=lambda k: -scores[k])
                incumbents = _incumbents(designs, ranked, s.top_k, s.per_topology, s.depth)
                fit_start = time.perf_counter()
                if gp.state is None:
                    gp.fit(*data(s.fit_points), steps=s.gp_steps_first)
                elif refit is not None and (refit.done() or wait_for_refit):
                    gp.state["raw"], seconds = refit.result()
                    timing["gp_refit"] += seconds
                    refit = None
                gp.fit(*data(s.max_points), steps=0)
                timing["gp_fit"] += time.perf_counter() - fit_start
                acq_start = time.perf_counter()
                local = []
                for design in incumbents:
                    local += space.neighbors(design, rng, s.perturb, s.mutations)
                local = [d for d in dict.fromkeys(local) if d not in visited]
                pools = []
                if local:
                    features = torch.as_tensor(
                        space.features(local), device=gp.device, dtype=gp.dtype
                    )
                    pools.append((features, lambda j: (local[j], "thompson-local")))
                    exploits = s.exploit
                    if s.exploit_final is not None and s.rounds > 1:
                        ramp = (s.exploit_final - s.exploit) * round_index / (s.rounds - 1)
                        exploits = s.exploit + int(round(ramp))
                    if exploits:
                        predicted = score_fn(gp.predict_mean(features)).cpu().numpy()
                        chosen = 0
                        for j in np.argsort(-predicted, kind="stable"):
                            chosen += add(local[int(j)], "exploit")
                            if chosen == exploits:
                                break
                slots = s.batch - len(batch)
                if slots > 0:
                    if incumbents and s.local_pool:
                        pf, pt, pl = space.perturb_on_device(
                            [d[0] for d in incumbents],
                            [d[1] for d in incumbents],
                            s.local_pool,
                            generator,
                            gp.device,
                            gp.dtype,
                            s.jump,
                            tuple(s.changes),
                        )
                        pools.append((pf, _decoder(pt, pl, "thompson-trust")))
                    rf, rt, rl = space.random_on_device(
                        s.random_pool, generator, gp.device, gp.dtype
                    )
                    pools.append((rf, _decoder(rt, rl, "thompson-random")))
                    feats = torch.cat([f for f, _ in pools])
                    offsets = np.cumsum([0] + [len(f) for f, _ in pools])
                    index, _ = gp.thompson(
                        Points(feats), samples=slots, score=score_fn, top=slots + 32
                    )
                    synchronize(gp.device)
                    for row in index:
                        for j in row:
                            j = int(j)
                            which = int(np.searchsorted(offsets, j, side="right") - 1)
                            design, source = pools[which][1](j - int(offsets[which]))
                            if add(design, source):
                                break
                timing["acquisition"] += time.perf_counter() - acq_start
            attempts = 0
            while len(batch) < s.batch and attempts < 1000:
                attempts += 1
                add(space.random(rng, 1)[0], "random")
            settle(block=False)
            eval_start = time.perf_counter()
            if observer is not None:
                observer({"kind": "candidate", "round": round_index,
                          "evaluations": len(records),
                          "topology": space.topology(batch[0]).id,
                          "values": space.values(batch[0]), "source": sources[0]})
            handle = evaluator.submit(space, batch, load_pf=load_pf, vdd=vdd, rules=rules)
            if (
                s.surrogate
                and gp.state is not None
                and refit is None
                and round_index % s.refit_every == 0
            ):
                refit = refitter.submit(
                    _refit, *data(s.fit_points), gp.state["raw"].clone(), s.gp_steps, s.threads
                )
            measured = evaluator.gather(handle)
            timing["evaluate"] += time.perf_counter() - eval_start
            at = time.perf_counter() - start
            for design, record, source in zip(batch, measured, sources, strict=True):
                record.update(
                    round=round_index,
                    source=source,
                    elapsed_seconds=at,
                    objective=objective(record, target),
                    design=[design[0], list(design[1])],
                )
                visited.add(design)
                design_indices[design] = len(records)
                designs.append(design)
                records.append(record)
                outputs.append(model_outputs(record))
                scores.append(float(_score_numpy([_outputs(record)])[0]))
            settle(block=True)
            best = state["best"]
            threshold = -np.inf if best is None else best["objective"]
            contenders = sorted(
                (
                    (r["objective"], d)
                    for d, r in zip(batch, measured, strict=True)
                    if r["valid"] and r["objective"] is not None and r["objective"] > threshold
                ),
                key=lambda c: -c[0],
            )[: s.verify_top]
            if contenders:
                chosen = [d for _, d in contenders]
                futures = evaluator.submit(
                    space, chosen, strict=True, load_pf=load_pf, vdd=vdd, rules=rules
                )
                stamps = {}
                for future in futures:
                    future.add_done_callback(
                        lambda f, stamps=stamps: stamps.__setitem__(id(f), time.perf_counter())
                    )
                pending.append((round_index, chosen, futures, stamps))
            rounds.append(
                {
                    "round": round_index,
                    "elapsed_seconds": time.perf_counter() - start,
                    "sources": sources,
                    "best": None if state["best"] is None else state["best"]["objective"],
                }
            )
            if observer is not None:
                observer({"kind": "round", "round": round_index,
                          "evaluations": len(records), "verifications": len(strict_records),
                          "best": state["best"]})
            if stop_after_verified and state["best"] is not None:
                break
        settle(block=True)
        best, first = state["best"], state["first"]
        wall = time.perf_counter() - start
        if refitter is not None:
            refitter.shutdown(wait=True, cancel_futures=True)
        torch.set_num_threads(threads)
        return {
            "method": ("chipjev" if prior is not None else "chipjev-no-prior")
            + ("" if s.surrogate else "-nogp"),
            "cls": cls,
            "target": target,
            "load_pf": load_pf,
            "vdd": vdd,
            "rules": rules,
            "settings": asdict(s),
            "device": device_info(gp.device),
            "acquisition_dtype": str(gp.dtype).replace("torch.", ""),
            "wide_kernel": gp.wide,
            "topologies": len(space.topologies),
            "starts": starts[: s.batch],
            "typed_prior": prior is not None,
            "verified": best is not None,
            "first_verified": first,
            "best": None
            if best is None
            else {
                "topology": best["topology"],
                "values": best["values"],
                "metrics": best["metrics"],
                "objective": best["objective"],
                "reported": reported(best, target),
                "seconds": best["elapsed_seconds"],
                "qualification": best.get("qualification"),
            },
            "evaluations": len(records),
            "verifications": len(strict_records),
            "false_passes": sum(1 for r in strict_records if not r["valid"]),
            "wall_seconds": wall,
            "timing": timing,
            "rounds": rounds,
            "records": [_compact(r) for r in records],
            "strict": [_compact(r) for r in strict_records],
        }


def warm(device=None, classes=()):
    """Create the accelerator context, load every lazily imported module (optimizer, linear
    algebra) and compile the Thompson kernel for each class's feature count before any
    timed run."""
    import torch

    from ..surrogate.gp import synchronize

    rng = np.random.default_rng(0)
    for dimension in sorted({6} | {ClassSpace(c).dimension for c in classes}):
        gp = TopoGP(device, seed=0).fit(rng.random((24, dimension)), rng.random((24, 7)), 3)
        gp.fit(rng.random((24, dimension)), rng.random((24, 7)), 0)
        x = torch.as_tensor(rng.random((64, dimension)), device=gp.device, dtype=gp.dtype)
        gp.predict_mean(x)
        gp.thompson(Points(x), samples=7, score=lambda v: v[..., 0], top=2)
        synchronize(gp.device)


def _incumbents(designs, ranked, top_k, per_topology, depth=0):
    """The `top_k` best designs in `ranked` order: the first `depth` regardless of their
    topology (depth on the leading topologies), then at most `per_topology` per topology
    (0: no cap). Capping keeps the neighbourhood search on the best design of several
    topologies, including the least-violating designs of topologies that have no feasible
    design yet, instead of collapsing onto the first feasible topology."""
    chosen, count = [], {}
    for k in ranked:
        topology = designs[k][0]
        if len(chosen) >= depth and per_topology and count.get(topology, 0) >= per_topology:
            continue
        chosen.append(designs[k])
        count[topology] = count.get(topology, 0) + 1
        if len(chosen) == top_k:
            break
    return chosen


def _refit(x, y, raw, steps, threads):
    """Hyperparameters fitted from `raw` on a private GP; returns (raw, seconds)."""
    from ..surrogate.gp import BatchedGP

    start = time.perf_counter()
    tuner = BatchedGP("cpu", fused=False, fit_threads=threads)
    tuner.state = {"raw": raw}
    tuner.fit(x, y, steps=steps)
    return tuner.state["raw"], time.perf_counter() - start


def _decoder(topologies, levels, source):
    def decode(j):
        design = (int(topologies[j].item()), tuple(int(x) for x in levels[j].cpu().tolist()))
        return design, source

    return decode


# Surrogate outputs: objective, then constraint margins with their scales (>= 0 means
# satisfied), then structural validity (bias found, function, bandwidth, power and, under
# the physical rules, saturation and open-loop settling) as +/-1.
MARGINS = (
    ("gain_db", 10.0),
    ("pm_deg", 30.0),
    ("current_decades", 0.5),
    ("region_v", 0.1),
    ("cmrr_db", 20.0),
)
STRUCTURAL = (
    "bias_found",
    "function",
    "bandwidth",
    "power",
    "saturation",
    "settles",
    "closed_loop",
)


def _outputs(record):
    margins = record.get("margins") or {}
    row = [np.nan if record.get("objective") is None else record["objective"]]
    for name, _ in MARGINS:
        value = margins.get(name)
        row.append(np.nan if value is None or not np.isfinite(value) else value)
    checks = record.get("checks") or {}
    ok = bool(checks) and all(checks.get(c, True) for c in STRUCTURAL)
    row.append(1.0 if ok else -1.0)
    return row


def _score_numpy(values):
    """Feasible designs score 100 + objective; others their worst scaled margin."""
    values = np.asarray(values, dtype=float)
    scaled = [values[:, 1 + j] / scale for j, (_, scale) in enumerate(MARGINS)]
    scaled.append(values[:, 1 + len(MARGINS)])
    worst = np.nanmin(np.where(np.isnan(np.stack(scaled)), -np.inf, np.stack(scaled)), axis=0)
    objective = np.nan_to_num(values[:, 0], nan=-np.inf)
    return np.where(worst >= 0, 100.0 + objective, np.maximum(worst, -1e3))


def _score_torch(values, scales):
    """_score_numpy on the device; `scales` holds the margin scales and 1 (structural)."""
    import torch

    worst = (values[..., 1:] / scales).min(-1).values
    return torch.where(worst >= 0, 100.0 + values[..., 0], worst.clamp_min(-1e3))


def _training_indices(records, scores, cap):
    """At most `cap` records: the best half by observed score plus the most recent."""
    n = len(records)
    if n <= cap:
        return list(range(n))
    keep = set(sorted(range(n), key=lambda k: -scores[k])[: cap // 2])
    for k in range(n - 1, -1, -1):
        if len(keep) >= cap:
            break
        keep.add(k)
    return sorted(keep)


def _compact(record):
    keep = (
        "topology",
        "design",
        "round",
        "source",
        "valid",
        "checks",
        "metrics",
        "margins",
        "error",
        "objective",
        "simulator_seconds",
        "wall_seconds",
        "elapsed_seconds",
        "strict",
        "qualification",
    )
    return {k: record[k] for k in keep if k in record}
