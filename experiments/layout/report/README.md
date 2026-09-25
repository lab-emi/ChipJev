# Physical demonstration measurements

One fresh run per public prompt after development tuning. All three pass full Magic DRC, Netgen LVS and strict extracted ngspice checks.

| Prompt | MOS/fingers | Area (µm²) | Layout + DRC (s) | Physical flow (s) | Whole worker (s) | R/C |
|---|---:|---:|---:|---:|---:|---:|
| High-gain op-amp | 13/17 | 5734 | 0.64 | 8.76 | 27.22 | 410/184 |
| Wideband op-amp | 9/12 | 4410 | 0.60 | 13.28 | 66.39 | 291/126 |
| Efficient OTA | 5/39 | 18401 | 0.84 | 19.69 | 31.27 | 376/306 |

Layout time includes PCell generation, placement, routing, full DRC, initial connectivity/capacitance extraction and GDS writing. Physical flow sums SVG, LVS, distributed RC extraction and strict ngspice for all early candidate screens and final sizing attempts. Candidate screens can overlap ongoing search; this cumulative time is not an extra term to add to whole-worker wall time. Total includes model loading and the live schematic workflow, but excludes browser/network time.

Pre/post measurements use the same qualification rules and independent input-bias searches. Their differences include PDK grid quantization, physical passive models, diffusion geometry and extracted RC; they are not a parasitic-only ablation. Supply, ideal gate biases and 100 pF load are external. These nominal TT checks do not establish matching, PVT yield, or fabrication signoff.
