"""The public demo's execution boundary and real EDA/stream path."""

import asyncio
import gzip
import hashlib
import io
import json
import time

import pytest
from aiohttp import WSMsgType
from aiohttp.test_utils import TestClient, TestServer

from chipjev import xschem
from chipjev.circuits.published import lookup
from chipjev.circuits.sky130_devices import build
from chipjev.paths import ROOT
from demo.schematic import schematic_steps
from demo.server import FIXTURE, MAX_VIEWERS, RUN_TTL, SERVICE, Service, create_app

ORIGIN = "https://chipjev.com"


def test_fixture_is_the_largest_qualified_final_chipjev_design():
    source = ROOT / FIXTURE["source"]
    assert hashlib.sha256(source.read_bytes()).hexdigest() == FIXTURE["source_sha256"]
    with gzip.open(source, "rt") as stream:
        source_run = json.load(stream)
    assert source_run["best"]["values"] == FIXTURE["values"]
    assert source_run["verified"]
    counts = []
    for path in source.parent.glob("*__chipjev__*.json.gz"):
        with gzip.open(path, "rt") as stream:
            data = json.load(stream)
        if data["verified"] and data["best"]:
            top = lookup(data["cls"], data["best"]["topology"])
            counts.append(len(build(top, data["best"]["values"], data["vdd"]).mos))
    assert max(counts) == FIXTURE["mosfets"] == 13
    assert len(counts) == FIXTURE["candidate_count"] == 60


def test_public_boundary_and_single_shared_run(tmp_path):
    async def scenario():
        app = create_app(tmp_path)
        service = app[SERVICE]
        service.readiness = lambda: []
        executed = []

        async def bounded_fake(run):
            executed.append(run.id)
            await asyncio.sleep(60)

        service.execute = bounded_fake
        async with TestClient(TestServer(app)) as client:
            for origin in (None, "null", "https://chipjev.com.evil.example"):
                headers = {"Origin": origin} if origin else {}
                response = await client.post("/api/runs", json={}, headers=headers)
                assert response.status == 403
            headers = {"Origin": ORIGIN}
            for body in ({"command": "id"}, {"path": "/etc/passwd"}, [], None, {"seed": 2}):
                response = await client.post("/api/runs", data=json.dumps(body),
                                             headers={**headers, "Content-Type": "application/json"})
                assert response.status == 400
            response = await client.post("/api/runs", data="x" * 65,
                                         headers={**headers, "Content-Type": "application/json"})
            assert response.status == 413
            assert (await client.post("/api/runs", data="{}", headers=headers)).status == 415
            assert (await client.post("/api/runs?command=id", json={}, headers=headers)).status == 400
            responses = await asyncio.gather(*[
                client.post("/api/runs", json={}, headers=headers) for _ in range(4)])
            payloads = [await response.json() for response in responses]
            assert {response.status for response in responses} == {200, 202}
            assert len({p["id"] for p in payloads}) == 1
            assert len(executed) == 1
            ident = payloads[0]["id"]
            response = await client.get(f"/api/runs/{ident}", headers=headers)
            assert response.headers["Access-Control-Allow-Origin"] == ORIGIN
            assert response.headers["Cache-Control"] == "no-store"
            assert response.headers["X-Content-Type-Options"] == "nosniff"
            assert "Access-Control-Allow-Credentials" not in response.headers
            for path in ("/README.md", "/.env", f"/api/runs/{ident}/artifacts/worker.log",
                         f"/api/runs/{ident}/artifacts/circuit.spice"):
                assert (await client.get(path)).status == 404
            service.viewers = MAX_VIEWERS
            assert (await client.get(f"/api/runs/{ident}/live", headers=headers)).status == 503
            service.viewers = 0
            service.runs[ident].created -= RUN_TTL + 1
            assert (await client.get(f"/api/runs/{ident}")).status == 404
            service.active = None
            service.next_start = time.monotonic() + 15
            assert (await client.post("/api/runs", json={}, headers=headers)).status == 429
    asyncio.run(scenario())


def test_cors_preflight_and_websocket_is_view_only(tmp_path):
    async def scenario():
        app = create_app(tmp_path)
        service = app[SERVICE]
        service.readiness = lambda: []

        async def waiting(run):
            await asyncio.sleep(60)
        service.execute = waiting
        async with TestClient(TestServer(app)) as client:
            headers = {"Origin": ORIGIN, "Access-Control-Request-Method": "POST",
                       "Access-Control-Request-Headers": "content-type"}
            response = await client.options("/api/runs", headers=headers)
            assert response.status == 204
            headers["Access-Control-Request-Headers"] = "x-command"
            assert (await client.options("/api/runs", headers=headers)).status == 403
            response = await client.post("/api/runs", json={}, headers={"Origin": ORIGIN})
            ident = (await response.json())["id"]
            async with client.ws_connect(f"/api/runs/{ident}/live", origin=ORIGIN) as ws:
                await ws.send_str("execute something")
                await ws.receive(timeout=3)
                assert ws.close_code == 1008
    asyncio.run(scenario())


