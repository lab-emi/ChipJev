"""Physical intent, independent device integrity, measured feedback and negative controls."""

import json

import numpy as np
import pytest

from chipjev.circuits.published import lookup
from chipjev.circuits.sky130_devices import build
from chipjev.layout.intent import derive
from chipjev.layout.magic import readiness, rectangles
from chipjev.layout.plan import LayoutPlan, arrangement
from chipjev.layout.quality import assess
from chipjev.layout.verification import ExtractedCircuit, verify
from chipjev.paths import ROOT
from chipjev.search.layout import LayoutGoal
from chipjev.simulation.analog import AnalogConditions, measure
from chipjev.simulation.sky130 import deck


def example():
    record = json.loads((ROOT / "experiments/layout/results/opamp-speed/result.json").read_text())
    return (
        lookup(record["cls"], record["topology"]),
        record["values"],
        record["physical"]["prelayout"],
    )


def test_native_and_scaled_magic_coordinates_are_identical(tmp_path):
    native = tmp_path / "native.mag"
    scaled = tmp_path / "scaled.mag"
    native.write_text("magic\ntech sky130A\n<< metal1 >>\nrect -7 0 25 50\n<< end >>\n")
    scaled.write_text(
        "magic\ntech sky130A\nmagscale 1 2\n<< metal1 >>\nrect -14 0 50 100\n<< end >>\n"
    )
    assert rectangles(native) == rectangles(scaled) == {"metal1": [(-14, 0, 50, 100)]}
    scaled.write_text(scaled.read_text().replace("magscale 1 2", "magscale 1 3"))
    with pytest.raises(ValueError, match="grid"):
        rectangles(scaled)


def test_intent_needs_connectivity_and_equal_geometry():
    top, values, _ = example()
    builder = build(top, values)
    intent = derive(builder)
    pair = next(g for g in intent["groups"] if g["role"] == "input_pair")
    a, b = pair["members"]
    assert builder.geometry[a] == builder.geometry[b]
    builder.geometry[a] = (builder.geometry[a][0] * 2, *builder.geometry[a][1:])
    assert not any(g["role"] == "input_pair" for g in derive(builder)["groups"])


@pytest.mark.parametrize("count", [2, 4, 10, 24])
def test_centroid_pattern_conserves_units_and_first_spatial_moments(count):
    a, b = [f"a{i}" for i in range(count)], [f"b{i}" for i in range(count)]
    rows = arrangement(a, b, "centroid", 8)
    assert sorted(n for row in rows for n in row) == sorted(a + b)
    centers = [
        np.mean(
            [(x, y) for y, row in enumerate(rows) for x, n in enumerate(row) if n[0] == prefix],
            axis=0,
        )
        for prefix in ("a", "b")
    ]
    assert np.allclose(*centers)


def test_invalid_and_ineffective_plans_are_masked():
    top, values, _ = example()
    builder = build(top, values)
    with pytest.raises(ValueError, match="even"):
        LayoutPlan(pattern="centroid").validate(builder, derive(builder))
    LayoutPlan(pattern="centroid", split=2).validate(builder, derive(builder))
    assert not any(a == "decap_location" for a, _ in LayoutPlan().neighbors())
    with pytest.raises(ValueError, match="boolean"):
        LayoutPlan(dummies="true")


def test_unknown_or_unmeasured_goals_cannot_pass():
    with pytest.raises(ValueError):
        LayoutGoal(maximum={"noise": 1})
    with pytest.raises(ValueError):
        LayoutGoal(maximum={"area_um2": float("nan")})
    with pytest.raises(ValueError):
        AnalogConditions(noise_high_hz=1.0)
    result = {
        "postlayout": {"metrics": {}},
        "quality": {},
        "analog": {"status": "measured", "metrics": {}},
        "valid": True,
        "layout": {"plan": {"dummies": True}},
    }
    assert not all(LayoutGoal(maximum={"input_noise_rms_v": 1e-4}).qualify(result).values())
    result["valid"] = False
    assert not all(LayoutGoal().qualify(result).values())


