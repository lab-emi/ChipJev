"""Typed decisions: a Laya decision model maps a design request to grammar choices.

Every question is typed: its answer is a probability distribution over a closed set of
options, never generated text. Parse questions recover the circuit class and objective;
class-conditional topology questions return one distribution per grammar decision (input
stage, polarity, stage count, later stages, compensation, buffer). Their product is a
proper prior over the class's topologies, so any answer composes into a member of the
grammar: a type-safe decision. All questions of one request run as one batched forward
pass of the non-autoregressive encoder (CUDA, MPS or CPU).

The checkpoint is the pinned laya-multilingual model (laya_torch.py), optionally with
fine-tuned weights for the trainable modules written by finetune.py.
"""

import hashlib
import json
import time
from pathlib import Path

import numpy as np

from ..circuits.grammar import SYMMETRIC, library

# -------------------------------------------------------------------------- questions

INPUT = {
    "single": "a single-ended input: one input terminal, a voltage amplifier",
    "differential": "a differential input pair: two input terminals, an op-amp or OTA",
}
STAGES = {
    "one": "one gain stage (a single-stage circuit)",
    "several": "two or more cascaded gain stages (a multi-stage circuit)",
}
OBJECTIVE = {
    "gain": "the low-frequency (DC) voltage gain",
    "gbw": "the gain-bandwidth product (GBW)",
    "fom": "the figure of merit FoM = GBW x load capacitance / power (power efficiency)",
}
CLASS_OF = {
    ("single", "one"): "amp1",
    ("differential", "one"): "opamp1",
    ("single", "several"): "ampN",
    ("differential", "several"): "opampN",
}

# Short textbook descriptions of the grammar's options ("option cards").
SE_KINDS = {
    "r": "resistor-loaded common source: low gain, wide bandwidth",
    "diode": "common source with a diode-connected load: low, well-defined gain, very fast",
    "cs": "common source with a current-source load: gain gm*ro",
    "cas": "cascode common source: high output resistance and gain (gm*ro)^2",
    "tele": "telescopic cascode: very high gain at low power, small output swing",
    "inv": "CMOS inverter: both devices amplify, high gm per current",
    "inv_cas": "cascoded CMOS inverter: very high gain and gm efficiency",
    "fold": "folded cascode: high gain, wider input range, more current",
    "sf": "source follower: gain below one, low output impedance",
}
DIFF_KINDS = {
    "ota5": "five-transistor OTA with a current-mirror load: moderate gain, fast",
    "tele": "telescopic cascode OTA: very high gain at low power, small swing",
    "fc": "folded-cascode OTA: high gain, wide input range, more power",
    "cmota": "current-mirror OTA: mirror gain raises bandwidth and slew rate",
    "rload": "resistor-loaded differential pair: low gain, wide bandwidth",
}
GAIN_KINDS = {k: SE_KINDS[k] for k in ("cs", "cas", "inv", "inv_cas")}
POLARITY = {
    "n": "NMOS input device: higher mobility and transconductance",
    "p": "PMOS input device: lower flicker noise, input near ground",
}
COUNT = {
    "2": "two gain stages: easier to stabilize",
    "3": "three gain stages: more gain, harder to stabilize",
}
COMP = {
    "none": "no compensation capacitor",
    "miller": "a Miller capacitor across the last stage (pole splitting)",
    "miller_rz": "a Miller capacitor with a nulling resistor (cancels the right-half-plane zero)",
    "miller2": "nested Miller compensation across the last two stages (three stages only)",
}
BUFFER = {
    "none": "no output buffer",
    "sf_n": "an NMOS source-follower output buffer",
    "sf_p": "a PMOS source-follower output buffer",
}


def _choice(instructions, criteria):
    return {"type": "choice", "instructions": instructions, "criteria": criteria}


PARSE_QUESTIONS = {
    "input": _choice("What kind of input does the requested circuit have?", INPUT),
    "stages": _choice("How many gain stages does the requested circuit have?", STAGES),
    "objective": _choice("Which quantity does the request ask to maximize?", OBJECTIVE),
}


GOAL = {
    "gain": "the highest DC voltage gain",
    "gbw": "the highest gain-bandwidth product",
    "fom": "the best FoM (GBW x load capacitance / power)",
}


