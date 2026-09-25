"""Typed decisions: the topology prior and the System Two (LLM) answer validation."""

import json

import pytest

from chipjev.circuits.grammar import library
from chipjev.decisions.typed import PARSE_QUESTIONS, topology_prior, topology_questions


def test_typed_prior_is_a_distribution_over_the_grammar():
    for cls in ("amp1", "opamp1", "ampN", "opampN"):
        questions = topology_questions(cls, "gain")
        uniform = {q: {o: 1.0 / len(d["criteria"]) for o in d["criteria"]}
                   for q, d in questions.items()}
        ids, prior = topology_prior(cls, uniform)
        assert ids == tuple(t.id for t in library(cls))
        assert prior.min() > 0 and abs(prior.sum() - 1) < 1e-12


def test_typed_prior_follows_the_answers():
    questions = topology_questions("opampN", "fom")
    answers = {q: {o: 1.0 / len(d["criteria"]) for o in d["criteria"]}
               for q, d in questions.items()}
    answers["first"] = {o: (0.96 if o == "tele" else 0.01) for o in answers["first"]}
    answers["count"] = {"2": 0.9, "3": 0.1}
    ids, prior = topology_prior("opampN", answers)
    mass = {k: sum(p for i, p in zip(ids, prior, strict=True) if i.startswith(k))
            for k in ("tele", "ota5")}
    assert mass["tele"] > 0.9 > mass["ota5"]
    stages = {t.id: len(t.stages) for t in library("opampN")}
    two = sum(p for i, p in zip(ids, prior, strict=True) if stages[i] == 2)
    assert two == pytest.approx(0.9)


def test_llm_answers_must_stay_inside_the_type():
    from chipjev.decisions.llm import validate

    questions = {**PARSE_QUESTIONS, **topology_questions("opampN", "fom")}
    answer = {q: {o: 1.0 for o in d["criteria"]} for q, d in questions.items()}
    probabilities = validate("Here: " + json.dumps(answer), questions)
    assert all(sum(p.values()) == pytest.approx(1.0) for p in probabilities.values())
    ids, prior = topology_prior("opampN", probabilities)
    assert prior.sum() == pytest.approx(1.0)
    missing = dict(answer)
    missing.pop("comp")
    with pytest.raises(ValueError):
        validate(json.dumps(missing), questions)
    outside = json.loads(json.dumps(answer))
    outside["first"]["folded"] = 0.5
    with pytest.raises(ValueError):
        validate(json.dumps(outside), questions)
    negative = json.loads(json.dumps(answer))
    negative["polarity"]["n"] = -1
    with pytest.raises(ValueError):
        validate(json.dumps(negative), questions)
    with pytest.raises(ValueError):
        validate("I would choose a folded cascode.", questions)


def test_llm_accepts_bracketed_ids_but_not_answers_outside_the_type():
    from chipjev.decisions.llm import prompt, validate

    questions = {**PARSE_QUESTIONS, **topology_questions("amp1", "fom")}
    assert "input: " in prompt("Design an amplifier.", questions)
    answer = {f"[{q}]": {f" {o} ": 1.0 for o in d["criteria"]} for q, d in questions.items()}
    probabilities = validate(json.dumps(answer), questions)
    assert set(probabilities) == set(questions)
    answer["[first]"]["[folded]"] = 0.2
    with pytest.raises(ValueError):
        validate(json.dumps(answer), questions)
