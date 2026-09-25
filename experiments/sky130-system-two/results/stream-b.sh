#!/usr/bin/env bash
# Cores 8-15: the System Two stage, then SKY130 part 3 of 4.
cd /home/cgao/git/ChipJev-Dev
eval "$(grep -E '^export OPENROUTER_API_KEY=' ~/.bashrc | tail -1)"
PYTHONPATH=src taskset -c 8-15 .venv/bin/python scripts/topo-v4-run.py --stage system2 >> runs/topo-v4/system2.log 2>&1
unset OPENROUTER_API_KEY
PYTHONPATH=src taskset -c 8-15 .venv/bin/python scripts/topo-v4-run.py --stage sky130 --part 3/4 >> runs/topo-v4/sky130-part3.log 2>&1
echo "stream-b done $(date)" >> runs/topo-v4/streams.log
