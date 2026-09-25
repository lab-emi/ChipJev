"""Pinned public SKY130 model acquisition; no PDK files are silently substituted.

  python -m chipjev.simulation.pdk      # download, verify and unpack into .tools/pdk
"""

import hashlib
import os
import urllib.request
import zipfile
from pathlib import Path

from ..paths import ROOT

REVISION = "0a9d1390ade361e2b4a2d33181e22367edbb8afc"
SHA256 = "bc46a070e6c8c217e61e97355ed2ab3f029706a99b5053a80860cd98963e1ce8"
URL = f"https://raw.githubusercontent.com/CODA-Team/AnalogGym/{REVISION}/PDK/sky130_pdk.zip"


def model_root():
    return Path(os.environ.get("CHIPJEV_PDK", ROOT / ".tools/pdk/sky130_pdk")).resolve()


def prepare():
    destination = ROOT / ".tools/pdk"
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / "sky130_pdk.zip"
    if not archive.exists():
        urllib.request.urlretrieve(URL, archive)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
        raise RuntimeError("SKY130 archive checksum mismatch; remove the archive and retry.")
    if not (model_root() / "libs.tech/ngspice/corners/tt.spice").exists():
        with zipfile.ZipFile(archive) as bundle:
            for member in bundle.infolist():
                path = (destination / member.filename).resolve()
                if not path.is_relative_to(destination.resolve()):
                    raise RuntimeError("Unsafe archive path.")
            bundle.extractall(destination)
    return model_root()


if __name__ == "__main__":
    print(prepare())
