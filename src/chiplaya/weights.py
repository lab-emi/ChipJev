"""Released ChipLaya weights: where each version lives and how it is verified.

A release holds the fine-tuned tensors only (FP16), as a PyTorch state file (``pt``, the
archival format ChipJev pins) and as the same tensors in safetensors (``safetensors``, no
pickle). The base checkpoint comes from Hugging Face at the pinned revision
(laya_torch.MODEL_ID and MODEL_REVISION, repeated in BASE with the weights' SHA-256).
Nothing is downloaded unless ``fetch(..., download=True)`` is called, and every file,
cached or downloaded, must match its SHA-256.
"""

import os
import shutil
import tempfile
import urllib.request
from pathlib import Path

REPOSITORY = "https://github.com/lab-emi/ChipLaya"
BASE = {
    "model": "aac6fef/laya-multilingual-mlx",
    "revision": "f2b4faf51023039425946074e2cf1361d2db11d5",
    "model.safetensors": "7fc5834af4d8fdfb268d272a9d1a66e5819a0daac98241651c4c888cc43adff1",
}
RELEASES = {
    "1.0.0": {
        "file": "typed-decisions.pt",
        "sha256": "f5df4faaeb1e2721657e5200293f7667ca525b8f86c1c8d3c3ab14193baeb8d5",
        "bytes": 69_681_899,
        "tensors": 56,
        "parameters": 34_831_873,
        "formats": {
            "safetensors": {
                "file": "typed-decisions.safetensors",
                "sha256": "08155a2669684494318da6b309e2c06e97e341dc6abce16ddd2e546306471b71",
                "bytes": 69_669_562,
            },
        },
    },
}
LATEST = "1.0.0"


def release(version=None, fmt="pt"):
    """One release file's manifest entry (default: the latest release, PyTorch format),
    with the release version and the download URL."""
    version = (version or LATEST).removeprefix("v")
    if version not in RELEASES:
        raise KeyError(f"unknown ChipLaya release {version!r}; known: {sorted(RELEASES)}")
    entry = RELEASES[version]
    if fmt != "pt":
        if fmt not in entry["formats"]:
            raise KeyError(f"ChipLaya v{version} has no {fmt!r} weights")
        entry = dict(entry, **entry["formats"][fmt])
    url = f"{REPOSITORY}/releases/download/v{version}/{entry['file']}"
    return {"version": version, "format": fmt, "url": url, **entry}


def identify(sha256):
    """The release version whose weights (in any format) have this SHA-256, or None."""
    for version, entry in RELEASES.items():
        digests = [entry["sha256"]] + [f["sha256"] for f in entry["formats"].values()]
        if sha256 in digests:
            return version
    return None


def cache_root(cache_dir=None):
    if cache_dir is not None:
        return Path(cache_dir)
    if os.environ.get("CHIPLAYA_CACHE"):
        return Path(os.environ["CHIPLAYA_CACHE"])
    base = os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
    return Path(base) / "chiplaya"


def fetch(version=None, fmt="pt", *, cache_dir=None, download=False):
    """Path of a release's verified weights file, downloading it only when asked."""
    from .model import sha256

    entry = release(version, fmt)
    path = cache_root(cache_dir) / f"v{entry['version']}" / entry["file"]
    if path.is_file():
        if sha256(path) == entry["sha256"]:
            return path
        raise ValueError(f"{path} does not match ChipLaya v{entry['version']}; delete it")
    if not download:
        raise FileNotFoundError(f"{path} is missing; fetch(download=True) downloads "
                                f"{entry['url']}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".part-", delete=False) as part:
        pass
    part = Path(part.name)
    try:
        with urllib.request.urlopen(entry["url"], timeout=60) as response, open(part, "wb") as out:
            shutil.copyfileobj(response, out, 1 << 20)
        digest = sha256(part)
        if digest != entry["sha256"]:
            raise ValueError(f"{entry['url']} has SHA-256 {digest}, expected {entry['sha256']}")
        umask = os.umask(0)
        os.umask(umask)
        part.chmod(0o666 & ~umask)  # a shared cache stays readable, as for any other file
        part.replace(path)
    except BaseException:
        part.unlink(missing_ok=True)  # never leave a partial or wrong file in the cache
        raise
    return path
