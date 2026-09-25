"""Repository locations used at run time: the root and the tools that the setup scripts
build into .tools (ngspice 47, the SKY130 models)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / ".tools"


def ngspice():
    """The simulator: ngspice 47 from .tools/bin (scripts/setup.sh), else ngspice on the PATH.

    The frozen runners put .tools/bin first on the PATH; resolving it here keeps every
    testbench on the same ngspice regardless of the caller's PATH (a distribution ngspice of
    another version gives different operating points)."""
    local = TOOLS / "bin/ngspice"
    return str(local) if local.exists() else "ngspice"
