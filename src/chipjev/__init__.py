"""ChipJev: ultrafast circuit design with a System One decision model and open-source EDA.

Subpackages, by function:

decisions        typed decisions: Laya on PyTorch (laya_torch), the typed questions and the
                 topology prior (typed), fine-tuning (finetune), the LLM System Two baseline
                 (llm)
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
"""

__version__ = "0.1.0"
