"""The live tree uses function names only; the frozen names live in the frozen code."""

import importlib
import importlib.util
import pkgutil
import re
import subprocess

import chipjev
from chipjev.paths import ROOT

FROZEN_NAMES = re.compile(r"chipjev_topo|chipjev\.rt\b|chipjev\.research\b|topo_system2|"
                          r"topo_xschem|chipjev\.laya_torch|test_topo")
# Files that must name the frozen modules: the differential probe and the frozen-tree tools.
ALLOWED = {"tests/equivalence/probe.py", "tests/test_layout.py", "reproduce/frozen.py",
           "reproduce/verify.py"}


def test_every_module_imports_on_the_cpu():
    for module in pkgutil.walk_packages(chipjev.__path__, "chipjev."):
        if module.name != "chipjev.__main__":
            importlib.import_module(module.name)


def test_frozen_packages_are_gone():
    for name in ("chipjev_topo", "chipjev_topo_v2", "chipjev_topo_v3", "chipjev_topo_v4",
                 "chipjev.rt", "chipjev.research"):
        assert importlib.util.find_spec(name.split(".")[0]) is None or (
            "." in name and importlib.util.find_spec(name) is None), name


def test_live_code_does_not_name_the_frozen_modules():
    files = subprocess.check_output(["git", "ls-files", "--cached", "--others",
                                     "--exclude-standard", "src", "scripts", "tests",
                                     "reproduce"], cwd=ROOT, text=True).split()
    offenders = []
    for name in files:
        if name in ALLOWED or not name.endswith((".py", ".sh")):
            continue
        for number, line in enumerate((ROOT / name).read_text().splitlines(), 1):
            if FROZEN_NAMES.search(line):
                offenders.append(f"{name}:{number}: {line.strip()}")
    assert not offenders, "\n".join(offenders)
