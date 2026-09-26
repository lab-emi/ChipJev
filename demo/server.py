"""Public API for the prompt-selected, view-only ChipJev demo. Bind to loopback only.

One shared run at a time. WebSocket messages carry actual xschem JPEG frames
and structured simulation events; spectators have no keyboard/mouse channel.
"""

import argparse
import asyncio
import contextlib
import fcntl
import json
import os
import re
import secrets
import shutil
import signal
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from aiohttp import web

from chipjev import xschem
from chipjev.layout.magic import readiness as layout_readiness
from chipjev.paths import ROOT, ngspice
from chipjev.simulation.pdk import model_root
from demo.examples import DEFAULT_EXAMPLE, EXAMPLES
from demo.runtime import inspect_runtime

FIXTURE = json.loads((ROOT / "demo/fixtures/sky130-opamp.json").read_text())
ARTIFACTS = {"circuit.sch": "text/plain", "circuit.spice": "text/plain",
             "result.json": "application/json", "plots.png": "image/png",
             "decisions.json": "application/json", "search.json": "application/json",
             "layout.svg": "image/svg+xml", "layout.mag": "text/plain",
             "layout.gds": "application/octet-stream", "pex.spice": "text/plain",
             "physical.json": "application/json", "drc.txt": "text/plain", "lvs.log": "text/plain",
             "physical-evidence.zip": "application/zip",
             "layout-intent.svg": "image/svg+xml", "optimization.json": "application/json"}
DEFAULT_ORIGINS = {"https://chipjev.com", "https://www.chipjev.com",
                   "https://lab-emi.github.io"}
RUN_TTL = 600
RUN_TIMEOUT = 300
COOLDOWN = 15
MAX_VIEWERS = 32
MAX_RETAINED = 8


@dataclass
class Run:
    id: str
    directory: Path
    example: str = DEFAULT_EXAMPLE
    created: float = field(default_factory=time.monotonic)
    events: list = field(default_factory=list)
    status: str = "running"
    task: asyncio.Task | None = None
    process: asyncio.subprocess.Process | None = None
    frame: bytes | None = None
    frame_stamp: int = 0
    viewers: int = 0


