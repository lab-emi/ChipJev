"""Professional template generator: structure, integrity, knowledge cards and EDA checks."""

import json
from pathlib import Path

import pytest

from chipjev.circuits.grammar import default_values
from chipjev.circuits.published import lookup
from chipjev.circuits.sky130_devices import build
from chipjev.layout.magic import readiness
from chipjev.layout.pro import tech as T
from chipjev.layout.pro.analysis import analyse
from chipjev.layout.pro.canvas import Canvas
from chipjev.layout.pro.integrity import validate
from chipjev.layout.pro.knowledge import CARDS, retrieve, review
from chipjev.layout.pro.mos import ArraySpec, Finger, MosArray
from chipjev.layout.pro.planner import (
    ProPlan,
    faithful,
    orient,
    pair_sequence,
    plan_units,
    segments,
)
from chipjev.paths import ROOT


def design(name):
    record = json.loads((ROOT / f"experiments/layout/results/{name}/result.json").read_text())
    return lookup(record["cls"], record["topology"]), record["values"]


def circuit(topology_id, cls="opamp1"):
    topology = lookup(cls, topology_id)
    builder = build(topology, default_values(topology))
    return topology, builder, analyse(builder, topology)


def test_pairs_and_symmetric_nets_grow_through_cascode_stacks():
    _, _, c = circuit("tele_n")
    # Input pair, NMOS cascodes, PMOS cascodes and PMOS loads are all found,
    # although each cascode pair's symmetry is only implied by its neighbour.
    assert len(c.pairs) == 4
    assert c.mirror["a1"] == "a2" and c.mirror["c1"] == "c2" and c.mirror["x1"] == "out"
    assert c.level[c.pairs[0][0]] == 1  # input pair sits one row in from the tail


def test_equal_sizing_alone_is_not_matching():
    _, builder, c = circuit("ota5_n")
    tail = next(n for n, m in c.devices.items() if m.g == "s1t")
    assert all(tail not in pair for pair in c.pairs)


def test_orientation_shares_diffusion_and_prefers_source_ends():
    terms = {"a": ("t1", "x1"), "b": ("t1", "out")}
    regions = orient(["a", "a", "b", "b", "b", "b", "a", "a"], terms, {"t1"})
    assert regions == ["t1", "x1", "t1", "out", "t1", "out", "t1", "x1", "t1"]
    # Two devices without a common net cannot share one diffusion.
    assert orient(["a", "b"], {"a": ("a1", "x1"), "b": ("a2", "out")}, set()) is None


def test_odd_finger_pairs_stay_interdigitated_with_shared_diffusion():
    terms = {"a": ("t1", "x1"), "b": ("t1", "out")}
    for count in (1, 2, 3, 5, 21):
        seq = ["a" if s == "A" else "b" for s in pair_sequence(count, "abba")]
        assert seq.count("a") == seq.count("b") == count
        # A..AB..BA..A could not share diffusion for odd counts: pairs fell back to A|B.
        assert orient(seq, terms, {"t1"}) is not None
        moment = {d: sum(i for i, s in enumerate(seq) if s == d) for d in "ab"}
        assert abs(moment["a"] - moment["b"]) == count % 2  # odd counts: the one-pitch minimum
    topology, values = design("ota-efficient")  # 21-finger input pair cut into [4,4,4,3,3,3]
    c = analyse(build(topology, values), topology)
    units = plan_units(c, ProPlan(), fold=1)
    assert next(u for u in units if set(u.devices) == set(c.pairs[0])).pattern == "abba"


def test_faithful_mode_keeps_the_simulated_finger():
    _, _, c = circuit("ota5_p")
    for m in c.devices.values():
        count, width, changed = faithful(m)
        assert count == m.nf and not changed
        assert abs(T.um(width) - m.w / m.nf) <= 0.005 + 1e-9


def test_tall_fingers_are_cut_into_latch_up_safe_segments():
    assert segments(9, 48.5, 2.4, pair=True) != [9]  # 50 um fingers need tap columns
    parts = segments(18, 49.9, 2.4, pair=True)
    assert sum(parts) == 18 and all((p * 2 + 2) * 2.69 + 0.29 <= 26.0 for p in parts)
    assert segments(6, 10.0, 0.5, pair=True) == [6]  # short fingers: one array


