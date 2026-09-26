#!/usr/bin/env bash
# Everything ChipJev needs to run and to reproduce the paper from the archives:
#   * uv-managed Python 3.13 and the locked environment in .venv (CUDA PyTorch, Triton,
#     Optuna, Hugging Face libraries), with the chipjev package installed in editable mode;
#   * the pinned Laya checkpoint (Hugging Face cache, loaded offline afterwards);
#   * the pinned SKY130 models (.tools/pdk, AnalogGym archive, checksum-verified);
#   * ngspice 47 with KLU, built from source into .tools/bin;
#   * with --xschem, xschem 3.4.7 built into .tools (only the SKY130 schematic export needs it;
#     the sky130A xschem symbol library comes from open_pdks/volare).
# Linux x86-64 (the searches pin CPU cores; the GPU paths need CUDA). Idempotent: finished
# steps are skipped. scripts/setup-analogcoder-pro.sh adds what rerunning the LLM baselines
# needs.
# Usage: scripts/setup.sh [--install-system-packages] [--xschem]
set -euo pipefail
export UV_PYTHON_PREFERENCE=only-managed
cd "$(dirname "$0")/.."
ROOT="$PWD"
PREFIX="$ROOT/.tools"
SOURCES="$PREFIX/src"
JOBS="$(nproc)"
NGSPICE_VERSION=47
NGSPICE_URL="https://sourceforge.net/projects/ngspice/files/ng-spice-rework/${NGSPICE_VERSION}/ngspice-${NGSPICE_VERSION}.tar.gz/download"
NGSPICE_SHA256=894e649651f1838a14095e5a5439e7d3aa63e87ede14d283173fda4fcdef675f
if [[ "$(uname -s)" != Linux ]]; then
  echo "This installer is for Linux." >&2
  exit 1
fi
XSCHEM=0
INSTALL=0
for arg in "$@"; do
  case "$arg" in
    --xschem) XSCHEM=1 ;;
    --no-xschem) XSCHEM=0 ;;
    --install-system-packages) INSTALL=1 ;;
    *) echo "unknown option $arg" >&2; exit 2 ;;
  esac
done

packages_for() {
  # Build dependencies of ngspice and xschem, and bubblewrap, per distribution family.
  if command -v pacman >/dev/null; then
    echo "pacman -S --needed --noconfirm base-devel tcl tk libx11 libxpm cairo libjpeg-turbo flex bison gawk bubblewrap"
  elif command -v apt-get >/dev/null; then
    echo "apt-get install -y build-essential tcl-dev tk-dev libx11-dev libxpm-dev libcairo2-dev libjpeg-dev flex bison gawk bubblewrap"
  elif command -v dnf >/dev/null; then
    echo "dnf install -y gcc make tcl-devel tk-devel libX11-devel libXpm-devel cairo-devel libjpeg-turbo-devel flex bison gawk bubblewrap"
  else
    echo ""
  fi
}

if [[ "$INSTALL" == 1 ]]; then
  command=$(packages_for)
  if [[ -z "$command" ]]; then
    echo "Unknown distribution; install gcc, make, flex, bison, Tcl/Tk, X11, Xpm, cairo, libjpeg, gawk and bubblewrap." >&2
    exit 1
  fi
  echo "Running: sudo $command"
  sudo $command
fi

command -v uv >/dev/null || { echo "uv is missing: https://docs.astral.sh/uv/getting-started/installation/" >&2; exit 1; }
for tool in make gcc; do
  command -v "$tool" >/dev/null || {
    echo "$tool is missing. Install it (e.g. sudo $(packages_for)) or rerun with --install-system-packages." >&2
    exit 1
  }
done
mkdir -p "$SOURCES" "$PREFIX/bin"