class Service:
    def __init__(self, directory, origins, preview=False, device="auto"):
        self.directory = directory.resolve()
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock = (self.directory / ".server.lock").open("a")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock.close()
            raise RuntimeError("Another demo server owns this state directory") from None
        # Previous process' demo outputs are disposable. Only our own
        # random run-directory names are eligible; never follow a symlink.
        for old in self.directory.iterdir():
            if re.fullmatch(r"[0-9a-f]{32}", old.name) and old.is_dir() and not old.is_symlink():
                shutil.rmtree(old)
        self.origins = frozenset(origins)
        self.preview = preview
        self.device = device
        self.compute = {"device": "Checking", "cuda": False}
        self.runtime_check = None
        self.runs = {}
        self.active = None
        self.next_start = 0.0
        self.viewers = 0
        self.admissions = deque(maxlen=120)
        self.maintenance = None

    def readiness(self):
        missing = [name for name in ("Xvfb", "xschem", "xauth", "ffmpeg", "prlimit")
                   if shutil.which(name) is None]
        if shutil.which(ngspice()) is None:
            missing.append("ngspice")
        if not (xschem.library() / "sky130_fd_pr/nfet_01v8.sym").exists():
            missing.append("SKY130 xschem symbols")
        if not (model_root() / "libs.ref/sky130_fd_pr/spice").exists():
            missing.append("SKY130 models")
        if self.runtime_check is None:
            self.compute, self.runtime_check = inspect_runtime(self.device)
        return missing + layout_readiness() + self.runtime_check

    def publish(self, run, event):
        # At most two events per search round plus the bounded phase events.
        if len(run.events) >= 400:
            raise RuntimeError("Worker exceeded the event limit")
        run.events.append({**event, "id": len(run.events) + 1,
                           "elapsed": round(time.monotonic() - run.created, 3)})

    def failure(self, run, message):
        run.status = "error"
        if not run.events or run.events[-1]["type"] != "error":
            self.publish(run, {"type": "error", "message": message})

    async def execute(self, run):
        # Do not pass hosting credentials, SSH agents, DISPLAY or a user's desktop
        # environment to EDA processes. The worker creates its own display.
        environment = {
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "PYTHONPATH": str(ROOT / "src") + os.pathsep + str(ROOT),
            "PYTHONUNBUFFERED": "1", "LC_ALL": "C.UTF-8", "OMP_NUM_THREADS": "8",
            "HF_HUB_OFFLINE": "1", "TOKENIZERS_PARALLELISM": "false",
            "TRITON_CACHE_DIR": str(self.directory / ".triton"),
            "TORCHINDUCTOR_CACHE_DIR": str(self.directory / ".torch-cache"),
            "OPENBLAS_NUM_THREADS": "1", "MPLCONFIGDIR": str(run.directory / "mpl"),
            "TMPDIR": str(run.directory), "CHIPJEV_PDK": str(model_root()),
            "CHIPJEV_SKY130_XSCHEM": str(xschem.library()),
        }
        # Tcl requires the existing HOME value even with an explicit rcfile.
        # xschem's writable configuration is separately redirected into this run.
        if "HOME" in os.environ:
            environment["HOME"] = os.environ["HOME"]
        if "HF_HOME" in os.environ:
            environment["HF_HOME"] = os.environ["HF_HOME"]
        try:
            with (run.directory / "worker.log").open("wb") as log:
                run.process = await asyncio.create_subprocess_exec(
                    "prlimit", "--cpu=1800:1800",
                    "--nofile=256:256", "--fsize=67108864:67108864", "--core=0:0", "--",
                    sys.executable, "-m", "demo.worker", "--directory", str(run.directory),
                    "--example", run.example, "--device", self.device,
                    cwd=ROOT, env=environment, start_new_session=True,
                    stdout=asyncio.subprocess.PIPE, stderr=log, limit=262144,
                )
                async with asyncio.timeout(RUN_TIMEOUT):
                    while line := await run.process.stdout.readline():
                        event = json.loads(line)
                        if event.get("type") not in {"stage", "waveforms", "result", "error"}:
                            raise RuntimeError("Unexpected worker event")
                        self.publish(run, event)
                        if event["type"] == "error":
                            run.status = "error"
                    code = await run.process.wait()
                    terminal = any(e.get("stage") in {"complete", "unqualified"} for e in run.events)
                    if code or not terminal:
                        self.failure(run, "The simulation stopped. Please try a new run.")
                    elif run.status != "error":
                        run.status = "complete"
        except TimeoutError:
            self.failure(run, "The simulation exceeded its 5-minute limit. Please try again.")
        except asyncio.CancelledError:
            self.failure(run, "The demo server is restarting. Please reconnect.")
            raise
        except Exception:
            self.failure(run, "The simulation could not finish. Please retry shortly.")
        finally:
            if run.process is not None:
                # Kill the whole group, including Xvfb/ngspice on timeout/crash.
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(run.process.pid, signal.SIGTERM)
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(run.process.wait(), timeout=2)
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(run.process.pid, signal.SIGKILL)
                await run.process.wait()
            if self.active == run.id:
                self.active = None
            self.next_start = time.monotonic() + COOLDOWN

    async def reap(self):
        while True:
            for ident, run in list(self.runs.items()):
                if run.status != "running" and time.monotonic() - run.created >= RUN_TTL:
                    del self.runs[ident]
                    await asyncio.to_thread(shutil.rmtree, run.directory, True)
            await asyncio.sleep(10)

    async def close(self):
        tasks = [r.task for r in self.runs.values() if r.task is not None]
        if self.maintenance:
            tasks.append(self.maintenance)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.lock.close()


SERVICE = web.AppKey("service", Service)


def json_response(data, status=200):
    return web.json_response(data, status=status, dumps=lambda x: json.dumps(x, allow_nan=False))


@web.middleware
async def policy(request, handler):
    service = request.app[SERVICE]
    origin = request.headers.get("Origin")
    if origin is not None and origin not in service.origins:
        return json_response({"error": "This browser origin is not allowed."}, 403)
    if request.path.startswith("/api/") and request.query:
        return json_response({"error": "Query parameters are not accepted."}, 400)
    try:
        return await handler(request)
    except web.HTTPException as exc:
        return json_response({"error": exc.reason}, exc.status)


