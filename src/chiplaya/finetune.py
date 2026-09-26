"""Fine-tuning ChipLaya on development data only.

Two sources of supervision, neither of which may use test conditions or test requests:

* Parse questions: templated design requests with known (input, stages, objective).
* Topology questions: soft target distributions over each question's options, supplied
  by the application as ``labels`` ({"labels": [{"cls", "target", "vdd", "load_pf",
  "targets": {question: {option: probability}}}, ...]}). ChipLaya v1's labels were
  distilled from ChipJev's measured development searches
  (chipjev.decisions.finetune.experience_labels in https://github.com/lab-emi/ChipJev).

Trainable modules: the decision head, option scorer, type embedding and the last four
encoder layers with the final norm (35M of 322M parameters). Only those tensors are saved.
"""

import json
import math
import random
import time
from pathlib import Path

import numpy as np

from .schema import CLASS_OF, OBJECTIVE, PARSE_QUESTIONS, state_text, topology_questions

TRAINABLE_LAYERS = 4

# ------------------------------------------------------------------------ templates

VERBS = (
    "Design", "Create", "Build", "Generate", "Synthesize", "Please design", "I need",
    "Give me", "Propose", "Come up with", "Help me design", "Can you design",
)
CLASS_PHRASES = {
    ("single", "one"): (
        "a single-stage amplifier", "a one-stage voltage amplifier",
        "a single-ended amplifier with one gain stage", "a single-transistor-stage amplifier",
        "a simple one-stage amplifier with a single input",
        "an amplifier with a single gain stage and a single-ended input",
        "a single-stage, single-input amplifier", "a one-stage common-source-type amplifier",
    ),
    ("differential", "one"): (
        "a single-stage op-amp", "a one-stage operational amplifier", "a single-stage OTA",
        "a one-stage operational transconductance amplifier",
        "a differential amplifier with one gain stage",
        "a single-stage differential-input amplifier", "an op-amp with a single gain stage",
        "a one-stage opamp with inputs Vinp and Vinn",
    ),
    ("single", "several"): (
        "a multi-stage amplifier", "a two-stage amplifier with a single input",
        "a three-stage single-ended amplifier", "a cascade of gain stages with one input",
        "a multistage voltage amplifier",
        "an amplifier with several cascaded stages and a single-ended input",
        "a two- or three-stage amplifier (single input)", "a multi-stage single-input amplifier",
    ),
    ("differential", "several"): (
        "a multi-stage op-amp", "a two-stage operational amplifier", "a three-stage op amp",
        "a multistage OTA", "a differential-input amplifier with two or more gain stages",
        "a two-stage opamp with a differential input pair",
        "an op-amp with an input pair followed by more gain stages",
        "a multi-stage operational amplifier with inputs Vinp and Vinn",
    ),
}
OBJECTIVE_PHRASES = {
    "gain": (
        "that maximizes voltage gain", "with the highest DC gain", "with maximum open-loop gain",
        "for the largest low-frequency gain", "optimized for gain",
        "with as much voltage gain as possible", "maximizing its gain in dB",
    ),
    "gbw": (
        "that maximizes the gain-bandwidth product", "with the highest GBW",
        "with maximum gain-bandwidth", "optimized for GBW", "for the largest gain times bandwidth",
        "maximizing the unity-gain bandwidth product",
    ),
    "fom": (
        "that maximizes the figure of merit GBW*CL/P",
        "with the best FoM (GBW times load capacitance over power)",
        "optimized for power efficiency (GBW per power)", "maximizing GBW/Power",
        "with the highest FoM", "for the best GBW-per-milliwatt figure of merit",
    ),
}
SUFFIXES = ("", " in 45 nm CMOS", " for a low-power front end", " with ideal bias sources",
            " using standard transistors")


def request(rng, key, objective, vdd=None, load=None):
    """One templated request for (input, stages) = key and an objective."""
    text = f"{rng.choice(VERBS)} {rng.choice(CLASS_PHRASES[key])} "
    text += rng.choice(OBJECTIVE_PHRASES[objective])
    if vdd is not None and rng.random() < 0.5:
        text += f" at {vdd:g} V"
    if load is not None and rng.random() < 0.5:
        text += f" driving {load:g} pF"
    return text + rng.choice(SUFFIXES) + rng.choice((".", "", "!"))


# ------------------------------------------------------------------------ dataset

KEY_OF = {cls: key for key, cls in CLASS_OF.items()}


