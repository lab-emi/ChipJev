#!/usr/bin/env bash
# Run this on the GPU host, outside a sandbox that hides /dev/nvidia*.
# Does not change drivers, system settings, DNS, or any other service.
set -euo pipefail
cd "$(dirname "$0")/.."
demo_root="$PWD"
export CHIPJEV_SKY130_XSCHEM="$demo_root/.tools/xschem"
export HF_HUB_OFFLINE=1
if [[ -d "$demo_root/.tools/huggingface" ]]; then
  export HF_HOME="$demo_root/.tools/huggingface"
fi
export PATH="$demo_root/.tools/bin:$PATH"
export PYTHONDONTWRITEBYTECODE=1
# This checkout's chipjev and vendored chiplaya, whatever the venv's editable install points at.
export PYTHONPATH="$demo_root/src:$demo_root"
.venv/bin/python -m demo.runtime --device cuda
.venv/bin/python - <<'PY'
import socket
from pathlib import Path
from demo.server import Service, DEFAULT_ORIGINS
service = Service(Path('runs/gpu-check'), DEFAULT_ORIGINS, device='cuda')
try:
    missing = service.readiness()
    if missing:
        raise SystemExit('Missing: ' + ', '.join(missing))
finally:
    service.lock.close()
with socket.socket() as sock:
    try:
        sock.bind(('127.0.0.1', 18766))
    except OSError:
        raise SystemExit('Port 18766 is occupied. Stop the previous ChipJev demo server first.')
PY
mkdir -p runs/gpu-service
if [[ "${1:-}" == "--background" ]]; then
  nohup .venv/bin/python -m demo.server --device cuda --preview --state "$demo_root/runs/gpu-service" > runs/gpu-service.log 2>&1 < /dev/null &
  echo "$!" > runs/gpu-service.pid
  .venv/bin/python - <<'PYWAIT'
import time, urllib.request
for attempt in range(40):
    try:
        with urllib.request.urlopen('http://127.0.0.1:18766/api/health', timeout=3) as response:
            print(response.read().decode())
        break
    except Exception:
        time.sleep(.5)
else:
    raise SystemExit('Service did not become ready. See runs/gpu-service.log.')
PYWAIT
  echo "Started CUDA demo, PID $(cat runs/gpu-service.pid)."
  echo "Preview: http://127.0.0.1:18766"
  echo "Log: $demo_root/runs/gpu-service.log"
  if command -v cloudflared >/dev/null; then
    # Separate temporary tunnel; never touch an existing named tunnel or token.
    nohup cloudflared tunnel --no-autoupdate --url http://127.0.0.1:18766 --protocol http2 > runs/gpu-tunnel.log 2>&1 < /dev/null &
    echo "$!" > runs/gpu-tunnel.pid
    .venv/bin/python - <<'PYTUNNEL'
import re, time
from pathlib import Path
for attempt in range(60):
    match = re.search(r'https://[a-z0-9-]+\.trycloudflare\.com', Path('runs/gpu-tunnel.log').read_text())
    if match:
        Path('runs/gpu-api-url.txt').write_text(match[0]+'\n')
        print('Temporary public API: '+match[0])
        break
    time.sleep(1)
else:
    print('Tunnel URL pending. Inspect runs/gpu-tunnel.log.')
PYTUNNEL
  fi
elif [[ $# == 0 ]]; then
  exec .venv/bin/python -m demo.server --device cuda --preview --state "$demo_root/runs/gpu-service"
else
  echo 'Usage: bash scripts/run-demo-gpu.sh [--background]' >&2
  exit 2
fi
