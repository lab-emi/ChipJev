"""xschem export of SKY130 designs (needs xschem and the sky130A xschem library)."""

import shutil

import pytest

from chipjev import xschem
from chipjev.circuits.grammar import default_values, library
from chipjev.circuits.sky130_devices import build


@pytest.mark.integration
def test_xschem_schematic_round_trips_the_netlist(tmp_path):
    if shutil.which("xschem") is None or not (xschem.library() / "sky130_fd_pr").exists():
        pytest.skip("xschem or the SKY130 xschem library is not installed")
    topology = library("opampN")[5]
    builder = build(topology, default_values(topology), 1.8)
    path = tmp_path / "design.sch"
    path.write_text(xschem.schematic(builder, topology.id, 1.8))
    ok, problems = xschem.check(builder, xschem.netlist(path, tmp_path / "net"), 1.8)
    assert ok, problems