async def response_headers(request, response):
    response.headers.update({"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                             "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY"})
    origin = request.headers.get("Origin")
    if origin in request.app[SERVICE].origins:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"


async def health(request):
    service = request.app[SERVICE]
    missing = service.readiness()
    return json_response({"ready": not missing, "missing": missing,
                          "active_run": service.active, "examples": list(EXAMPLES.values()),
                          "compute": service.compute, "mode": "live-design", "retention_seconds": RUN_TTL},
                         503 if missing else 200)


async def preflight(request):
    if request.headers.get("Origin") not in request.app[SERVICE].origins:
        raise web.HTTPForbidden()
    if request.headers.get("Access-Control-Request-Method") != "POST":
        raise web.HTTPMethodNotAllowed("OPTIONS", ["POST"])
    headers = request.headers.get("Access-Control-Request-Headers", "").lower().split(",")
    if any(h.strip() not in {"", "content-type"} for h in headers):
        raise web.HTTPForbidden()
    return web.Response(status=204, headers={"Access-Control-Allow-Methods": "POST",
                                            "Access-Control-Allow-Headers": "Content-Type",
                                            "Access-Control-Max-Age": "600"})


async def start(request):
    service = request.app[SERVICE]
    if request.headers.get("Origin") not in service.origins:
        return json_response({"error": "An allowed browser Origin is required."}, 403)
    if request.content_type != "application/json":
        return json_response({"error": "Send a JSON object with a listed example ID."}, 415)
    try:
        async with asyncio.timeout(3):
            body = await request.read()
        payload = json.loads(body)
        if not isinstance(payload, dict) or set(payload) - {"example"}:
            raise ValueError
        example_id = payload.get("example", DEFAULT_EXAMPLE)
        if not isinstance(example_id, str) or example_id not in EXAMPLES:
            raise ValueError
    except (ValueError, TimeoutError):
        return json_response({"error": "Only a listed example ID is accepted; prompts and commands cannot be submitted."}, 400)
    if service.readiness():
        return json_response({"error": "The simulation service is not ready."}, 503)
    if service.active:
        return json_response({"id": service.active, "joined": True,
                              "example": EXAMPLES[service.runs[service.active].example]}, 200)
    now = time.monotonic()
    if now < service.next_start:
        seconds = max(1, int(service.next_start - now) + 1)
        return json_response({"error": f"The demo is cooling down. Retry in {seconds} seconds.",
                              "retry_after": seconds}, 429)
    if len(service.admissions) == 120 and now - service.admissions[0] < 3600:
        return json_response({"error": "The hourly run limit has been reached. Please try later."}, 429)
    # Drop the oldest retained result before admission. No unbounded disk growth.
    if len(service.runs) >= MAX_RETAINED:
        old = next((r for r in service.runs.values() if r.status != "running" and not r.viewers), None)
        if old is None:
            return json_response({"error": "The demo is at capacity. Please retry shortly."}, 503)
        del service.runs[old.id]
        shutil.rmtree(old.directory, ignore_errors=True)
    ident = secrets.token_hex(16)
    directory = service.directory / ident
    directory.mkdir(mode=0o700)
    run = Run(ident, directory, example=example_id)
    service.runs[ident] = run
    service.active = ident
    service.admissions.append(now)
    run.task = asyncio.create_task(service.execute(run))
    return json_response({"id": ident, "joined": False, "example": EXAMPLES[example_id]}, 202)


def get_run(request):
    run = request.app[SERVICE].runs.get(request.match_info["id"])
    if run is None or time.monotonic() - run.created >= RUN_TTL:
        raise web.HTTPNotFound(reason="This run has expired. Start a new simulation.")
    return run


async def snapshot(request):
    run = get_run(request)
    return json_response({"id": run.id, "status": run.status, "example": EXAMPLES[run.example], "events": run.events})


async def stream(request):
    service = request.app[SERVICE]
    run = get_run(request)
    # A browser WebSocket always sends an Origin. No keyboard/control messages exist.
    if request.headers.get("Origin") not in service.origins:
        raise web.HTTPForbidden()
    if service.viewers >= MAX_VIEWERS:
        raise web.HTTPServiceUnavailable(reason="The live stream is full. Please retry shortly.")
    ws = web.WebSocketResponse(heartbeat=20, max_msg_size=64, compress=False)
    await ws.prepare(request)
    service.viewers += 1
    run.viewers += 1

    async def receive():
        async for message in ws:
            if message.type in {web.WSMsgType.TEXT, web.WSMsgType.BINARY}:
                await ws.close(code=1008, message=b"View-only stream")
                return

    receiver = asyncio.create_task(receive())
    sent, last_stamp = 0, 0
    try:
        while not ws.closed:
            if time.monotonic() - run.created >= RUN_TTL:
                break
            async with asyncio.timeout(5):
                for event in run.events[sent:]:
                    await ws.send_json(event)
                    sent += 1
                path = run.directory / "frame.jpg"
                try:
                    stamp = path.stat().st_mtime_ns
                    if stamp != run.frame_stamp:
                        # Only the latest frame is retained; slow clients cannot queue video.
                        run.frame = path.read_bytes()
                        run.frame_stamp = stamp
                    if run.frame and stamp != last_stamp:
                        await ws.send_bytes(run.frame)
                        last_stamp = stamp
                except FileNotFoundError:
                    pass
            if run.status != "running":
                await ws.send_json({"type": "finished", "status": run.status})
                break
            await asyncio.sleep(0.125)
    except (TimeoutError, ConnectionError):
        pass
    finally:
        receiver.cancel()
        await asyncio.gather(receiver, return_exceptions=True)
        service.viewers -= 1
        run.viewers -= 1
        await ws.close()
    return ws


async def artifact(request):
    run = get_run(request)
    name = request.match_info["name"]
    if name not in ARTIFACTS or run.status != "complete":
        raise web.HTTPNotFound()
    path = run.directory / name
    if not path.is_file():
        raise web.HTTPNotFound()
    if name == "circuit.spice":
        content = path.read_text().replace(str(run.directory), "<run>").replace(str(ROOT), "<repo>")
        return web.Response(text=content, content_type="text/plain",
                            headers={"Content-Disposition": f'attachment; filename="{name}"'})
    return web.FileResponse(path, headers={"Content-Type": ARTIFACTS[name],
                                          "Content-Disposition": f'attachment; filename="{name}"'})


def create_app(directory=None, origins=None, preview=False, device="auto"):
    service = Service(directory or ROOT / "runs/live-demo", origins or DEFAULT_ORIGINS, preview, device)
    app = web.Application(middlewares=[policy], client_max_size=64)
    app[SERVICE] = service
    app.on_response_prepare.append(response_headers)
    app.router.add_get("/api/health", health)
    app.router.add_options("/api/runs", preflight)
    app.router.add_post("/api/runs", start)
    prefix = r"/api/runs/{id:[0-9a-f]{32}}"
    app.router.add_get(prefix, snapshot)
    app.router.add_get(prefix + "/live", stream)
    app.router.add_get(prefix + "/artifacts/{name}", artifact)
    if preview:
        async def index(request):
            return web.FileResponse(ROOT / "website/index.html")
        app.router.add_get("/", index)
        # Explicit public directory only; never expose the repository or run root.
        app.router.add_static("/", ROOT / "website", show_index=False, follow_symlinks=False)

    async def lifecycle(app):
        service.maintenance = asyncio.create_task(service.reap())
        try:
            yield
        finally:
            await service.close()
    app.cleanup_ctx.append(lifecycle)
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=18766)
    parser.add_argument("--preview", action="store_true", help="Also serve the website locally")
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    parser.add_argument("--state", type=Path, default=ROOT / "runs/live-demo")
    args = parser.parse_args()
    origins = set(filter(None, os.environ.get("CHIPJEV_DEMO_ORIGINS", "").split(","))) or DEFAULT_ORIGINS
    if args.preview:
        origins = origins | {f"http://localhost:{args.port}", f"http://127.0.0.1:{args.port}"}
    web.run_app(create_app(args.state, origins, args.preview, args.device), host="127.0.0.1", port=args.port,
                access_log=None, handler_cancellation=True, shutdown_timeout=5)


if __name__ == "__main__":
    main()
