#!/usr/bin/env bash
# Verify the recorded experiments and regenerate their reports.
#
#   reproduce/reproduce-paper.sh                 # recorded evidence; no GPU or API key
#   reproduce/reproduce-paper.sh --rerun         # rerun the frozen experiments
#   reproduce/reproduce-paper.sh --skip-setup    # use installed tools
#
# Reports and generated figures are written to runs/reports. The manuscript is maintained
# separately. Exact reruns require the optional source snapshots documented in
# reproduce/README.md, a CUDA GPU, CPU ids 0-15, bubblewrap, xschem, SKY130 libraries and
# OPENROUTER_API_KEY. A full rerun takes about 15 hours and $12 in API calls on the study host.
# Interrupted search stages resume from their journals. GPU and LLM runs are not
# bit-identical: compare reported medians and intervals with the recorded evidence.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"
MODE="archive"
SETUP=1
for arg in "$@"; do
  case "$arg" in
    --rerun) MODE="rerun" ;;
    --skip-setup) SETUP=0 ;;
    -h|--help) sed -n '2,/^set -euo pipefail/{ /^set -euo pipefail/d; p; }' "$0"; exit 0 ;;
    *) echo "unknown option $arg" >&2; exit 2 ;;
  esac
done
if [[ "$MODE" == "rerun" ]]; then
  for archive in reproduce/frozen-code.tar.gz experiments/ptm45/frozen-source.tar.gz \
      experiments/sky130-system-two/frozen-source.tar.gz; do
    [[ -f "$archive" ]] || {
      echo "--rerun needs the optional source archive $archive; see reproduce/README.md." >&2
      exit 1
    }
  done
fi
export PATH="$ROOT/.tools/bin:$PATH"
PY="$ROOT/.venv/bin/python"
run() { echo "+ $*"; "$@"; }

if [[ "$SETUP" == 1 ]]; then
  if [[ "$MODE" == "rerun" ]]; then
    run ./scripts/setup.sh --xschem
    run ./scripts/setup-analogcoder-pro.sh
  else
    run ./scripts/setup.sh
  fi
fi
[[ -x "$PY" ]] || { echo "missing $PY; run scripts/setup.sh" >&2; exit 1; }

run "$PY" reproduce/verify.py
if [[ -f reproduce/frozen-code.tar.gz && -f experiments/ptm45/frozen-source.tar.gz \
    && -f experiments/sky130-system-two/frozen-source.tar.gz ]]; then
  run "$PY" reproduce/frozen.py materialize
  run "$PY" reproduce/frozen.py check
else
  echo "Frozen runner checks skipped: optional source archives are absent (see reproduce/README.md)."
fi

if [[ "$MODE" == "archive" ]]; then
  run "$PY" reproduce/resimulate.py
  run "$PY" reproduce/report_ptm45.py
  run "$PY" reproduce/report_sky130_system_two.py
  echo "Done: experiment summaries and runs/reports/generated, runs/reports/figures."
  exit 0
fi

# ------------------------------------------------------------------------------ rerun
command -v bwrap >/dev/null || { echo "--rerun needs bubblewrap (AnalogCoder-Pro's sandbox)." >&2; exit 1; }
command -v xschem >/dev/null || { echo "--rerun needs xschem (the SKY130 schematic export)." >&2; exit 1; }
PYTHONPATH=src "$PY" -c "import sys; from chipjev.xschem import library; sys.exit(not (library() / 'sky130_fd_pr').exists())" \
  || { echo "--rerun needs the sky130A xschem library (~/.volare/sky130A/libs.tech/xschem or CHIPJEV_SKY130_XSCHEM)." >&2; exit 1; }
"$PY" -c "import sys, torch; sys.exit(not torch.cuda.is_available())" \
  || { echo "--rerun needs a CUDA GPU (nvidia-smi must work)." >&2; exit 1; }
[[ -n "${OPENROUTER_API_KEY:-}" ]] \
  || { echo "--rerun needs OPENROUTER_API_KEY (AnalogCoder-Pro's flows and the System Two decisions)." >&2; exit 1; }
