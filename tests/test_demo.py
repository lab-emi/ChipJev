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
from demo.examples import EXAMPLES
from demo.schematic import routed_schematic, schematic_steps
from demo.server import FIXTURE, MAX_VIEWERS, RUN_TTL, SERVICE, Service, create_app
from demo.worker import HEIGHT, PANE_WIDTH, WIDTH, Screen

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
            for body in ({"command": "id"}, {"path": "/etc/passwd"}, [], None, {"seed": 2}, {"example": "../../tmp"},
                         {"example": []}, {"example": "opamp-gain", "prompt": "id"}):
                response = await client.post("/api/runs", data=json.dumps(body),
                                             headers={**headers, "Content-Type": "application/json"})
                assert response.status == 400
            response = await client.post("/api/runs", data="x" * 65,
                                         headers={**headers, "Content-Type": "application/json"})
            assert response.status == 413
            assert (await client.post("/api/runs", data="{}", headers=headers)).status == 415
            assert (await client.post("/api/runs?command=id", json={}, headers=headers)).status == 400
            responses = await asyncio.gather(*[
                client.post("/api/runs", json={"example": "opamp-speed"}, headers=headers) for _ in range(4)])
            payloads = [await response.json() for response in responses]
            assert {response.status for response in responses} == {200, 202}
            assert len({p["id"] for p in payloads}) == 1
            assert len(executed) == 1
            assert all(p["example"] == EXAMPLES["opamp-speed"] for p in payloads)
            assert service.runs[payloads[0]["id"]].example == "opamp-speed"
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
def test_native_dual_view_reloads_cells_and_restores_selected_geometry(tmp_path):
    import shutil

    import numpy as np
    from PIL import Image

    service = Service(tmp_path / "service", {ORIGIN})
    try:
        if missing := service.readiness():
            pytest.skip("Demo dependencies missing: " + ", ".join(missing))
    finally:
        service.lock.close()
    source = ROOT / "experiments/analog-layout/opamp-gain"
    shutil.copyfile(source / "circuit.sch", tmp_path / "step-0.sch")
    screen = Screen(tmp_path)
    frames = []
    try:
        screen.start()
        screen.show(0)
        for name in ("initial-layout.mag", "layout.mag", "initial-layout.mag"):
            screen.show_layout(source / name)
            frame = Image.open(tmp_path / "frame.jpg")
            assert frame.size == (WIDTH, HEIGHT)
            # Exclude native menus/cell titles: compare actual layout geometry.
            frames.append(np.array(frame.crop((PANE_WIDTH + 30, 60, WIDTH - 205, HEIGHT - 30)),
                                   dtype=float))
            assert (tmp_path / f"view-{screen.layout_sequence}.mag").read_bytes() == (source / name).read_bytes()
        assert frames[0].std() > 20, "Magic must draw real, nonblank geometry"
        change = np.abs(frames[1] - frames[0]).mean()
        assert change > 2, "A new layout.mag must not reuse Magic's previous cell cache"
        assert np.abs(frames[2] - frames[0]).mean() < change / 4, "Restore the selected geometry"
    finally:
        screen.close()
    assert all(p.poll() is not None for p in screen.processes)


@pytest.mark.integration
def test_real_xschem_ngspice_and_reconnectable_video(tmp_path):
    async def scenario():
        app = create_app(tmp_path, device="cpu")
        if missing := app[SERVICE].readiness():
            app[SERVICE].lock.close()
            pytest.skip("Demo dependencies missing: " + ", ".join(missing))
        from PIL import Image

        async with TestClient(TestServer(app)) as client:
            response = await client.post("/api/runs", json={"example": "ota-efficient"}, headers={"Origin": ORIGIN})
            assert response.status == 202
            ident = (await response.json())["id"]
            frames, events = [], []
            async with asyncio.timeout(300):
                async with client.ws_connect(f"/api/runs/{ident}/live", origin=ORIGIN) as ws:
                    async for message in ws:
                        if message.type == WSMsgType.BINARY:
                            frames.append(hashlib.sha256(message.data).hexdigest())
                            assert Image.open(io.BytesIO(message.data)).size == (WIDTH, HEIGHT)
                        elif message.type == WSMsgType.TEXT:
                            events.append(json.loads(message.data))
            assert len(set(frames)) >= 6, "Expected changing, live xschem + Magic frames"
            assert not any(e["type"] == "error" for e in events), events
            result = next(e for e in events if e["type"] == "result")
            assert result["valid"] and result["netlist_match"]
            assert result["mode"] == "live-design" and result["example"]["id"] == "ota-efficient"
            assert result["model"]["device"] == "cpu"
            assert result["laya_inference_seconds"] > 0
            assert result["search"]["typed_prior"] and result["search"]["evaluations"] >= 8
            assert result["timings_seconds"]["search"] > 0
            iterations = [e["layout_iteration"] for e in events if e.get("layout_iteration")]
            evaluated = [e for e in iterations if e["status"] == "evaluated" and "phase" not in e]
            history = result["physical"]["optimization"]["history"]
            assert len(evaluated) == len(history)
            assert [e["plan_id"] for e in evaluated] == [h["plan_id"] for h in history]
            selected = [e for e in iterations if e["status"] == "selected"][-1]
            assert selected["plan_id"] == result["physical"]["layout"]["plan_id"]
            assert selected["valid"]
            # DRC and LVS are separate live steps; each reports running, then its verdict.
            stages = [e["stage"] for e in events if e["type"] == "stage"]
            assert (stages.index("layout") < stages.index("drc") < stages.index("lvs")
                    < stages.index("extracting") < stages.index("postsimulating"))
            verdicts = [e["verification"] for e in events if e.get("verification")]
            for gate in ("drc", "lvs"):
                states = [v[gate]["status"] for v in verdicts if v.get(gate)]
                assert states.index("running") < states.index("passed"), states
            final = next(e for e in events if e.get("stage") == "complete")["verification"]
            layout_number = selected["index"] + 1
            assert final["drc"] == {"status": "passed", "errors": 0, "layout": layout_number,
                                    "selected": True}
            assert final["lvs"]["status"] == "passed" and final["lvs"]["layout"] == layout_number
            assert final["lvs"]["devices"] == result["physical"]["lvs"]["devices"] > 0
            snapshots = sorted((tmp_path / ident).glob("view-*.mag"),
                               key=lambda p: int(p.stem.split("-")[-1]))
            assert len(snapshots) >= 2
            assert snapshots[-1].read_bytes() == (tmp_path / ident / "layout.mag").read_bytes()
            decisions = await (await client.get(f"/api/runs/{ident}/artifacts/decisions.json")).json()
            trace = await (await client.get(f"/api/runs/{ident}/artifacts/search.json")).json()
            assert decisions["search_prior"] == trace["prior"]
            assert len(set(round(p, 4) for p in trace["prior"])) > 1
            assert any(r["source"] == "typed" for r in trace["records"])
            assert trace["evaluations"] == len(trace["records"])
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


