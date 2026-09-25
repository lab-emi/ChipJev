# topo-v4 deviations and execution notes

No frozen file, setting, task, seed or budget was changed after the freeze
(2026-09-24 23:27 CEST).

1. **Execution in parts.** The frozen, shuffled job lists were executed by two streams that
   started together: cores 0-7 ran SKY130 parts 0, 1 and 2 of 4 (`--part k/4`: every fourth
   job from k), and cores 8-15 ran the System Two stage (then its corrected rerun, item 3) and
   SKY130 part 3. The two core sets are the host's two core complexes, each with its own L3
   cache; every run still used eight physical cores. Each part keeps its own journal
   (`results.part<k>of4.jsonl`).
2. **Development records.** The development checks before the freeze are archived with the
   results, including the two runs before the testbench fixes described in PROTOCOL.md.
3. **System Two stage voided and rerun (addendum system2b).** The frozen prompt of
   `chipjev_topo_v4.system2` printed each question as "[id] text" and asked for "the question
   and option ids given in brackets". GPT-5-mini copied the brackets into its keys ("[input]")
   in 21 of its first 34 calls; the answers' content was valid, but the frozen validator counted
   them as type errors and four requests fell back to the uniform prior. Because this penalized
   the baseline for an ambiguity of our prompt, the stage was stopped at 23:47 after 38 of 180
   runs, its runs were moved to `runs/topo-v4/void/` (archived, not reported), and the complete
   stage (all three decision engines, the same job list) was rerun as the separately frozen
   addendum `system2b/` with a corrected prompt and key matching (`src/chipjev/topo_system2.py`,
   `scripts/topo-v4-system2b.py`). The SKY130 stage was not affected. Worker processes of the
   stopped runner and of the stopped development runs were terminated. SKY130 part 3 ran on
   cores 8-15 before the addendum (`runs/topo-v4/stream-b2.sh`).
