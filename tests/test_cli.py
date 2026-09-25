"""The command line and the benchmark task definitions."""

import json

import pytest

from chipjev.cli import main
from chipjev.paths import ROOT
from chipjev.tasks import task, tasks


def test_tasks_and_statements_are_the_frozen_ones():
    protocol = json.loads((ROOT / "experiments/ptm45/protocol.json").read_text())
    assert len(tasks()) == 12
    for t in tasks():
        assert t["statement"] == protocol["acpro_statements"][str(t["acpro_id"])]
    assert task("opampN-gbw") == task(58)
    with pytest.raises(KeyError):
        task("opampN-slew")


def test_tasks_command_lists_all_twelve(capsys):
    assert main(["tasks"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 12 and lines[0].startswith("amp1-gain")


def test_design_needs_a_request_or_a_task():
    with pytest.raises(SystemExit):
        main(["design"])
