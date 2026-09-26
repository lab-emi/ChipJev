# Goal-driven layout evidence

This archive records three fresh public demo runs on 2026-09-26. It is separate from the original row-generator archive in `experiments/layout` and from the frozen schematic benchmarks.

See [measured results and geometry comparison](report/README.md), [machine-readable summary](report/summary.json), and [implementation/coverage guide](../../docs/analog-layout-usage.md). Each case contains native Magic/GDS, the explicit plan history, schematic and extracted netlists, and an evidence ZIP with all evaluated plans and raw tool logs. `MANIFEST.json` hashes the evidence; `result.json` hashes the source files used by each run. The report refuses changed source during capture and verifies archived evidence before rendering.

Regenerate the report from these bytes:

```bash
PYTHONPATH=src:. .venv/bin/python reproduce/report_analog_layout.py
```

For fresh measurements, run `demo.worker --example ID --directory FRESH_PATH --device cuda` once for each of `opamp-gain`, `opamp-speed`, and `ota-efficient`. Pass the three output directories to `reproduce/report_analog_layout.py --runs ... --archive FRESH_ARCHIVE`. Run workers sequentially to avoid introducing benchmark contention. Every prompt starts circuit search from its grammar/prior, not a saved design.

Release verification: `PYTHONPATH=src:. .venv/bin/python -m pytest -q -m 'not frozen'` completed with **90 passed, 1 skipped, 1 deselected**. The skipped test requires optional frozen source archives; the 14 live-versus-frozen probe comparisons passed. The run includes real Magic/Netgen/ngspice, GDS re-import, geometry/auxiliary-device tampering, seeded mismatch reproducibility and a live CPU demo. Ruff and the two browser-clock tests also passed. A separate browser-driven CUDA high-gain run completed in 48.58 s and exposed the six-step layout history, device groups and analog plots without console errors.

These prompts informed implementation and timing choices. All delivered cases pass nominal fixed-condition qualification. Bounds for noise, IR, mismatch or yield are not inferred from successful measurement. Current Laya weights are circuit-trained; expert-layout preference collection and held-out topology evaluation have not been performed. Full EM, density/antenna, spatial mismatch, thermal and substrate-noise signoff are outside coverage.

Source paths recorded here predate the ChipJev/ChipLaya split: `src/chipjev/decisions/laya_torch.py` now lives, byte-identical (SHA-256 `d15285ec…`), at `src/chiplaya/laya_torch.py`, the vendored [ChipLaya](https://github.com/lab-emi/ChipLaya) package; the recorded hashes stay valid for that file.
