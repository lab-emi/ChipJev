"""System Two decisions: an autoregressive LLM answers ChipJev's typed questions.

This is the baseline for the System One decision model (Laya). The LLM receives the same
state (design request and testbench conditions), the same typed questions and the same
option cards (typed.py) and must return, for every question, a probability for every
option as one JSON object. An answer that cannot be read as such (no JSON, a missing
question, an option outside the type, no positive probability) is a type error; the call
is repeated up to MAX_CALLS times, and the latency of every call counts. The product of the
answers is the same topology prior p(t) as Laya's (topology_prior), so the search that
follows is identical. If every call fails, the prior is uniform and the failure is recorded.

Questions are printed as "id: text", the prompt asks for the words before the colons, and
keys are compared after stripping surrounding whitespace, brackets and quotes. This is the
prompt of the paper's System Two comparison (the system2b addendum, whose records carry
prompt = "system2b"). A first prompt printed "[id] text" and asked for "the ids given in
brackets"; GPT-5-mini copied the brackets into its keys, so valid answers counted as type
errors, and that stage was voided (experiments/sky130-system-two/DEVIATIONS.md).
"""

import json
import math
import os
import time

from .typed import (
    CLASS_OF,
    PARSE_QUESTIONS,
    state_text,
    topology_prior,
    topology_questions,
)

BASE_URL = "https://openrouter.ai/api/v1"
MAX_CALLS = 3
TIMEOUT_S = 300.0
# Provider routing (transport only), as for the AnalogCoder-Pro flow.
PROVIDERS = {
    "deepseek/deepseek-chat-v3-0324": {
        "order": ["SiliconFlow", "DeepInfra"], "ignore": ["GMICloud"], "allow_fallbacks": True
    },
}
# Deterministic decoding where the model allows it; GPT-5 models accept only the default.
TEMPERATURE = {"deepseek/deepseek-chat-v3-0324": 0.0}

PROMPT = """You are an expert analog integrated-circuit designer. Answer the typed design \
questions below for this design request.

Request: {state}

For every question, give a probability for every listed option: numbers between 0 and 1 \
that sum to 1 for that question. Answer with one JSON object and nothing else, in the form \
{{"<question id>": {{"<option id>": <probability>, ...}}, ...}}, where the question ids and \
option ids are the words before the colons below.

{questions}"""


def render(questions):
    lines = []
    for qid, question in questions.items():
        lines.append(f"{qid}: {question['instructions']}")
        lines += [f"  - {oid}: {text}" for oid, text in question["criteria"].items()]
    return "\n".join(lines)


def prompt(state, questions):
    return PROMPT.format(state=state, questions=render(questions))


def _key(value):
    return str(value).strip().strip("[]\"'").strip()


def validate(text, questions):
    """{question: {option: probability}}; ValueError is a type error (see module notes)."""
    if not text or "{" not in text or "}" not in text:
        raise ValueError("no JSON object")
    answer = json.loads(text[text.index("{"): text.rindex("}") + 1])
    if not isinstance(answer, dict):
        raise ValueError("answer is not an object")
    answer = {_key(k): v for k, v in answer.items()}
    out = {}
    for qid, question in questions.items():
        given = answer.get(qid)
        if not isinstance(given, dict):
            raise ValueError(f"missing question {qid}")
        given = {_key(k): v for k, v in given.items()}
        unknown = sorted(k for k in given if k not in question["criteria"])
        if unknown:
            raise ValueError(f"options outside the type for {qid}: {unknown}")
        probabilities = {}
        for oid in question["criteria"]:
            try:
                value = float(given.get(oid, 0.0))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"non-numeric probability for {qid}/{oid}") from exc
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"invalid probability for {qid}/{oid}")
            probabilities[oid] = value
        total = sum(probabilities.values())
        if total <= 0:
            raise ValueError(f"no positive probability for {qid}")
        out[qid] = {k: v / total for k, v in probabilities.items()}
    return out


