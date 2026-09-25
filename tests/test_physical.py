"""Real physical verification, including negative controls for cosmetic wiring."""

import json
import shutil
from concurrent.futures import Future
from pathlib import Path

import pytest

from chipjev.circuits.grammar import default_values
from chipjev.circuits.published import lookup
from chipjev.circuits.sky130_devices import build
from chipjev.layout.magic import primitive_specs, readiness, run_magic, synthesize
from chipjev.layout.verification import ExtractedCircuit, extract_rc, lvs, spice_number
from demo.design import LayoutEvaluator


def test_physical_grid_and_parallel_fingers():
    top = lookup("opamp1", "ota5_p")
    builder = build(top, {"1.vt": 0.63, "1.L": 509, "1.in": 500, "1.ld": 15.6, "1.tail": 66.1})
    specs, _, geometry = primitive_specs(builder)
    for name, entry in geometry.items():
        width, length, count = entry["drawn"]
        assert count == builder.geometry[name][2]
        assert width / count <= 50.01
        assert length >= 0.15
        assert sum(s["logical"] == name for s in specs) == count
        assert abs(width / count / 0.01 - round(width / count / 0.01)) < 1e-8


def test_spice_units():
    assert spice_number("3.2fF") == pytest.approx(3.2e-15)
    assert spice_number("1.5meg") == 1.5e6
    assert spice_number("1e-9") == 1e-9
    with pytest.raises(ValueError):
        spice_number("garbage")


def test_headroom_future_preserves_errors_and_missing_metrics(monkeypatch):
    from chipjev.search.evaluator import Evaluator

    source = Future()
    monkeypatch.setattr(Evaluator, "submit", lambda *a, **k: [source])
    evaluator = object.__new__(LayoutEvaluator)
    handle = evaluator.submit(None, None)
    assert not handle[0].done()
    record = {
        "valid": False,
        "cls": "opamp1",
        "metrics": {"gain_db": None},
        "checks": {},
        "margins": {"gain_db": None},
    }
    source.set_result(record)
    assert handle[0].done() and not handle[0].result()["valid"]


@pytest.mark.integration
@pytest.mark.parametrize(
    "cls,tid",
    [("opamp1", "ota5_p"), ("opampN", "ota5_n+inv_cas"), ("opampN", "cmota_p+inv_cas+miller_rz")],
)
def test_real_magic_drc_lvs_rc_and_gds_roundtrip(tmp_path, cls, tid):
    if missing := readiness():
        pytest.skip(str(missing))
    top = lookup(cls, tid)
    values = default_values(top)
    layout = synthesize(top, values, tmp_path / "source")
    source = tmp_path / "source"
    assert layout["drc_errors"] == 0
    assert lvs(source)["passed"]
    pex = extract_rc(source)
    assert pex["resistors"] > 0 and pex["capacitors"] > 0
    ExtractedCircuit(build(top, values), source / "pex.spice")
    assert (source / "layout.gds").stat().st_size > 1000
    # Re-import the delivered GDS and check its extracted netlist independently.
    target = tmp_path / "roundtrip"
    target.mkdir()
    shutil.copy2(source / "reference.spice", target / "reference.spice")
    run_magic(
        target,
        f"""gds read {{{source / "layout.gds"}}}
load layout
select top cell
port makeall
extract unique
extract all
ext2spice lvs
ext2spice scale off
ext2spice -o lvs.spice
""",
        "roundtrip",
    )
    assert lvs(target)["passed"]
    # Device tampering must be detected even if D/G/S connectivity is unchanged.
    text = (source / "pex.spice").read_text()
    (source / "pex.spice").write_text(text.replace("w=", "w=9", 1))
    with pytest.raises(ValueError, match="geometry"):
        ExtractedCircuit(build(top, values), source / "pex.spice")
    # Labels do not stand in for conductors: removing M2 must fail LVS.
    text = (source / "layout.mag").read_text()
    start = text.index("<< metal2 >>")
    end = text.index("<<", start + 3)
    (source / "layout.mag").write_text(text[:start] + text[end:])
    run_magic(
        source,
        """load layout
select top cell
extract unique
extract all
ext2spice lvs
ext2spice scale off
ext2spice -o lvs.spice
""",
        "disconnected",
    )
    assert not lvs(source)["passed"]


def test_physical_result_requires_all_gates():
    # Archived evidence is checked without needing a GPU, toolchain or internet.
    root = Path(__file__).resolve().parents[1] / "experiments/layout/results"
    paths = list(root.glob("*/result.json"))
    if not paths:
        pytest.skip("Physical demonstration evidence has not been generated")
    for path in paths:
        result = json.loads(path.read_text())
        physical = result["physical"]
        assert result["valid"] and physical["valid"]
        assert physical["layout"]["drc_errors"] == 0
        assert physical["lvs"]["passed"]
        assert physical["postlayout"]["valid"]
        assert physical["pex"]["resistors"] > 0 and physical["pex"]["capacitors"] > 0
