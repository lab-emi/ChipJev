# Development record of the PTM 45 nm study (protocol topo-v3)

Everything here precedes the freeze and uses development conditions only. The test
condition (1.2 V, 100 pF) and the test statements were never used for training or selection.

* `experience-results.jsonl`: 72 searches without typed decisions (the frozen search of the
  previous study, topo-v2), all twelve class/objective pairs at six supply/load conditions,
  one seed each; every run qualified. The raw run records and
  the stage log are archived in `experience-runs.tar.gz` (extract into `runs/topo-v3-dev/` of
  the frozen tree, `runs/frozen`).
* `labels.json`: soft grammar labels distilled from those runs
  (`chipjev.decisions.finetune.experience_labels`).
* `training.json`: the training record of the frozen typed-decision weights
  (objective-conditioned grammar questions, six epochs, 8,532 examples). The weights
  themselves are archived as `../typed-decisions.pt` (SHA-256 `f5df4f...`, the hash in
  `../protocol.json`); the frozen runners read them from `runs/topo-v3-dev/typed/` inside the
  frozen tree, where `reproduce/frozen.py` places them.
* `training-classlevel.json`: an earlier model whose grammar questions did not name the
  objective. Its priors were nearly objective-independent, so the questions were changed.
* `validation-*-prior.json.gz`: the class-level and the frozen model at the validation
  condition (1.15 V, 70 pF), typed prior versus the search without typed decisions (two and
  three seeds per task). With the frozen model, the prior reached that search's median about 1.6x
  sooner (geometric mean over nine tasks where both arms reached it) and found the first
  qualified design about 1.5x sooner; op-amp GBW/FoM gained most, and the multi-stage
  op-amp gain task varied strongly across seeds in both arms.
* `parsing-development.json`: 11/12 hand-written development requests parsed correctly by
  the frozen model (one "GBW per unit power" request read as GBW).

A third model trained after adding more FoM phrasings parsed all twelve development
requests, but its grammar priors differed substantially and were not validated, so it
was discarded; the training templates were restored to those of the frozen model.
