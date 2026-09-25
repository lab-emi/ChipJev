"""ngspice testbenches (PTM 45 nm, SKY130) and the robustness checks."""

import shutil

import numpy as np
import pytest

from chipjev.circuits.grammar import Topology, default_values, library
from chipjev.paths import ngspice
from chipjev.simulation import analysis, ptm45

OTA = Topology("opamp1", ("ota5_n",))


def _need_ngspice():
    if not shutil.which(ngspice()):
        pytest.skip("ngspice not installed (scripts/setup.sh builds it into .tools/bin)")


@pytest.mark.integration
def test_ptm45_measures_a_five_transistor_ota(tmp_path):
    _need_ngspice()
    values = {"1.in": 64, "1.ld": 32, "1.tail": 64, "1.L": 360, "1.vt": 0.45}
    record = ptm45.evaluate(OTA, values, tmp_path, rules="physical")
    assert record["error"] is None
    m = record["metrics"]
    assert 30 < m["gain_db"] < 60
    assert m["gbw_mhz"] > 0 and m["power_uw"] > 0
    assert m["pm_deg"] > 60
    assert m["settle_v"] < analysis.SETTLE_V
    assert record["checks"]["saturation"] and record["checks"]["settles"]
    assert m["gbw_mhz"] <= m["gbw_def_mhz"]
    assert record["valid"]
    strict = ptm45.evaluate(OTA, values, tmp_path / "strict", strict=True, rules="physical")
    assert strict["valid"]
    assert strict["metrics"]["gain_db"] == pytest.approx(m["gain_db"], abs=0.5)
    # The published rules drop the added requirements (and the stability run).
    loose = ptm45.evaluate(OTA, values, tmp_path / "loose", rules="published")
    assert "saturation" not in loose["checks"] and "stability" not in loose["checks"]
    assert loose["metrics"]["gbw_mhz"] == pytest.approx(m["gbw_def_mhz"], rel=1e-6)


@pytest.mark.integration
def test_triode_tail_fails_the_physical_rules(tmp_path):
    _need_ngspice()
    values = {"1.in": 32, "1.ld": 32, "1.tail": 32, "1.L": 180, "1.vt": 0.6}
    record = ptm45.evaluate(OTA, values, tmp_path, rules="physical")
    assert not record["checks"]["saturation"] and not record["valid"]
    assert ptm45.evaluate(OTA, values, tmp_path / "p", rules="published")["valid"]


@pytest.mark.integration
def test_qualified_ota_tracks_both_buffer_step_directions(tmp_path):
    _need_ngspice()
    values = {"1.in": 64, "1.ld": 32, "1.tail": 64, "1.L": 360, "1.vt": 0.45}
    record = ptm45.evaluate(OTA, values, tmp_path, strict=True)
    assert record["valid"], record
    checks = record["qualification"]
    assert [s["direction"] for s in checks["steps"]] == [1, -1]
    assert checks["max_gain_error"] < 0.02
    assert checks["max_dc_error_v"] < 0.01


def test_sky130_deck_uses_pdk_devices_and_probes():
    from chipjev.simulation.sky130 import deck

    topology = library("opampN")[0]
    try:
        text, builder = deck(topology, default_values(topology))
    except FileNotFoundError:
        pytest.skip("SKY130 models are not installed")
    assert ".option scale=1u wnflag=1" in text
    assert "sky130_fd_pr__nfet_01v8" in text and "sky130_fd_pr__pfet_01v8" in text
    assert "@m.xm1.msky130_fd_pr__" in text
    assert all(line.startswith("xm") for line in builder.lines if "fet_01v8" in line)
    # Bulks at the rails: NMOS to ground, PMOS to VDD.
    for line in builder.lines:
        if "nfet_01v8" in line:
            assert line.split()[4] == "0"
        if "pfet_01v8" in line:
            assert line.split()[4] == "vdd"


@pytest.mark.integration
def test_sky130_evaluation_measures_a_textbook_amplifier():
    from chipjev.simulation.sky130 import evaluate, ngspice

    if shutil.which(ngspice()) is None:
        pytest.skip("ngspice is not installed")
    topology = next(t for t in library("amp1") if t.id == "r_n")
    try:
        record = evaluate(topology, default_values(topology), vdd=1.8)
    except FileNotFoundError:
        pytest.skip("SKY130 models are not installed")
    if record["error"] and "SKY130" in record["error"]:
        pytest.skip("SKY130 models are not installed")
    assert record["technology"] == "sky130-tt"
    assert record["error"] is None
    assert record["metrics"]["gain_db"] > 10
    assert 0.5 < record["metrics"]["vout_dc"] < 1.3


def test_mismatch_shift_is_applied_to_every_transistor():
    from chipjev.circuits.published import lookup
    from chipjev.simulation.robustness import Shifted, device_areas

    topology = lookup("opampN", "ota5_n+cs_p+miller")
    values = default_values(topology)
    areas = device_areas(topology, values, 1.2)
    shifted = Shifted(topology, np.arange(len(areas)) * 1e-3).build(values, 1.2)
    lines = [line for line in shifted.lines if line.startswith("m")]
    assert len(lines) == len(areas) and all("delvto=" in line for line in lines)