[[ "$(nproc --all)" -ge 16 ]] \
  || { echo "--rerun needs CPU ids 0-15 (searches on 0-7, AnalogCoder-Pro attempts on 8-15)." >&2; exit 1; }
# The typed stage's LLM parse baseline and the System Two addendum use the OpenAI client,
# which the locked environment does not contain (experiments/ptm45/DEVIATIONS.md, item 1).
run uv pip install --python "$PY" "openai==3.19.2"
TREE="$ROOT/runs/frozen"
# frozen LOG CMD...: run CMD in the frozen tree (its own src first), appending to runs/LOG there.
frozen() {
  local log="$TREE/runs/$1"; shift
  mkdir -p "$(dirname "$log")"
  echo "+ [frozen] $* >> runs/frozen/runs/${log#"$TREE/runs/"}"
  "$PY" reproduce/frozen.py exec -- "$@" 2>&1 | tee -a "$log"
}
# PTM 45 nm study (protocol topo-v3, frozen 2026-09-24 18:31): typed decisions, ablations,
# main comparison, AnalogCoder-Pro's flows, robustness, then the post-hoc checks reported as such.
# A frozen tree under /tmp cannot run AnalogCoder-Pro's sandbox, which mounts a private /tmp.
frozen topo-v3/typed.log taskset -c 0-7 "$PY" scripts/topo-v3-run.py --stage typed
frozen topo-v3/ablation.log taskset -c 0-7 "$PY" scripts/topo-v3-run.py --stage ablation
frozen topo-v3/main.log taskset -c 0-7 "$PY" scripts/topo-v3-run.py --stage main
frozen acpro-llm/deepseek-v3.log "$PY" scripts/acpro-llm-run.py \
  --model deepseek/deepseek-chat-v3-0324 --tasks 51-62 --attempts 30 --parallel 8 --cores 8-15 \
  --timeout 3600
frozen topo-v3/robustness.log taskset -c 0-7 "$PY" scripts/topo-v3-run.py --stage robustness
frozen acpro-llm/gpt-5-mini.log "$PY" scripts/acpro-llm-run.py --model openai/gpt-5-mini \
  --tasks 51-62 --attempts 10 --parallel 8 --cores 8-15 --timeout 3600
frozen acpro-llm/lenient.log taskset -c 0-7 "$PY" scripts/acpro-lenient.py --model openai/gpt-5-mini
frozen acpro-llm/diagnose.log "$PY" scripts/acpro-diagnose.py
frozen topo-v3/corner-select.log "$PY" scripts/topo-v3-corner-select.py --runs runs/topo-v3
frozen topo-v3/typed-latency.log "$PY" scripts/typed-latency.py \
  --output experiments/topo-v3/typed-latency.json
frozen topo-v3/latency.log taskset -c 0-7 "$PY" scripts/topo-latency.py --outputs 7 --pools 65536 \
  --output experiments/topo-v3/latency.json
frozen archive-ptm45.log "$PY" scripts/topo-v3-archive.py
# SKY130 and System Two study (protocol topo-v4, frozen 23:27, and its system2b addendum, 23:50).
frozen topo-v4/sky130.log taskset -c 0-7 "$PY" scripts/topo-v4-run.py --stage sky130
frozen topo-v4/system2b.log taskset -c 0-7 "$PY" scripts/topo-v4-system2b.py --stage system2b
frozen xschem-export.log "$PY" scripts/topo-v4-xschem.py
frozen archive-sky130-system-two.log "$PY" scripts/topo-v4-archive.py

# Report the fresh archives without a manuscript checkout.
OUT="$ROOT/runs/rerun/reports"
mkdir -p "$OUT"
run "$PY" reproduce/report_ptm45.py --study "$TREE/experiments/topo-v3" --output "$OUT"
run "$PY" reproduce/report_sky130_system_two.py --study "$TREE/experiments/topo-v4" \
  --ptm45-summary "$TREE/experiments/topo-v3/report/summary.json" \
  --llm-runs "$TREE/experiments/topo-v3/results/acpro-llm" --output "$OUT"
echo "Done: runs/rerun/reports."
