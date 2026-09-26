"""ChipJev runs the ChipLaya release it pins, and that release is the frozen model.

src/chiplaya is vendored byte for byte from https://github.com/lab-emi/ChipLaya at the tag
in CHIPLAYA.json (scripts/sync_chiplaya.py). These checks tie it to the frozen evidence: its
runtime is the protocols' Laya runtime, its released weights are the protocols' weights, and
its questions cover every decision of ChipJev's topology grammar.
"""

import importlib.metadata
import importlib.util
import json
from pathlib import Path

import pytest

import chipjev
import chiplaya
from chipjev.circuits.grammar import library
from chipjev.decisions.typed import decisions, released_sha256, topology_questions
from chipjev.paths import ROOT, WEIGHTS

PIN = json.loads((ROOT / "CHIPLAYA.json").read_text())
PROTOCOL = json.loads((ROOT / "experiments/ptm45/protocol.json").read_text())
CLASSES = ("amp1", "opamp1", "ampN", "opampN")


def sync():
    spec = importlib.util.spec_from_file_location("sync_chiplaya",
                                                  ROOT / "scripts/sync_chiplaya.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_vendored_copy_is_the_one_imported():
    repository = Path(__file__).resolve().parents[1]  # independent of chipjev.paths.ROOT
    assert ROOT == repository
    assert Path(chipjev.__file__).resolve().parent == repository / "src/chipjev"
    assert Path(chiplaya.__file__).resolve().parent == repository / "src/chiplaya"
    with pytest.raises(importlib.metadata.PackageNotFoundError):
        importlib.metadata.distribution("chiplaya")  # no separate install to shadow it


def test_the_vendored_copy_matches_its_pin():
    assert sync().check(PIN) == []
    assert chiplaya.__version__ == PIN["version"] and PIN["tag"] == f"v{PIN['version']}"


def test_the_runtime_is_the_frozen_runtime():
    frozen = PROTOCOL["code_hashes"]["src/chipjev/laya_torch.py"]
    assert sync().sha256(ROOT / "src/chiplaya/laya_torch.py") == frozen


def test_the_released_weights_are_the_frozen_weights():
    from chiplaya.weights import release

    frozen = PROTOCOL["typed_weights_sha256"]
    assert PIN["weights"]["sha256"] == released_sha256() == frozen
    assert release(PIN["weights"]["release"])["sha256"] == frozen  # listed by the release
    assert ROOT / PIN["weights"]["path"] == WEIGHTS


@pytest.mark.parametrize("cls", CLASSES)
def test_every_grammar_decision_is_an_option(cls):
    questions = topology_questions(cls, "gain")
    for topology in library(cls):
        values = decisions(topology)
        chosen = [("first", values["first"]), ("polarity", values["polarity"])]
        if "count" in values:
            chosen += [("count", values["count"]), ("comp", values["comp"])]
            for kind, polarity in values["later"]:
                chosen += [("later", kind), ("later_polarity", polarity)]
        if "buffer" in values:
            chosen.append(("buffer", values["buffer"]))
        for question, option in chosen:
            if option is not None:  # symmetric stages have no polarity
                assert option in questions[question]["criteria"], (topology.id, question)
