# Reproduction

The repository includes the current package, experiment protocols, trained weights,
checksummed results, report generators and reproduction scripts. Frozen source snapshots
are optional local inputs and are excluded from Git.

## Verify and regenerate recorded results

```bash
python3 reproduce/verify.py
reproduce/reproduce-paper.sh
```

The verifier uses only the Python standard library. It checks protocol records, live frozen
inputs, weights and every recorded result against their checksums. Missing source snapshots
are reported explicitly; their recorded member hashes remain available, but their bytes and
the frozen runners cannot be checked until the snapshots are restored. Missing or changed
experiment data still fails verification. Any source snapshot that is present is checked.

The reproduction script installs the documented Linux tools, re-simulates the recorded
designs with the current package, and regenerates experiment summaries, tables and figures
under `runs/reports/`. The manuscript is maintained separately. It also checks the frozen
runners when all source snapshots are installed. `--skip-setup` uses existing tools.

## Exact experiment reruns

Obtain the original source snapshots from the experiment maintainer and restore them at
these paths. They cannot be reconstructed byte for byte from the current package layout.
The recorded checksums are retained unchanged:

| Local archive | SHA-256 record |
|---|---|
| `reproduce/frozen-code.tar.gz` | [`frozen-code.json`](frozen-code.json), `sha256` |
| `experiments/ptm45/frozen-source.tar.gz` | [`../experiments/ptm45/MANIFEST.json`](../experiments/ptm45/MANIFEST.json), `files.frozen-source.tar.gz` |
| `experiments/sky130-system-two/frozen-source.tar.gz` | [`../experiments/sky130-system-two/MANIFEST.json`](../experiments/sky130-system-two/MANIFEST.json), `files.frozen-source.tar.gz` |

Then run:

```bash
python3 reproduce/verify.py --require-frozen
reproduce/reproduce-paper.sh --rerun
```

`--rerun` checks for the source snapshots before installing tools. The frozen runners require
a CUDA GPU, the documented CPU allocation, simulator and PDK tools, and an OpenRouter API key
for the LLM baselines; see the [project README](../README.md#reproduce-the-experiments).
Tests that execute frozen code are skipped when the source snapshots are absent; tests
against the recorded golden output remain available.
