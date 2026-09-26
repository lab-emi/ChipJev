"""python -m chiplaya "Design a two-stage op-amp with maximum DC gain." --vdd 1.8 --load 100"""

import argparse
import json

from .model import ChipLaya


def main(argv=None):
    parser = argparse.ArgumentParser(prog="chiplaya", description=__doc__)
    parser.add_argument("request", help="a free-text amplifier design request")
    parser.add_argument("--vdd", type=float, help="supply voltage (V)")
    parser.add_argument("--load", type=float, help="load capacitance (pF)")
    parser.add_argument("--class", dest="cls", choices=("amp1", "opamp1", "ampN", "opampN"),
                        help="ask the topology questions of this class (default: parsed)")
    parser.add_argument("--objective", choices=("gain", "gbw", "fom"),
                        help="ask the topology questions for this objective (default: parsed)")
    parser.add_argument("--weights", help="a local weights file instead of the release")
    parser.add_argument("--version", help="the release to load (default: the latest)")
    parser.add_argument("--format", choices=("safetensors", "pt"), default="safetensors",
                        help="the release's weights format")
    parser.add_argument("--device", help="cuda, mps or cpu (default: the best available)")
    parser.add_argument("--offline", action="store_true",
                        help="use cached files only; never download")
    parser.add_argument("--json", action="store_true", help="print the full answer as JSON")
    args = parser.parse_args(argv)
    if args.weights:
        model = ChipLaya(weights=args.weights, device=args.device, offline=args.offline)
    else:
        model = ChipLaya.pretrained(args.version, fmt=args.format, device=args.device,
                                    offline=args.offline)
    model.warm(1)  # the first pass pays for CUDA initialization
    result = model.ask(args.request, vdd=args.vdd, load_pf=args.load, cls=args.cls,
                       objective=args.objective)
    if args.json:
        print(json.dumps({**result, "model": model.metadata}, indent=1))
        return
    print(f"ChipLaya on {model.metadata['device']}: class {result['class']}, objective "
          f"{result['objective']}; {1000 * result['seconds']:.1f} ms")
    for question, answer in result["answers"].items():
        ranked = sorted(answer["probabilities"].items(), key=lambda kv: -kv[1])
        print(f"  {question:15s} " + ", ".join(f"{k} {v:.2f}" for k, v in ranked))


if __name__ == "__main__":
    main()
