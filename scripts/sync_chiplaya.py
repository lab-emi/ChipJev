"""Keep ChipJev's vendored ChipLaya model package in step with its release.

ChipLaya (https://github.com/lab-emi/ChipLaya) is developed in its own repository. ChipJev
vendors src/chiplaya/ byte for byte at a release tag, because uv.lock (hashed by the frozen
protocols) must not gain a dependency, and pins it in CHIPLAYA.json: the tag, its commit,
the SHA-256 of every vendored file and of the fine-tuned weights ChipJev ships.

  python scripts/sync_chiplaya.py --check               # offline: src/chiplaya and weights match the pin
  python scripts/sync_chiplaya.py --check --upstream    # also: the pin matches ChipLaya on GitHub
  python scripts/sync_chiplaya.py --latest              # the latest ChipLaya release tag
  python scripts/sync_chiplaya.py --update v1.1.0       # vendor another release, rewrite the pin
"""

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIN = ROOT / "CHIPLAYA.json"
PACKAGE = "src/chiplaya"
REPOSITORY = "https://github.com/lab-emi/ChipLaya"


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def vendored(root=ROOT):
    """{relative path: SHA-256} of the package files (no caches)."""
    base = root / PACKAGE
    return {str(p.relative_to(base)): sha256(p) for p in sorted(base.rglob("*"))
            if p.is_file() and "__pycache__" not in p.parts}


