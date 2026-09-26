"""Laya ranks professional-layout actions, with guidelines injected per action.

State text: the goal, the incumbent's measurements and the critic's findings
(symptoms first, within Laya's 512-token budget). Option cards: the one-knob
plan change plus the one or two knowledge cards retrieved for exactly that
action under the current symptoms. The same text goes into the trajectory
log, so fine-tuning on measured outcomes teaches Laya to use the guidelines
(retrieval-augmented fine-tuning) rather than to memorize them.
"""

from ..layout.pro.knowledge import retrieve

INSTRUCTIONS = (
    "Choose the next analog layout action most likely to improve the goal while keeping "
    "DRC, LVS and post-layout qualification. Measurements are authoritative; guidelines "
    "are advice that applies only when the symptom matches."
)


def state_text(goal, incumbent, symptoms, plan):
    m = (incumbent or {}).get("metrics", {})
    parts = [
        f"Goal {goal}.",
        f"Incumbent valid={incumbent.get('valid') if incumbent else None}; "
        f"area={incumbent.get('area_um2', 0):.0f}um2; critic={incumbent.get('critic', 0):.0f}."
        if incumbent else "No incumbent.",
        "Post-layout " + ", ".join(f"{k}={m[k]:.3g}" for k in ("gain_db", "gbw_mhz", "pm_deg", "power_uw")
                                   if isinstance(m.get(k), (int, float))) + "." if m else "",
        f"Symptoms: {', '.join(symptoms) or 'none'}.",
        "Plan " + ", ".join(f"{k}={v}" for k, v in plan.items()) + ".",
    ]
    return " ".join(p for p in parts if p)


NAMES = {
    "aspect": "block aspect ratio", "max_finger_um": "maximum finger width",
    "pair_pattern": "matched-pair pattern", "dummies": "end dummies on matched arrays",
    "single_dummies": "end dummies on single devices", "rail_um": "power rail width",
    "decap": "MOS decoupling fill", "passives": "capacitor placement",
    "shield_inputs": "grounded input shields", "refinger": "re-fingering with re-qualification",
}


def describe(field, old, new):
    """Direction-explicit action text (a small encoder needs the polarity spelled out)."""
    name = NAMES.get(field, field)
    if isinstance(new, bool):
        return f"{'enable' if new else 'disable'} {name}"
    if isinstance(new, (int, float)) and isinstance(old, (int, float)):
        return f"{'increase' if new > old else 'decrease'} {name} {old} to {new}"
    return f"change {name} from {old} to {new}"


def option_text(field, old, new, symptoms):
    cards = retrieve(field, symptoms)
    advice = " ".join(c.guideline for c in cards)
    text = describe(field, old, new) + (f". Guideline: {advice}" if advice else "")
    return text, [c.id for c in cards]


class ProLayoutDecisions:
    def __init__(self, model):
        self.model = model

    def rank(self, state, options):
        """options: {key: text}. Returns ({key: probability}, seconds, model_state)."""
        question = {"action": {"type": "choice", "instructions": INSTRUCTIONS, "criteria": options}}
        laya = getattr(self.model, "laya", None)
        model_state = state
        if laya is not None:
            from .laya_torch import build_prefix

            prefix, _ = build_prefix(laya.tok, laya._to_internal(question["action"]),
                                     laya.cfg.get("head_max_len", 192))
            room = laya.cfg.get("max_len", 512) - len(prefix) - 1
            tokens = laya.tok(model_state)["input_ids"]
            if len(tokens) > room:
                model_state = laya.tok.backend.decode(tokens[:room])
        answer, seconds = self.model._predict(model_state, question)
        return answer["action"]["probabilities"], seconds, model_state
