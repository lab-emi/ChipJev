"""Portable PyTorch runtime for the pinned Laya multilingual checkpoint (CUDA, MPS or CPU).

This mirrors the Laya-MLX inference path used on Apple Silicon (ModernBERT encoder,
decision Transformer head, calibrated option scorer) and loads the *same* pinned FP16
safetensors, so Linux/CUDA and macOS runs share weights, prompts and calibration.
Prompt construction and calibration are adapted from laya-mlx 0.1.0 (Apache-2.0,
https://github.com/mizorewww/laya-mlx, revision fc1df62), itself adapted from upstream
Laya (https://github.com/NandhaKishorM/laya). See THIRD_PARTY_NOTICES.md.
"""

import json
import math
import time
from pathlib import Path

import numpy as np

MODEL_ID = "aac6fef/laya-multilingual-mlx"
MODEL_REVISION = "f2b4faf51023039425946074e2cf1361d2db11d5"
QTYPES = {"choice": 0, "score": 1, "noul": 2}
QTYPE_NAMES = {v: k for k, v in QTYPES.items()}


def best_device(preferred=None):
    import torch

    if preferred:
        return torch.device(preferred)
    if torch.cuda.is_available():
        return torch.device("cuda")
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


# ---------------------------------------------------------------- prompt formatting


def serialize_state(state):
    return state if isinstance(state, str) else json.dumps(state, ensure_ascii=False)


def render_criterion(value):
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(", ", ": "), default=str)


def render_options(q):
    t, crit = q["t"], q.get("crit")
    if t == "choice":
        return [
            k if v is None or v == "" else "%s: %s" % (k, render_criterion(v))
            for k, v in crit.items()
        ]
    if t == "score":
        return ["level %d: %s" % (i, render_criterion(c)) for i, c in enumerate(crit)]
    crit = crit or {}
    false_crit, true_crit = crit.get("false"), crit.get("true")
    return [
        "false: "
        + (
            render_criterion(false_crit)
            if false_crit not in (None, "")
            else "no, the statement does not hold"
        ),
        "true: "
        + (
            render_criterion(true_crit)
            if true_crit not in (None, "")
            else "yes, the statement holds"
        ),
    ]


