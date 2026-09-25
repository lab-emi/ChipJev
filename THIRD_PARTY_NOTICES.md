# Third-party notices

## Laya, Laya-MLX and the Laya checkpoint (src/chipjev/decisions/laya_torch.py, experiments/ptm45/typed-decisions.pt)

- `src/chipjev/decisions/laya_torch.py` is a PyTorch port of [Laya-MLX](https://github.com/mizorewww/laya-mlx)
  0.1.0 (revision `fc1df62828a3fedf4d8229fdac1cbd85f1cdf337`, Apache-2.0), which derives from
  [Laya](https://github.com/NandhaKishorM/laya) by Convai Innovations and the Laya contributors
  (Apache-2.0, upstream revision `6a5819129eb220570792e417e49723d697efd76f`). It adapts Laya-MLX's
  question rendering, token-sequence construction, confidence calculation and calibrated option
  scoring, and re-expresses its MLX network definition (ModernBERT encoder and Laya decision
  head) in PyTorch.
- The checkpoint [`aac6fef/laya-multilingual-mlx`](https://huggingface.co/aac6fef/laya-multilingual-mlx)
  (revision `f2b4faf51023039425946074e2cf1361d2db11d5`, Apache-2.0), an MLX FP16 conversion of
  [`convaiinnovations/laya-multilingual`](https://huggingface.co/convaiinnovations/laya-multilingual),
  is downloaded by the setup scripts and not redistributed. `experiments/ptm45/typed-decisions.pt`
  holds ChipJev's fine-tuned values of 35M of its parameters.

These derived portions remain under the Apache License 2.0
([LICENSES/Apache-2.0.txt](LICENSES/Apache-2.0.txt), the copy that Laya-MLX ships). The complete
Laya-MLX NOTICE, which the checkpoint also carries, and ChipJev's changes are reproduced in
[NOTICE](NOTICE).

## PTM 45 nm device models (src/chipjev/simulation/models/ptm45hp.pm)

`src/chipjev/simulation/models/ptm45hp.pm` is the Predictive Technology Model (PTM) 45 nm
high-performance (metal gate, high-k, strained Si) BSIM4 model card of the Nanoscale
Integration and Modeling Group, Arizona State University (W. Zhao and Y. Cao, IEEE Trans.
Electron Devices 53(11), 2006; <https://ptm.asu.edu/>), copied unmodified from the
Verilog-to-Routing repository (`vtr_flow/tech/PTM_45nm/45nm.pm`,
<https://github.com/verilog-to-routing/vtr-verilog-to-routing>). SHA-256:
`9ab66a7bc4a547b2f869ceaec03f0a73d90db95cf0a9bb6c581b5a31b2edc2b9`. PTM model cards are
provided by their authors for research use; they are predictive models, not a foundry PDK.

## AnalogCoder-Pro (not redistributed)

The released code of AnalogCoder-Pro (<https://github.com/laiyao1/AnalogCoderPro>, commit
`05542af`) is fetched into the git-ignored `.tools/acpro` by `scripts/setup-analogcoder-pro.sh` and run
unchanged inside a bubblewrap sandbox; its prompts, checks and generated programs are not
included in this repository. The unreleased device-model module and sizing helper are
reconstructed in `src/chipjev/analogcoder_pro/helper.py` from the paper's description.

## Other runtimes

xschem, ngspice, the SKY130 models (via the pinned AnalogGym archive), PyTorch, Triton (the
fused Thompson-sampling kernels), Optuna and the Hugging Face libraries are used as external
dependencies under their own licenses; none of their source is included here.

## Live demo schematic symbols

`scripts/setup-demo.sh` downloads two unmodified SKY130 xschem symbols from
[StefanSchippers/xschem_sky130](https://github.com/StefanSchippers/xschem_sky130),
revision `fef70fad3804d1c298c70f78de769825d7dfea19`. These symbols are Copyright
2021 Stefan Frederik Schippers, Apache-2.0. Their notices and the repository
license are retained under the ignored `.tools/xschem/` installation directory.
No third-party symbol source is redistributed as part of the website.