def test_site_prompts_match_the_server_allowlist():
    assert json.loads((ROOT / "website/examples.json").read_text()) == list(EXAMPLES.values())


def test_the_worker_publishes_the_chiplaya_release_and_no_paths():
    from demo.worker import published_model

    pin = json.loads((ROOT / "CHIPLAYA.json").read_text())
    metadata = {"model": "aac6fef/laya-multilingual-mlx", "revision": "f2b4faf", "precision":
                "float16", "runtime": "pytorch", "device": "cuda", "path": str(ROOT / "x"),
                "fine_tuned": {"path": str(ROOT / "w.pt"), "sha256": pin["weights"]["sha256"]}}
    published = published_model(metadata)
    assert published["release"] == f"ChipLaya {pin['tag']}"
    assert str(ROOT) not in json.dumps(published)
    unknown = published_model(dict(metadata, fine_tuned={"path": "w", "sha256": "0" * 64}))
    assert unknown["release"] is None


def test_the_site_credits_the_pinned_chiplaya_release():
    pin = json.loads((ROOT / "CHIPLAYA.json").read_text())
    page = (ROOT / "website/index.html").read_text()
    assert f"ChipLaya {pin['tag']}" in page
    assert f"https://github.com/lab-emi/ChipLaya/releases/tag/{pin['tag']}" in page
    assert "https://github.com/lab-emi/ChipJev/blob/main/NOTICE" in page


def test_every_public_prompt_constrains_a_nonempty_grammar():
    from chipjev.circuits.grammar import library
    from demo.examples import allows

    for example in EXAMPLES.values():
        # Only one- and two-stage op-amps have wired xschem views in the live demo.
        assert example["cls"] in ("opamp1", "opampN") and example["stages"] in (1, 2)
        allowed = [t for t in library(example["cls"]) if len(t.stages) == example["stages"]
                   and allows(example, t)]
        assert allowed, example["id"]
        if example.get("first"):
            assert all(t.stages[0].rpartition("_")[0] in example["first"] for t in allowed)
        if example.get("polarity"):
            assert all(t.stages[0].endswith("_" + example["polarity"]) for t in allowed)
        assert {"name", "title", "prompt", "seed", "headroom"} <= set(example)


def test_exhausted_search_respects_failed_strict_remeasurement():
    from demo.design import least_violating

    margins = {"gain_db": 40, "pm_deg": 5, "current_decades": 0.1,
               "region_v": 0.1, "cmrr_db": 20}
    apparent_pass = {"design": [0, [1, 2]], "objective": 110,
                     "margins": margins, "checks": {"closed_loop": True}}
    rejected = {**apparent_pass, "margins": {**margins, "gain_db": -50},
                "checks": {"closed_loop": False}}
    near_pass = {**apparent_pass, "design": [0, [1, 3]],
                 "margins": {**margins, "current_decades": -0.01}}
    result = {"records": [apparent_pass, near_pass], "strict": [rejected]}
    assert least_violating(result) is near_pass


@pytest.mark.integration
def test_every_public_topology_has_real_equivalent_wiring(tmp_path):
    import shutil

    from chipjev.circuits.space import ClassSpace

    if not shutil.which("xschem") or not (xschem.library() / "sky130_fd_pr/nfet_01v8.sym").exists():
        pytest.skip("xschem and SKY130 symbols are required")
    for cls, stages in (("opampN", 2), ("opamp1", 1)):
        space = ClassSpace(cls)
        for index, top in enumerate(space.topologies):
            if len(top.stages) != stages:
                continue
            builder = build(top, space.values(space.canonical(top.id)), 1.8)
            path = tmp_path / f"{cls}-{index}.sch"
            path.write_text(routed_schematic(builder, top.id, 1.8))
            netlist = xschem.netlist(path, tmp_path / f"netlist-{cls}-{index}")
            assert xschem.check(builder, netlist, 1.8) == (True, []), top.id
