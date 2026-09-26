"""Laya ranks finite physical actions from explicit goals and measured feedback.

No free-form EDA commands, invented PDK numbers, or claim of expert layout
training. The caller may supply the already resident TypedDecisions instance.
"""

import json
from collections import Counter


def state_text(state):
    """Put measured feedback ahead of optional detail in Laya's bounded context."""
    goal = state["goal"]
    latest = state["history"][-1]
    failed = [k for k, v in (latest.get("checks") or {}).items() if not v]
    failed += [k for k, v in (latest.get("qualification_checks") or {}).items() if not v]
    if latest.get("error"):
        failed.append(str(latest["error"])[:100])
    measured = {**(latest.get("metrics") or {}), **(latest.get("quality") or {})}
    keys = list(dict.fromkeys([
        *goal.get("minimum", {}), *goal.get("maximum", {}),
        "area_um2", "gain_db", "gbw_mhz", "pm_deg", "input_noise_rms_v",
        "psrr_min_db", "internal_supply_drop_v", "input_cap_imbalance_ff", "centroid_error_um",
    ]))
    values = "; ".join(f"{k}={measured[k]:.4g}" for k in keys
                       if isinstance(measured.get(k), (int, float)))
    limits = {k: goal.get(k, {}) for k in ("minimum", "maximum")}
    plan = latest["plan"]
    roles = Counter(g["role"] for g in state["groups"])
    return "\n".join([
        f"Goal {goal['objective']}; last feasible={latest['valid']}; failed={','.join(failed) or 'none'}.",
        values,
        "Bounds " + json.dumps(limits, separators=(",", ":")),
        f"Plan {plan['pattern']}; columns={plan['columns']}; row={plan['fingers_per_row']}; "
        f"split={plan['split']}; rail={plan['rail_multiplier']}; decap={plan['decap_pf']}pF; "
        f"dummies={plan['dummies']}; separator={plan['shield_inputs']}.",
        f"Roles {dict(roles)}; PDK {state['technology']}; fixed bias={state['fixed_input_bias_v']:.4g}V; "
        f"remaining={state['remaining_seconds']:.3g}s.",
    ])


class LayoutDecisions:
    def __init__(self, model):
        self.model = model

    def rank(self, state, candidates):
        # Six concise cards fit the pinned encoder's 512-token budget. IDs are
        # local typed choices; full immutable plans remain in the saved trace.
        candidates = candidates[:6]
        cards = {
            f"a{i}": f"{action}: {getattr(p, action)}; {p.columns} columns, "
            f"{p.fingers_per_row}/row, {p.pattern}, split {p.split}"
            for i, (action, p) in enumerate(candidates)
        }
        question = {
            "action": {
                "type": "choice",
                "instructions": "Choose the next legal analog layout action most likely to improve "
                "the stated goal without violating measured circuit constraints. "
                "Measurements are authoritative; proxies are uncertain.",
                "criteria": cards,
            }
        }
        model_state = state_text(state)
        laya = getattr(self.model, "laya", None)
        token_count = None
        omitted = False
        if laya is not None:
            from .laya_torch import build_prefix

            prefix, _ = build_prefix(laya.tok, laya._to_internal(question["action"]),
                                     laya.cfg.get("head_max_len", 192))
            room = laya.cfg.get("max_len", 512) - len(prefix) - 1
            tokens = laya.tok(model_state)["input_ids"]
            token_count = len(tokens)
            omitted = token_count > room
            if omitted:
                model_state = laya.tok.backend.decode(tokens[:room])
        answer, seconds = self.model._predict(model_state, question)
        probabilities = {
            p.id: answer["action"]["probabilities"][f"a{i}"] for i, (_, p) in enumerate(candidates)
        }
        ranked = sorted(candidates, key=lambda item: -probabilities[item[1].id])
        return ranked, {
            "seconds": seconds,
            "probabilities": probabilities,
            "state": state,
            "model_state": model_state,
            "model_state_tokens": token_count,
            "model_state_truncated": omitted,
            "policy": "Laya typed action prior; EDA determines acceptance",
        }
