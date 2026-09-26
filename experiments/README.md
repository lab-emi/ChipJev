# Experiments

Two frozen studies produce every number of the paper. Each directory holds its preregistered
protocol (`PROTOCOL.md`, `protocol.json`), execution notes (`DEVIATIONS.md`), the evidence
archive (`results/`, checksummed by `results/MANIFEST.json`), the generated report (`report/`)
and further evidence listed in the study's `MANIFEST.json`.

| Directory | Protocol id (frozen) | Content | Paper |
|---|---|---|---|
| [ptm45/](ptm45/README.md) | topo-v3 (2026-09-24 18:31 CEST) | AnalogCoder-Pro's twelve tasks on PTM 45 nm: ChipJev versus AnalogCoder-Pro's released LLM flow, eight-worker TPE and random search; typed decisions, ablations, corners and mismatch; the fine-tuned weights `typed-decisions.pt` | Table I, Fig. 2, Table II |
| [sky130-system-two/](sky130-system-two/README.md) | topo-v4 (23:27) and its addendum topo-v4-system2b (23:50, `system2b/`) | the same tasks on the open SKY130 PDK; System One (Laya) versus System Two (LLM) decisions; xschem export | Table III, Table II |

The task specification of both studies is `src/chipjev/tasks.json` (`chipjev tasks`).

## Frozen names

The protocols were frozen before the repository was organized by function. `PROTOCOL.md`,
`protocol.json`, `DEVIATIONS.md` and the evidence therefore name the code, the scripts and the
directories as they were then, and they are never edited. The original code is supplied
separately as `reproduce/frozen-code.tar.gz`; see the optional source snapshot requirements
in [reproduce/README.md](../reproduce/README.md). Once restored, a rerun executes it in its
original layout (`.venv/bin/python reproduce/frozen.py`), and `reproduce/verify.py` checks
that it holds every hashed file. Without it, verification checks the recorded member hashes.
Where the same code lives in the current package:

| Frozen name | Current name |
|---|---|
| `experiments/topo-v3/`, `experiments/topo-v4/` | `experiments/ptm45/`, `experiments/sky130-system-two/` |
| `experiments/topo-v1/tasks-test.json` | `src/chipjev/tasks.json` |
| `chipjev_topo.grammar`, `.published` | `chipjev.circuits.grammar`, `.published` |
| `chipjev_topo.space`, `chipjev_topo_v2.space`, `chipjev_topo_v3.space` | `chipjev.circuits.space.ClassSpace` (options `carry_sizes`, `prior`, `roles`) |
| `chipjev_topo_v4.sky130` | `chipjev.circuits.sky130_devices` |
| `chipjev_topo_v2.bench` (+ `qualification`) | `chipjev.simulation.analysis` (measurement) and `chipjev.simulation.ptm45` (PTM deck, evaluation, unity-buffer test) |
| `chipjev_topo_v4.bench` | `chipjev.simulation.sky130` |
| `chipjev_topo_v3.robustness` | `chipjev.simulation.robustness` |
| `chipjev.research.pdk` | `chipjev.simulation.pdk` |
| `chipjev_topo/models/ptm45hp.pm` | `chipjev/simulation/models/ptm45hp.pm` |
| `chipjev.rt.surrogate`, `chipjev_topo.gp` | `chipjev.surrogate.gp` (`BatchedGP`, `TopoGP`) |
| `chipjev.rt.kernels`, `chipjev_topo.kernels` | `chipjev.surrogate.grid_kernel`, `chipjev.surrogate.pool_kernel` |
| `chipjev_topo_v2.search.ChipJevTopo` (method id `chipjev-v2`) | `chipjev.search.loop.ChipJevSearch.run(prior=None)` |
| `chipjev_topo_v3.search.ChipJevTopo` (method id `chipjev`) | `chipjev.search.loop.ChipJevSearch.run(prior=...)` |
| `chipjev_topo_v2.search.Evaluator`, `chipjev_topo_v4.search.Evaluator` | `chipjev.search.evaluator.Evaluator(workers, technology=...)` |
| `chipjev_topo_v2.baselines` (`tpe8`, `random8`), `chipjev_topo.baselines` (their helpers) | `chipjev.search.baselines` |
| `chipjev_topo.bench`, `.search`, `.provenance` (the first study's testbench, search and guard; hashed but superseded or unused) | no counterpart (removed as unreachable) |
| `chipjev.laya_torch`, `chipjev_topo_v3.typed`, `.finetune` | `chiplaya.laya_torch` (the vendored ChipLaya package, `src/chiplaya/laya_torch.py`, byte-identical), `chipjev.decisions.typed` (questions from `chiplaya.schema`), `chipjev.decisions.finetune` (trainer from `chiplaya.finetune`) |
| `chipjev_topo_v4.system2`, `chipjev.topo_system2` (system2b prompt) | `chipjev.decisions.llm` (the system2b prompt) |
| `chipjev_topo_v3.acpro`, `.netlist` | `chipjev.analogcoder_pro.helper`, `.netlist` |
| `chipjev.topo_xschem`, `chipjev.rt.provenance` | `chipjev.xschem`, `chipjev.provenance` |
| `scripts/typed-decide.py` | `chipjev decide` |
| `scripts/topo-v3-report.py`, `scripts/topo-v4-report.py` | `reproduce/report_ptm45.py`, `reproduce/report_sky130_system_two.py` |
| `scripts/verify-frozen.py`, `scripts/reproduce-paper.sh` | `reproduce/verify.py`, `reproduce/reproduce-paper.sh` |
| `scripts/setup-linux.sh`, `setup-research.sh`, `setup-acpro.sh` | `scripts/setup.sh`, `scripts/setup-analogcoder-pro.sh` |
| `tests/test_topo*.py`, `test_rt_surrogate.py` | `tests/test_*.py` by function |
| paper macros `\VThree*`, `\VFour*` | `\Ptm*`, `\Sky*`, `\SysTwo*` (same values) |
| runners, post-hoc and archive scripts (`scripts/topo-v3-run.py`, `topo-v4-run.py`, `topo-v4-system2b.py`, `acpro-llm-run.py`, ...) | unchanged in the frozen code; run through `reproduce/frozen.py exec` |

`tests/test_equivalence.py` checks the map: the same deterministic inputs through the frozen
code and the current package (grammar and netlists, the design space with every option, the
surrogates, typed decisions, both testbenches and their ngspice records, the worker pool on
both technologies, seeded search traces with and without the prior, the TPE and random
baselines, robustness checks, the AnalogCoder-Pro pieces, xschem schematics) give identical
results.
