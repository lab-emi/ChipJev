#!/usr/bin/env bash
# What rerunning AnalogCoder-Pro's released LLM flow needs (reproduce/reproduce-paper.sh --rerun):
#   * the authors' repository at the pinned commit 05542af in .tools/acpro (not redistributed;
#     the frozen runners also read its task statements);
#   * ngspice 47 as a shared library (.tools/ngspice-shared, --with-ngshared) for PySpice;
#   * a Python 3.11 virtual environment (.tools/acpro-venv) with the package versions used in
#     the study: PySpice 1.5, NumPy 1.26, Optuna 4.9, openai 3.19.2;
#   * bubblewrap, in which every generated program and the sizing helper run.
# Run scripts/setup.sh first. Idempotent: finished steps are skipped.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"
TOOLS="$ROOT/.tools"
SRC="$TOOLS/src"
NGSPICE_VERSION=47
NGSPICE_URL="https://sourceforge.net/projects/ngspice/files/ng-spice-rework/${NGSPICE_VERSION}/ngspice-${NGSPICE_VERSION}.tar.gz/download"
mkdir -p "$SRC"

command -v uv >/dev/null || { echo "Install uv first (scripts/setup.sh)." >&2; exit 1; }
command -v bwrap >/dev/null \
  || echo "bubblewrap is missing (apt-get install bubblewrap): AnalogCoder-Pro's flow cannot run without it." >&2

ACPRO="$TOOLS/acpro/AnalogCoderPro"
if [[ ! -d "$ACPRO/.git" ]]; then
  echo "Fetching AnalogCoder-Pro (commit 05542af) into .tools/acpro..."
  mkdir -p "$(dirname "$ACPRO")"
  git clone -q https://github.com/laiyao1/AnalogCoderPro.git "$ACPRO"
fi
git -C "$ACPRO" checkout -q 05542af46020e5c37d5a7e3ca79da9f24626e1c9

if [[ ! -f "$TOOLS/ngspice-shared/lib/libngspice.so" ]]; then
  if [[ ! -f "$SRC/ngspice-${NGSPICE_VERSION}.tar.gz" ]]; then
    curl -L --fail -o "$SRC/ngspice-${NGSPICE_VERSION}.tar.gz.part" "$NGSPICE_URL"
    mv "$SRC/ngspice-${NGSPICE_VERSION}.tar.gz.part" "$SRC/ngspice-${NGSPICE_VERSION}.tar.gz"
  fi
  if [[ "$(sha256sum "$SRC/ngspice-${NGSPICE_VERSION}.tar.gz" | awk '{print $1}')" != 894e649651f1838a14095e5a5439e7d3aa63e87ede14d283173fda4fcdef675f ]]; then
    echo "Checksum mismatch: $SRC/ngspice-${NGSPICE_VERSION}.tar.gz. Remove it and retry." >&2
    exit 1
  fi
  echo "Building the ngspice ${NGSPICE_VERSION} shared library into .tools/ngspice-shared..."
  dir="$SRC/ngspice-${NGSPICE_VERSION}-shared"
  mkdir -p "$TOOLS/ngspice-shared"
  rm -rf "$dir" && mkdir -p "$dir"
  tar -xzf "$SRC/ngspice-${NGSPICE_VERSION}.tar.gz" -C "$dir" --strip-components=1
  ( cd "$dir" && ./configure --prefix="$TOOLS/ngspice-shared" --with-x=no --with-readline=no \
      --enable-openmp --with-ngshared && make -j"$(nproc)" && make install ) \
    > "$TOOLS/build-ngspice${NGSPICE_VERSION}-ngspice-shared.log" 2>&1 \
    || { tail -30 "$TOOLS/build-ngspice${NGSPICE_VERSION}-ngspice-shared.log" >&2; exit 1; }
fi

if [[ ! -x "$TOOLS/acpro-venv/bin/python" ]]; then
  echo "Creating .tools/acpro-venv (Python 3.11)..."
  uv venv --python 3.11 "$TOOLS/acpro-venv"
fi
uv pip install --python "$TOOLS/acpro-venv/bin/python" \
  "PySpice==1.5" "numpy==1.26.4" "optuna==4.9.0" "openai==3.19.2" "scipy==1.17.1" "matplotlib==3.11.2" "cffi==2.1.1"
"$TOOLS/acpro-venv/bin/python" -c "import PySpice, numpy, optuna, openai; print('acpro-venv ok:', PySpice.__version__, numpy.__version__, optuna.__version__)"
echo "AnalogCoder-Pro environment ready (.tools/acpro, .tools/acpro-venv, .tools/ngspice-shared)."