def test_restart_cleans_only_owned_run_dirs_and_refuses_duplicate_server(tmp_path):
    old = tmp_path / ("a" * 32)
    old.mkdir()
    (old / "frame.jpg").write_bytes(b"old")
    unrelated = tmp_path / "keep.txt"
    unrelated.write_text("keep")
    service = Service(tmp_path, {ORIGIN})
    try:
        assert not old.exists()
        assert unrelated.read_text() == "keep"
        with pytest.raises(RuntimeError, match="Another demo server"):
            Service(tmp_path, {ORIGIN})
    finally:
        service.lock.close()


@pytest.mark.integration
def test_wired_schematic_requires_physical_signal_connections(tmp_path):
    import shutil

    if not shutil.which("xschem") or not (xschem.library() / "sky130_fd_pr/nfet_01v8.sym").exists():
        pytest.skip("xschem and SKY130 symbols are required")
    builder = build(lookup(FIXTURE["cls"], FIXTURE["topology"]), FIXTURE["values"], FIXTURE["vdd"])
    steps = schematic_steps(builder, FIXTURE)
    schematic = steps[-1].schematic
    path = tmp_path / "wired.sch"
    path.write_text(schematic)
    netlist = xschem.netlist(path, tmp_path / "connected")
    assert xschem.check(builder, netlist, FIXTURE["vdd"]) == (True, [])
    # If wiring were cosmetic and repeated pin labels still connected the circuit,
    # removing every wire would leave the same netlist. This must fail instead.
    path.write_text("\n".join(line for line in schematic.splitlines() if not line.startswith("N ")) + "\n")
    disconnected = xschem.netlist(path, tmp_path / "disconnected")
    ok, problems = xschem.check(builder, disconnected, FIXTURE["vdd"])
    assert not ok
    assert sum("connectivity" in problem for problem in problems) >= FIXTURE["mosfets"]


@pytest.mark.integration
def test_real_xschem_ngspice_and_reconnectable_video(tmp_path):
    async def scenario():
        app = create_app(tmp_path)
        if missing := app[SERVICE].readiness():
            app[SERVICE].lock.close()
            pytest.skip("Demo dependencies missing: " + ", ".join(missing))
        from PIL import Image

        async with TestClient(TestServer(app)) as client:
            response = await client.post("/api/runs", json={}, headers={"Origin": ORIGIN})
            assert response.status == 202
            ident = (await response.json())["id"]
            frames, events = [], []
            async with asyncio.timeout(90):
                async with client.ws_connect(f"/api/runs/{ident}/live", origin=ORIGIN) as ws:
                    async for message in ws:
                        if message.type == WSMsgType.BINARY:
                            frames.append(hashlib.sha256(message.data).hexdigest())
                            assert Image.open(io.BytesIO(message.data)).size == (1440, 900)
                        elif message.type == WSMsgType.TEXT:
                            events.append(json.loads(message.data))
            assert len(set(frames)) >= 6, "Expected changing, live xschem frames"
            assert not any(e["type"] == "error" for e in events), events
            result = next(e for e in events if e["type"] == "result")
            assert result["valid"] and result["netlist_match"]
            assert result["metrics"]["gain_db"] == pytest.approx(FIXTURE["reference_metrics"]["gain_db"], abs=0.1)
            assert result["wall_seconds"] > 0 and result["demo_seconds"] > result["wall_seconds"]
            waves = next(e for e in events if e["type"] == "waveforms")
            assert len(waves["frequency_hz"]) > 100 and len(waves["steps"]) == 2
            assert events[-1] == {"type": "finished", "status": "complete"}
            response = await client.get(f"/api/runs/{ident}/artifacts/result.json")
            assert response.status == 200
            assert (await response.json())["valid"]
            response = await client.get(f"/api/runs/{ident}/artifacts/circuit.spice")
            text = await response.text()
            assert str(ROOT) not in text and str(tmp_path) not in text
            # A later viewer receives the complete result and final real frame.
            replay = []
            async with client.ws_connect(f"/api/runs/{ident}/live", origin=ORIGIN) as ws:
                async for message in ws:
                    if message.type == WSMsgType.TEXT:
                        replay.append(json.loads(message.data))
            assert next(e for e in replay if e["type"] == "result")["id"] == result["id"]
    asyncio.run(scenario())
