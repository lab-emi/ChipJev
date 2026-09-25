# PTM 45 nm study (protocol topo-v3): typed decisions on CUDA and the measured LLM flow

This study adds typed decisions (a fine-tuned Laya decision model on CUDA) to the qualified
topology search, measures AnalogCoder-Pro's released LLM flow end to end on the same twelve
tasks (PTM 45 nm, 1.2 V, 100 pF), ablates the role-slot representation and the GPU
acquisition, and checks every delivered design at corners and under mismatch. It produces
Table I, Fig. 2 and most of Table II of the paper.

Read [PROTOCOL.md](PROTOCOL.md) before using the numbers, [DEVIATIONS.md](DEVIATIONS.md) for
execution notes and [development/README.md](development/README.md) for everything that
preceded the freeze. The protocol was frozen as **topo-v3**; PROTOCOL.md, protocol.json and
the evidence name the code by its paths at that time (for example `chipjev_topo_v3.typed`,
`scripts/topo-v3-run.py`, `experiments/topo-v3`), which are preserved in the optional local
`reproduce/frozen-code.tar.gz` snapshot; see [reproduce/README.md](../../reproduce/README.md).
The map to the current
package is in [experiments/README.md](../README.md). `report/RESULTS.md` and
`report/summary.json` are generated from the archive in `results/` by
`reproduce/report_ptm45.py`.

## Results

Generated summary: [report/RESULTS.md](report/RESULTS.md) (machine-readable:
`report/summary.json`). ChipJev 60/60 qualified runs (without typed decisions 59/60, joint TPE
51/60, random 33/60), 9.3 s median per run, 3.6x (2.0-5.0x) sooner to TPE's final quality and
2.7x fewer simulations. AnalogCoder-Pro's released flow (DeepSeek-V3): 253/360 functional
netlists, 47 qualified designs for 5 of 12 tasks and no op-amp, 1.0 h per task. With GPT-5-mini (the model named in its repository; 10 attempts per task, added after the freeze):
110/120 functional netlists, 9 qualified designs for 3 amplifier tasks (11 for 4 tasks when the
code blocks dropped by the released extraction are joined, frozen `scripts/acpro-lenient.py`) and no
op-amp, 4 min per attempt, $8.29. Typed
decisions: 12/12 statements, 110/120 held-out requests, 8.3 ms per pass. Scrambled role slots:
no consistent effect. CPU acquisition: 37x longer runs. Corner and mismatch checks: nominal
designs of every method keep little margin (see RESULTS.md). The threshold hint of
AnalogCoder-Pro's prompts is checked in [acpro-threshold-check.md](acpro-threshold-check.md).

## Host

AMD Ryzen 9 7950X, NVIDIA RTX 4090 (driver 580.178.04, CUDA 13.0), Ubuntu 24.04, ngspice 47
(KLU) built into `.tools`, uv-managed Python 3.13 with the locked environment. Search jobs use
eight physical cores (0-7); AnalogCoder-Pro attempts use one core each (8-15).

## Reproduce

From the archive (minutes, no GPU): `.venv/bin/python reproduce/report_ptm45.py`, or all
experiment reports with `reproduce/reproduce-paper.sh`. Generated tables and figures go to
`runs/reports/`; the manuscript is maintained separately. Exact reruns require the three local source
snapshots listed in [reproduce/README.md](../../reproduce/README.md). Rerunning executes the frozen code itself:
`reproduce/reproduce-paper.sh --rerun` runs every stage below in order inside `runs/frozen`
(rebuilt by `reproduce/frozen.py` from `reproduce/frozen-code.tar.gz` in the original layout).
A single stage runs the same way, from the repository root: `frozen.py exec` runs the command
in `runs/frozen`, so the paths after `--` are relative to it. The typed stage and the System Two
stages need the OpenAI client, which the locked environment lacks (DEVIATIONS item 1):

```bash
scripts/setup.sh && scripts/setup-analogcoder-pro.sh        # environment, ngspice 47, AnalogCoder-Pro
PY=$PWD/.venv/bin/python
uv pip install --python $PY openai==3.19.2
$PY reproduce/frozen.py materialize && $PY reproduce/frozen.py check
$PY reproduce/frozen.py exec -- taskset -c 0-7 $PY scripts/topo-v3-run.py --stage typed   # needs OPENROUTER_API_KEY
$PY reproduce/frozen.py exec -- taskset -c 0-7 $PY scripts/topo-v3-run.py --stage ablation
$PY reproduce/frozen.py exec -- taskset -c 0-7 $PY scripts/topo-v3-run.py --stage main
$PY reproduce/frozen.py exec -- $PY scripts/acpro-llm-run.py --model deepseek/deepseek-chat-v3-0324 \
    --tasks 51-62 --attempts 30 --parallel 8 --cores 8-15 --timeout 3600      # needs OPENROUTER_API_KEY
$PY reproduce/frozen.py exec -- taskset -c 0-7 $PY scripts/topo-v3-run.py --stage robustness
```

Post-hoc checks, added after the freeze and reported as such (see DEVIATIONS.md), run in the
frozen tree too: `scripts/acpro-diagnose.py` (the LLM's own sizes, strict),
`scripts/acpro-llm-run.py --model openai/gpt-5-mini --attempts 10` (second LLM),
`scripts/acpro-lenient.py`, `scripts/topo-v3-corner-select.py`, `scripts/typed-latency.py`,
`scripts/topo-latency.py` and `scripts/topo-v3-archive.py` (evidence archive and MANIFEST);
`reproduce/reproduce-paper.sh --rerun` lists their exact arguments. The development steps
before the freeze ran `scripts/topo-v3-dev.py experience | labels | finetune --epochs 6`.

The runner refuses to start if any of the 36 hashed files or the typed-decision weights
differ from `protocol.json`. Fine-tuning on a GPU is not bit-reproducible, so retraining
produces different weights; the frozen weights are archived as `typed-decisions.pt` (SHA-256
`f5df4faa...`), which `reproduce/frozen.py` copies to `runs/topo-v3-dev/typed/` inside the
frozen tree and the live package (`chipjev decide`, `chipjev design`) reads directly.
`reproduce/verify.py` checks every hash, the weights and both evidence archives.

The AnalogCoder-Pro flow needs `.tools/acpro-venv` (Python 3.11, PySpice 1.5, NumPy 1.26,
Optuna 4.9, openai), a shared ngspice 47 library (`--with-ngshared` into
`.tools/ngspice-shared`) and bubblewrap, all installed by `scripts/setup-analogcoder-pro.sh`.
The authors' repository is fetched at commit 05542af into `.tools/acpro`; it is not
redistributed here.
