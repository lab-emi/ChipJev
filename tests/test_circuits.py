"""The topology grammar, published topologies, the joint design space and SKY130 devices."""

import numpy as np
import pytest

from chipjev.circuits.grammar import (
    CLASSES,
    LEVELS,
    Topology,
    build,
    default_values,
    library,
    slot_kind,
)
from chipjev.circuits.published import PUBLISHED, lookup
from chipjev.circuits.space import ClassSpace


def test_library_sizes_and_unique_ids():
    sizes = {cls: len(library(cls)) for cls in CLASSES}
    assert sizes == {"amp1": 16, "opamp1": 10, "ampN": 2916, "opampN": 1620}
    assert sum(sizes.values()) == 4562
    for cls in CLASSES:
        ids = [t.id for t in library(cls)]
        assert len(ids) == len(set(ids))


def test_every_topology_builds_with_default_values():
    for cls in CLASSES:
        for topology in library(cls)[:: 1 if len(library(cls)) < 100 else 97]:
            b = build(topology, default_values(topology))
            assert b.mos, topology.id
            nodes = {n for _, d, g, s, _ in b.mos for n in (d, g, s)}
            assert "out" in nodes
            assert ("inp" in nodes and "inn" in nodes) if topology.differential else "in" in nodes
            for volts in b.bias.values():
                assert 0.0 <= volts <= 1.2


def test_polarity_mirror_swaps_device_types_and_rails():
    n = build(Topology("amp1", ("cs_n",)), {"1.in": 8, "1.ld": 8, "1.L": 90, "1.vld": 0.5})
    p = build(Topology("amp1", ("cs_p",)), {"1.in": 8, "1.ld": 8, "1.L": 90, "1.vld": 0.5})
    assert [m[4] for m in n.mos] == ["n", "p"]
    assert [m[4] for m in p.mos] == ["p", "n"]
    assert n.mos[0][3] == "0" and p.mos[0][3] == "vdd"
    # gate strength 0.5 V: NMOS gate at 0.5 V, PMOS gate at VDD - 0.5 V
    assert list(n.bias.values()) == [pytest.approx(0.7)]
    assert list(p.bias.values()) == [pytest.approx(0.5)]


def test_published_topologies_build():
    counts = {"acpro_a": 8, "acpro_b": 9, "acpro_c": 9}
    for tid, topology in PUBLISHED.items():
        b = build(topology, default_values(topology))
        assert len(b.mos) == counts[tid]
        assert lookup(topology.cls, tid) is topology
    with pytest.raises(ValueError):
        lookup("amp1", "acpro_a")


def test_space_features_and_levels_round_trip():
    space = ClassSpace("opampN")
    rng = np.random.default_rng(0)
    designs = space.random(rng, 50)
    x = space.features(designs)
    assert x.shape == (50, space.dimension)
    assert np.all((x >= 0) & (x <= 1))
    for d in designs:
        values = space.values(d)
        assert set(values) == set(space.topology(d).slots())
        for slot, value in values.items():
            assert space.slots[space.slot_index[slot]] == slot
            assert value in LEVELS[slot_kind(slot)]


def test_mutations_change_one_choice():
    space = ClassSpace("opampN")
    i = space.index["ota5_n+cs_p+miller"]
    ids = {space.topologies[j].id for j in space.mutations(i)}
    assert "ota5_n+cs_p+miller_rz" in ids  # compensation
    assert "tele_n+cs_p+miller" in ids  # first stage
    assert "ota5_n+cs_p+cs_n+miller" in ids  # appended stage
    assert "ota5_n+cs_n+miller_rz" not in ids  # two choices


def test_neighbors_keep_shared_slot_levels():
    space = ClassSpace("opampN")
    rng = np.random.default_rng(1)
    design = space.canonical("ota5_n+cs_p+miller")
    moves = space.neighbors(design, rng, perturb=4, mutations=1)
    other = [m for m in moves if m[0] != design[0]]
    assert other
    for i, vec in other:
        for j in np.nonzero(space.active[i] & space.active[design[0]])[0]:
            assert vec[j] == design[1][j]


def test_without_carried_sizes_mutated_neighbors_draw_new_sizes():
    space = ClassSpace("opampN", carry_sizes=False)
    design = space.canonical("ota5_n+cs_p+miller")
    moves = space.neighbors(design, np.random.default_rng(1), perturb=4, mutations=1)
    other = [m for m in moves if m[0] != design[0]]
    shared = [(i, j) for i, _ in other for j in np.nonzero(space.active[i] & space.active[design[0]])[0]]
    changed = sum(dict(other)[i][j] != design[1][j] for i, j in shared)
    assert changed > len(shared) // 2
    local = [m for m in moves if m[0] == design[0]]
    assert local == [m for m in ClassSpace("opampN").neighbors(
        design, np.random.default_rng(1), perturb=4, mutations=1) if m[0] == design[0]]


def test_scrambled_roles_permute_within_each_topology():
    rng = np.random.default_rng(0)
    base, scrambled = ClassSpace("opampN"), ClassSpace("opampN", roles=False)
    designs = base.random(rng, 16)
    a, b = base.features(designs), scrambled.features(designs)
    width = base.descriptors.shape[1]
    assert np.array_equal(a[:, :width], b[:, :width])
    for row_a, row_b in zip(a[:, width:], b[:, width:], strict=True):
        assert sorted(row_a) == pytest.approx(sorted(row_b))
    assert not np.array_equal(a, b)


def test_prior_sampling_uses_the_prior():
    space = ClassSpace("opamp1")
    prior = np.zeros(len(space.topologies))
    prior[3] = 1.0
    sampled = ClassSpace("opamp1", prior=prior).random(np.random.default_rng(1), 50)
    assert {d[0] for d in sampled} == {3}
    with pytest.raises(ValueError):
        ClassSpace("opamp1", prior=prior[:-1])


def test_sky130_geometry_respects_the_model_bins():
    from chipjev.circuits.sky130_devices import FINGER_MAX_UM, W_MIN_UM, geometry, strength

    for ratio in (1.0, 3.7, 44.0, 500.0):
        for length_nm in (45.0, 180.0, 720.0):
            width, length, fingers = geometry(ratio, length_nm)
            assert length == pytest.approx(length_nm * 150 / 45 / 1000)
            assert width >= W_MIN_UM
            assert W_MIN_UM <= width / fingers <= FINGER_MAX_UM + 1e-9
    assert strength(0.20) == pytest.approx(0.35)
    assert strength(1.00) == pytest.approx(1.75)
