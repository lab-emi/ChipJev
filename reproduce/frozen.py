"""The exact code that produced the paper's evidence, rebuilt as a runnable tree.

Both studies were frozen as protocols before their test runs: topo-v3 (experiments/ptm45)
and topo-v4 with its system2b addendum (experiments/sky130-system-two). Their runners hash
every file they execute by repository-relative path and refuse to start after any change,
and the evidence names those paths. reproduce/frozen-code.tar.gz holds that code exactly as
it was when the evidence was produced (the last state before the repository was reorganized
by function). This tool rebuilds the original layout under runs/frozen and runs
commands inside it, so a rerun executes the frozen code itself, never the live package.
The source archives are optional local inputs and are not included in this repository;
see reproduce/README.md for their paths and checksum records.

  python reproduce/frozen.py materialize          # build runs/frozen (idempotent)
  python reproduce/frozen.py check                # the frozen runners' own code checks
  python reproduce/frozen.py exec -- CMD ...      # run CMD in runs/frozen (paths relative to it)

A tree under /tmp (--tree) cannot run AnalogCoder-Pro's flow: its bubblewrap sandbox mounts a
private /tmp.

Standard library only.
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "reproduce/frozen-code.tar.gz"
RECORD = ROOT / "reproduce/frozen-code.json"
DEFAULT_TREE = ROOT / "runs/frozen"
PTM45 = ROOT / "experiments/ptm45"
SKY130 = ROOT / "experiments/sky130-system-two"
# Live evidence copied into the tree at the paths the frozen code expects.
COPIES = {
    PTM45 / "typed-decisions.pt": "runs/topo-v3-dev/typed/typed-decisions.pt",
}
# Frozen SKY130 model files (the TT include chain hashed by topo-v4): real files, taken from
# the study's frozen-source archive, because the runner refuses a symlinked model root.
PDK_ARCHIVE = SKY130 / "frozen-source.tar.gz"
ARCHIVES = (ARCHIVE, PTM45 / "frozen-source.tar.gz", PDK_ARCHIVE)
# Tools built by the setup scripts, shared with the live tree.
TOOL_LINKS = ("bin", "acpro", "acpro-venv", "ngspice-shared")
CHECK = r"""
import importlib.util, json, sys
from pathlib import Path

root = Path.cwd().resolve()

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, root / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

v3 = load("topo_v3_run", "scripts/topo-v3-run.py")
v3.check_frozen()
v4 = load("topo_v4_run", "scripts/topo-v4-run.py")
v4.check_frozen()
s2 = load("topo_v4_system2b", "scripts/topo-v4-system2b.py")
s2.check()
outside = sorted(name for name, module in sys.modules.items()
                 if name.split(".")[0] in ("chipjev", "chipjev_topo", "chipjev_topo_v2",
                                           "chipjev_topo_v3", "chipjev_topo_v4")
                 and getattr(module, "__file__", None)
                 and not Path(module.__file__).resolve().is_relative_to(root))
if outside:
    raise SystemExit(f"modules loaded from outside the frozen tree: {outside}")
print(json.dumps({"topo-v3": len(v3.source_hashes()), "topo-v4": len(v4.source_hashes()),
                  "topo-v4-system2b": len(s2.source_hashes())}))
"""


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def members(archive):
    """{path: sha256} of the regular files in a tar.gz archive, read in memory."""
    out = {}
    with tarfile.open(archive, "r:gz") as bundle:
        for info in bundle.getmembers():
            if info.isfile():
                out[info.name] = hashlib.sha256(bundle.extractfile(info).read()).hexdigest()
    return out


def _extract(archive, tree, keep=lambda name: True):
    with tarfile.open(archive, "r:gz") as bundle:
        for info in bundle.getmembers():
            name = info.name
            if not keep(name) or info.isdir():
                continue
            if not info.isfile() or name.startswith("/") or ".." in Path(name).parts:
                raise SystemExit(f"refusing archive member {name!r} of {archive.name}")
            target = tree / name
            data = bundle.extractfile(info).read()
            if target.exists() and target.read_bytes() == data:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            os.chmod(target, info.mode & 0o777 or 0o644)


def require_archives():
    """Fail with restore instructions when optional source archives are absent."""
    missing = [str(path.relative_to(ROOT)) for path in ARCHIVES if not path.is_file()]
    if missing:
        raise SystemExit(
            "Frozen source archives are not included in this repository. "
            "Restore these files for exact experiment reruns:\n  "
            + "\n  ".join(missing)
            + "\nSee reproduce/README.md for the checksum records."
        )


def materialize(tree=DEFAULT_TREE):
    """Build (or refresh) the frozen tree; returns its path."""
    require_archives()
    record = json.loads(RECORD.read_text())
    if sha256(ARCHIVE) != record["sha256"]:
        raise SystemExit(f"{ARCHIVE.relative_to(ROOT)} differs from {RECORD.name}")
    tree.mkdir(parents=True, exist_ok=True)
    _extract(ARCHIVE, tree)
    _extract(PDK_ARCHIVE, tree, keep=lambda name: name.startswith(".tools/pdk/"))
    for source, name in COPIES.items():
        target = tree / name
        if not (target.exists() and sha256(target) == sha256(source)):
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    for name in TOOL_LINKS:
        link, source = tree / ".tools" / name, ROOT / ".tools" / name
        if source.exists() and not link.exists():
            link.symlink_to(source)
    (tree / "runs").mkdir(exist_ok=True)
    (tree / "MATERIALIZED.json").write_text(json.dumps(
        {"archive_sha256": record["sha256"], "commit": record["commit"]}, indent=1) + "\n")
    return tree


def environment(tree):
    """Environment of every command in the frozen tree: its own src first, the frozen
    SKY130 model root, the tools built by the setup scripts."""
    env = dict(os.environ)
    env.pop("CHIPJEV_PDK", None)
    env["PYTHONPATH"] = str(tree / "src")
    env["PATH"] = f"{tree / '.tools/bin'}{os.pathsep}{env.get('PATH', '')}"
    return env


def check(tree=DEFAULT_TREE, python=sys.executable):
    """Run the three frozen runners' own checks inside the tree and make sure that no module
    of the old packages was loaded from anywhere else."""
    result = subprocess.run([python, "-c", CHECK], cwd=tree, env=environment(tree),
                            capture_output=True, text=True)
    if result.returncode:
        sys.stderr.write(result.stdout + result.stderr)
        raise SystemExit("the frozen code checks failed")
    counts = json.loads(result.stdout.strip().splitlines()[-1])
    print(f"frozen tree {tree}: runner checks passed ({counts})")
    return counts


def run(command, tree=DEFAULT_TREE):
    return subprocess.run(command, cwd=tree, env=environment(tree)).returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tree", type=Path, default=DEFAULT_TREE)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("materialize")
    sub.add_parser("check")
    execute = sub.add_parser("exec")
    execute.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    tree = args.tree.resolve()
    if args.action == "materialize":
        print(materialize(tree))
    elif args.action == "check":
        check(tree)
    else:
        command = args.command[1:] if args.command[:1] == ["--"] else args.command
        if not command:
            parser.error("exec needs a command")
        if not (tree / "MATERIALIZED.json").exists():
            materialize(tree)
        sys.exit(run(command, tree))


if __name__ == "__main__":
    main()
