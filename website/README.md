# ChipJev website

Static HTML/CSS/JavaScript for GitHub Pages. No frontend build, CDN dependencies,
visitor login, third-party fonts or tracking scripts are required.

The main action starts a real, fixed-example xschem/ngspice run. The backend streams
actual xschem JPEGs and measured waveform arrays over a view-only WebSocket.
The idle poster is a reference capture. It is never presented as a live run.

See [deployment instructions](../deploy/chipjev/README.md) for setup, architecture,
resource limits, Cloudflare Tunnel and Squarespace/custom-domain steps.

Preview with `.venv/bin/python -m demo.server --preview` from the repository root,
after `bash scripts/setup-demo.sh`. Browse `http://127.0.0.1:18766`.

To change the public backend, run `demo.configure_site` as documented. It updates
both the public API URL and the CSP; updating `config.json` alone is insufficient.
Local previews automatically use the same origin. Keep the backend origin HTTPS
for the published page, and allow the page's exact browser origin on the backend.

The site has explicit ready, starting, running, reconnecting, unqualified,
failed, offline and complete states. Refreshing the tab resumes its run while
that run is retained. Download links expire after ten minutes. The service shares
one live run among simultaneous visitors, rather than starting unlimited processes.
