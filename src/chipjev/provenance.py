"""Code fingerprints and the runtime description (host, GPU, tools, package versions, git
state) recorded with experiment results."""

import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess

from .paths import ROOT
from .simulation.pdk import SHA256

# Version of the measurement conventions recorded in the frozen protocols (unchanged since
# the value was introduced; kept so that new runtime records stay comparable).
MEASUREMENT_VERSION = "2026-09-21.3"

PACKAGES = (
    "numpy",
    "scipy",
    "scikit-learn",
    "torch",
    "optuna",
    "transformers",
    "tokenizers",
    "safetensors",
    "huggingface-hub",
    "mlx",
    "mlx-lm",
    "laya-mlx",
)


def fingerprint(value):
    """SHA-256 of a JSON value (sorted keys, compact separators)."""
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def code_hashes():
    """SHA-256 of every source file of the package, the lock and the project file."""
    files = sorted((ROOT / "src").rglob("*.py"))
    files += [ROOT / "uv.lock", ROOT / "pyproject.toml"]
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in files if "__pycache__" not in p.parts}


def code_fingerprint(hashes=None):
    return fingerprint(hashes or code_hashes())


def _processor():
    if platform.system() == "Darwin":
        return subprocess.check_output(
            ["sysctl", "-n", "machdep.cpu.brand_string"], text=True
        ).strip()
    try:
        with open("/proc/cpuinfo") as stream:
            for line in stream:
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor()


def _git(*args):
    try:
        return subprocess.check_output(
            ["git", *args], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def runtime():
    import psutil

    versions = {}
    for package in PACKAGES:
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = None
    tools = {}
    for name in ("xschem", "ngspice"):
        executable = ROOT / ".tools/bin" / name
        command = str(executable) if executable.exists() else name
        try:
            proc = subprocess.run(
                [command, "--version"], capture_output=True, text=True, timeout=10
            )
            tools[name] = (proc.stdout + proc.stderr).strip()
        except (OSError, subprocess.TimeoutExpired):
            tools[name] = None
    accelerator = None
    try:
        import torch

        if torch.cuda.is_available():
            accelerator = {
                "type": "cuda",
                "name": torch.cuda.get_device_name(0),
                "cuda": torch.version.cuda,
                "memory_bytes": torch.cuda.get_device_properties(0).total_memory,
            }
        elif getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            accelerator = {"type": "mps", "name": platform.machine()}
    except ImportError:
        pass
    hashes = code_hashes()
    return {
        "platform": platform.platform(),
        "architecture": platform.machine(),
        "processor": _processor(),
        "logical_cpus": os.cpu_count(),
        "memory_bytes": psutil.virtual_memory().total,
        "python": platform.python_version(),
        "packages": versions,
        "accelerator": accelerator,
        "tools": tools,
        "git_commit": _git("rev-parse", "HEAD"),
        "git_dirty": bool(_git("status", "--porcelain")),
        "code_hashes": hashes,
        "code_sha256": code_fingerprint(hashes),
        "measurement_version": MEASUREMENT_VERSION,
        "pdk_archive_sha256": SHA256,
    }
