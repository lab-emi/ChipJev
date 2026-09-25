"""Bounded sizing recovery when nominal schematic qualification is lost after PEX."""

import json
import shutil
import time
from pathlib import Path

from ..circuits.grammar import LEVELS, slot_kind
from ..simulation.sky130 import evaluate
from .verification import verify


def complete(
    topology,
    values,
    directory,
    *,
    vdd=1.8,
    load_pf=100,
    observer=None,
    prelayout=None,
    max_candidates=48,
):
    """Keep all attempts; publish only the final checked layout at the output root.

    Recovery keeps topology fixed and tries adjacent sizing-grid values, lengths
    first. No hand-selected circuit, cached sizing, or relaxed checks are used.
    """
    start = time.perf_counter()
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    if any(directory.glob("attempt-*")) or (directory / "physical.json").exists():
        raise FileExistsError("Use a fresh physical output directory to avoid stale evidence")
    candidates = [(dict(values), None)]
    slots = sorted(values, key=lambda s: (slot_kind(s) != "length", s))
    for slot in slots:
        grid = LEVELS[slot_kind(slot)]
        index = min(range(len(grid)), key=lambda i: abs(grid[i] - values[slot]))
        for offset in (1, -1, 4, -4):
            if 0 <= index + offset < len(grid):
                candidates.append(({**values, slot: grid[index + offset]}, slot))
    # Length changes often need a neighboring bias/ratio change to keep the
    # input common-mode range. Try these coupled moves after the single moves.
    single_moves = candidates[1:]
    for length in (s for s in slots if slot_kind(s) == "length"):
        grid = LEVELS["length"]
        index = min(range(len(grid)), key=lambda i: abs(grid[i] - values[length]))
        if index + 1 >= len(grid):
            continue
        for candidate, changed in single_moves:
            if changed != length and slot_kind(changed) != "length":
                candidates.append(({**candidate, length: grid[index + 1]}, f"{length},{changed}"))
    attempts = []
    chosen = None
    first = None
    for index, (candidate, changed) in enumerate(candidates[: max_candidates + 1]):
        target = directory / f"attempt-{index:02d}"
        pre = (
            prelayout
            if index == 0 and prelayout is not None
            else evaluate(
                topology,
                candidate,
                directory=target / "prelayout",
                strict=True,
                keep=True,
                vdd=vdd,
                load_pf=load_pf,
            )
        )
        if not pre["valid"] and index:
            attempts.append(
                {
                    "index": index,
                    "values": candidate,
                    "changed_slot": changed,
                    "prelayout": pre,
                    "physical": None,
                    "valid": False,
                }
            )
            continue
        result = verify(
            topology, candidate, target, vdd=vdd, load_pf=load_pf, observer=observer, prelayout=pre
        )
        attempts.append(
            {
                "index": index,
                "values": candidate,
                "changed_slot": changed,
                "valid": result["valid"],
                "physical": f"attempt-{index:02d}/physical.json",
            }
        )
        if first is None:
            first = (target, result, candidate)
        if result["valid"]:
            chosen = (target, result, candidate)
            break
        if result["layout"]["drc_errors"] or not result["lvs"]["passed"]:
            break  # Sizing is not a repair for a physical connectivity/DRC defect.
    source, result, selected = chosen or first
    for path in source.iterdir():
        if path.is_file():
            shutil.copy2(path, directory / path.name)
        elif path.name in ("prelayout", "postlayout"):
            shutil.copytree(path, directory / path.name, dirs_exist_ok=True)
    result.update(
        values=selected,
        recovery={
            "attempts": attempts,
            "changed": selected != values,
            "max_candidates": max_candidates,
        },
        total_seconds=time.perf_counter() - start,
    )
    (directory / "physical.json").write_text(json.dumps(result, indent=2, allow_nan=False))
    return result
