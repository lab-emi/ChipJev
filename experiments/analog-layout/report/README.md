# Goal-driven analog layout: measured development runs

Same circuit sizing and fixed input bias within each layout search; real Magic/Netgen/ngspice. PCell cache is warm, Laya is resident on an RTX 4090. Wall times are host measurements and exclude network/browser latency.

| Prompt | Initial → final area (µm²) | Reduction | First feasible (s) | Layout loop (s) | Whole demo (s) | Rejected / evaluated |
|---|---:|---:|---:|---:|---:|---:|
| opamp-gain | 13196 → 8686 | 34.2% | 4.61 | 22.07 | 47.38 | 3 / 6 |
| opamp-speed | 86621 → 86621 | 0.0% | 5.05 | 19.24 | 72.59 | 5 / 6 |
| ota-efficient | 28439 → 24485 | 13.9% | 6.62 | 38.52 | 67.95 | 0 / 6 |

All delivered layouts pass full available Magic DRC, unique LVS, declared-device/PEX integrity, and strict fixed-bias nominal OP/AC/transient checks. Noise/PSRR and finite-impedance supply metrics are measurements, with no invented acceptance limits. Failed candidates are retained in the evidence ZIP.

This comparison starts from the new grouped generator; it does not claim area or speed superiority over the archived row generator or competing layout tools. The three prompts informed development. No expert-layout-trained checkpoint or cross-topology generalization result is claimed. EM, density/antenna closure, spatial mismatch, thermal and substrate-noise signoff are outside the implemented coverage.
