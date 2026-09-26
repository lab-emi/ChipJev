"""Fine-tuning the typed decisions on development data only.

Two sources of supervision, neither of which uses the test condition or test requests:

* Parse questions: templated design requests with known (input, stages, objective).
* Topology questions: soft labels distilled from measured development searches. For each
  task condition and grammar decision, an option's score is the best online-qualified
  objective among all designs that used it; the target distribution is a softmax of the
  score deficit to the best option (2 dB for gain, 0.05 decade for log GBW and FoM),
  mixed with 5% uniform mass. Options that never qualified sit two temperatures below the
  worst qualified option.

Trainable modules: the decision head, option scorer, type embedding and the last four
encoder layers with the final norm (35M of 322M parameters). Only those tensors are saved.

The request templates, the dataset, the trainer and the parsing evaluation are ChipLaya's
(chiplaya.finetune, re-exported here); the grammar labels below are ChipJev's.
"""

import gzip
import json
import math
from pathlib import Path

import numpy as np

from chiplaya.finetune import (  # noqa: F401  (ChipLaya's trainer, re-exported)
    CLASS_PHRASES,
    DEV_REQUESTS,
    KEY_OF,
    OBJECTIVE_PHRASES,
    SUFFIXES,
    TRAINABLE_LAYERS,
    VERBS,
    build_examples,
    evaluate_parsing,
    parse_targets,
    request,
    train,
    trainable,
)

from ..circuits.grammar import library
from .typed import decisions, topology_questions

TAU = {"gain": 2.0, "gbw": 0.05, "fom": 0.05}
UNIFORM = 0.05

# ------------------------------------------------------------------------ labels


def experience_labels(rows, run_dir):
    """Soft labels per development task condition from its measured search records."""
    spaces, entries = {}, []
    for row in rows:
        cls, target = row["cls"], row["target"]
        spaces.setdefault(cls, {t.id: t for t in library(cls)})
        with gzip.open(Path(run_dir) / row["run_file"], "rt") as stream:
            result = json.load(stream)
        best = {}
        for record in result["records"]:
            if not record.get("valid") or record.get("objective") is None:
                continue
            topology = spaces[cls].get(record["topology"])
            if topology is None:
                continue
            value = float(record["objective"])
            for question, option in _options(decisions(topology)):
                key = (question, option)
                best[key] = max(best.get(key, -math.inf), value)
        questions = topology_questions(cls, target)
        targets = {}
        for question, definition in questions.items():
            options = list(definition["criteria"])
            scores = np.array([best.get((question, o), -math.inf) for o in options])
            if not np.isfinite(scores).any():
                targets[question] = {o: 1.0 / len(options) for o in options}
                continue
            tau = TAU[target]
            floor = scores[np.isfinite(scores)].min() - 2 * tau
            scores = np.where(np.isfinite(scores), scores, floor)
            p = np.exp((scores - scores.max()) / tau)
            p = (1 - UNIFORM) * p / p.sum() + UNIFORM / len(options)
            targets[question] = {o: float(v) for o, v in zip(options, p, strict=True)}
        entries.append(
            {"cls": cls, "target": target, "vdd": row["vdd"], "load_pf": row["load_pf"],
             "seed": row["seed"], "targets": targets,
             "qualified_designs": int(sum(1 for r in result["records"] if r.get("valid")))}
        )
    return {"tau": TAU, "uniform": UNIFORM, "labels": entries}


def _options(values):
    yield "first", values["first"]
    if values["polarity"] is not None:
        yield "polarity", values["polarity"]
    if "count" in values:
        yield "count", values["count"]
        for kind, pol in values["later"]:
            yield "later", kind
            if pol is not None:
                yield "later_polarity", pol
        yield "comp", values["comp"]
    if "buffer" in values:
        yield "buffer", values["buffer"]