def parse_targets(key, objective):
    inp, stages = key
    return {
        "input": {o: float(o == inp) for o in PARSE_QUESTIONS["input"]["criteria"]},
        "stages": {o: float(o == stages) for o in PARSE_QUESTIONS["stages"]["criteria"]},
        "objective": {o: float(o == objective) for o in OBJECTIVE},
    }


def build_examples(labels, seed=0, parse_only=1800, per_condition=6):
    rng = random.Random(seed)
    examples = []
    for _ in range(parse_only):
        key = rng.choice(list(CLASS_PHRASES))
        objective = rng.choice(list(OBJECTIVE))
        vdd = rng.choice((None, 0.9, 1.0, 1.1, 1.3, 1.4))
        load = rng.choice((None, 5.0, 10.0, 30.0, 50.0, 200.0, 300.0))
        state = request(rng, key, objective, vdd, load)
        for q, target in parse_targets(key, objective).items():
            examples.append((state, PARSE_QUESTIONS[q], target))
    for entry in labels["labels"]:
        key = KEY_OF[entry["cls"]]
        questions = topology_questions(entry["cls"], entry["target"])
        for _ in range(per_condition):
            text = request(rng, key, entry["target"], entry["vdd"], entry["load_pf"])
            state = state_text(text, entry["vdd"], entry["load_pf"])
            for q, target in parse_targets(key, entry["target"]).items():
                examples.append((state, PARSE_QUESTIONS[q], target))
            for q, target in entry["targets"].items():
                examples.append((state, questions[q], target))
    rng.shuffle(examples)
    return examples


def _tensorize(tok, cfg, batch):
    from .laya_torch import QTYPES, build_sequence, render_options

    max_len, head = cfg.get("max_len", 512), cfg.get("head_max_len", 192)
    items, targets = [], []
    for state, definition, target in batch:
        criteria = definition["criteria"]
        q = {"t": definition["type"], "ins": definition["instructions"], "crit": criteria}
        ids, markers = build_sequence(tok, state, q, max_len, head)
        if len(markers) != len(render_options(q)):
            raise ValueError("question exceeds the token budget")
        items.append((ids, markers, QTYPES[q["t"]]))
        targets.append([target[o] for o in criteria])
    n, length = len(items), max(len(i[0]) for i in items)
    count = max(2, max(len(i[1]) for i in items))
    ids = np.full((n, length), tok.pad_token_id, dtype=np.int64)
    mask = np.zeros((n, length), dtype=bool)
    pos = np.zeros((n, count), dtype=np.int64)
    pmask = np.zeros((n, count), dtype=bool)
    tgt = np.zeros((n, count), dtype=np.float32)
    for row, (seq, markers, _) in enumerate(items):
        ids[row, : len(seq)] = seq
        mask[row, : len(seq)] = True
        pos[row, : len(markers)] = markers
        pmask[row, : len(markers)] = True
        tgt[row, : len(markers)] = targets[row]
    qtype = np.array([i[2] for i in items], dtype=np.int64)
    return ids, mask, pos, pmask, qtype, tgt


def trainable(model, layers=TRAINABLE_LAYERS):
    names = []
    for name, parameter in model.named_parameters():
        keep = name.startswith(("head.", "scorer.", "type_emb.", "encoder.final_norm."))
        for k in range(len(model.encoder.layers) - layers, len(model.encoder.layers)):
            keep |= name.startswith(f"encoder.layers.{k}.")
        parameter.requires_grad_(keep)
        if keep:
            names.append(name)
    return names


