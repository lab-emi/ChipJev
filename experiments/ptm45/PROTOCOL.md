# topo-v3 protocol: typed decisions, the measured LLM flow and robustness

topo-v1 and topo-v2 stay frozen and unchanged. topo-v3 is a new versioned study on a new
host. It adds (1) typed decisions made by a Laya decision model on CUDA, (2) an end-to-end
measurement of AnalogCoder-Pro's released LLM flow, (3) two mechanism ablations and
(4) corner and mismatch checks of every delivered design. Settings, weights, source hashes
and the complete run manifest are fixed by `scripts/topo-v3-run.py --freeze` before any
test-task optimization. No positive outcome is required; every run is reported.

## Host

AMD Ryzen 9 7950X (16 cores), NVIDIA RTX 4090 (24 GB, driver 580.178.04, CUDA 13.0),
Ubuntu 24.04, ngspice 47 (KLU) built locally into `.tools`, uv-managed Python 3.13 with the
locked environment (PyTorch 2.14 cu130, Triton 3.8, Optuna 4.9). The GPU runs no other job.
Search jobs are restricted to eight distinct physical cores (0-7, one CCD).

## Typed decisions (ChipJev-TD)

A design request is answered by typed questions, each a probability distribution over a
closed option set: parse questions (input type, stage count, objective) and grammar
questions conditioned on the class and objective (input stage, input polarity, stage count,
later gain stage and its polarity, compensation, output buffer). The product of the grammar
answers is a distribution over the class's topologies (`typed.topology_prior`), so every
answer names a grammar member. The model is the pinned `laya-multilingual` checkpoint run
through the PyTorch port (`chipjev.laya_torch`, FP16 on CUDA), with its decision head,
option scorer, type embedding and last four encoder layers fine-tuned on development data
only (`chipjev_topo_v3.finetune`):

* parse labels from templated requests;
* grammar labels distilled from 72 measured development searches of the frozen topo-v2
  method: all 12 class/objective pairs at (0.9 V, 5 pF), (1.0 V, 10 pF), (1.0 V, 50 pF),
  (1.1 V, 30 pF), (1.3 V, 200 pF) and (1.4 V, 300 pF). The test condition (1.2 V, 100 pF)
  and the test statements are never used for training or selection.

The prior mix (0.5) and the number of typed starts (4) were checked on the validation
condition (1.15 V, 70 pF) only. The weights are identified by their SHA-256 in
`protocol.json`.

## Main experiment: 240 runs

The twelve AnalogCoder-Pro unified tasks (1.2 V, 100 pF, 27 C, PTM 45 nm HP), five seeds,
1,024 online evaluations and eight persistent ngspice workers per run, qualified rules of
topo-v2 (saturation, 60-180 degree phase margin at every crossing, class minimum gains,
open-loop perturbation screen, CMRR >= 40 dB and strict +/-10-mV unity-buffer steps for
op-amps; strict re-simulation of every reported incumbent).

* `chipjev`: typed decisions for the task's own AnalogCoder-Pro statement
  (`problem_set.tsv`, ids 51-62) plus the testbench conditions, then the topo-v2 search
  loop with the typed prior: the four textbook starts plus the four most probable typed
  topologies, and uniform candidates drawn from 0.5 prior + 0.5 uniform. The typed
  inference is timed as part of the run; model loading is startup, like worker creation.
* `chipjev-v2`: the frozen topo-v2 method (textbook starts and uniform candidates).
* `tpe8`, `random8`: the topo-v2 eight-worker joint TPE and random search, with the
  topo-v2 shared initial designs (four textbook and four random).

Jobs run one at a time in a shuffled order (seed 20270925).

## Ablations: 32 runs

On the multi-stage gain and FoM tasks, relative to `chipjev`:

1. `scrambled-roles`: each topology writes its slot levels to a fixed topology-specific
   permutation of its active slot columns, so a feature no longer means the same sizing
   role in different topologies (mutations still carry sizes by role). Five seeds.
2. `cpu-acquisition`: the identical method with the pathwise Thompson pass evaluated
   eagerly on the eight CPU cores in FP32 instead of the fused GPU kernel. Three seeds.

## AnalogCoder-Pro, end to end

The authors' released code (github.com/laiyao1/AnalogCoderPro, commit 05542af) runs
unchanged for tasks 51-62: its prompts, sampling temperature, three generation rounds with
error feedback, DC sweep, operating-point and function checks, and LLM parameter extraction.
The LLM is DeepSeek-V3-0324 (a base model of the paper) through OpenRouter; provider
routing prefers full-context FP8 providers. The unreleased model module is the testbench's
PTM card, and the unreleased optimizer helper runs TPE for 1,000 trials (250 random,
multivariate) from the LLM's initial values on the common testbench under the qualified
rules, with the same feasibility-first score and strict incumbent re-simulation as every
other method. Thirty attempts per task, as in the paper; each attempt is one timed process
on one core. Generated code runs in a network-less sandbox. The LLM runs were started
before the ChipJev freeze; they involve no ChipJev setting, and their harness hashes were
recorded at launch.

## Endpoints

Primary, as topo-v2: qualified runs, failure-aware median [IQR] quality and median time per
task and method; numeric wins, feasibility wins and ties (0.5 dB or a factor 1.05).

Secondary, fixed before the runs:

* Time to reference: the reference of a task is the median final quality of `tpe8`
  (within the tie band); if that median is not qualified, any qualified design. For every
  run, the first elapsed time and online-evaluation count at which a strictly qualified
  incumbent meets the reference (never: infinity). Per task, the ratio of the `tpe8`
  median to the `chipjev` median; the geometric mean over tasks where both are finite,
  with a 95% percentile bootstrap interval (10,000 resamples of seeds within tasks).
  Tasks where only one method reaches the reference are reported as feasibility outcomes.
* Typed-prior effect: `chipjev` versus `chipjev-v2` on the same endpoints.
* AnalogCoder-Pro: per task, attempts with a functional netlist (its own checks) and with a
  qualified sized design; best-of-30 quality; LLM time, tokens and cost; protocol time as
  the sum of its thirty measured attempt times, and the time until its first design that
  meets the reference, with attempts in index order.
* Typed decisions: parse accuracy on the twelve statements and on 120 held-out requests
  written by another LLM (`heldout-requests.json`, generated before the freeze), for the
  zero-shot and fine-tuned models and for DeepSeek-V3 asked the same question; median
  latency; validity of the answers.
* Robustness: for every qualified final design, strict qualification at -40 and 125 C and
  at -10% and +10% supply, and 64 mismatch samples with delvto ~ N(0, 3.5 mV um / sqrt(WL)).

## Limits

The testbench is nominal PTM 45 nm with ideal bias sources. PTM has no process corners or
mismatch data; the assumed mismatch coefficient is stated. Corner and mismatch checks
describe the delivered designs; no method optimizes for them. The LLM flow's released
parameterization keeps L = 45 nm, which is part of the measured flow. Absolute times
depend on this host and on the LLM provider's latency; LLM time is reported separately.
