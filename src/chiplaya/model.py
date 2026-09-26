"""ChipLaya: typed decisions for analog amplifier design requests.

The model is the pinned Laya multilingual checkpoint (laya_torch.py) with ChipLaya's
fine-tuned values of its decision head, option scorer, type embedding, final norm and last
four encoder layers (weights.py). All questions of one request run as one batched forward
pass of the non-autoregressive encoder (CUDA, MPS or CPU).
"""

import hashlib
import time
from pathlib import Path

from .schema import CLASS_OF, PARSE_QUESTIONS, state_text, topology_questions


class ChipLaya:
    """Laya typed decisions for design requests, with optional fine-tuned weights.

    ``weights`` is a fine-tuned state file (None: the base Laya checkpoint);
    ``expected_sha256`` rejects any other file. ``offline`` resolves the base checkpoint
    from the local Hugging Face cache only. ``ChipLaya.pretrained()`` downloads both.
    """

    def __init__(self, weights=None, device=None, dtype="float16", offline=True,
                 expected_sha256=None):
        import torch

        from .laya_torch import LayaTorch

        start = time.perf_counter()
        self.weights = None
        if weights is not None:
            path = Path(weights)
            digest = sha256(path)
            if expected_sha256 is not None and digest != expected_sha256:
                raise ValueError(f"{path} has SHA-256 {digest}, expected {expected_sha256}")
        self.laya = LayaTorch(offline=offline, device=device, dtype=dtype, batch_size=64)
        if weights is not None:
            if path.suffix == ".safetensors":
                from safetensors.torch import load_file

                state = load_file(str(path))
            else:
                state = torch.load(path, map_location="cpu", weights_only=True)
            missing = [k for k in state if k not in self.laya.model.state_dict()]
            if missing:
                raise ValueError(f"fine-tuned weights do not match the model: {missing[:4]}")
            self.laya.model.load_state_dict(state, strict=False)
            self.laya.model.to(self.laya.device, self.laya.dtype).eval()
            self.weights = {"path": str(path), "sha256": digest}
        self.load_seconds = time.perf_counter() - start
        self.metadata = dict(self.laya.metadata, fine_tuned=self.weights)

    @classmethod
    def pretrained(cls, version=None, *, fmt="safetensors", device=None, dtype="float16",
                   offline=False, cache_dir=None):
        """A released ChipLaya model. Online (the default), missing files are downloaded:
        the base checkpoint at its pinned revision from Hugging Face and the fine-tuned
        weights (``fmt`` "safetensors" or "pt") from the GitHub release. Both are checked
        against their SHA-256."""
        from . import weights as releases

        release = releases.release(version, fmt)
        path = releases.fetch(release["version"], fmt, cache_dir=cache_dir,
                              download=not offline)
        model = cls(weights=path, device=device, dtype=dtype, offline=offline,
                    expected_sha256=release["sha256"])
        base = sha256(model.laya.path / "model.safetensors")
        if base != releases.BASE["model.safetensors"]:
            raise ValueError(f"the cached base checkpoint {model.laya.path} has SHA-256 "
                             f"{base}, expected {releases.BASE['model.safetensors']}")
        return model

    def warm(self, repeats=3):
        for _ in range(repeats):
            self.ask("Design a two-stage op-amp with maximum gain.", cls="opampN",
                     objective="gain")

    def ask(self, request, *, vdd=None, load_pf=None, cls=None, objective=None):
        """Typed decisions for one request: the parse questions, then the topology
        questions of the class and objective (default: the parsed ones). With both given,
        all questions run as one batched forward pass; otherwise the parse pass comes
        first. Returns the typed answers, the parsed specification and the measured
        latency."""
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
        return {
            "state": state,
            "class": CLASS_OF[(answers["input"]["choice"], answers["stages"]["choice"])],
            "objective": answers["objective"]["choice"],
            "topology_class": cls,
            "topology_objective": objective,
            "answers": {k: {"choice": v["choice"], "probabilities": v["probabilities"]}
                        for k, v in answers.items()},
            "seconds": seconds,
        }

    def _predict(self, state, questions):
        start = time.perf_counter()
        result = self.laya.predict(state, questions)
        return result["answers"], time.perf_counter() - start


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()
