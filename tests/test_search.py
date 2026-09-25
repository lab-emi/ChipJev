"""The measurement worker pool: record counting and the technology of every worker."""

import shutil

import pytest

from chipjev.circuits.space import ClassSpace
from chipjev.paths import ngspice
from chipjev.search.evaluator import Evaluator, Tally, evaluate_function


def test_tally_counts_timeouts_per_kind():
    tally = Tally()
    tally.observe({"valid": False, "strict": False, "error": "simulator timeout",
                   "simulator_seconds": 2.0})
    tally.observe({"valid": True, "strict": False, "error": None, "simulator_seconds": 0.1})
    tally.observe({"valid": True, "strict": True, "error": None, "simulator_seconds": 0.3})
    tally.observe(1234)  # worker warm-up results are ignored
    counts = tally.take()
    assert counts["online_records"] == 2 and counts["online_timeouts"] == 1
    assert counts["online_valid"] == 1 and counts["strict_records"] == 1
    assert tally.take() == {}


def test_unknown_technology_is_rejected():
    with pytest.raises(ValueError):
        evaluate_function("gf180")
    with pytest.raises(ValueError):
        Evaluator(1, technology="gf180")


@pytest.mark.integration
def test_workers_measure_on_the_requested_technology():
    if not shutil.which(ngspice()):
        pytest.skip("ngspice not installed")
    space = ClassSpace("amp1")
    design = space.canonical("cs_n")
    for technology, vdd in (("ptm45", 1.2), ("sky130", 1.8)):
        evaluator = Evaluator(1, technology=technology)
        try:
            (record,) = evaluator.map(space, [design], vdd=vdd)
        finally:
            evaluator.close()
        if technology == "sky130" and record.get("error") and "SKY130" in record["error"]:
            pytest.skip("SKY130 models are not installed")
        assert record.get("technology", "ptm45") == ("sky130-tt" if technology == "sky130"
                                                     else "ptm45")