# ngspice 47 (batch binary, KLU): the simulator of every testbench.
if ! "$PREFIX/bin/ngspice" -v 2>/dev/null | grep -q "ngspice-${NGSPICE_VERSION}"; then
  if [[ ! -f "$SOURCES/ngspice-${NGSPICE_VERSION}.tar.gz" ]]; then
    echo "Downloading ngspice ${NGSPICE_VERSION}..."
    curl -L --fail -o "$SOURCES/ngspice-${NGSPICE_VERSION}.tar.gz.part" "$NGSPICE_URL"
    mv "$SOURCES/ngspice-${NGSPICE_VERSION}.tar.gz.part" "$SOURCES/ngspice-${NGSPICE_VERSION}.tar.gz"
  fi
  if [[ "$(sha256sum "$SOURCES/ngspice-${NGSPICE_VERSION}.tar.gz" | awk '{print $1}')" != "$NGSPICE_SHA256" ]]; then
    echo "Checksum mismatch: $SOURCES/ngspice-${NGSPICE_VERSION}.tar.gz. Remove it and retry." >&2
    exit 1
  fi
  echo "Building ngspice ${NGSPICE_VERSION} into .tools..."
  dir="$SOURCES/ngspice-${NGSPICE_VERSION}"
  rm -rf "$dir" && mkdir -p "$dir"
  tar -xzf "$SOURCES/ngspice-${NGSPICE_VERSION}.tar.gz" -C "$dir" --strip-components=1
  ( cd "$dir" && ./configure --prefix="$PREFIX" --with-x=no --with-readline=no --enable-openmp \
      && make -j"$JOBS" && make install ) > "$PREFIX/build-ngspice${NGSPICE_VERSION}-tools.log" 2>&1 \
    || { tail -30 "$PREFIX/build-ngspice${NGSPICE_VERSION}-tools.log" >&2; exit 1; }
fi
"$PREFIX/bin/ngspice" -v | sed -n 2p

# xschem 3.4.7 (optional).
if [[ "$XSCHEM" == 1 && ! -x "$(command -v xschem || true)" ]]; then
  command -v pkg-config >/dev/null || { echo "pkg-config is missing: sudo $(packages_for)" >&2; exit 1; }
  for module in tk cairo x11 xpm; do
    pkg-config --exists "$module" || {
      echo "Development files for $module are missing: sudo $(packages_for)" >&2
      exit 1
    }
  done
  STAMP="xschem-3.4.7-linux-v1"
  if [[ ! -f "$PREFIX/$STAMP" || ! -x "$PREFIX/bin/xschem" ]]; then
    archive="$SOURCES/xschem.tar.gz"
    if [[ ! -f "$archive" ]]; then
      curl -fL --retry 3 \
        "https://codeload.github.com/StefanSchippers/xschem/tar.gz/92dd8fe5f4d5c1057489710d8a22f18fdc9d7ed0" \
        -o "$archive.part"
      mv "$archive.part" "$archive"
    fi
    if [[ "$(sha256sum "$archive" | awk '{print $1}')" != db5250690bc193bb2874e7a3b43d7bfc3499c882feb7fa885080434cc9a81c7c ]]; then
      echo "Checksum mismatch: $archive. Remove it and retry." >&2
      exit 1
    fi
    rm -rf "$SOURCES/xschem" && mkdir -p "$SOURCES/xschem"
    tar -xzf "$archive" -C "$SOURCES/xschem" --strip-components=1
    echo "Building xschem 3.4.7 against the system X11 Tcl/Tk..."
    (
      cd "$SOURCES/xschem"
      ./configure --prefix="$PREFIX" --user-conf-dir="$PREFIX/config" &&
      make -j"$JOBS" &&
      make install
    ) >"$PREFIX/build-xschem.log" 2>&1 || { tail -40 "$PREFIX/build-xschem.log"; exit 1; }
    touch "$PREFIX/$STAMP"
  fi
fi

# Python 3.13, the locked environment, the SKY130 models and the Laya checkpoint.
uv python install 3.13
uv sync --frozen --python 3.13 --all-extras
uv run --frozen --all-extras python -m chipjev.simulation.pdk
uv run --frozen --all-extras python - <<'PY'
from huggingface_hub import snapshot_download

from chiplaya.laya_torch import MODEL_ID, MODEL_REVISION

snapshot_download(MODEL_ID, revision=MODEL_REVISION,
                  allow_patterns=['*.json', '*.safetensors', 'tokenizer/*', 'LICENSE*', 'NOTICE*'])
print(f"Laya checkpoint {MODEL_ID}@{MODEL_REVISION[:7]} cached.")
import torch
if torch.cuda.is_available():
    print("CUDA:", torch.cuda.get_device_name(0), "| torch", torch.__version__)
else:
    print("No CUDA device: Laya and the acquisition run on the CPU (slower).")
PY
echo "Ready. Try: .venv/bin/chipjev decide \"Design a two-stage op-amp with the highest gain-bandwidth product\""
