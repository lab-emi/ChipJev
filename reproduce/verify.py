"""Verify the frozen evidence behind the paper before regenerating or rerunning anything.

Checks, and exits nonzero on any failure:
  * when supplied, reproduce/frozen-code.tar.gz (the code that produced the evidence) matches
    reproduce/frozen-code.json, and holds every file hashed by the three frozen protocols
    (experiments/ptm45/protocol.json, experiments/sky130-system-two/protocol.json and its
    system2b addendum) with the recorded SHA-256; the protocols in the archive are the ones
    in experiments/;
  * when supplied, each study's frozen-source.tar.gz holds exactly its protocol's
    hashed files, byte-identical to the frozen-code archive;
  * the frozen inputs that are still used live (the task file, the PTM model card, the
    PROTOCOL.md files, held-out requests, development labels, uv.lock and, when installed,
    the SKY130 model files) are byte-identical at their current paths;
  * the fine-tuned typed-decision weights match the frozen hash;
  * every archived evidence file matches its manifest (results/MANIFEST.json and the
    study-level MANIFEST.json of both studies); only the optional frozen source archives
    may be absent, and every such omission is reported.

  .venv/bin/python reproduce/verify.py [--require-frozen] [--tree runs/frozen]

With --tree it also runs the frozen runners' own code checks in a materialized frozen tree
(reproduce/frozen.py). --require-frozen requires all three optional source archives.
Without them, source hashes are checked against the recorded member list, not archive bytes.
Standard library only.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "reproduce"))
import frozen  # noqa: E402

PTM45 = "experiments/ptm45"
SKY130 = "experiments/sky130-system-two"
# Protocol files: live path -> path inside the frozen code (and in the protocols' own keys).
PROTOCOLS = {
    f"{PTM45}/protocol.json": "experiments/topo-v3/protocol.json",
    f"{SKY130}/protocol.json": "experiments/topo-v4/protocol.json",
    f"{SKY130}/system2b/protocol.json": "experiments/topo-v4/system2b/protocol.json",
}
FROZEN_SOURCES = {  # study frozen-source archive -> its protocol
    f"{PTM45}/frozen-source.tar.gz": f"{PTM45}/protocol.json",
    f"{SKY130}/frozen-source.tar.gz": f"{SKY130}/protocol.json",
}
# Hashed frozen inputs still used live: frozen path -> live path.
LIVE = {
    "experiments/topo-v1/tasks-test.json": "src/chipjev/tasks.json",
    "src/chipjev_topo/models/ptm45hp.pm": "src/chipjev/simulation/models/ptm45hp.pm",
    "experiments/topo-v3/PROTOCOL.md": f"{PTM45}/PROTOCOL.md",
    "experiments/topo-v3/heldout-requests.json": f"{PTM45}/heldout-requests.json",
    "experiments/topo-v3/development/labels.json": f"{PTM45}/development/labels.json",
    "experiments/topo-v4/PROTOCOL.md": f"{SKY130}/PROTOCOL.md",
    "experiments/topo-v4/system2b/PROTOCOL.md": f"{SKY130}/system2b/PROTOCOL.md",
    "uv.lock": "uv.lock",
}
WEIGHTS = f"{PTM45}/typed-decisions.pt"
STUDIES = (PTM45, SKY130)
SKIP = ("report", "results")  # a study's top-level manifest excludes generated and archived dirs


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tree", type=Path, help="also check a materialized frozen tree")
    parser.add_argument("--require-frozen", action="store_true",
                        help="fail if any optional frozen source archive is absent")
    args = parser.parse_args()
    failures = []
    if args.require_frozen:
        frozen.require_archives()
    missing_archives = {path for path in frozen.ARCHIVES if not path.is_file()}
    for path in sorted(missing_archives):
        print(f"Optional source archive absent: {path.relative_to(ROOT)}")

    record = json.loads(frozen.RECORD.read_text())
    code = record["files"]
    if frozen.ARCHIVE not in missing_archives:
        code = frozen.members(frozen.ARCHIVE)
        if frozen.sha256(frozen.ARCHIVE) != record["sha256"] or code != record["files"]:
            failures.append("reproduce/frozen-code.tar.gz differs from frozen-code.json")
        print(f"frozen code archive: {len(code)} files checked")
    else:
        print(f"frozen code member record: {len(code)} hashes (archive bytes not checked)")

    pdk = (frozen.members(frozen.PDK_ARCHIVE)
           if frozen.PDK_ARCHIVE not in missing_archives else None)
    hashes = {}
    for live, name in PROTOCOLS.items():
        text = (ROOT / live).read_bytes()
        if code.get(name) != hashlib.sha256(text).hexdigest():
            failures.append(f"{live} differs from the frozen code's {name}")
        protocol = json.loads(text)
        for path, expected in protocol["code_hashes"].items():
            source = pdk if path.startswith(".tools/pdk/") else code
            if source is not None and source.get(path) != expected:
                failures.append(f"{live}: {path} missing or changed in the frozen code")
            if hashes.setdefault(path, expected) != expected:
                failures.append(f"conflicting protocol hashes for {path}")
        print(f"{live}: {len(protocol['code_hashes'])} source hash records checked")
    addendum = json.loads((ROOT / f"{SKY130}/system2b/protocol.json").read_text())
    if addendum["topo_v4_protocol_sha256"] != frozen.sha256(ROOT / f"{SKY130}/protocol.json"):
        failures.append("the system2b addendum does not pin the SKY130 protocol")

    for archive, protocol in FROZEN_SOURCES.items():
        if ROOT / archive in missing_archives:
            continue
        expected = json.loads((ROOT / protocol).read_text())["code_hashes"]
        found = frozen.members(ROOT / archive)
        if found != expected:
            failures.append(f"{archive} differs from {protocol} code_hashes")
        mismatched = [p for p, h in found.items()
                      if not p.startswith(".tools/") and code.get(p) != h]
        if mismatched:
            failures.append(f"{archive} disagrees with the frozen code: {mismatched[:3]}")
        print(f"{archive}: {len(found)} files")

    for name, live in LIVE.items():
        if frozen.sha256(ROOT / live) != hashes[name]:
            failures.append(f"{live} differs from the frozen {name}")
    installed = 0
    for name, expected in hashes.items():
        if name.startswith(".tools/pdk/") and (ROOT / name).exists():
            installed += 1
            if frozen.sha256(ROOT / name) != expected:
                failures.append(f"{name} differs from the frozen SKY130 model file")
    print(f"live frozen inputs: {len(LIVE)} files identical"
          + (f", {installed} SKY130 model files" if installed else ""))

    expected_weights = json.loads((ROOT / f"{PTM45}/protocol.json").read_text())[
        "typed_weights_sha256"]
    if frozen.sha256(ROOT / WEIGHTS) != expected_weights:
        failures.append(f"{WEIGHTS} differs from the frozen hash")

    for study in STUDIES:
        for archive, top in ((ROOT / study / "results", False), (ROOT / study, True)):
            manifest = json.loads((archive / "MANIFEST.json").read_text())["files"]
            checked = 0
            for name, expected in manifest.items():
                path = archive / name
                if path in missing_archives:
                    continue
                checked += 1
                if not path.exists():
                    failures.append(f"{archive.relative_to(ROOT)}: missing {name}")
                elif frozen.sha256(path) != expected:
                    failures.append(f"{archive.relative_to(ROOT)}: changed {name}")
            extra = sorted(str(p.relative_to(archive)) for p in archive.rglob("*")
                           if p.is_file() and p.name != "MANIFEST.json"
                           and not (top and (p.relative_to(archive).parts[0] in SKIP
                                             or p.suffix == ".md"))
                           and str(p.relative_to(archive)) not in manifest)
            if extra:
                failures.append(f"{archive.relative_to(ROOT)}: files not in MANIFEST: {extra[:5]}")
            print(f"{archive.relative_to(ROOT)}: {checked} archived files checked")

    if args.tree:
        try:
            frozen.check(args.tree.resolve())
        except SystemExit as exc:
            failures.append(str(exc))
    if failures:
        print("\n".join("FAIL " + f for f in failures))
        sys.exit(1)
    print("Protocols, live frozen inputs, weights and evidence verified.")
    if missing_archives:
        print("Frozen source archive checks are incomplete; restore the optional archives "
              "and use --require-frozen for full source verification.")
    else:
        print("All frozen source archives verified.")


if __name__ == "__main__":
    main()
