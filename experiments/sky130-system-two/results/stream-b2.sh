#!/usr/bin/env bash
# Cores 8-15 after the System Two stage was voided (DEVIATIONS 3): SKY130 part 3 of 4, then
# the corrected System Two addendum (system2b) once it is frozen.
cd /home/cgao/git/ChipJev-Dev
PYTHONPATH=src taskset -c 8-15 .venv/bin/python scripts/topo-v4-run.py --stage sky130 --part 3/4 >> runs/topo-v4/sky130-part3.log 2>&1
until [ -f experiments/topo-v4/system2b/protocol.json ]; do sleep 30; done
eval "$(grep -E '^export OPENROUTER_API_KEY=' ~/.bashrc | tail -1)"
PYTHONPATH=src taskset -c 8-15 .venv/bin/python scripts/topo-v4-system2b.py --stage system2b >> runs/topo-v4/system2b.log 2>&1
echo "stream-b2 done $(date)" >> runs/topo-v4/streams.log
