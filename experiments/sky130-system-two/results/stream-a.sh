#!/usr/bin/env bash
# Cores 0-7: SKY130 parts 0, 1 and 2 of 4.
cd /home/cgao/git/ChipJev-Dev
for k in 0 1 2; do
  PYTHONPATH=src taskset -c 0-7 .venv/bin/python scripts/topo-v4-run.py --stage sky130 --part $k/4 >> runs/topo-v4/sky130-part$k.log 2>&1
done
echo "stream-a done $(date)" >> runs/topo-v4/streams.log
