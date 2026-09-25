#!/usr/bin/env bash
# Install the pinned CUDA/Laya runtime and EDA tools without changing uv.lock.
set -euo pipefail
cd "$(dirname "$0")/.."
demo_root="$PWD"
for tool in uv curl rg make gcc Xvfb xschem xauth ffmpeg prlimit; do
  command -v "$tool" >/dev/null || {
    echo "Missing $tool. See deploy/chipjev/README.md for prerequisites." >&2
    exit 1
  }
done
mkdir -p .tools/bin .tools/src .tools/xschem/sky130_fd_pr
export UV_PYTHON_INSTALL_DIR="$demo_root/.tools/python"
uv python install 3.13
uv sync --frozen --python 3.13 --extra research --extra rt
uv pip install --python .venv/bin/python --require-hashes -r demo/requirements.lock
.venv/bin/python -m chipjev.simulation.pdk
bash scripts/setup-layout.sh
export HF_HOME="$demo_root/.tools/huggingface"
.venv/bin/python - <<'PYMODEL'
from huggingface_hub import snapshot_download
from chipjev.decisions.laya_torch import MODEL_ID, MODEL_REVISION
snapshot_download(MODEL_ID, revision=MODEL_REVISION,
    allow_patterns=["*.json", "*.safetensors", "tokenizer/*", "LICENSE*", "NOTICE*"])
PYMODEL

if ! .tools/bin/ngspice -v 2>/dev/null | rg -q 'ngspice-47'; then
  archive="$demo_root/.tools/src/ngspice-47.tar.gz"
  curl -fL --retry 3 'https://sourceforge.net/projects/ngspice/files/ng-spice-rework/47/ngspice-47.tar.gz/download' -o "$archive.part"
  echo "894e649651f1838a14095e5a5439e7d3aa63e87ede14d283173fda4fcdef675f  $archive.part" | sha256sum -c -
  mv "$archive.part" "$archive"
  mkdir -p .tools/src/ngspice-demo
  tar -xzf "$archive" --strip-components=1 -C .tools/src/ngspice-demo
  (
    cd .tools/src/ngspice-demo
    ./configure --prefix="$demo_root/.tools" --with-x=no --with-readline=no --enable-openmp
    make -j4
    make install
  ) > .tools/build-ngspice-demo.log 2>&1
fi

symbol_revision=fef70fad3804d1c298c70f78de769825d7dfea19
for device in nfet pfet; do
  path=".tools/xschem/sky130_fd_pr/${device}_01v8.sym"
  curl -fL --retry 3 "https://raw.githubusercontent.com/StefanSchippers/xschem_sky130/$symbol_revision/sky130_fd_pr/${device}_01v8.sym" -o "$path.part"
  if [[ "$device" == nfet ]]; then
    digest=b54043812f570e711a9bbd2ab9b6c10fc40f52fd25604f90a47b5bb34da49186
  else
    digest=c340f1c03641fb9ff7e2289084a6bac42ceaee2bd4adc985f4ac6225b224b090
  fi
  echo "$digest  $path.part" | sha256sum -c -
  mv "$path.part" "$path"
done
curl -fL --retry 3 "https://raw.githubusercontent.com/StefanSchippers/xschem_sky130/$symbol_revision/LICENSE" -o .tools/xschem/LICENSE
echo 'Ready. Start the demo with:'
echo 'bash scripts/run-demo-gpu.sh'