def released_weights(root=ROOT):
    """{version: SHA-256} of the releases listed by the vendored weights manifest."""
    spec = importlib.util.spec_from_file_location("_chiplaya_weights",
                                                  root / PACKAGE / "weights.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return {version: entry["sha256"] for version, entry in module.RELEASES.items()}


def check(pin):
    """Offline consistency of the vendored package and the weights with the pin."""
    problems = []
    files = vendored()
    if files != pin["files"]:
        changed = sorted(k for k in set(files) | set(pin["files"])
                         if files.get(k) != pin["files"].get(k))
        problems.append(f"{PACKAGE} differs from CHIPLAYA.json ({pin['tag']}): {changed}")
    if pin["tag"] != f"v{pin['version']}":
        problems.append(f"CHIPLAYA.json tag {pin['tag']} is not version {pin['version']}")
    if f"__version__ = \"{pin['version']}\"" not in (ROOT / PACKAGE / "__init__.py").read_text():
        problems.append(f"{PACKAGE}/__init__.py is not version {pin['version']}")
    weights = pin["weights"]
    if sha256(ROOT / weights["path"]) != weights["sha256"]:
        problems.append(f"{weights['path']} does not match CHIPLAYA.json")
    if released_weights().get(weights["release"]) != weights["sha256"]:
        problems.append(f"the pinned weights are not ChipLaya's weights release "
                        f"{weights['release']} in {PACKAGE}/weights.py")
    return problems


def clone(tag, into):
    subprocess.run(["git", "-c", "advice.detachedHead=false", "clone", "--quiet", "--depth", "1",
                    "--branch", tag,
                    f"{REPOSITORY}.git", str(into)], check=True,
                   env=dict(os.environ, GIT_TERMINAL_PROMPT="0"))
    commit = subprocess.run(["git", "-C", str(into), "rev-parse", "HEAD"], check=True,
                            capture_output=True, text=True).stdout.strip()
    return commit


def upstream(pin):
    """The pinned tag on GitHub is the pinned commit, with byte-identical package files."""
    with tempfile.TemporaryDirectory() as tmp:
        commit = clone(pin["tag"], Path(tmp) / "ChipLaya")
        problems = []
        if commit != pin["commit"]:
            problems.append(f"{pin['tag']} is {commit} on GitHub, CHIPLAYA.json pins "
                            f"{pin['commit']}")
        if vendored(Path(tmp) / "ChipLaya") != pin["files"]:
            problems.append(f"{PACKAGE} at {pin['tag']} on GitHub differs from CHIPLAYA.json")
        return problems


def latest():
    """The newest vX.Y.Z tag of ChipLaya on GitHub (None when GitHub cannot be reached)."""
    try:
        refs = subprocess.run(["git", "ls-remote", "--tags", "--refs", f"{REPOSITORY}.git", "v*"],
                              check=True, capture_output=True, text=True,
                              env=dict(os.environ, GIT_TERMINAL_PROMPT="0")).stdout
    except subprocess.CalledProcessError as error:
        report("warning", f"cannot list ChipLaya releases: {error.stderr.strip()}")
        return None
    tags = [line.split("refs/tags/")[1] for line in refs.splitlines()]
    tags = [t for t in tags if re.fullmatch(r"v\d+\.\d+\.\d+", t)]
    return max(tags, key=lambda t: tuple(int(x) for x in t[1:].split(".")), default=None)


def update(tag, pin):
    """Vendor ChipLaya at `tag`. ChipJev's weights are frozen evidence, so the release must
    still list them; the tree is changed only after the release checks out."""
    if not re.fullmatch(r"v\d+\.\d+\.\d+", tag):
        sys.exit(f"{tag} is not a release tag (vX.Y.Z)")
    weights = pin["weights"]
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "ChipLaya"
        commit = clone(tag, source)
        version = tag.removeprefix("v")
        if f"__version__ = \"{version}\"" not in (source / PACKAGE / "__init__.py").read_text():
            sys.exit(f"ChipLaya {tag} is not package version {version}; not vendored")
        if released_weights(source).get(weights["release"]) != weights["sha256"]:
            sys.exit(f"ChipLaya {tag} does not list ChipJev's weights (release "
                     f"{weights['release']}, {weights['sha256'][:12]}...), which the frozen "
                     "studies pin; nothing was changed. Adopting new weights means a new "
                     "weights file and protocol, not a sync.")
        shutil.rmtree(ROOT / PACKAGE)
        shutil.copytree(source / PACKAGE, ROOT / PACKAGE,
                        ignore=shutil.ignore_patterns("__pycache__"))
    pin = {**pin, "version": version, "tag": tag, "commit": commit, "files": vendored()}
    PIN.write_text(json.dumps(pin, indent=2) + "\n")
    return pin


def report(level, message):
    if os.environ.get("GITHUB_ACTIONS"):
        print(f"::{level}::{message}")
    else:
        print(f"{level}: {message}", file=sys.stderr if level == "error" else sys.stdout)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="verify the pin offline")
    parser.add_argument("--upstream", action="store_true",
                        help="with --check: also verify the pin against GitHub")
    parser.add_argument("--latest", action="store_true",
                        help="print the latest release and whether the pin is behind")
    parser.add_argument("--update", metavar="TAG", help="vendor this ChipLaya release")
    args = parser.parse_args()
    pin = json.loads(PIN.read_text())
    if args.update:
        pin = update(args.update, pin)
        print(f"vendored ChipLaya {pin['tag']} ({pin['commit'][:12]}), {len(pin['files'])} files")
    problems = []
    if args.check or args.update:
        problems += check(pin)
        if args.upstream:
            problems += upstream(pin)
    if args.latest:
        newest = latest()
        print(f"latest ChipLaya release: {newest}; ChipJev pins {pin['tag']}")
        if newest and newest != pin["tag"]:
            report("warning", f"ChipLaya {newest} is available; ChipJev pins {pin['tag']} "
                              f"(python scripts/sync_chiplaya.py --update {newest})")
    for problem in problems:
        report("error", problem)
    if problems:
        sys.exit(1)
    if args.check or args.update:
        print(f"ChipLaya {pin['tag']} ({pin['commit'][:12]}): {len(pin['files'])} vendored files "
              f"and the weights match CHIPLAYA.json" + (" and GitHub" if args.upstream else ""))


if __name__ == "__main__":
    main()
