"""Persistent pool of ngspice measurement workers shared by ChipJev and the baselines.

Every method measures a design through ``_measure`` in a worker process. The technology is
an argument of the pool: each worker resolves the testbench's ``evaluate`` once, when it
starts (PTM 45 nm: simulation/ptm45.py; SKY130: simulation/sky130.py at a process corner),
so every method runs unchanged and identically on either technology; SKY130 records carry
``technology = "sky130-<corner>"``. Workers are spawned (identical on Linux and macOS).
"""

import functools
import multiprocessing
import os
import threading
from collections import Counter
from concurrent.futures import ProcessPoolExecutor

from ..circuits.grammar import VDD
from ..simulation.analysis import LOAD_PF

__all__ = ["TECHNOLOGIES", "Evaluator", "Tally"]

TECHNOLOGIES = ("ptm45", "sky130")


def evaluate_function(technology="ptm45", corner="tt"):
    """The testbench's ``evaluate`` for a technology (and SKY130 process corner)."""
    if technology == "ptm45":
        from ..simulation.ptm45 import evaluate

        return evaluate
    if technology == "sky130":
        from ..simulation import sky130

        return functools.partial(sky130.evaluate, corner=corner)
    raise ValueError(f"unknown technology {technology!r}")


_EVALUATE = None  # set in each worker by _worker_init (PTM 45 nm when unset)
_TOPOLOGIES = {}


def _worker_init(technology="ptm45", corner="tt", options=None):
    global _EVALUATE
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[name] = "1"
    _EVALUATE = evaluate_function(technology, corner)
    if options:
        _EVALUATE = functools.partial(_EVALUATE, **options)


def _measure(args):
    cls, topology_id, values, strict, load_pf, vdd, rules = args
    from ..circuits.published import lookup

    key = (cls, topology_id)
    if key not in _TOPOLOGIES:
        _TOPOLOGIES[key] = lookup(cls, topology_id)
    evaluate = _EVALUATE or evaluate_function()
    return evaluate(_TOPOLOGIES[key], values, strict=strict, load_pf=load_pf, vdd=vdd, rules=rules)


def _warm(_):
    return os.getpid()


class Tally:
    """Counts of measured records (online/strict, errors, simulator time-outs)."""

    def __init__(self):
        self.lock = threading.Lock()
        self.counts = Counter()

    def observe(self, record):
        if not isinstance(record, dict) or "valid" not in record:
            return
        kind = "strict" if record.get("strict") else "online"
        error = record.get("error") or ""
        with self.lock:
            self.counts[f"{kind}_records"] += 1
            self.counts[f"{kind}_errors"] += bool(error)
            self.counts[f"{kind}_timeouts"] += error == "simulator timeout"
            self.counts[f"{kind}_valid"] += bool(record.get("valid"))
            self.counts[f"{kind}_simulator_seconds"] += record.get("simulator_seconds") or 0.0

    def take(self):
        with self.lock:
            counts, self.counts = dict(self.counts), Counter()
        return counts


class _CountingPool:
    """The worker pool; ``map`` counts the records it returns (joint TPE measures through
    ``evaluator.pool.map``), futures from ``submit`` are counted by ``Evaluator.gather``."""

    def __init__(self, pool, tally):
        self._pool, self._tally = pool, tally

    def map(self, fn, *iterables, **kwargs):
        results = list(self._pool.map(fn, *iterables, **kwargs))
        for result in results:
            self._tally.observe(result)
        return results

    def submit(self, fn, *args, **kwargs):
        return self._pool.submit(fn, *args, **kwargs)

    def shutdown(self, *args, **kwargs):
        return self._pool.shutdown(*args, **kwargs)


class Evaluator:
    """Persistent pool of `workers` measurement processes on `technology` ("ptm45" or
    "sky130" at `corner`); ``tally`` counts the records of every method (reset with
    ``tally.take()``)."""

    def __init__(self, workers, technology="ptm45", corner="tt", evaluate_options=None):
        if technology not in TECHNOLOGIES:
            raise ValueError(f"unknown technology {technology!r}")
        self.technology, self.corner = technology, corner
        self.tally = Tally()
        context = multiprocessing.get_context("spawn")
        pool = ProcessPoolExecutor(workers, mp_context=context, initializer=_worker_init,
                                   initargs=(technology, corner, evaluate_options))
        list(pool.map(_warm, range(workers)))
        self.pool = _CountingPool(pool, self.tally)

    def submit(self, space, designs, strict=False, load_pf=LOAD_PF, vdd=VDD, rules="qualified"):
        """Start measuring `designs`; `gather` the returned handle for the records."""
        return [
            self.pool.submit(
                _measure,
                (space.cls, space.topology(d).id, space.values(d), strict, load_pf, vdd, rules),
            )
            for d in designs
        ]

    def gather(self, handle):
        records = [future.result() for future in handle]
        for record in records:
            self.tally.observe(record)
        return records

    def map(self, space, designs, strict=False, load_pf=LOAD_PF, vdd=VDD, rules="qualified"):
        return self.gather(self.submit(space, designs, strict, load_pf, vdd, rules))

    def close(self):
        self.pool.shutdown(wait=True, cancel_futures=True)