def test_plan_units_account_for_every_finger():
    topology, values = design("opamp-gain")
    builder = build(topology, values)
    c = analyse(builder, topology)
    units = plan_units(c, ProPlan())
    drawn = {}
    for unit in units:
        for row in unit.rows:
            for spec in row:
                for f in spec.fingers:
                    if f.kind == "active":
                        drawn[f.device] = drawn.get(f.device, 0) + 1
    assert drawn == {n: m.nf for n, m in c.devices.items()}


def test_knowledge_cards_are_injected_per_action_and_symptom():
    assert all(c.enforced for c in CARDS if c.id != "noise.isolated_well")
    stability = [c.id for c in retrieve("pair_pattern", ["stability", "pm"])]
    assert "passive.simple_when_fast" in stability or "closure.pm_loss" in stability
    assert [c.id for c in retrieve("rail_um", ["supply"])][0] == "power.stacked_rails"
    assert retrieve("no_such_field", ["pm"]) == []


def stub_evaluate(job, index=None):
    """Stand-in for the physical flow: the seed plan is the best layout; every move is worse."""
    directory, plan = Path(job[3]), job[4]
    directory.mkdir(parents=True, exist_ok=True)
    worse = plan != ProPlan().to_dict()
    (directory / "physical.json").write_text(json.dumps({"layout": {"plan_id": ProPlan(**plan).id}}))
    return {"valid": True, "drc": 0, "lvs": True, "metrics": {"gain_db": 60.0}, "checks": {},
            "area_um2": 110.0 if worse else 100.0, "critic": 60.0 if worse else 70.0, "findings": [],
            "symptoms": [], "seconds": 0.0}


@pytest.mark.parametrize("budget, patience, reason, evaluations, iterations", [
    (50, 2, "converged", 9, 3),   # seed, then two iterations of 4 without a better layout
    (6, 0, "evaluations", 6, 3),  # exact cap: the third iteration is trimmed to 1 layout
])
def test_layout_loop_stops_on_convergence_or_an_exact_budget(tmp_path, monkeypatch, budget, patience,
                                                            reason, evaluations, iterations):
    import chipjev.search.pro_layout as loop

    monkeypatch.setattr(loop, "_evaluate", stub_evaluate)
    topology, values = design("ota-efficient")
    result = loop.optimize_pro(topology, values, tmp_path / "loop", max_evaluations=budget,
                               patience=patience, budget_seconds=600, input_bias=0.9,
                               prelayout={"valid": True, "metrics": {"vin_dc": 0.9}}, log=lambda _: None)
    stop = result["optimization"]["stop"]
    assert (stop["reason"], stop["evaluations"], stop["iterations"]) == (reason, evaluations, iterations)
    assert len(result["optimization"]["history"]) == evaluations and stop["text"]


def test_a_failed_candidate_is_recorded_not_fatal_to_the_trace():
    from chipjev.search.pro_layout import objective, stored_objective

    # A RoutingSpace candidate has no metrics; its -inf objective once crashed the
    # whole demo run when optimization.json was written with allow_nan=False.
    failed = {"valid": False, "error": "RoutingSpace: No metal3 trunk position"}
    record = {**failed, "objective": stored_objective(objective(failed, "quality", 1.0))}
    assert record["objective"] is None and json.loads(json.dumps(record, allow_nan=False)) == record
    assert stored_objective(3.5) == 3.5


def test_critic_reports_every_finding_with_a_card():
    layout = {"placements": [], "groups": [], "trunks": [], "symmetric_nets": {}, "rails": [],
              "plan": {"rail_um": 1.0}, "area_um2": 100.0, "width_um": 10.0, "height_um": 10.0}
    result = review(layout, {"devices": {}, "logical": {}}, drc_errors=0)
    assert result["findings"] and all(f["card"] in {c.id for c in CARDS} for f in result["findings"])
    assert 0 <= result["score"] <= 100


