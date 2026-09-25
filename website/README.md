# ChipJev website

Static HTML/CSS/JavaScript for GitHub Pages. No frontend build, CDN dependencies,
visitor login, third-party fonts or tracking scripts are required.

The canonical public URL is `https://chipjev.com/`; GitHub Pages redirects the
`www` and original GitHub Pages addresses to it. `robots.txt` allows crawling and
advertises `sitemap.xml`, which lists canonical HTML pages only. Add new public
pages to the sitemap when they are published. Submit the sitemap in the Google
Search Console domain property for `chipjev.com`, which covers both hostnames.
Indexing requests are processed by Google and do not guarantee inclusion.

The visitor selects an allowlisted text prompt and starts a fresh Laya → ChipJev
search → xschem → ngspice pipeline. Native xschem frames, actual model decisions,
measured waveform arrays and performance arrive over a view-only WebSocket.
`demo/analog_layout.py` connects differential pairs, active loads, gain stages and
feedback with electrical xschem wires. Real search candidates are sampled for the live display; the selected result is netlist-verified before the final simulation.
No archived design or measurement seeds a run. The idle poster is clearly labeled
as a reference capture. It is never substituted for an unavailable live backend.

The button timer starts on click; server phase clocks distinguish Laya loading
and inference, design search, and final simulation. Reconnecting restores the run.
The selected prompt and the actual CPU/CUDA device stay visible. The GPU launcher
requires CUDA and fails explicitly if device access is unavailable.

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
