"""ChipJev: ultrafast circuit design with a System One decision model and open-source EDA.

Subpackages, by function:

decisions        typed decisions: ChipLaya's answers mapped onto the topology grammar as a
                 prior (typed), the grammar labels for fine-tuning (finetune), the LLM
                 System Two baseline (llm), layout decisions (layout, pro_layout)
circuits         the topology grammar and its netlists (grammar, published), the joint
                 topology-and-sizing design space (space), SKY130 devices (sky130_devices)
simulation       ngspice testbenches: shared measurement (analysis), PTM 45 nm (ptm45),
                 SKY130 (sky130, pdk), PVT corners and mismatch (robustness)
surrogate        batched Gaussian processes and the fused Triton Thompson-sampling kernels
search           the ChipJev search loop (loop), the worker pool (evaluator), the TPE and
                 random baselines (baselines)
analogcoder_pro  AnalogCoder-Pro's unreleased sizing helper and PTM model module,
                 reconstructed on the common testbench, and its netlist adapter

Command line: ``chipjev decide``, ``chipjev design`` and ``chipjev tasks`` (cli.py).

The decision model itself is ChipLaya (the ``chiplaya`` package beside this one): Laya on
PyTorch, the typed questions and the fine-tuned weights, developed at
https://github.com/lab-emi/ChipLaya and vendored at the release pinned in CHIPLAYA.json.
"""

__version__ = "0.1.0"


def _vendored_chiplaya():
    """ChipJev runs the ChipLaya copy vendored beside it (src/chiplaya, CHIPLAYA.json). A
    separately installed chiplaya would shadow it from site-packages or overwrite it."""
    import importlib.metadata
    import importlib.util
    from pathlib import Path

    spec = importlib.util.find_spec("chiplaya")
    vendored = (Path(__file__).resolve().parents[1] / "chiplaya").resolve()
    found = Path(spec.origin).resolve().parent if spec and spec.origin else None
    try:
        installed = importlib.metadata.distribution("chiplaya")
    except importlib.metadata.PackageNotFoundError:
        installed = None
    if installed is not None:
        raise ImportError(f"chiplaya {installed.version} is installed in this environment; "
                          f"ChipJev runs the ChipLaya copy vendored at {vendored} "
                          "(CHIPLAYA.json), so uninstall the separate chiplaya package")
    if found is not None and found != vendored:
        raise ImportError(f"ChipJev runs the ChipLaya copy vendored at {vendored} "
                          f"(CHIPLAYA.json), but chiplaya resolves to {found}; put this "
                          "checkout's src first on the path (PYTHONPATH=src)")


_vendored_chiplaya()
