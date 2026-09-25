"""The frozen evidence verifies, the frozen code rebuilds and passes its own checks, and the
committed golden output is what the frozen code produces."""

import gzip
import json
import shutil
import subprocess
import sys

import pytest

from chipjev.paths import ROOT, ngspice

sys.path.insert(0, str(ROOT / "reproduce"))
import frozen  # noqa: E402


def test_evidence_and_frozen_code_verify():
    result = subprocess.run([sys.executable, str(ROOT / "reproduce/verify.py")],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("script, arguments", [
    ("verify.py", ["--require-frozen"]),
    ("frozen.py", ["materialize"]),
])
def test_missing_source_archives_report_restore_instructions(tmp_path, script, arguments):
    reproduction = tmp_path / "reproduce"
    reproduction.mkdir()
    for name in ("verify.py", "frozen.py"):
        shutil.copy2(ROOT / "reproduce" / name, reproduction / name)
    result = subprocess.run([sys.executable, str(reproduction / script), *arguments],
                            capture_output=True, text=True)
    assert result.returncode != 0
    assert "reproduce/README.md" in result.stderr
    for archive in frozen.ARCHIVES:
        assert str(archive.relative_to(ROOT)) in result.stderr
    assert "Traceback" not in result.stderr
    assert not (tmp_path / "runs/frozen").exists()


def test_rerun_requires_source_archives_before_setup(tmp_path):
    reproduction = tmp_path / "reproduce"
    reproduction.mkdir()
    shutil.copy2(ROOT / "reproduce/reproduce-paper.sh", reproduction / "reproduce-paper.sh")
    result = subprocess.run(["bash", str(reproduction / "reproduce-paper.sh"), "--rerun"],
                            capture_output=True, text=True)
    assert result.returncode != 0
    assert "--rerun needs the optional source archive" in result.stderr
    assert "reproduce/README.md" in result.stderr
    assert "setup.sh" not in result.stderr


@pytest.mark.integration
def test_archived_designs_resimulate_to_the_archived_results():
    import resimulate

    from chipjev.simulation.pdk import model_root

    if not shutil.which(ngspice()):
        pytest.skip("ngspice not installed")
    jobs = resimulate.design_jobs(resimulate.STAGES[:1], limit=2) + resimulate.robustness_jobs(1)
    if model_root().exists():
        jobs += resimulate.design_jobs(resimulate.STAGES[2:3], limit=2)
    for job in jobs:
        _, differences, _ = resimulate.run(job)
        assert not differences, (job["run"], differences)


@pytest.fixture(scope="module")
def tree(tmp_path_factory):
    if any(not path.is_file() for path in frozen.ARCHIVES):
        pytest.skip("optional frozen source archives not installed; see reproduce/README.md")
    return frozen.materialize(tmp_path_factory.mktemp("frozen"))


def test_frozen_tree_passes_the_runners_own_checks(tree):
    counts = frozen.check(tree)
    assert counts == {"topo-v3": 36, "topo-v4": 45, "topo-v4-system2b": 48}


@pytest.mark.frozen
def test_golden_output_is_the_frozen_codes_output(tree, tmp_path):
    if not shutil.which(ngspice()):
        pytest.skip("ngspice not installed")
    out = tmp_path / "frozen.json.gz"
    env = dict(frozen.environment(tree), CUDA_VISIBLE_DEVICES="")
    subprocess.run([sys.executable, str(ROOT / "tests/equivalence/probe.py"), "--side", "frozen",
                    "--out", str(out), "--weights",
                    str(ROOT / "experiments/ptm45/typed-decisions.pt")],
                   check=True, env=env, cwd=tree)
    fresh = json.load(gzip.open(out))
    golden = json.load(gzip.open(ROOT / "tests/equivalence/golden.json.gz"))
    assert fresh == golden
