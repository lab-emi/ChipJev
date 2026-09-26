# ChipJev live design demo

The static frontend runs on GitHub Pages. A Linux GPU host runs Laya, ChipJev,
xschem, Magic, Netgen and ngspice. This uses [OpenDPD Studio’s Pages + Tunnel architecture](https://github.com/lab-emi/OpenDPD/blob/main/docs/architecture/public-studio.md).
The browser selects an allowlisted prompt and receives a view-only WebSocket
stream. It cannot submit arbitrary prompts, Tcl, SPICE, files, paths or commands.

```text
Browser → GitHub Pages (chipjev.com)
   └── HTTPS/WSS → Cloudflare Tunnel (api.chipjev.com)
                       └── 127.0.0.1:18766
                           ├── Laya typed decisions on CUDA
                           ├── ChipJev topology/sizing search on CUDA
                           ├── 8 CPU ngspice workers
                           └── private Xvfb + live xschem / Magic + measured plots
```

The registrar can remain Squarespace. A named Cloudflare Tunnel requires the
chipjev.com DNS zone to be active in Cloudflare. The code and service units do
not themselves establish DNS or install a running production service.

## What each click runs

1. Select one of the text prompts in `demo/examples.py`: a complex two-stage
   high-gain op-amp (at least 13 MOSFETs), a wideband two-stage op-amp, or an
   efficient single-stage OTA. All use SKY130 TT, 1.8 V and a 100 pF load.
2. Load the pinned Laya checkpoint and ChipJev fine-tuned weights. Run fresh
   batched typed decisions on the exact selected prompt. Condition its topology
   probabilities on the prompt’s hard stage-count and complexity constraints.
3. Pass that prior into **the actual `ChipJevSearch`**. Typed starts and the
   prior/uniform mixture guide joint topology and transistor-sizing search.
   Eight parallel ngspice workers measure every candidate batch. xschem displays
   sampled candidates as the search runs, with real electrical wires. Display
   updates do not block CUDA acquisition.
   There is no artificial construction delay or prerecorded live footage.
4. Screen strict candidates through actual Magic/Netgen/RC ngspice. Reject failed
   post-layout candidates back into the search. Stop at the first RC-qualified solution, or after 96 batches / a 180 s
   search budget. This interactive profile uses 256 random features, a 1,024-point
   random acquisition pool and a 2,048-point local pool. It is not the full paper
   benchmark. Per-prompt seeds are fixed for reproducibility; no archived sizing
   solution, plot or measurement seeds the search. CPU and CUDA may choose
   different designs because their numerical and random sampling paths differ.
5. Export and netlist the selected wired xschem circuit. Compare every device,
   connection and geometry against ChipJev’s generated circuit. Abort on mismatch.
6. Run a fresh strict SKY130 testbench: AC sweep and positive/negative unity-buffer
   steps. Stream measured arrays and performance numbers. An unqualified search
   result is explicitly labeled; it is never replaced by an archived success.
7. Generate real SKY130 PCells and routing, run full Magic DRC and Netgen LVS,
   extract distributed RC and simulate the actual extracted netlist in ngspice.
   DRC and LVS are separate live steps: each candidate reports running, then its
   verdict (violations, or matched devices and nets). A passed step turns into a
   green check; the final state is that of the selected layout.
   Bounded sizing recovery preserves every attempt; post-layout checks retain
   the original strict limits. See [physical-flow details](../../experiments/layout/README.md).
8. Keep xschem and Magic visible together in one synchronized 1920 × 900 capture.
   Each physical candidate opens in native Magic before LVS/RC extraction; the
   stream reports its plan, iteration and measured acceptance. After optimization,
   restore the selected layout, which can differ from the last attempted candidate.
   The browser splits that single frame into two panes, stacked on small screens.
   Final geometry and device-group views remain available beside the live view.
   R/C counts, schematic/post-layout metrics and both sets of waveforms follow.

The phase clocks report Laya (including load), design search (including candidate
simulations), schematic simulation, layout/DRC, LVS/RC extraction, and post-layout
simulation/refinement. A separate measurement reports Laya
inference latency. Total time starts at the click and freezes when the measured
result arrives. Joining an active run adopts its server elapsed time. The UI and
JSON state the actual CPU/CUDA device; `--device cuda` refuses CPU fallback.

Downloadable artifacts are `decisions.json` (model revision, fine-tuned weight
hash, answers and prior), `search.json` (prior, settings, candidate records and
strict checks), `circuit.sch`, `circuit.spice`, `result.json`, and `plots.png`, plus `layout.mag`,
`layout.gds`, `layout.svg`, `pex.spice`, `physical.json`, `drc.txt`, `lvs.log` and
`physical-evidence.zip` (all attempts, scripts, logs and waveforms).
The idle poster is a labeled native xschem + Magic capture: the final frame of a
completed live run of the default prompt (its selected schematic and layout). It is
not a live result. The viewer
opens private flat-cell copies with unique names to avoid Magic's cell cache;
it does not save or edit extraction inputs. Interactive DRC is disabled in the
viewer; every candidate still runs the full batch DRC/LVS/PEX qualification.

## Local setup and GPU access

Requirements: Linux, NVIDIA GPU with a driver compatible with the locked PyTorch
CUDA 13.0 runtime, Python 3.13, ngspice 47, xschem, Xvfb, xauth, ffmpeg,
Magic ≥8.3.684 and LVS Netgen. `setup-demo.sh` builds the pinned local Magic;
install Tcl/Tk, X11, OpenGL/Mesa and Cairo development headers and the Netgen LVS
tool first. The live viewer requires Magic's OpenGL backend and Xvfb GLX support.
Mesa software rendering uses two llvmpipe rendering threads and does not occupy the CUDA GPU.

```bash
sudo apt-get install -y build-essential curl ripgrep xschem xvfb xauth ffmpeg util-linux libgl-dev libglx-mesa0 libgl1-mesa-dri
# Install uv from https://docs.astral.sh/uv/getting-started/installation/ if needed.
bash scripts/setup-demo.sh
bash scripts/run-demo-gpu.sh
```

The installer preserves `uv.lock`, installs the `rt` and `research` extras plus
hashed HTTP dependencies, and downloads the pinned Laya checkpoint under
`.tools/huggingface`. GPU kernels use the installed NVIDIA driver; a separate
CUDA toolkit installation is not required by this runtime. The launcher performs
an actual CUDA tensor operation before starting the server. The local preview is
`http://127.0.0.1:18766`; production mode without `--preview` serves only `/api/`.

Run the launcher **in the host terminal**. If host `nvidia-smi` works but a sandbox
has no `/dev/nvidia*`, reinstalling the driver does not fix that sandbox’s device
visibility. Do not bypass its isolation. Start the reviewed service on the host.

For a temporary public preview, with cloudflared already installed:

```bash
bash scripts/run-demo-gpu.sh --background
```

This starts a background GPU server and a separate Quick Tunnel. It prints the
new HTTPS URL and writes it to `runs/gpu-api-url.txt`; configure the frontend with
`python -m demo.configure_site --api <that-url>` and republish Pages. Logs and PIDs
are under `runs/gpu-service.*` and `runs/gpu-tunnel.*`. It never modifies another
named tunnel. A Quick Tunnel is temporary and does not establish chipjev.com.
Stop these exact PIDs before switching to the durable service. It is not a
replacement for an unprivileged service on an always-on host.

For explicit CPU development, start `python -m demo.server --device cpu --preview`
with `CHIPJEV_SKY130_XSCHEM` and, if applicable, `HF_HOME` set to the paths above.
The UI will display CPU. An ordinary `uv sync` removes the extra HTTP packages;
restore them with `uv pip install --python .venv/bin/python --require-hashes -r demo/requirements.lock`.

## Validation

```bash
CHIPJEV_SKY130_XSCHEM="$PWD/.tools/xschem" .venv/bin/python -m pytest -q tests/test_demo.py
node --test tests/browser/run-clock.test.mjs
```

The integration test runs real Laya, the real search, xschem, Magic and ngspice. It decodes
changing dual-editor JPEGs, checks that the measured prior is the one used by search,
matches live iteration events to the measured optimization history, verifies the
restored Magic cell against the selected artifact, and downloads/replays results.
A native display test compares changed and restored layout pixels without touching
the extraction inputs. A routing test checks all 190 public
grammar layouts with xschem. Removing signal wires must break connectivity.
Other tests cover prompt allowlisting, origins, shared admission, body/resource
limits, private artifacts, expiry, view-only sockets, and reconnecting timers.
The Pages CI runs the lightweight API and browser-clock tests; EDA/model tests
require the locally installed tools and checkpoint.

## Durable compute service

A VM per visitor is unnecessary for this bounded prompt-selector API. Use a
separate unprivileged service on an always-on GPU host. The included systemd unit
has a read-only root, private temporary files, no capabilities or privilege
escalation, and loopback-only network access. GPU access uses `DevicePolicy=closed`
and explicit NVIDIA device allowances. `PrivateDevices=true` would hide the GPU;
see [systemd’s device policy](https://www.freedesktop.org/software/systemd/man/latest/systemd.resource-control.html#DeviceAllow=).
Cloudflare credentials belong to a separate service and never reach EDA workers.

Install a fresh clone at `/opt/chipjev`, run `scripts/setup-demo.sh` there, and
check the host with `python -m demo.runtime --device cuda`. Keep the checkout and
model cache readable by the dynamic service user. Do not copy a development
`.venv` or symlinked tool tree. The installer keeps Python under `.tools/python`.

```bash
sudo chown -R root:root /opt/chipjev
sudo install -m 644 /opt/chipjev/deploy/chipjev/chipjev-demo.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now chipjev-demo.service
curl --fail http://127.0.0.1:18766/api/health
```

Expect `ready: true`, `mode: live-design`, and `compute.cuda: true`. Check failures
with `journalctl -u chipjev-demo.service` and private worker logs under
`/var/lib/chipjev-demo`. These commands require host administration; committing
these files does not install them. Test the CUDA and EDA path after installation.

Limits: one shared run, 32 viewers, 5 minutes per entire run, a 15-second cooldown,
120 runs/hour, eight retained results and ten-minute expiry. The service has an
8 GiB RAM cap, eight-core CPU quota and 256-task cap. Workers have CPU, open-file,
file-size and core-dump limits. Do not impose the old 4 GiB virtual-address-space
limit: CUDA reserves a large virtual address space. Timeout/shutdown kills the
worker process group. Restart cleans only the service’s random run directories.
GPU work is bounded by a fixed model, fixed search profile and single admission.

`POST /api/runs` accepts only `{"example":"opamp-gain"}` or another listed ID;
`{}` selects the default. Concurrent visitors join the same run and see its actual
selected prompt. Inputs cannot edit constraints, budgets, source code or files.
Origin checks protect browsers, not authenticate callers. Fixed global limits
also apply to non-browser callers. Editable SPICE/Tcl would need a new isolation
design because those are executable languages.

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