def build_prefix(tok, q, head_max_len=192):
    mask_tok = tok.mask_token
    opts = render_options(q)
    ins = str(q["ins"]).replace(mask_tok, " ")
    head_ids = tok("%s question: %s" % (q["t"], ins))["input_ids"]
    opt_ids = [
        [tok.mask_token_id] + tok(" " + o.replace(mask_tok, " "))["input_ids"][:48] for o in opts
    ]
    opt_budget = head_max_len - sum(len(o) for o in opt_ids)
    if opt_budget < 16:
        per = max(4, (head_max_len - 16) // max(1, len(opt_ids)))
        opt_ids = [o[:per] for o in opt_ids]
        opt_budget = head_max_len - sum(len(o) for o in opt_ids)
    head_ids = head_ids[: max(8, opt_budget)]
    ids = [tok.cls_token_id] + head_ids + [tok.sep_token_id]
    markers = []
    for o in opt_ids:
        markers.append(len(ids))
        ids.extend(o)
    ids.append(tok.sep_token_id)
    return ids, markers


def build_sequence(tok, state, q, max_len=512, head_max_len=192):
    ids, markers = build_prefix(tok, q, head_max_len)
    room = max(0, max_len - len(ids) - 1)
    st = tok(serialize_state(state).replace(tok.mask_token, " "))["input_ids"][:room]
    ids = ids + st + [tok.sep_token_id]
    return ids[:max_len], [m for m in markers if m < max_len]


def temp_bucket(qtype, k):
    size = "2" if k <= 2 else "3-5" if k <= 5 else "6-10" if k <= 10 else "11+"
    return "%s:%s" % (QTYPE_NAMES[int(qtype)], size)


def confidence_from_probs(p, k):
    if k < 2:
        return 1.0
    p = p[:k]
    ent = -(p * np.log(np.clip(p, 1e-12, 1.0))).sum()
    return float(np.clip(1.0 - ent / math.log(k), 0.0, 1.0))


class Tokenizer:
    def __init__(self, path):
        from tokenizers import Tokenizer as Backend

        path = Path(path)
        self.backend = Backend.from_file(str(path / "tokenizer.json"))
        self.backend.no_padding()
        self.backend.no_truncation()
        config = json.loads((path / "tokenizer_config.json").read_text())
        for name in ("cls_token", "sep_token", "pad_token", "mask_token"):
            value = config.get(name)
            if isinstance(value, dict):
                value = value.get("content")
            token_id = self.backend.token_to_id(value) if isinstance(value, str) else None
            if token_id is None:
                raise ValueError(f"Tokenizer is missing a valid {name}")
            setattr(self, name, value)
            setattr(self, name + "_id", token_id)

    def __call__(self, text, add_special_tokens=False):
        return {"input_ids": self.backend.encode(text, add_special_tokens=add_special_tokens).ids}


# ---------------------------------------------------------------- model


def _modules():
    import torch
    from torch import nn
    from torch.nn import functional as F

    def rope(x, base):
        # Non-interleaved (rotate-half) RoPE, as mx.fast.rope(traditional=False).
        dim = x.shape[-1]
        half = dim // 2
        inv = base ** (-torch.arange(0, half, device=x.device, dtype=torch.float32) / half)
        pos = torch.arange(x.shape[-2], device=x.device, dtype=torch.float32)
        angles = pos[:, None] * inv[None, :]
        cos, sin = angles.cos().to(x.dtype), angles.sin().to(x.dtype)
        x1, x2 = x[..., :half], x[..., half:]
        return torch.cat([x1 * cos - x2 * sin, x2 * cos + x1 * sin], dim=-1)

    class Embeddings(nn.Module):
        def __init__(self, cfg):
            super().__init__()
            self.tok_embeddings = nn.Embedding(cfg["vocab_size"], cfg["hidden_size"])
            self.norm = nn.LayerNorm(cfg["hidden_size"], eps=cfg["norm_eps"], bias=False)

        def forward(self, ids):
            return self.norm(self.tok_embeddings(ids))

    class EncoderAttention(nn.Module):
        def __init__(self, cfg, base):
            super().__init__()
            self.heads = cfg["num_attention_heads"]
            self.head_dim = cfg["hidden_size"] // self.heads
            self.base = base
            size = cfg["hidden_size"]
            self.Wqkv = nn.Linear(size, 3 * size, bias=False)
            self.Wo = nn.Linear(size, size, bias=False)

        def forward(self, x, mask):
            b, length, _ = x.shape
            qkv = self.Wqkv(x).view(b, length, 3, self.heads, self.head_dim)
            q, k, v = (qkv[:, :, i].transpose(1, 2) for i in range(3))
            q, k = rope(q, self.base), rope(k, self.base)
            out = F.scaled_dot_product_attention(q, k, v, attn_mask=mask)
            return self.Wo(out.transpose(1, 2).reshape(b, length, -1))

    class EncoderMLP(nn.Module):
        def __init__(self, cfg):
            super().__init__()
            self.Wi = nn.Linear(cfg["hidden_size"], 2 * cfg["intermediate_size"], bias=False)
            self.Wo = nn.Linear(cfg["intermediate_size"], cfg["hidden_size"], bias=False)

        def forward(self, x):
            value, gate = self.Wi(x).chunk(2, dim=-1)
            return self.Wo(F.gelu(value) * gate)

    class EncoderLayer(nn.Module):
        def __init__(self, cfg, index, kind):
            super().__init__()
            self.kind = kind
            size, eps = cfg["hidden_size"], cfg["norm_eps"]
            self.attn_norm = (
                nn.Identity() if index == 0 else nn.LayerNorm(size, eps=eps, bias=False)
            )
            base = cfg["rope_base"][kind]
            self.attn = EncoderAttention(cfg, base)
            self.mlp_norm = nn.LayerNorm(size, eps=eps, bias=False)
            self.mlp = EncoderMLP(cfg)

        def forward(self, x, masks):
            x = x + self.attn(self.attn_norm(x), masks[self.kind])
            return x + self.mlp(self.mlp_norm(x))

    class ModernBert(nn.Module):
        def __init__(self, cfg):
            super().__init__()
            self.cfg = cfg
            self.embeddings = Embeddings(cfg)
            self.layers = nn.ModuleList(
                EncoderLayer(cfg, i, kind) for i, kind in enumerate(cfg["layer_types"])
            )
            self.final_norm = nn.LayerNorm(cfg["hidden_size"], eps=cfg["norm_eps"], bias=False)

        def forward(self, input_ids, attention_mask):
            x = self.embeddings(input_ids)
            valid = attention_mask.bool()
            full = valid[:, None, None, :]
            positions = torch.arange(valid.shape[1], device=valid.device)
            local = (positions[:, None] - positions[None, :]).abs() <= self.cfg[
                "local_attention"
            ] // 2
            local = (local[None, None] | ~valid[:, None, :, None]) & full
            masks = {"full_attention": full, "sliding_attention": local}
            for layer in self.layers:
                x = layer(x, masks)
            return self.final_norm(x)

    class HeadAttention(nn.Module):
        """PyTorch MultiheadAttention parameter layout (in_proj_weight / out_proj)."""

        def __init__(self, dims):
            super().__init__()
            self.heads = max(1, dims // 64)
            self.head_dim = dims // self.heads
            self.in_proj_weight = nn.Parameter(torch.empty(3 * dims, dims))
            self.in_proj_bias = nn.Parameter(torch.empty(3 * dims))
            self.out_proj = nn.Linear(dims, dims)

        def forward(self, x, mask):
            b, length, _ = x.shape
            qkv = F.linear(x, self.in_proj_weight, self.in_proj_bias)
            qkv = qkv.view(b, length, 3, self.heads, self.head_dim)
            q, k, v = (qkv[:, :, i].transpose(1, 2) for i in range(3))
            out = F.scaled_dot_product_attention(q, k, v, attn_mask=mask)
            return self.out_proj(out.transpose(1, 2).reshape(b, length, -1))

    class HeadLayer(nn.Module):
        def __init__(self, dims):
            super().__init__()
            self.self_attn = HeadAttention(dims)
            self.norm1 = nn.LayerNorm(dims)
            self.norm2 = nn.LayerNorm(dims)
            self.linear1 = nn.Linear(dims, 4 * dims)
            self.linear2 = nn.Linear(4 * dims, dims)

        def forward(self, x, mask):
            x = x + self.self_attn(self.norm1(x), mask)
            # torch.nn.TransformerEncoderLayer's default activation is ReLU.
            return x + self.linear2(F.relu(self.linear1(self.norm2(x))))

    class DecisionHead(nn.Module):
        def __init__(self, dims, count):
            super().__init__()
            self.layers = nn.ModuleList(HeadLayer(dims) for _ in range(count))

        def forward(self, x, mask):
            for layer in self.layers:
                x = layer(x, mask)
            return x

    class DecisionModel(nn.Module):
        def __init__(self, encoder_cfg, agent_cfg):
            super().__init__()
            dims = encoder_cfg["hidden_size"]
            self.encoder = ModernBert(encoder_cfg)
            self.head = DecisionHead(dims, agent_cfg.get("head_layers", 2))
            self.type_emb = nn.Embedding(3, dims)
            self.scorer = nn.Sequential(
                nn.LayerNorm(dims), nn.Linear(dims, dims), nn.GELU(), nn.Linear(dims, 1)
            )
            self.act_head = nn.Sequential(
                nn.Linear(dims + 4, 256),
                nn.GELU(),
                nn.Linear(256, len(agent_cfg.get("act_costs", {})) + 1),
            )
            self.register_buffer("temperature", torch.ones(3))

        def forward(self, input_ids, attention_mask, marker_pos, marker_mask, qtype):
            h = self.encoder(input_ids, attention_mask)
            h = h + self.type_emb(qtype)[:, None, :]
            h = self.head(h, attention_mask.bool()[:, None, None, :])
            rows = torch.arange(h.shape[0], device=h.device)[:, None]
            markers = h[rows, marker_pos.clamp(min=0)]
            logits = self.scorer(markers).squeeze(-1).float()
            logits = torch.where(marker_mask, logits, torch.full_like(logits, -1e4))
            p = logits.softmax(-1)
            k = marker_mask.sum(-1).clamp(min=2).float()
            entropy = -(p * p.clamp(min=1e-9).log()).sum(-1) / k.log()
            top = p.sort(-1).values[:, -2:]
            features = torch.stack([top[:, 1], top[:, 1] - top[:, 0], entropy, k / 255.0], -1)
            pooled = torch.cat([h[:, 0].float(), features], -1)
            action = self.act_head(pooled.to(self.act_head[0].weight.dtype)).float()
            return logits, action

    return DecisionModel


def encoder_config(raw):
    cfg = {
        "vocab_size": raw["vocab_size"],
        "hidden_size": raw["hidden_size"],
        "intermediate_size": raw["intermediate_size"],
        "num_attention_heads": raw["num_attention_heads"],
        "norm_eps": raw.get("norm_eps", 1e-5),
        "local_attention": raw.get("local_attention", 128),
    }
    if raw.get("model_type", "modernbert") != "modernbert":
        raise ValueError("Laya requires a ModernBERT encoder")
    if raw.get("hidden_activation", "gelu") != "gelu" or raw.get("norm_bias", False):
        raise ValueError("Unsupported ModernBERT variant")
    if raw.get("attention_bias", False) or raw.get("mlp_bias", False):
        raise ValueError("Unsupported ModernBERT variant")
    layers = raw["num_hidden_layers"]
    every = raw.get("global_attn_every_n_layers", 3)
    cfg["layer_types"] = raw.get("layer_types") or [
        "full_attention" if i % every == 0 else "sliding_attention" for i in range(layers)
    ]
    rope = raw.get("rope_parameters") or {}
    cfg["rope_base"] = {
        "full_attention": float(
            rope.get("full_attention", {}).get("rope_theta", raw.get("global_rope_theta", 160000.0))
        ),
        "sliding_attention": float(
            rope.get("sliding_attention", {}).get(
                "rope_theta", raw.get("local_rope_theta", 10000.0)
            )
        ),
    }
    for kind in ("full_attention", "sliding_attention"):
        if rope.get(kind, {}).get("rope_type", "default") != "default":
            raise ValueError("Only default ModernBERT RoPE is supported")
    return cfg


def torch_names(weights):
    """Map the published MLX-layout names back to the PyTorch module layout."""
    result = {}
    for name, value in weights.items():
        name = name.replace(".in_proj.weight", ".in_proj_weight")
        name = name.replace(".in_proj.bias", ".in_proj_bias")
        for prefix in ("scorer", "act_head"):
            name = name.replace(prefix + ".layers.", prefix + ".")
        if name in result:
            raise ValueError(f"Duplicate Laya parameter after renaming: {name}")
        result[name] = value
    return result


class LayaTorch:
    """Laya typed decisions with the pinned checkpoint on any PyTorch device."""

    def __init__(self, offline=True, device=None, dtype="float16", batch_size=64):
        import torch
        from huggingface_hub import snapshot_download
        from safetensors.torch import load_file

        start = time.perf_counter()
        self.device = best_device(device)
        if self.device.type == "cpu" and dtype == "float16":
            dtype = "float32"  # CPU half-precision kernels are slow and less complete
        self.dtype = {
            "float16": torch.float16,
            "bfloat16": torch.bfloat16,
            "float32": torch.float32,
        }[dtype]
        self.batch_size = batch_size
        path = Path(
            snapshot_download(
                MODEL_ID,
                revision=MODEL_REVISION,
                allow_patterns=["*.json", "*.safetensors", "tokenizer/*", "LICENSE*", "NOTICE*"],
                local_files_only=offline,
            )
        )
        self.cfg = json.loads((path / "rl_agent_config.json").read_text())
        raw = json.loads((path / "encoder/config.json").read_text())
        self.tok = Tokenizer(path / "tokenizer")
        self.temperature = self.cfg.get("temperature", [1.0, 1.0, 1.0])
        self.temperature_by_options = self.cfg.get("temperature_by_options", {})
        model = _modules()(encoder_config(raw), self.cfg)
        weights = torch_names(load_file(str(path / "model.safetensors")))
        missing, unexpected = model.load_state_dict(weights, strict=False)
        if missing or unexpected:
            raise RuntimeError(f"Laya weights do not match: {missing[:4]} {unexpected[:4]}")
        self.model = model.to(self.device, self.dtype).eval()
        self.path = path
        self.metadata = {
            "model": MODEL_ID,
            "revision": MODEL_REVISION,
            "precision": dtype,
            "runtime": f"pytorch-{torch.__version__}",
            "device": str(self.device)
            + (f" ({torch.cuda.get_device_name(0)})" if self.device.type == "cuda" else ""),
        }
        self.load_seconds = time.perf_counter() - start

    @staticmethod
    def _to_internal(qdef):
        kind = qdef.get("type")
        if kind not in QTYPES or "instructions" not in qdef:
            raise ValueError("Invalid Laya question")
        criteria = qdef.get("criteria")
        if kind == "choice" and isinstance(criteria, list):
            criteria = dict.fromkeys(criteria)
        instructions = qdef["instructions"]
        if not isinstance(instructions, str):
            instructions = json.dumps(instructions)
        return {"t": kind, "ins": instructions, "crit": criteria}

    def predict(self, state, questions):
        import torch

        items, internal = [], []
        max_len, head = self.cfg.get("max_len", 512), self.cfg.get("head_max_len", 192)
        for qid, definition in questions.items():
            q = self._to_internal(definition)
            ids, markers = build_sequence(self.tok, state, q, max_len, head)
            if len(markers) != len(render_options(q)):
                raise ValueError(f"Question {qid!r} has too many options for the token budget")
            items.append({"ids": ids, "markers": markers, "qtype": QTYPES[q["t"]]})
            internal.append(q)
        answers, keys = {}, list(questions)
        for start in range(0, len(items), self.batch_size):
            chunk = items[start : start + self.batch_size]
            n, length = len(chunk), max(len(i["ids"]) for i in chunk)
            count = max(2, max(len(i["markers"]) for i in chunk))
            ids = np.full((n, length), self.tok.pad_token_id, dtype=np.int64)
            mask = np.zeros((n, length), dtype=bool)
            pos = np.zeros((n, count), dtype=np.int64)
            pmask = np.zeros((n, count), dtype=bool)
            for row, item in enumerate(chunk):
                ids[row, : len(item["ids"])] = item["ids"]
                mask[row, : len(item["ids"])] = True
                pos[row, : len(item["markers"])] = item["markers"]
                pmask[row, : len(item["markers"])] = True
            qtype = np.array([i["qtype"] for i in chunk], dtype=np.int64)
            with torch.inference_mode():
                tensors = [
                    torch.from_numpy(a).to(self.device) for a in (ids, mask, pos, pmask, qtype)
                ]
                logits, act = self.model(*tensors)
                logits, act = logits.cpu().numpy(), act.cpu().numpy()
            if not np.isfinite(logits).all():
                raise FloatingPointError("Non-finite Laya outputs")
            act = np.exp(act - act.max(axis=-1, keepdims=True))
            act /= act.sum(axis=-1, keepdims=True)
            for row, item in enumerate(chunk):
                qid, q = keys[start + row], internal[start + row]
                k, qt = len(item["markers"]), item["qtype"]
                scale = self.temperature_by_options.get(temp_bucket(qt, k), self.temperature[qt])
                z = logits[row, :k] / max(1e-3, float(scale))
                p = np.exp(z - z.max())
                p /= p.sum()
                answer = {
                    "type": q["t"],
                    "confidence": round(confidence_from_probs(p, k), 4),
                    "action": {"act_probability": round(float(act[row, 0]), 4)},
                }
                if q["t"] == "choice":
                    labels = list(q["crit"])
                    answer.update(
                        choice=labels[int(p.argmax())],
                        probabilities={lb: round(float(v), 4) for lb, v in zip(labels, p)},
                    )
                elif q["t"] == "score":
                    answer.update(
                        score=round(float((np.arange(k) * p).sum()), 4),
                        probabilities={str(i): round(float(v), 4) for i, v in enumerate(p)},
                    )
                else:
                    answer.update(
                        noul=round(float(p[1]), 4),
                        confidence=round(max(float(p[1]), 1.0 - float(p[1])), 4),
                    )
                answers[qid] = answer
        return {
            "model": "laya-rl-agent",
            "answers": answers,
            "usage": {"input_tokens": sum(len(i["ids"]) for i in items), "output_tokens": 0},
        }