class LLMDecisions:
    """System Two counterpart of typed.TypedDecisions (same ask()), through OpenRouter."""

    def __init__(self, model, api_key=None):
        from openai import OpenAI

        key = api_key or os.environ.get("OPENROUTER_API_KEY")
        if not key:
            raise RuntimeError("OPENROUTER_API_KEY is not set")
        self.model = model
        self.client = OpenAI(api_key=key, base_url=BASE_URL, timeout=TIMEOUT_S, max_retries=0)
        self.metadata = {"model": model, "base_url": BASE_URL, "max_calls": MAX_CALLS,
                         "temperature": TEMPERATURE.get(model), "provider": PROVIDERS.get(model),
                         "prompt": "system2b"}

    def _call(self, text):
        body = {"usage": {"include": True}}
        if self.model in PROVIDERS:
            body["provider"] = PROVIDERS[self.model]
        kwargs = {"model": self.model, "messages": [{"role": "user", "content": text}],
                  "extra_body": body}
        if TEMPERATURE.get(self.model) is not None:
            kwargs["temperature"] = TEMPERATURE[self.model]
        start = time.perf_counter()
        row = {"error": None}
        try:
            reply = self.client.chat.completions.create(**kwargs)
            row["text"] = reply.choices[0].message.content or ""
            usage = reply.usage
            extra = getattr(usage, "model_extra", None) or {}
            row.update(prompt_tokens=getattr(usage, "prompt_tokens", None),
                       completion_tokens=getattr(usage, "completion_tokens", None),
                       cost=getattr(usage, "cost", None) or extra.get("cost"),
                       provider=getattr(reply, "provider", None)
                       or (getattr(reply, "model_extra", None) or {}).get("provider"))
        except Exception as exc:  # network or API failure: recorded, then retried
            row.update(text="", error=f"{type(exc).__name__}: {exc}")
        row["seconds"] = time.perf_counter() - start
        return row

    def ask(self, request, *, vdd=None, load_pf=None, cls=None, objective=None):
        """All questions (parse and grammar questions of the given class and objective) in
        one call, as Laya's single pass; repeated on type errors."""
        if cls is None or objective is None:
            raise ValueError("the System Two baseline is asked with the task's class and objective")
        state = state_text(request, vdd, load_pf)
        questions = {**PARSE_QUESTIONS, **topology_questions(cls, objective)}
        text = prompt(state, questions)
        calls, probabilities = [], None
        for _ in range(MAX_CALLS):
            row = self._call(text)
            if row["error"] is None:
                try:
                    probabilities = validate(row["text"], questions)
                except ValueError as exc:
                    row["type_error"] = str(exc)
            calls.append(row)
            if probabilities is not None:
                break
        failed = probabilities is None
        if failed:
            probabilities = {q: {o: 1.0 / len(v["criteria"]) for o in v["criteria"]}
                             for q, v in questions.items()}
        answers = {q: {"choice": max(p, key=p.get), "probabilities": p}
                   for q, p in probabilities.items()}
        ids, prior = topology_prior(cls, probabilities)
        return {
            "state": state,
            "class": CLASS_OF[(answers["input"]["choice"], answers["stages"]["choice"])],
            "objective": answers["objective"]["choice"],
            "topology_class": cls,
            "topology_objective": objective,
            "answers": answers,
            "topologies": ids,
            "prior": prior.tolist(),
            "seconds": sum(c["seconds"] for c in calls),
            "calls": [{k: c.get(k) for k in ("seconds", "error", "type_error", "prompt_tokens",
                                            "completion_tokens", "cost", "provider")}
                      for c in calls],
            "type_errors": sum(1 for c in calls if c.get("type_error")),
            "api_errors": sum(1 for c in calls if c["error"]),
            "failed": failed,
            "raw": [c.get("text", "") for c in calls],
            "prompt": "system2b",
        }
