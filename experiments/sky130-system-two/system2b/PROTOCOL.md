# topo-v4 addendum system2b: System Two stage with a corrected prompt

Frozen with `scripts/topo-v4-system2b.py --freeze` before any of its runs. It replaces the
frozen `system2` stage of topo-v4, which was stopped after 38 of its 180 runs and voided
(`../DEVIATIONS.md`, item 3): the frozen prompt printed each question as "[id] text" and asked
for "the question and option ids given in brackets", and GPT-5-mini copied the brackets into
its keys ("[input]") in 21 of its first 34 calls, so answers with valid content counted as type
errors and four requests fell back to the uniform prior. The voided runs are archived.

Everything is as in `../PROTOCOL.md` (questions, tasks, testbench, methods, seeds, budgets,
endpoints and the same shuffled job list of 180 runs, executed by the frozen `run_stage` of
`scripts/topo-v4-run.py`), except the LLM decisions: `src/chipjev/topo_system2.py` prints each
question as "id: text", asks for "the words before the colons" as ids, and compares keys after
stripping surrounding whitespace, brackets and quotes. Options outside the type, missing
questions and non-numeric or negative probabilities remain type errors; the models, providers,
temperatures and the limit of three calls per request are unchanged. Laya's runs are repeated
so that the three decision engines run under the same conditions. The corrected prompt was
checked once per model on the development request (opampN-GBW, 1.0 V, 10 pF) before the freeze.
