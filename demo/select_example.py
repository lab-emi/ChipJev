"""Extract the largest published, qualified ChipJev SKY130 final design.

Run from the repository root: .venv/bin/python -m demo.select_example
Complexity is ordered by MOS count, passive count, then gain-stage count.
No archived evidence is modified.
"""

import gzip
import hashlib
import json

from chipjev.circuits.published import lookup
from chipjev.circuits.sky130_devices import build
from chipjev.paths import ROOT


def select():
    root = ROOT / "experiments/sky130-system-two/results/sky130/runs"
    candidates = []
    for path in sorted(root.glob("*__chipjev__*.json.gz")):
        with gzip.open(path, "rt") as stream:
            record = json.load(stream)
        best = record["best"]
        if not record["verified"] or best is None:
            continue
        topology = lookup(record["cls"], best["topology"])
        builder = build(topology, best["values"], record["vdd"])
        rank = (len(builder.mos), len(builder.lines) - len(builder.mos), len(topology.stages))
        candidates.append((rank, path, record))
    rank, path, record = max(candidates, key=lambda item: item[0])
    fixture = {
        "title": "13-transistor, two-stage SKY130 op-amp",
        "selection": "Most MOSFETs among qualified ChipJev final designs in the SKY130 study",
        "candidate_count": len(candidates),
        "source": str(path.relative_to(ROOT)),
        "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "task": record["task"],
        "seed": record["seed"],
        "topology": record["best"]["topology"],
        "cls": record["cls"],
        "vdd": record["vdd"],
        "load_pf": record["load_pf"],
        "mosfets": rank[0],
        "passives": rank[1],
        "stages": rank[2],
        "values": record["best"]["values"],
        "reference_metrics": record["best"]["metrics"],
    }
    destination = ROOT / "demo/fixtures/sky130-opamp.json"
    destination.write_text(json.dumps(fixture, indent=2, allow_nan=False) + "\n")
    print(f"{fixture['topology']}: {rank}; {len(candidates)} qualified designs; {destination}")
    return fixture


if __name__ == "__main__":
    select()
