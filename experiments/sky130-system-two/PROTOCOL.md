# topo-v4 protocol: open PDK and System One versus System Two decisions

Frozen before any test run with `scripts/topo-v4-run.py --freeze`; `protocol.json` holds the
SHA-256 of every source file, the typed-decision weights, the SKY130 model files and the
shuffled job lists. topo-v1, topo-v2 and topo-v3 are unchanged; their numbers are not pooled
with topo-v4 except where stated as a reference.

## Questions

1. **Open PDK (stage `sky130`).** On the open SkyWater SKY130 PDK, does ChipJev, with the
   method, settings and fine-tuned Laya weights frozen in topo-v3, deliver qualified designs
   sooner and better than eight-worker joint TPE and eight-worker random search?
2. **System One versus System Two (stage `system2`).** With the same search, how do Laya's
   typed decisions (System One: one non-autoregressive pass) compare with an LLM that answers
   the same typed questions (System Two: DeepSeek-V3, GPT-5-mini)? Decision latency, type
   errors, run time, time to the first qualified design and final quality.

## Tasks and testbench

* `sky130`: AnalogCoder-Pro's twelve unified task specifications ({single, multi-stage} x
  {amplifier, op-amp} x {gain, GBW, FoM}) with its statements as requests, on SKY130
  (`sky130_fd_pr__nfet_01v8`/`pfet_01v8`, TT, 27 C), VDD = 1.8 V, CL = 100 pF. The testbench,
  checks, metrics and qualification (saturation, 60-180 degree phase margin at every unity-gain
  crossing, minimum gains 20/40/40/60 dB, settling, CMRR >= 40 dB, +/-10-mV unity-buffer steps
  for op-amps) are those of topo-v2/v3 (`chipjev_topo_v2.bench.analyze`), unchanged.
  Technology mapping (`chipjev_topo_v4.sky130`): L = 150/45 x grammar length (150 nm-2.4 um),
  W = W/L x L >= 0.42 um in fingers of at most 50 um with xschem's default diffusion geometry,
  bulks at the rails, gate strengths 0.20-1.00 V mapped linearly to 0.35-1.75 V; ideal
  resistors, capacitors and bias sources. ngspice runs in the PDK's standard mode
  (`ngbehavior=hsa`). An online simulation that exceeds 2 s fails (every method); strict
  re-simulation has 60 s. Two changes from the PTM testbench, both found in development and
  applied to every method: (i) strict tolerances are reltol 1e-6, vntol 1e-9 and abstol
  1e-12 A (topo-v3: 1e-14 A), because the femtoampere gate-leakage branches of SKY130's bias
  sources make buffer transients abort ("timestep too small") at 1e-14 and 1e-13; (ii) the
  op-amp unity-buffer test also runs online (online tolerances, 2-s limit per transient), so
  that online validity and qualification apply the same checks. Without (ii), op-amps that
  pass every open-loop check at the edge of AnalogCoder-Pro's input-bias sweep (0.2 V) failed
  205 of 208 strict rechecks in a development run.
* `system2`: the twelve topo-v3 tasks (PTM 45 nm HP, 1.2 V, 100 pF, 27 C), identical
  testbench and rules.

## Methods

All searches: 1,024 evaluations, eight SPICE workers on eight physical cores, five seeds
(0-4), the same feasibility-first score and strict-failure feedback.

* `chipjev`: topo-v3 ChipJev (`Settings(prior_mix=0.5, typed_starts=4)`) with the frozen
  fine-tuned Laya decisions on CUDA, asked the parse and grammar questions of the task's
  class and objective in one pass; decision time counts.
* `tpe8`, `random8` (sky130 only): topo-v2/v3 eight-worker joint TPE (grouped multivariate,
  constant liar, 256 random starts) and random search, unchanged.
* `chipjev-deepseek`, `chipjev-gpt5mini` (system2 only): identical to `chipjev` except that
  `chipjev_topo_v4.system2.LLMDecisions` answers the same questions through OpenRouter
  (DeepSeek-V3-0324 at temperature 0 with the provider routing of the AnalogCoder-Pro runs;
  GPT-5-mini at its default). The LLM must return JSON probabilities for every option; an
  answer outside the type is repeated up to three calls in total, every call's latency counts,
  and a request without a valid answer falls back to the uniform prior (recorded).

## Endpoints

Primary, per stage:

* Qualified runs per method (of 60).
* `sky130`: task medians of the final qualified objective (failed seeds rank below all
  qualified values); numeric wins, feasibility wins, ties (within 0.5 dB or 5%) and losses of
  ChipJev against TPE's medians; time and simulations until a run's qualified incumbent
  reaches TPE's median final quality, as geometric-mean ratios of median times over the tasks
  where both medians reach it, with 95% bootstrap intervals over seeds (seed 20270926).
* `system2`: median decision latency and its ratio to Laya; type errors and failed
  decisions; median run time including decisions; median time to the first qualified design;
  task medians of each LLM variant against `chipjev` (wins, ties within 0.5 dB or 5%, losses).

Secondary: first-qualified times, simulator time-outs per method, per-task tables.

## Development before the freeze

Development checks only (no test task, no test condition): the `sky130` pipeline at
CL = 10 pF on one task per class (amp1-FoM, opamp1-GBW, ampN-gain, opampN-FoM), each method,
seed 100 (`scripts/topo-v4-run.py --dev`), and the `system2` pipeline on one PTM development
task (opampN-GBW at 1.0 V and 10 pF, each decision engine, seed 100; `--dev --stage system2`).
The development runs found the two testbench issues above; their records are kept in
`runs/topo-v4-dev/` (`sky130-before-abstol-fix`, `sky130-before-online-buffer`, and the final
check). Search settings and weights are those frozen in topo-v3 and are not tuned. Deviations
after the freeze are recorded in `DEVIATIONS.md`.
