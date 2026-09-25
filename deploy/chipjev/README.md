# ChipJev live demo deployment

The website is a static GitHub Pages site. The simulation runs on a Linux host;
GitHub Pages cannot execute xschem or ngspice. This follows
[OpenDPD Studio's Pages + Tunnel architecture](https://github.com/lab-emi/OpenDPD/blob/main/docs/architecture/public-studio.md),
with a much smaller public surface: one fixed example and a view-only stream.

```text
Browser ── HTTPS ── GitHub Pages (chipjev.com)
   └──── HTTPS/WSS ── Cloudflare Tunnel (api.chipjev.com)
                            └── 127.0.0.1:18766
                                fixed-run API, unprivileged systemd service
                                  ├── private Xvfb + xschem
                                  ├── fresh ngspice 47 AC/buffer simulations
                                  └── JPEG frames + measured waveform events
```

The registrar can remain Squarespace. A named Cloudflare Tunnel on
`api.chipjev.com` requires the domain's DNS zone to be active in Cloudflare.
Changing nameservers changes DNS hosting, not domain ownership or registration.

## What a visitor actually runs

`demo/select_example.py` ranks all 60 qualified **final** ChipJev designs in the
archived SKY130 study by MOS count, then passive count and gain-stage count.
It selects `cmota_n+inv_cas+miller`, seed 2 of `sky130-opampN-gain`, with 13 MOSFETs
and one Miller capacitor. The checked-in fixture records the evidence path,
SHA-256, physical values and reference metrics. It does not alter the evidence.

Each click starts a fresh run, or joins the current shared run:

1. Start an Xvfb display with its own Xauthority cookie; never capture the host desktop.
2. Assemble actual xschem schematics, adding one device and its named net connections
   every 140 ms. This display pacing is included in the reported demo duration.
3. Netlist the final schematic with xschem. Compare device identity, connectivity and
   geometry against ChipJev's generated circuit. A mismatch aborts the run.
4. Run ChipJev's existing strict SKY130 testbench on that verified circuit, including
   the AC sweep and positive/negative unity-buffer steps. The testbench is generated
   by ChipJev; the connectivity check establishes equivalence to the xschem netlist.
5. Stream measured arrays and the final result, with downloadable schematic, SPICE
   circuit and JSON. Failed qualification remains visible as a failure.

There is **no new Laya inference or topology search** in this button demo. It is a
live reconstruction and re-simulation of a published example, explicitly labeled
in the UI. It requires no GPU, model checkpoint, LLM API key or visitor account.
The idle poster is labeled as a reference capture; an unavailable backend never
substitutes a recording or fabricated simulation data.

## Local setup

Linux x86-64, Python 3.13 (managed by uv), ngspice 47, xschem, Xvfb, xauth and
ffmpeg are required. On Ubuntu, install prerequisites with:

```bash
sudo apt-get install -y build-essential curl ripgrep xschem xvfb xauth ffmpeg util-linux
# Install uv from https://docs.astral.sh/uv/getting-started/installation/ if needed.
bash scripts/setup-demo.sh
CHIPJEV_SKY130_XSCHEM="$PWD/.tools/xschem" .venv/bin/python -m demo.server --preview
```

Open `http://127.0.0.1:18766`. The preview serves only `website/` and the API;
production serves only the API. `setup-demo.sh` installs the CPU research extras,
adds the separately hashed HTTP dependencies, builds ngspice 47 if needed, and
downloads the pinned models and two Apache-2.0 SKY130 symbols. The frozen root
`uv.lock` is unchanged. An ordinary subsequent `uv sync` removes the demo's HTTP
dependencies; rerun the `uv pip install` line below if that happens.

```bash
uv pip install --python .venv/bin/python --require-hashes -r demo/requirements.lock
CHIPJEV_SKY130_XSCHEM="$PWD/.tools/xschem" .venv/bin/python -m pytest -q tests/test_demo.py
```

The integration test really launches xschem and ngspice, decodes changing JPEGs,
checks qualification and netlist equivalence, downloads results, and reconnects.
Tests also cover foreign origins, arbitrary inputs, body limits, shared admission,
cooldown, private artifacts, expired runs, viewer limits, and view-only sockets.

## Durable compute service

Use a dedicated, always-on Linux host. A per-visitor VM is unnecessary for this
fixed-input API. The included systemd unit runs as a separate dynamic user with a
read-only filesystem, private temporary directory/devices, no capabilities, no
privilege escalation and loopback-only networking. Cloudflare credentials belong
to a different service and are never passed to EDA workers.

Install a **fresh clone** at `/opt/chipjev`, then run `scripts/setup-demo.sh` there.
Do not copy a development `.venv` or `.tools` tree. The installer keeps its managed
Python under `.tools/python`, so `ProtectHome=true` does not hide the interpreter.
After installation, make the checkout root-owned and world-readable/executable
as appropriate; the service must be able to read source, models, symbols and fonts.

```bash
sudo chown -R root:root /opt/chipjev
sudo install -m 644 /opt/chipjev/deploy/chipjev/chipjev-demo.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now chipjev-demo.service
curl --fail http://127.0.0.1:18766/api/health
```

The response must say `"ready": true`. Inspect failures with
`journalctl -u chipjev-demo.service` and the private worker logs under
`/var/lib/chipjev-demo`. Do not run the public API as your normal desktop user.
The installation above requires host administration; committing these units does
not install or start them.

Limits: one shared run, 32 live viewers, 90 seconds per run, 15-second cooldown,
120 runs/hour, at most eight retained results, ten-minute expiry. Per-process CPU,
address-space, open-file and file-size limits supplement the service's 2 GiB
memory cap, two-core quota and 64-task cap. Timeout/shutdown kills the worker's
whole process group. Restart discards the previous service's run directories.
No user-supplied Tcl, SPICE, shell, paths, text, parameters, uploads or remote
desktop input are accepted. Origin checks are browser protections, not identity
authentication; global limits still apply to non-browser callers. The results
are public examples, so run IDs are not private-data credentials.

Keep this boundary fixed. Offering editable SPICE or Tcl later would expose
executable tool languages and require a new isolation design.

## Named HTTPS tunnel

After Cloudflare DNS is active, use an authenticated cloudflared CLI on the host:

```bash
cloudflared tunnel create chipjev-demo
cloudflared tunnel route dns chipjev-demo api.chipjev.com
```

Record the returned UUID. Copy `cloudflared.yml.example` to
`/etc/chipjev-demo/cloudflared.yml` and replace the tunnel UUID. Install the generated
tunnel JSON as `/etc/chipjev-demo/tunnel.json`, root-owned, mode `0600`. Install
cloudflared at `/usr/local/bin/cloudflared` (or adjust `ExecStart`).

```bash
sudo install -m 644 /opt/chipjev/deploy/chipjev/cloudflared-chipjev.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now cloudflared-chipjev.service
curl --fail https://api.chipjev.com/api/health
```

The tunnel unit uses systemd `LoadCredential`. Never commit the tunnel JSON, login
certificate, a tunnel token or any DNS API key. Do not modify the OpenDPD tunnel.
Allow WebSocket upgrades and disable caching for the API hostname. The ingress
only forwards `/api/`; all other paths return 404.

For a **temporary development demonstration only**, `cloudflared tunnel --url
http://127.0.0.1:18766 --protocol http2` provides a random HTTPS origin. It has no
uptime guarantee, changes when recreated, and lasts only while both foreground
processes remain alive. This implementation uses WebSockets, so it does not depend
on the SSE support absent from Quick Tunnels. Never describe it as a durable
production deployment.

## GitHub Pages and chipjev.com

Enable GitHub Actions as this repository's Pages source. The pinned Pages workflow
verifies the API boundary and JavaScript before uploading **only** `website/`.
Before configuring a custom domain, the site is available at
`https://lab-emi.github.io/ChipJev/`.

1. In Squarespace, preserve all existing mail/TXT records and set the domain's
   nameservers to the exact pair assigned to **chipjev.com** by Cloudflare. Do not
   guess this pair or use another zone's nameservers. Wait for Cloudflare to show
   the zone as active.
2. In Cloudflare DNS, replace the Squarespace parking records for the apex and
   `www` with the following **DNS-only** records. Preserve unrelated records.

   | Type | Name | Value |
   | --- | --- | --- |
   | A | @ | 185.199.108.153 |
   | A | @ | 185.199.109.153 |
   | A | @ | 185.199.110.153 |
   | A | @ | 185.199.111.153 |
   | CNAME | www | lab-emi.github.io |

   `cloudflared tunnel route dns` creates the proxied `api` tunnel record separately.
   Do not create wildcard DNS records. Follow
   [GitHub's custom domain documentation](https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/managing-a-custom-domain-for-your-github-pages-site).
3. In GitHub → repository Settings → Pages, set the custom domain to `chipjev.com`.
   Enable **Enforce HTTPS** once the certificate is available. With an Actions
   deployment, the repository setting establishes the custom domain; a `CNAME`
   file alone does not configure it. Verify domain ownership in GitHub where available.
4. Configure the frontend for the durable API and custom domain, then commit/push:

   ```bash
   .venv/bin/python -m demo.configure_site --api https://api.chipjev.com --public-url https://chipjev.com/
   ```

   This updates both `config.json` and the **exact-origin CSP**. Never put secrets
   in frontend configuration. The backend's default origin allowlist already covers
   `chipjev.com`, `www.chipjev.com` and the repository's GitHub Pages origin.
5. Verify HTTPS on the apex and `www`, run the button through to qualification,
   reconnect once, and download that run's artifacts. Use a desktop and a narrow
   mobile viewport for visual acceptance. DNS propagation and certificate issuance
   may finish later than the code deployment.

To roll back, stop the two services and restore the prior Pages/DNS settings.
The scientific package, frozen lockfile and archived experiments are unchanged.