def test_fixed_bias_deck_has_no_hidden_recalibration(monkeypatch):
    monkeypatch.setattr("chipjev.simulation.sky130.include_text", lambda *a, **kw: "* PDK includes")
    top, values, _ = example()
    text, _ = deck(top, values, input_bias=0.85, mismatch_seed=10)
    assert "set vbest = 0.85" in text
    assert ".options seed=11 seedinfo" in text
    assert "dc vcm" not in text


def test_layout_model_sees_latest_failure_before_long_background():
    from chipjev.decisions.layout import state_text
    state = {
        "goal": {"objective": "area", "minimum": {}, "maximum": {"internal_supply_drop_v": .01}},
        "history": [{"plan": LayoutPlan().to_dict(), "valid": False,
                     "checks": {"max:internal_supply_drop_v": False},
                     "metrics": {"internal_supply_drop_v": .02}, "quality": {"area_um2": 100}}],
        "groups": [{"role": "input_pair", "reason": "long background "*100}]*10,
        "technology": "sky130-analog-1", "fixed_input_bias_v": .85, "remaining_seconds": 20,
    }
    text = state_text(state)
    assert "max:internal_supply_drop_v" in text[:100]
    assert "internal_supply_drop_v=0.02" in text[:200]
    assert "long background" not in text
    state["history"][-1].update(metrics=None, quality=None, checks=None, error="DRC failed")
    assert "DRC failed" in state_text(state)


@pytest.fixture(scope="module")
def compact(tmp_path_factory):
    if missing := readiness():
        pytest.skip(str(missing))
    top, values, pre = example()
    directory = tmp_path_factory.mktemp("professional")
    result = verify(
        top,
        values,
        directory,
        plan=LayoutPlan(columns=1, fingers_per_row=20),
        prelayout=pre,
        input_bias=pre["metrics"]["vin_dc"],
    )
    return top, values, pre, directory, result


@pytest.mark.integration
def test_compact_geometry_reference_and_rc_are_consistent(compact):
    top, values, _, directory, result = compact
    assert result["valid"] and result["layout"]["drc_errors"] == 0 and result["lvs"]["passed"]
    circuit = ExtractedCircuit(build(top, values), directory / "pex.spice")
    quality = assess(result["layout"], directory, circuit)
    assert len(quality["matching"]) == 2 and quality["net_capacitance_ff"]["inp"] > 0
    # A declared reference-size error must fail even when Netgen normalizes W/L.
    reference = directory / "reference.spice"
    original = reference.read_text()
    reference.write_text(original.replace("w=", "w=9", 1))
    try:
        with pytest.raises(ValueError, match="declared implementation"):
            ExtractedCircuit(build(top, values), directory / "pex.spice")
    finally:
        reference.write_text(original)
    # Removing a dummy declaration cannot silently remove it from qualification.
    manifest = directory / "manifest.json"
    original = manifest.read_text()
    data = json.loads(original)
    del data["devices"][next(k for k, v in data["devices"].items() if v["auxiliary"])]
    manifest.write_text(json.dumps(data))
    try:
        with pytest.raises(ValueError, match="associate|dummy"):
            ExtractedCircuit(build(top, values), directory / "pex.spice")
    finally:
        manifest.write_text(original)


@pytest.mark.integration
def test_noise_and_seeded_pdk_mismatch_are_reproducible(compact, tmp_path):
    top, values, pre, directory, _ = compact
    circuit = ExtractedCircuit(build(top, values), directory / "pex.spice")
    results = [
        measure(
            top, circuit, tmp_path / str(i), input_bias=pre["metrics"]["vin_dc"], mismatch_seed=seed
        )
        for i, seed in enumerate((11, 11, 22))
    ]
    assert all(r["status"] == "measured" for r in results)
    assert results[0]["metrics"] == results[1]["metrics"]
    assert results[0]["metrics"]["input_offset_v"] != results[2]["metrics"]["input_offset_v"]
    assert all(r["metrics"]["input_noise_rms_v"] > 0 for r in results)