def train(labels, out_dir, *, seed=0, epochs=3, batch_size=32, lr=5e-5, device="cuda", examples=None):
    """Fine-tune on development examples; saves only the trainable tensors (FP16)."""
    import torch

    from .laya_torch import LayaTorch

    torch.manual_seed(seed)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    base = LayaTorch(offline=True, device=device, dtype="float32")
    model, tok, cfg = base.model, base.tok, base.cfg
    names = trainable(model)
    examples = build_examples(labels, seed=seed) if examples is None else examples
    if not examples or epochs < 1:
        raise ValueError("Training requires labeled examples and positive epochs")
    parameters = [p for p in model.parameters() if p.requires_grad]
    optimizer = torch.optim.AdamW(parameters, lr=lr, weight_decay=0.01)
    steps = epochs * math.ceil(len(examples) / batch_size)
    schedule = torch.optim.lr_scheduler.LambdaLR(
        optimizer, lambda k: min(1.0, (k + 1) / (0.05 * steps)) * max(0.0, 1 - k / steps)
    )
    model.train()
    losses, start = [], time.perf_counter()
    rng = random.Random(seed)
    for epoch in range(epochs):
        order = list(range(len(examples)))
        rng.shuffle(order)
        for b in range(0, len(order), batch_size):
            batch = [examples[k] for k in order[b : b + batch_size]]
            ids, mask, pos, pmask, qtype, tgt = (
                torch.from_numpy(a).to(device) for a in _tensorize(tok, cfg, batch)
            )
            with torch.autocast("cuda", dtype=torch.bfloat16, enabled=device == "cuda"):
                logits, _ = model(ids, mask, pos, pmask, qtype)
            logits = logits.float().masked_fill(~pmask, -1e4)
            loss = -(tgt * torch.log_softmax(logits, -1)).sum(-1).mean()
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(parameters, 1.0)
            optimizer.step()
            schedule.step()
            losses.append(float(loss))
        print(f"epoch {epoch + 1}: mean loss {np.mean(losses[-50:]):.4f}", flush=True)
    model.eval()
    state = {k: v.detach().to(torch.float16).cpu() for k, v in model.state_dict().items()
             if k in names}
    path = out_dir / "typed-decisions.pt"
    torch.save(state, path)
    from .model import sha256

    summary = {
        "examples": len(examples),
        "epochs": epochs,
        "batch_size": batch_size,
        "learning_rate": lr,
        "seed": seed,
        "trainable_tensors": len(names),
        "trainable_parameters": int(sum(model.state_dict()[k].numel() for k in names)),
        "final_loss": float(np.mean(losses[-50:])),
        "train_seconds": time.perf_counter() - start,
        "weights": str(path),
        "sha256": sha256(path),
        "labels": labels["summary"] if "summary" in labels else {"tau": labels["tau"], "uniform": labels["uniform"],
                   "conditions": sorted({(e["vdd"], e["load_pf"]) for e in labels["labels"]})},
    }
    (out_dir / "training.json").write_text(json.dumps(summary, indent=1))
    return summary


# ------------------------------------------------------------------------ evaluation

# Hand-written development requests, disjoint from the training templates.
DEV_REQUESTS = (
    ("Design a two-stage op-amp with the highest possible open-loop gain.", "opampN", "gain"),
    ("I need a single transistor-stage amplifier (single-ended input) that maximizes the "
     "gain-bandwidth product.", "amp1", "gbw"),
    ("Please build a differential-input amplifier with one gain stage and the best GBW per "
     "unit power.", "opamp1", "fom"),
    ("Create a cascade of several amplifying stages with a single input that achieves the "
     "largest FoM = GBW*CL/P.", "ampN", "fom"),
    ("Give me a one-stage operational transconductance amplifier with maximum DC gain.",
     "opamp1", "gain"),
    ("Build an amplifier made of three cascaded common-source-like stages, single-ended, for "
     "maximum bandwidth times gain.", "ampN", "gbw"),
    ("A fully differential-input, multi-stage operational amplifier optimized for power "
     "efficiency (GBW times load over power).", "opampN", "fom"),
    ("Single-ended one-stage amplifier, target: largest possible voltage gain.", "amp1", "gain"),
    ("An op amp with an input differential pair followed by a second gain stage; maximize the "
     "gain-bandwidth product.", "opampN", "gbw"),
    ("Design a simple amplifier with one stage and a single input to maximize efficiency, i.e. "
     "GBW*CL/Power.", "amp1", "fom"),
    ("Multi-stage single-input voltage amplifier with the highest low-frequency gain.", "ampN",
     "gain"),
    ("Single-stage op-amp (inputs Vinp and Vinn) with maximum unity-gain bandwidth product.",
     "opamp1", "gbw"),
)


def evaluate_parsing(weights=None, requests=DEV_REQUESTS, device="cuda"):
    from .model import ChipLaya

    model = ChipLaya(weights=weights, device=device)
    model.warm()
    rows, seconds = [], []
    for text, cls, objective in requests:
        result = model.ask(text)
        seconds.append(result["seconds"])
        rows.append({"request": text, "class": cls, "objective": objective,
                     "parsed_class": result["class"], "parsed_objective": result["objective"],
                     "correct": result["class"] == cls and result["objective"] == objective})
    return {
        "weights": model.weights,
        "correct": sum(r["correct"] for r in rows),
        "count": len(rows),
        "class_correct": sum(r["class"] == r["parsed_class"] for r in rows),
        "objective_correct": sum(r["objective"] == r["parsed_objective"] for r in rows),
        "median_ms": 1000 * float(np.median(seconds)),
        "rows": rows,
    }
