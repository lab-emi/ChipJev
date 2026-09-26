# ChipJev website

Static HTML/CSS/JavaScript for GitHub Pages. No frontend build, CDN dependencies,
visitor login, third-party fonts or tracking scripts are required.

When changing the live workspace, bump the stylesheet and app-module query versions
in `index.html` together so returning visitors do not mix cached and new UI assets.

The visitor selects an allowlisted text prompt and starts a fresh Laya → ChipJev
search → xschem → Magic layout/PEX → ngspice pipeline. Native xschem + Magic frames, actual model decisions,
measured waveform arrays and performance arrive over a view-only WebSocket.
`demo/analog_layout.py` connects differential pairs, active loads, gain stages and
feedback with electrical xschem wires. Real search candidates are sampled for the live display; the selected result is netlist-verified before the final simulation.
No archived design or measurement seeds a run. The idle poster is clearly labeled
as a reference capture. It is never substituted for an unavailable live backend.

The button timer starts on click; server phase clocks distinguish Laya loading
and inference, design search (including candidate RC screening), schematic simulation,
layout/DRC, LVS/RC extraction, and post-layout simulation/refinement. Reconnecting restores the run.
The selected prompt and the actual CPU/CUDA device stay visible. The GPU launcher
requires CUDA and fails explicitly if device access is unavailable.

Both native editors are visible throughout the run. A single synchronized capture
is split into adjacent panes on desktop and stacked panes on phones. Magic loads
each generated physical candidate, with live iteration, area and acceptance status,
then restores the selected incumbent before capture stops. The default completed
view preserves both editors; optional final-geometry and device-group views remain.

The completed run offers DRC and LVS status,
extracted R/C counts, an explicit pre/post performance table, and separate AC and
closed-loop response plots. Magic, GDSII, PEX and the full verification ZIP are
downloadable. A failed post-layout candidate cannot terminate the live search.

See [deployment instructions](../deploy/chipjev/README.md) for setup, architecture,
resource limits, Cloudflare Tunnel and Squarespace/custom-domain steps.

Preview with `bash scripts/run-demo-gpu.sh` from the repository root,
after `bash scripts/setup-demo.sh`. Browse `http://127.0.0.1:18766`.

To change the public backend, run `demo.configure_site` as documented. It updates
both the public API URL and the CSP; updating `config.json` alone is insufficient.
Local previews automatically use the same origin. Keep the backend origin HTTPS
for the published page, and allow the page's exact browser origin on the backend.

The site has explicit ready, starting, running, reconnecting, unqualified,
failed, offline and complete states. Refreshing the tab resumes its run while
that run is retained. Download links expire after ten minutes. The service shares
one live run among simultaneous visitors, rather than starting unlimited processes.