@pytest.mark.integration
def test_shared_diffusion_pair_array_is_drc_clean(tmp_path):
    if missing := readiness():
        pytest.skip(f"missing tools: {missing}")
    from chipjev.layout.pro.check import drc

    fingers = [Finger("vss", None, "dummy"), Finger("inp", "m2"), Finger("inn", "m3"),
               Finger("inn", "m3"), Finger("inp", "m2"), Finger("vss", None, "dummy")]
    spec = ArraySpec("n", 400, 30, fingers, ["x1", "x1", "t1", "out", "t1", "x1", "x1"],
                     top_gate="inp", bottom_gate="inn", strap_nets=["t1", "x1", "out"])
    array = MosArray(spec)
    canvas = Canvas()
    canvas.merge(array.canvas)
    x0, y0, x1, y1 = canvas.bounds()
    # A contacted tap below: the latch-up rules need one within 15 um.
    ty = y0 - 150
    canvas.rect("psubdiff", x0, ty, x1, ty + T.TAP_W)
    canvas.rect("psubdiffcont", x0 + 24, ty + 24, x1 - 24, ty + 58)
    canvas.rect("locali", x0 + 8, ty + 24, x1 - 8, ty + 58)
    canvas.rect("viali", x0 + 24, ty + 24, x1 - 24, ty + 58)
    canvas.rect("metal1", x0, ty + 18, x1, ty + 64)
    for pin in array.pins["dummy_heads"]:
        a, _, b, d = pin["rect"]
        canvas.rect("metal1", a, ty + 18, b, d)
    count, errors, _ = drc(canvas, directory=tmp_path)
    assert count == 0, errors[:5]


@pytest.mark.integration
def test_a_minimum_width_finger_straps_outside_its_diffusion_drc_clean(tmp_path):
    # 0.42 um fingers cannot host two metal2 straps over the diffusion (cascode and
    # folded-cascode devices in two-stage op-amps); the straps stack below it instead.
    if missing := readiness():
        pytest.skip(f"missing tools: {missing}")
    from chipjev.layout.pro.check import drc

    fingers = [Finger("vss", None, "dummy"), Finger("g1", "m7"), Finger("g1", "m7"),
               Finger("vss", None, "dummy")]
    spec = ArraySpec("n", 84, 30, fingers, ["out", "out", "s2a", "out", "out"], top_gate="g1",
                     strap_nets=["out", "s2a"], strap_side="bottom")
    array = MosArray(spec)
    assert array.outside("bottom") > 0 and all(pin["y"] < 0 for pin in array.pins["straps"])
    canvas = Canvas()
    canvas.merge(array.canvas)
    x0, y0, x1, y1 = canvas.bounds()
    ty = y0 - 150
    canvas.rect("psubdiff", x0, ty, x1, ty + T.TAP_W)
    canvas.rect("psubdiffcont", x0 + 24, ty + 24, x1 - 24, ty + 58)
    canvas.rect("locali", x0 + 8, ty + 24, x1 - 8, ty + 58)
    canvas.rect("viali", x0 + 24, ty + 24, x1 - 24, ty + 58)
    canvas.rect("metal1", x0, ty + 18, x1, ty + 64)
    for pin in array.pins["dummy_heads"]:
        a, _, b, d = pin["rect"]
        canvas.rect("metal1", a, ty + 18, b, d)
    count, errors, _ = drc(canvas, directory=tmp_path)
    assert count == 0, errors[:5]


@pytest.mark.integration
@pytest.mark.parametrize("name", ["opamp-gain", "ota-efficient"])
def test_generated_layout_is_drc_and_lvs_clean_with_declared_integrity(tmp_path, name):
    if missing := readiness():
        pytest.skip(f"missing tools: {missing}")
    from chipjev.layout.pro.compiler import synthesize
    from chipjev.layout.verification import lvs

    topology, values = design(name)
    result = synthesize(topology, values, tmp_path, plan=ProPlan())
    assert result["drc_errors"] == 0
    assert lvs(tmp_path)["passed"]
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    counts, auxiliaries = validate(build(topology, values), manifest)
    assert counts == {n: g[2] for n, g in build(topology, values).geometry.items()}
    # Tampering with one declared finger is caught before any simulation.
    ident = next(k for k, d in manifest["devices"].items() if d["role"] == "active")
    manifest["devices"][ident]["nets"][1] = "vdd"
    with pytest.raises(ValueError):
        validate(build(topology, values), manifest)


@pytest.mark.integration
@pytest.mark.parametrize("rail", [0.6, 2.0])
def test_every_power_rail_width_is_drc_and_lvs_clean(tmp_path, rail):
    # 2 um rails once hung power-strap via2 pads past the rail ends: 128 met2.2 slivers.
    if missing := readiness():
        pytest.skip(f"missing tools: {missing}")
    from chipjev.layout.pro.compiler import synthesize
    from chipjev.layout.verification import lvs

    topology, values = design("opamp-speed")
    result = synthesize(topology, values, tmp_path, plan=ProPlan(rail_um=rail))
    assert result["drc_errors"] == 0
    assert lvs(tmp_path)["passed"]
