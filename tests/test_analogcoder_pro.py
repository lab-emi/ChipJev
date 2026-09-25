"""AnalogCoder-Pro's reconstructed model module and the LLM netlist adapter."""

import pytest

from chipjev.analogcoder_pro.helper import TASKS, ptm_params
from chipjev.analogcoder_pro.netlist import parse
from chipjev.tasks import ANALOGCODER_PRO_ID


def test_llm_netlist_adapter_maps_nodes_and_removes_sources_and_load():
    text = """.title demo
.model nmos_model nmos (level=54 version=4.0)
.model pmos_model pmos (level=54 version=4.0)
Vdd Vdd 0 1.2
Vin Vin 0 0.6
Vbias Vbias 0 0.78
M1 Vout Vin 0 0 nmos_model l=4.5e-08 w=1e-06
M2 Vout Vbias Vdd Vdd pmos_model l=4.5e-08 w=2u
Cload Vout 0 1pF
Cc Vout Vin 0.5p
R1 Vout Vdd 10kOhm
"""
    b = parse(text, differential=False, vdd=1.2)
    assert b.bias == {"x_vbias": pytest.approx(0.78)}
    assert [m[1:] for m in b.mos] == [("out", "in", "0", "n"), ("out", "x_vbias", "vdd", "p")]
    assert any(line.startswith("c1_llm out in 5e-13") for line in b.lines)
    assert not any("1e-12" in line for line in b.lines)  # load capacitor removed
    assert any(line.startswith("r1_llm out vdd 10000") for line in b.lines)


def test_ptm_card_as_pyspice_parameters():
    nmos, pmos = ptm_params("nmos"), ptm_params("pmos")
    assert nmos["level"] == 54 and pmos["level"] == 54
    assert nmos["vth0"] > 0 > pmos["vth0"]


def test_task_ids_agree():
    assert {v: k for k, v in TASKS.items()} == ANALOGCODER_PRO_ID
