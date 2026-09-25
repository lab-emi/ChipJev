# topo-v3 deviations and execution notes

No frozen file, setting, task, seed or budget was changed after the freeze
(2026-09-24 18:31 CEST). The notes below record how the frozen stages were executed.

1. **LLM client in the project environment.** The typed stage's LLM-parse baseline imports
   the OpenAI client, which the locked project environment does not contain. The first
   typed-stage execution completed the Laya evaluations and then stopped at that import
   before writing any result. `openai==3.19.2` (the version already used by the
   AnalogCoder-Pro environment) was installed into the local `.venv` without changing
   `uv.lock` or any hashed file, and the stage was rerun unchanged. A fresh `uv sync` removes
   the package again; reinstall it before rerunning that stage.
2. **Concurrent execution.** The AnalogCoder-Pro attempts (cores 8-15, network-bound for
   most of each attempt) overlapped with the typed and ablation stages (cores 0-7 and the
   GPU). The rerun typed stage additionally ran on the SMT siblings of cores 0-7 while the
   ablation stage ran, so its Laya latency figures include that contention; the main stage
   records the latency of every typed call again. The main stage started only after the
   last AnalogCoder-Pro attempt had finished.
3. **Additions after the freeze, reported as such.** (a) A check of AnalogCoder-Pro's flow
   with GPT-5-mini, the model named in its released README, with 10 attempts per task
   (`scripts/acpro-llm-run.py --model openai/gpt-5-mini --attempts 10`). (b) A post-hoc
   diagnosis of every extracted AnalogCoder-Pro design at the LLM's own sizes
   (`scripts/acpro-diagnose.py`). (c) The descriptive time for ChipJev to match
   AnalogCoder-Pro's best-of-30 designs. (d) Latency microbenchmarks of the typed decisions
   (`scripts/typed-latency.py`) and the acquisition kernel (`scripts/topo-latency.py`) on
   the idle host. (e) A lenient-extraction rerun for the GPT-5-mini check
   (`scripts/acpro-lenient.py`): AnalogCoder-Pro's released `extract_code` keeps only the
   last fenced code block of the parameter-extraction answer. GPT-5-mini often splits that
   answer into three blocks (`create_circuit`, `param_ranges_definition`, `initial_params`),
   so the sizing helper receives only the last one and the attempt ends as unusable code;
   DeepSeek-V3 answered in one block (1 of 253 extractions unusable, for an unrelated
   import error). For every unusable multi-block answer, the check joins all blocks, applies
   the same clean-up and reruns the same helper (same seed, trials, testbench and strict
   verification) in the same sandbox, without any LLM call. Both counts are reported; the
   released-flow results are unchanged. None of these changes a frozen endpoint.
4. **Lint.** `scripts/topo-v3-run.py` and `scripts/topo-v3-dev.py` were frozen with three
   Ruff style findings (import grouping and one unused import). They are left unchanged so
   that their hashes keep matching `protocol.json`.