def topology_questions(cls, objective):
    """Typed grammar questions for one circuit class and objective. The objective is part
    of each question, so the answers are conditioned on the parsed objective."""
    goal = GOAL[objective]
    differential = cls.startswith("opamp")
    first = DIFF_KINDS if differential else (SE_KINDS if cls == "amp1" else GAIN_KINDS)
    what = "differential input stage" if differential else "first (input) stage"
    questions = {
        "first": _choice(f"Which {what} gives {goal}?", first),
        "polarity": _choice(f"Which input device type gives {goal}?", POLARITY),
    }
    if cls in ("ampN", "opampN"):
        questions["count"] = _choice(f"How many gain stages give {goal}?", COUNT)
        questions["later"] = _choice(
            f"Which gain stage after the first stage gives {goal}?", GAIN_KINDS
        )
        questions["later_polarity"] = _choice(
            f"Which input device type of the following gain stages gives {goal}?", POLARITY
        )
        questions["comp"] = _choice(f"Which frequency compensation gives {goal}?", COMP)
    if cls == "ampN":
        questions["buffer"] = _choice(f"Which output buffer gives {goal}?", BUFFER)
    return questions


def state_text(request, vdd=None, load_pf=None):
    """The decision state: the designer's request plus the testbench conditions."""
    text = request.strip()
    if vdd is not None and load_pf is not None:
        text += f" Testbench: VDD = {vdd:g} V, load capacitance CL = {load_pf:g} pF."
    return text


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


class TypedDecisions:
    """Laya typed decisions for design requests, with optional fine-tuned weights."""

    def __init__(self, weights=None, device=None, dtype="float16", offline=True):
        import torch

        from .laya_torch import LayaTorch

        start = time.perf_counter()
        self.laya = LayaTorch(offline=offline, device=device, dtype=dtype, batch_size=64)
        self.weights = None
        if weights is not None:
            path = Path(weights)
            state = torch.load(path, map_location="cpu", weights_only=True)
            missing = [k for k in state if k not in self.laya.model.state_dict()]
            if missing:
                raise ValueError(f"fine-tuned weights do not match the model: {missing[:4]}")
            self.laya.model.load_state_dict(state, strict=False)
            self.laya.model.to(self.laya.device, self.laya.dtype).eval()
            self.weights = {"path": str(path), "sha256": sha256(path)}
        self.load_seconds = time.perf_counter() - start
        self.metadata = dict(self.laya.metadata, fine_tuned=self.weights)

    def warm(self, repeats=3):
        for _ in range(repeats):
            self.ask("Design a two-stage op-amp with maximum gain.", cls="opampN",
                     objective="gain")

    def ask(self, request, *, vdd=None, load_pf=None, cls=None, objective=None):
        """Typed decisions for one request: the parse questions, then the topology
        questions of the class and objective (default: the parsed ones). With both given,
        all questions run as one batched forward pass; otherwise the parse pass comes
        first. Returns the typed answers, the parsed specification, the topology prior and
        the measured latency."""
        state = state_text(request, vdd, load_pf)
        if cls is None or objective is None:
            parsed, first = self._predict(state, PARSE_QUESTIONS)
            cls = cls or CLASS_OF[(parsed["input"]["choice"], parsed["stages"]["choice"])]
            objective = objective or parsed["objective"]["choice"]
            topo, second = self._predict(state, topology_questions(cls, objective))
            answers, seconds = {**parsed, **topo}, first + second
        else:
            answers, seconds = self._predict(
                state, {**PARSE_QUESTIONS, **topology_questions(cls, objective)}
            )
        parsed_cls = CLASS_OF[(answers["input"]["choice"], answers["stages"]["choice"])]
        probabilities = {k: v["probabilities"] for k, v in answers.items()}
        ids, prior = topology_prior(cls, probabilities)
        return {
            "state": state,
            "class": parsed_cls,
            "objective": answers["objective"]["choice"],
            "topology_class": cls,
            "topology_objective": objective,
            "answers": {k: {"choice": v["choice"], "probabilities": v["probabilities"]}
                        for k, v in answers.items()},
            "topologies": ids,
            "prior": prior.tolist(),
            "seconds": seconds,
        }

    def _predict(self, state, questions):
        start = time.perf_counter()
        result = self.laya.predict(state, questions)
        return result["answers"], time.perf_counter() - start


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


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def dump(result):
    return json.dumps(result, allow_nan=False)
