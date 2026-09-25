#!/usr/bin/env bash
# Install a pinned Magic with the fixed SKY130 passive-device RC extractor.
set -euo pipefail
cd "$(dirname "$0")/.."
layout_root="$PWD"
revision=4f53bb3091d1e4a9b2009a58f157a8a4331d4c84
for tool in git make gcc netgen; do
  command -v "$tool" >/dev/null || { echo "Missing $tool (Netgen must be the LVS tool)." >&2; exit 1; }
done
if [[ -x .tools/magic/bin/magic ]] && [[ "$(.tools/magic/bin/magic --commit)" == "$revision" ]]; then
  echo 'Pinned Magic is already installed.'
  exit 0
fi
mkdir -p .tools/src
if [[ ! -d .tools/src/magic-layout/.git ]]; then
  git clone --no-checkout https://github.com/RTimothyEdwards/magic.git .tools/src/magic-layout
fi
git -C .tools/src/magic-layout fetch origin "$revision"
git -C .tools/src/magic-layout checkout --detach "$revision"
(
  cd .tools/src/magic-layout
  ./configure --prefix="$layout_root/.tools/magic" --disable-opengl
  make -j4
  make install
) > .tools/build-magic-layout.log 2>&1
.tools/magic/bin/magic --version
echo 'Magic installed. Build prerequisites: Tcl/Tk development headers, X11, Cairo, make, gcc.'
