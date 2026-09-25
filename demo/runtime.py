"""Report the real compute device and validate the pinned offline model cache."""

from pathlib import Path

from chipjev.decisions.laya_torch import MODEL_ID, MODEL_REVISION
from chipjev.paths import ROOT


def inspect_runtime(device="auto"):
    missing, info = [], {"device": "unavailable", "cuda": False}
    try:
        import torch
        from huggingface_hub import snapshot_download
        cuda = torch.cuda.is_available()
        if device == "cuda" and not cuda:
            missing.append("CUDA device access")
        use_cuda = cuda and device != "cpu"
        info = {"device": f"CUDA · {torch.cuda.get_device_name(0)}" if use_cuda else "CPU",
                "cuda": use_cuda, "torch": torch.__version__, "cuda_runtime": torch.version.cuda}
        folder = Path(snapshot_download(MODEL_ID, revision=MODEL_REVISION, local_files_only=True,
                      allow_patterns=["*.json", "*.safetensors", "tokenizer/*", "LICENSE*", "NOTICE*"]))
        for name in ("model.safetensors", "rl_agent_config.json", "encoder/config.json",
                     "tokenizer/tokenizer.json"):
            if not (folder / name).is_file():
                missing.append(f"Laya {name}")
    except ImportError:
        missing.append("PyTorch / Laya dependencies (run scripts/setup-demo.sh)")
    except Exception:
        missing.append("Pinned Laya checkpoint (run scripts/setup-demo.sh)")
    if not (ROOT / "experiments/ptm45/typed-decisions.pt").is_file():
        missing.append("ChipJev typed-decision weights")
    return info, missing


def main():
    import argparse
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="cuda")
    args = parser.parse_args()
    info, missing = inspect_runtime(args.device)
    print(json.dumps({**info, "missing": missing}, indent=2))
    if missing:
        return 1
    if info["cuda"]:
        # Execute actual CUDA kernels, not just a driver-version query.
        import torch
        a = torch.ones((64, 64), device="cuda")
        assert (a @ a).sum().item() == 64 ** 3
        torch.cuda.synchronize()
        print("CUDA tensor execution passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
