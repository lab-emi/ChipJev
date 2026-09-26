# SKY130 layout and post-layout demonstration

This page describes the archived v1 row-generator measurements. The current CLI/demo use the goal-driven analog loop; see [implementation and scope](../../docs/analog-layout-usage.md). Use `--legacy` to reproduce the generator described below.

This extension closes the live ChipJev flow:

**Laya → topology/sizing search → wired xschem → Magic layout/DRC → Netgen LVS → Magic distributed RC PEX → strict ngspice.**

The [measured report](report/README.md) is generated from three fresh, complete public-prompt runs. This is an engineering demonstration after tuning on these prompts, **not a held-out or preregistered success-rate benchmark**. The original PTM and SKY130 frozen studies are unchanged. No archived topology, sizing solution or waveform is loaded by a live run.

## What is physically generated

Native SKY130 Magic PCells provide wells, active/poly, contacts and guard rings. MOS fingers retain the schematic finger count; each finger's width and length snap to 10 nm on the 5 nm drawing grid. Poly resistors and tiled MIM capacitors replace ideal schematic passives. Deterministic row placement and separate terminal columns route M1 access, M2 branches and M3 net trunks (M4 for MIM plates). Each net has one label on connected geometry.

Acceptance requires all of the following:

1. Strict schematic qualification and a connected xschem netlist.
2. Zero errors in Magic's full available SKY130 DRC style.
3. Netgen's unique LVS match, without property errors, against the grid-quantized physical reference.
4. Nonempty distributed parasitic R and C extraction. Zero capacitance threshold; all-net resistance extraction; 0.1 Ω minimum resistance setting.
5. Unchanged device count, geometry and connectivity from LVS extraction to RC extraction. Resistance contraction is used only for this integrity check; the simulator gets the complete extracted network.
6. Strict extracted ngspice OP, every-finger saturation, AC gain/GBW/PM/CMRR, power, open-loop perturbation and ±10 mV closed-loop checks.

Supply, ideal gate-bias sources and the 100 pF load remain external. Pre/post testbenches independently find input common-mode bias. Differences include quantization, actual passive/diffusion models, bias recalibration and RC. They must not be interpreted as a parasitic-only ablation.

## Reproduce

Use the existing locked Python environment, ngspice 47 and pinned SKY130 archive (`scripts/setup.sh`). Install the LVS **Netgen** executable (not the mesh generator), Tcl/Tk development headers, X11/Cairo development packages, make and gcc. Then:

```bash
bash scripts/setup-layout.sh
.venv/bin/chipjev layout runs/designs/YOUR-SKY130-RUN/result.json.gz --output runs/physical-check
# Disable sizing recovery to verify exactly the supplied design:
.venv/bin/chipjev layout experiments/layout/results/opamp-speed/result.json --output runs/physical-exact --no-recovery
```

The setup script builds Magic 8.3.684 at commit `4f53bb3091d1e4a9b2009a58f157a8a4331d4c84` locally under `.tools/magic`, without replacing the system installation. Older versions are rejected because the required passive-device distributed-RC behavior was not reliable in the previous local build.

For complete live runs, install the demo dependencies with `bash scripts/setup-demo.sh`, set `CHIPJEV_SKY130_XSCHEM` to the symbol library, and run:

```bash
.venv/bin/python -m demo.worker --device cuda --example opamp-gain --directory runs/fresh-gain
.venv/bin/python -m demo.worker --device cuda --example opamp-speed --directory runs/fresh-speed
.venv/bin/python -m demo.worker --device cuda --example ota-efficient --directory runs/fresh-ota
.venv/bin/python reproduce/report_layout.py
.venv/bin/python -m pytest -q tests/test_physical.py
```

Use fresh output directories. `report_layout.py` verifies every archived file hash and rebuilds tables, metrics and the exact-geometry figure under `report/`. With a separate manuscript checkout, `--paper PATH` copies its generated inputs there. `--runs DIR DIR DIR --archive NEW_PATH` captures a new set without overwriting evidence.

The evidence ZIP contains Magic scripts/logs, device PCells, final and failed physical attempts, extracted netlists and post-layout testbenches/waveforms. Absolute PDK include paths in recorded decks reflect the measured host; use the CLI to regenerate them on another host. Native GDS preserves labels, but not Magic port metadata: for an independent GDS LVS re-import use `port makeall` before extraction, as in `tests/test_physical.py`.

## Development choices and limits

Existing public-prompt seeds remain 0/2/2. The search profile reserves gain/PM/CMRR margins of 1 dB/2°/1 dB for the high-gain prompt, 1 dB gain for the OTA, and no extra margin for bandwidth. These are search heuristics; they never relax post-layout acceptance. Broadly adding margins to bandwidth search exhausted its budget during development. Removing all extra margins from high-gain search yielded an unqualified long-running physical recovery. Both failures informed this per-objective profile. A previously marginal OTA also failed after PEX. Failed trials are not included as successful observations.

Strictly qualified schematic candidates are screened with actual layout/PEX during the live search. A failed extracted candidate feeds back into the search instead of terminating it. All screening attempts are recorded under `physical-search/` in the evidence ZIP. The final selected layout is independently regenerated and verified. The report sums physical screening time and final physical-flow time; this cumulative physical cost may overlap search, and must not be added to the whole-worker elapsed time.

After a failed electrical check, at most 48 neighboring sizing candidates are considered with the topology fixed; each must pass fresh schematic screening before another layout is generated. All attempts are retained, and the total physical timing includes them. A DRC/LVS defect stops this recovery.

This fast row generator does not optimize common-centroid placement, symmetry, density fill, antenna closure, electromigration/IR drop or matching. The results establish nominal TT block behavior, not PVT/mismatch yield, package integration, bias generation or manufacturing signoff. They do not establish post-layout coverage of the 4,562-topology grammar or the 60-run frozen benchmark. Dedicated layout tools such as ALIGN, MAGICAL, GLayout and AnalogMaster already exist; no unmatched layout-speed superiority claim is made.
