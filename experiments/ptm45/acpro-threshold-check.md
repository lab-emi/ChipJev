# Threshold hint in AnalogCoder-Pro's prompts versus the testbench card

AnalogCoder-Pro's released prompts tell the LLM to bias with "Vth = 0.22V". The common
testbench uses the PTM 45 nm HP card (vth0 = 0.469 V NMOS, -0.492 V PMOS at zero bias).
At the channel length that the flow's parameter extraction fixes (L = 45 nm) and
VDS = 0.6 V, a DC sweep of that card (W = 0.45 um, ngspice 47) gives:

| Device | Constant-current threshold (100 nA x W/L) | Max-gm extrapolated threshold |
|---|---|---|
| NMOS | 0.241 V | 0.42 V |
| PMOS | 0.309 V | 0.49 V |

The hint is therefore consistent with the card's short-channel constant-current threshold,
and the prompts were used unchanged. Measured 2026-09-24 on the topo-v3 host.
