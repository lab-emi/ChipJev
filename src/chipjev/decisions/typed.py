"""Typed decisions: ChipLaya maps a design request to grammar choices.

Every question is typed: its answer is a probability distribution over a closed set of
options, never generated text. Parse questions recover the circuit class and objective;
class-conditional topology questions return one distribution per grammar decision (input
stage, polarity, stage count, later stages, compensation, buffer). Their product is a
proper prior over the class's topologies, so any answer composes into a member of the
grammar: a type-safe decision. All questions of one request run as one batched forward
pass of the non-autoregressive encoder (CUDA, MPS or CPU).

The model, its questions and its runtime are ChipLaya (src/chiplaya, vendored from
https://github.com/lab-emi/ChipLaya at the release pinned in CHIPLAYA.json): the pinned
laya-multilingual checkpoint, optionally with fine-tuned weights for its trainable modules.
This module maps ChipLaya's answers onto ChipJev's topology grammar.
"""

import json

import numpy as np

from chiplaya.model import ChipLaya, sha256  # noqa: F401  (sha256 re-exported)
from chiplaya.schema import (  # noqa: F401  (the question schema, re-exported)
    BUFFER,
    CLASS_OF,
    COMP,
    COUNT,
    DIFF_KINDS,
    GAIN_KINDS,
    GOAL,
    INPUT,
    OBJECTIVE,
    PARSE_QUESTIONS,
    POLARITY,
    SE_KINDS,
    STAGES,
    _choice,
    state_text,
    topology_questions,
)

from ..circuits.grammar import SYMMETRIC, library
from ..paths import CHIPLAYA

# -------------------------------------------------------------------------- grammar map


def _kind_pol(stage):
    if stage in SYMMETRIC:
        return stage, None
    kind, pol = stage.rsplit("_", 1)
    return kind, pol


def decisions(topology):
    """Decision values of a grammar topology: {question: option} (later stages as a list)."""
    kind, pol = _kind_pol(topology.stages[0])
    values = {"first": kind, "polarity": pol}
    if topology.cls in ("ampN", "opampN"):
        values["count"] = str(len(topology.stages))
        values["later"] = [_kind_pol(s) for s in topology.stages[1:]]
        values["comp"] = topology.comp
    if topology.cls == "ampN":
        values["buffer"] = topology.buffer
    return values


def topology_prior(cls, probabilities, floor=1e-6):
    """Prior over library(cls) from per-question option probabilities.

    p(t) = P(first) P(polarity) [P(count) prod_k P(later_k) P(later_polarity_k)
    P(comp | count) P(buffer)], where symmetric stages (inverters) skip their polarity
    factor and P(comp | two stages) is renormalized without nested Miller. Each factor
    is normalized, so the product is a distribution over the grammar; it is renormalized
    numerically as well. Returns (topology ids, probabilities)."""

    def p(question, option):
        return max(float(probabilities[question].get(option, 0.0)), floor)

    topologies = library(cls)
    weights = []
    for topology in topologies:
        d = decisions(topology)
        w = p("first", d["first"])
        if d["polarity"] is not None:
            w *= p("polarity", d["polarity"])
        if "count" in d:
            w *= p("count", d["count"])
            for kind, pol in d["later"]:
                w *= p("later", kind)
                if pol is not None:
                    w *= p("later_polarity", pol)
            allowed = [c for c in COMP if c != "miller2" or d["count"] == "3"]
            w *= p("comp", d["comp"]) / sum(p("comp", c) for c in allowed)
        if "buffer" in d:
            w *= p("buffer", d["buffer"])
        weights.append(w)
    weights = np.array(weights, dtype=float)
    return tuple(t.id for t in topologies), weights / weights.sum()


# -------------------------------------------------------------------------- model


class TypedDecisions(ChipLaya):
    """ChipLaya's typed decisions with the topology prior over ChipJev's grammar."""

    def ask(self, request, *, vdd=None, load_pf=None, cls=None, objective=None):
        """ChipLaya's answers for one request (see ChipLaya.ask) plus the prior over the
        topologies of the asked class and objective."""
        result = super().ask(request, vdd=vdd, load_pf=load_pf, cls=cls, objective=objective)
        seconds = result.pop("seconds")
        probabilities = {k: v["probabilities"] for k, v in result["answers"].items()}
        ids, prior = topology_prior(result["topology_class"], probabilities)
        return {**result, "topologies": ids, "prior": prior.tolist(), "seconds": seconds}


def pinned():
    """The ChipLaya release ChipJev vendors and the weights it runs (CHIPLAYA.json)."""
    return json.loads(CHIPLAYA.read_text())


def released_sha256():
    """SHA-256 of ChipJev's default weights, experiments/ptm45/typed-decisions.pt: the
    pinned ChipLaya weights release."""
    return pinned()["weights"]["sha256"]


def release_label(digest):
    """"ChipLaya vX.Y.Z" for the pinned release's weights, else the release that lists these
    weights (by SHA-256), else None (weights that are no ChipLaya release)."""
    from chiplaya.weights import identify

    pin = pinned()
    if digest == pin["weights"]["sha256"]:
        return f"ChipLaya {pin['tag']}"
    version = identify(digest)
    return f"ChipLaya v{version}" if version else None


def ranked(ids, prior, count, exclude=()):
    """The `count` most probable topology ids, skipping `exclude`."""
    order = np.argsort(-np.asarray(prior), kind="stable")
    chosen = []
    for j in order:
        if ids[j] not in exclude and ids[j] not in chosen:
            chosen.append(ids[j])
        if len(chosen) == count:
            break
    return chosen


def dump(result):
    return json.dumps(result, allow_nan=False)
