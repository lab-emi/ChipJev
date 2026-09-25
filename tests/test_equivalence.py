"""The live package computes exactly what the frozen code computed.

tests/equivalence/probe.py runs deterministic inputs through every part of the package
(grammar and netlists, the design space with all ablation options, the surrogates, typed
decisions and the LLM answer validation, PTM 45 nm and SKY130 decks and ngspice records,
the worker pool on both technologies, seeded search traces with and without the typed
prior, the TPE and random baselines, AnalogCoder-Pro's helper pieces, robustness checks,
xschem schematics and Laya's typed decisions on the CPU). golden.json.gz is the same probe
run on the frozen code (reproduce/frozen-code.tar.gz); test_reproducibility.py checks that
the golden output still is what the frozen code produces.
"""

import gzip
import json
import os
import shutil
import subprocess
import sys

import pytest

from chipjev.paths import ROOT, ngspice

PROBE = ROOT / "tests/equivalence/probe.py"
GOLDEN = ROOT / "tests/equivalence/golden.json.gz"
SECTIONS = ("grammar", "sky130_devices", "space", "surrogate", "decisions", "decks",
            "evaluate", "evaluator", "search", "baselines", "analogcoder_pro", "robustness",
            "xschem", "typed")


@pytest.fixture(scope="module")
def live(tmp_path_factory):
    if not shutil.which(ngspice()):
        pytest.skip("ngspice not installed")
    out = tmp_path_factory.mktemp("probe") / "live.json.gz"
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), CUDA_VISIBLE_DEVICES="")
    subprocess.run([sys.executable, str(PROBE), "--side", "live", "--out", str(out),
                    "--weights", str(ROOT / "experiments/ptm45/typed-decisions.pt")],
                   check=True, env=env, cwd=ROOT)
    return json.load(gzip.open(out))


@pytest.fixture(scope="module")
def golden():
    return json.load(gzip.open(GOLDEN))


def first_difference(a, b, path=""):
    if type(a) is not type(b):
        return path, a, b
    if isinstance(a, dict):
        for key in sorted(set(a) | set(b)):
            if key not in a or key not in b:
                return f"{path}/{key}", a.get(key), b.get(key)
            found = first_difference(a[key], b[key], f"{path}/{key}")
            if found:
                return found
    elif isinstance(a, list):
        if len(a) != len(b):
            return f"{path} (length)", len(a), len(b)
        for i, (x, y) in enumerate(zip(a, b, strict=True)):
            found = first_difference(x, y, f"{path}[{i}]")
            if found:
                return found
    elif a != b:
        return path, a, b
    return None


@pytest.mark.integration
@pytest.mark.parametrize("section", SECTIONS)
def test_live_package_equals_frozen_code(section, live, golden):
    assert section in golden and section in live
    difference = first_difference(golden[section], live[section], section)
    assert difference is None, f"first difference at {difference[0]}: {difference[1:]}"
