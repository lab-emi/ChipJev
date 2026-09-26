"""Run Magic's full DRC deck on a canvas (template development and tests)."""

import re
import tempfile
from pathlib import Path

from ..magic import run_magic

SCRIPT = """load {name}
select top cell
drc euclidean on
drc style drc(full)
drc on
drc check
drc catchup
set fd [open drc.txt w]
foreach {{why boxes}} [drc listall why] {{
    foreach b $boxes {{ puts $fd "$why|$b" }}
}}
close $fd
puts "@@DRC [drc list count total]"
"""


def drc(canvas, ports=(), name="probe", directory=None):
    """Return (count, [(rule, box)]) for the canvas written as a flat Magic cell."""
    directory = Path(directory or tempfile.mkdtemp(prefix="chipjev-drc-"))
    directory.mkdir(parents=True, exist_ok=True)
    canvas.write_mag(directory / f"{name}.mag", list(ports))
    output = run_magic(directory, SCRIPT.format(name=name), f"drc_{name}")
    count = int(re.search(r"@@DRC (\d+)", output)[1])
    errors = []
    for line in (directory / "drc.txt").read_text().splitlines():
        if "|" in line:
            why, box = line.rsplit("|", 1)
            errors.append((why, tuple(int(float(v)) for v in box.split())))
    return count, errors, directory