@pytest.mark.integration
@pytest.mark.parametrize("decap,multiplier", [(5.0, 1), (0.0, 3)])
def test_tiled_decap_is_real_connected_and_included_in_lvs(compact, tmp_path, decap, multiplier):
    top, values, pre, _, _ = compact
    result = verify(
        top,
        values,
        tmp_path,
        plan=LayoutPlan(columns=1, decap_pf=decap, rail_multiplier=multiplier),
        prelayout=pre,
        input_bias=pre["metrics"]["vin_dc"],
    )
    assert result["valid"] and result["lvs"]["passed"] and result["layout"]["drc_errors"] == 0
    assert ("cdecap" in (tmp_path / "reference.spice").read_text()) == bool(decap)
    circuit = ExtractedCircuit(build(top, values), tmp_path / "pex.spice")
    bench = measure(top, circuit, tmp_path / "analog", input_bias=pre["metrics"]["vin_dc"])
    assert bench["status"] == "measured"
    assert bench["conditions"]["supply_resistance_ohm"] > 0
    assert bench["metrics"]["supply_early_droop_v"] > 0


def test_grid_profile_matches_compiler_without_changing_legacy_builder():
    from chipjev.circuits.sky130_devices import build_on_grid
    from chipjev.layout.magic import primitive_specs

    top, values, _ = example()
    original = build(top, values)
    snapped = build_on_grid(top, values)
    _, _, geometry = primitive_specs(original)
    assert any(snapped.geometry[n] != original.geometry[n] for n in original.geometry)
    for name, (_, _, nf) in snapped.geometry.items():
        assert snapped.geometry[name] == pytest.approx(geometry[name]["drawn"])
        assert nf == original.geometry[name][2]


@pytest.mark.integration
def test_delivered_gds_roundtrip_preserves_connectivity(compact, tmp_path):
    import shutil

    from chipjev.layout.magic import run_magic
    from chipjev.layout.verification import lvs

    _, _, _, source, _ = compact
    shutil.copy2(source / "reference.spice", tmp_path / "reference.spice")
    run_magic(
        tmp_path,
        f"""gds read {{{source / "layout.gds"}}}
load layout
select top cell
port makeall
drc euclidean on
drc style drc(full)
drc on
drc check
drc catchup
puts "@@ROUNDTRIP [drc list count total]"
extract unique
extract all
ext2spice lvs
ext2spice scale off
ext2spice -o lvs.spice
""",
        "roundtrip",
    )
    assert "@@ROUNDTRIP 0" in (tmp_path / "roundtrip.log").read_text()
    assert lvs(tmp_path)["passed"]


def test_preference_data_requires_human_labels_and_family_holdout(tmp_path):
    from chipjev.decisions.layout_preferences import examples

    row = {
        "family": "a",
        "design_identity": "id",
        "goal": {},
        "fixed_input_bias_v": 0.9,
        "candidates": {n: {"plan": LayoutPlan().to_dict(), "valid": True} for n in ("a0", "a1")},
        "label_source": "unreviewed",
        "preferred": None,
    }
    p = tmp_path / "reviews.jsonl"
    p.write_text(json.dumps(row) + "\n")
    with pytest.raises(ValueError, match="explicit"):
        examples([p], {"b"})
    row.update(
        label_source="expert", preferred="a0", reviewer="test reviewer", reason="test annotation"
    )
    p.write_text(
        json.dumps(row)
        + "\n"
        + json.dumps({**row, "family": "b", "design_identity": "different"})
        + "\n"
    )
    train, test = examples([p], {"b"})
    assert len(train) == len(test) == 1
    p.write_text(json.dumps(row) + "\n" + json.dumps({**row, "family": "b"}) + "\n")
    with pytest.raises(ValueError, match="cross family"):
        examples([p], {"b"})


def test_legacy_mode_cannot_silently_ignore_robustness_request(tmp_path):
    from chipjev.cli import main

    with pytest.raises(ValueError, match="Legacy"):
        main(
            [
                "layout",
                str(tmp_path / "unused.json"),
                "--output",
                str(tmp_path / "out"),
                "--legacy",
                "--corners",
                "tt",
                "ss",
            ]
        )
