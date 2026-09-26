"""One bounded live run: real xschem and Magic on a private X server, plus ngspice.

Only the server starts this process. No browser-supplied paths, Tcl, SPICE, or
parameters reach it. stdout is a JSON-lines event channel; tool logs stay local.
"""

import argparse
import hashlib
import json
import os
import secrets
import select
import shutil
import subprocess
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from chipjev import xschem
from chipjev.circuits.published import lookup
from chipjev.circuits.sky130_devices import build_on_grid as build
from chipjev.paths import ROOT, magic
from chipjev.provenance import code_hashes
from chipjev.search.pro_layout import optimize_pro as physical_design
from chipjev.simulation.pdk import model_root
from chipjev.simulation.sky130 import evaluate
from demo import design
from demo.examples import DEFAULT_EXAMPLE, EXAMPLES
from demo.schematic import routed_schematic, text
from demo.timing import RunTiming

PANE_WIDTH, HEIGHT = 960, 900
WIDTH = PANE_WIDTH * 2


def emit(kind, **data):
    print(json.dumps({"type": kind, **data}, allow_nan=False), flush=True)


def atomic_write(path, data):
    temporary = path.with_suffix(path.suffix + ".tmp")
    if isinstance(data, bytes):
        temporary.write_bytes(data)
    else:
        temporary.write_text(data)
    temporary.replace(path)


class Screen:
    def __init__(self, directory):
        self.directory = directory
        self.processes = []
        self.logs = []
        self.capture_error = None
        self.first_frame = threading.Event()
        self.frame_count = 0
        self.layout_sequence = 0
        self.closed = False

    def launch(self, command, **kwargs):
        log = (self.directory / f"{Path(command[0]).name}.log").open("ab")
        self.logs.append(log)
        process = subprocess.Popen(command, stderr=log, stdout=kwargs.pop("stdout", log),
                                   cwd=self.directory, **kwargs)
        self.processes.append(process)
        return process

    def start(self):
        auth = self.directory / ".Xauthority"
        auth.touch(mode=0o600)
        cookie = secrets.token_hex(16)
        subprocess.run(["xauth", "-f", str(auth), "add", ":0", ".", cookie],
                       check=True, capture_output=True, timeout=5)
        read_fd, write_fd = os.pipe()
        try:
            self.launch(["Xvfb", "-displayfd", str(write_fd), "-screen", "0",
                         f"{WIDTH}x{HEIGHT}x24", "-nolisten", "tcp", "+extension", "GLX",
                         "-auth", str(auth)],
                        pass_fds=(write_fd,))
            os.close(write_fd)
            write_fd = None
            if not select.select([read_fd], [], [], 8)[0]:
                raise RuntimeError("The private display did not start")
            number = os.read(read_fd, 64).decode().strip()
            if not number.isdecimal():
                raise RuntimeError("The private display returned no display number")
        finally:
            os.close(read_fd)
            if write_fd is not None:
                os.close(write_fd)
        display = f":{number}"
        subprocess.run(["xauth", "-f", str(auth), "add", display, ".", cookie],
                       check=True, capture_output=True, timeout=5)
        env = {**os.environ, "DISPLAY": display, "XAUTHORITY": str(auth)}
        rc = self.directory / "xschemrc"
        config = self.directory / "xschem-config"
        config.mkdir()
        rc.write_text(f"set USER_CONF_DIR {{{config}}}\n"
                      f"set canvas_width {PANE_WIDTH}\nset canvas_height {HEIGHT - 100}\n"
                      "set XSCHEM_LIBRARY_PATH {}\n"
                      "append XSCHEM_LIBRARY_PATH ${XSCHEM_SHAREDIR}/xschem_library\n"
                      f"append XSCHEM_LIBRARY_PATH :{xschem.library()}\n"
                      "set netlist_type spice\nset lvs_netlist 0\n"
                      "set dark_colorscheme 1\nset dark_gui_colorscheme 1\n"
                      "set draw_grid 0\nset autoload_new_window 0\nset zoom_full_center 1\n"
                      "set change_lw 0\nset line_width 1.8\n"
                      "set enable_layer(5) 0\n")
        driver = self.directory / "display.tcl"
        driver.write_text(f"wm geometry . {PANE_WIDTH}x{HEIGHT}+0+0\n" + '''
wm title . {ChipJev | LIVE xschem | SKY130}
set chipjev_stage -1
proc chipjev_tick {} {
    global chipjev_stage
    if {[file exists stage.txt]} {
        set fd [open stage.txt r]
        set next [string trim [read $fd 16]]
        close $fd
        if {[regexp {^[0-9]{1,3}$} $next] && $next != $chipjev_stage} {
            set chipjev_stage $next
            xschem load [file normalize step-$next.sch]
            update
            xschem zoom_full center
            xschem redraw
            set fd [open shown.txt w]
            puts $fd $next
            close $fd
        }
    }
    after 40 chipjev_tick
}
after 100 chipjev_tick
''')
        self.launch(["xschem", "-r", "--rcfile", str(rc), "--script", str(driver),
                     str(self.directory / "step-0.sch")], env=env, stdin=subprocess.DEVNULL)
        # Both native editors share one capture. Unique cell names prevent Magic
        # from showing a cached layout when successive candidates use layout.mag.
        magic_driver = self.directory / "magic-display.tcl"
        magic_driver.write_text(
            f"set chipjev_geometry {PANE_WIDTH}x{HEIGHT}+{PANE_WIDTH}+0\n"
            + (ROOT / "demo/magic-display.tcl").read_text())
        self.launch([magic(), "-d", "OGL", "-noconsole", "-rcfile", "/dev/null",
                     "-T", str(model_root() / "libs.tech/magic/sky130A.tech"),
                     str(magic_driver)],
                    env={**env, "LIBGL_ALWAYS_SOFTWARE": "1", "LP_NUM_THREADS": "2",
                         "MESA_SHADER_CACHE_DIR": str(self.directory / "mesa-cache")},
                    stdin=subprocess.DEVNULL)
        ffmpeg = self.launch(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
                              "-f", "x11grab", "-draw_mouse", "0", "-framerate", "8", "-video_size",
                              f"{WIDTH}x{HEIGHT}", "-i", display, "-an", "-threads", "1",
                              "-c:v", "mjpeg", "-q:v", "5", "-f", "image2pipe", "pipe:1"],
                             env=env, stdout=subprocess.PIPE)

        def capture():
            data = b""
            try:
                while chunk := ffmpeg.stdout.read(32768):
                    data += chunk
                    if len(data) > 8_000_000:
                        raise RuntimeError("Display frame exceeds the size limit")
                    while (end := data.find(b"\xff\xd9")) != -1:
                        frame, data = data[:end + 2], data[end + 2:]
                        start = frame.find(b"\xff\xd8")
                        if start >= 0:
                            atomic_write(self.directory / "frame.jpg", frame[start:])
                            self.frame_count += 1
                            self.first_frame.set()
            except Exception as exc:
                self.capture_error = exc

        self.thread = threading.Thread(target=capture, daemon=True)
        self.thread.start()
        if not self.first_frame.wait(10):
            raise RuntimeError("No live display frame arrived")
        self.check()
        self.await_ack("magic-shown.txt", "0", "Magic")

    def check(self):
        if self.capture_error or any(p.poll() is not None for p in self.processes):
            raise RuntimeError("The live display stopped unexpectedly")

    def show(self, index):
        self.check()
        atomic_write(self.directory / "stage.txt", str(index))
        self.await_ack("shown.txt", str(index), "xschem")

    def await_ack(self, filename, expected, tool):
        deadline = time.monotonic() + 3
        shown = self.directory / filename
        while time.monotonic() < deadline:
            self.check()
            if shown.exists() and shown.read_text().strip() == expected:
                return
            time.sleep(0.025)
        raise RuntimeError(f"{tool} did not acknowledge the display update")

    def show_layout(self, path):
        self.check()
        self.layout_sequence += 1
        index = self.layout_sequence
        # The compiler emits a flat cell. Display a private, immutable copy so
        # the viewer cannot change extraction evidence or reuse an older cell.
        atomic_write(self.directory / f"view-{index}.mag", Path(path).read_bytes())
        atomic_write(self.directory / "magic-stage.txt", str(index))
        self.await_ack("magic-shown.txt", str(index), "Magic")
        # Capture the acknowledged repaint before the next candidate, including
        # the final incumbent before this worker closes the two editor windows.
        target = self.frame_count + 2
        deadline = time.monotonic() + 3
        while self.frame_count < target:
            self.check()
            if time.monotonic() >= deadline:
                raise RuntimeError("The updated Magic frame was not captured")
            time.sleep(0.025)

    def close(self):
        self.closed = True
        for process in reversed(self.processes):
            if process.poll() is None:
                process.terminate()
        for process in reversed(self.processes):
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        if hasattr(self, "thread"):
            self.thread.join(timeout=2)
        for log in self.logs:
            log.close()


def streamed(result):
    """The result as streamed to browsers: every measurement the page shows, without the
    duplicate attempt list, per-candidate critic findings and Laya's proposal texts (all
    kept in result.json, physical.json and optimization.json)."""
    physical = dict(result["physical"])
    trace = dict(physical["optimization"])
    keep = ("index", "action", "plan_id", "valid", "accepted", "drc", "lvs", "area_um2", "metrics",
            "checks", "error", "critic", "objective")
    trace["history"] = [{k: h[k] for k in keep if k in h} for h in trace["history"]]
    trace.pop("decisions", None)
    physical["optimization"] = trace
    physical["recovery"] = {**physical["recovery"], "attempts": len(physical["recovery"]["attempts"])}
    return {**result, "physical": physical}


def waveforms(directory, result):
    ac = np.atleast_2d(np.loadtxt(directory / "ac.tsv", skiprows=1))
    if ac.shape[1] != 3 or not np.isfinite(ac).all():
        raise RuntimeError("Unexpected AC output")
    return {
        "frequency_hz": ac[:, 0].tolist(),
        "gain_db": (20 * np.log10(np.maximum(ac[:, 1], 1e-30))).tolist(),
        "phase_deg": ac[:, 2].tolist(),
        "steps": result.get("qualification", {}).get("steps", []),
    }


def plot(directory, waves):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                         "axes.spines.top": False, "axes.spines.right": False})
    fig, (ac, step) = plt.subplots(1, 2, figsize=(14.4, 3), dpi=100, layout="constrained")
    ac.semilogx(waves["frequency_hz"], waves["gain_db"], color="#087cbd", lw=2)
    ac.axhline(0, color="#bcc8d4", lw=0.8)
    ac.set(title="Fresh ngspice run · Open-loop AC response", xlabel="Frequency (Hz)",
           ylabel="Gain (dB)", xlim=(1, 1e11))
    for data, color in zip(waves["steps"], ("#087cbd", "#e28526"), strict=False):
        if "waveform" in data:
            wave = data["waveform"]
            step.plot(wave["t_us"], wave["delta_mv"], lw=2, color=color,
                      label=f"{data['direction'] * 10:+d} mV input")
    step.set(title="Fresh ngspice run · Unity-buffer step response", xlabel="Time (µs)",
             ylabel="Output change (mV)")
    step.legend(loc="lower right", frameon=False, fontsize=9)
    for axis in (ac, step):
        axis.grid(alpha=0.16)
    path = directory / "plots.tmp.png"
    fig.savefig(path, facecolor="#ffffff")
    plt.close(fig)
    path.replace(directory / "plots.png")


def published_model(metadata):
    """The model description that leaves the worker: fixed fields only, never a local path.
    ``release`` is the ChipLaya release the fine-tuned weights belong to."""
    import chiplaya
    from chipjev.decisions.typed import release_label

    digest = metadata["fine_tuned"]["sha256"]
    return {**{k: metadata[k] for k in ("model", "revision", "precision", "runtime", "device")},
            "fine_tuned": {"sha256": digest}, "chiplaya": chiplaya.__version__,
            "release": release_label(digest)}


def run(directory, example_id=DEFAULT_EXAMPLE, device=None):
    timing = RunTiming()
    example = EXAMPLES[example_id]
    source_hashes = code_hashes()
    source_hashes.update({str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in sorted((ROOT / "demo").iterdir())
                          if p.suffix in {".py", ".tcl"}})

    # DRC and LVS verdicts shown as pipeline steps. A pass belongs to a real
    # candidate layout; the final values are those of the selected layout.
    checks = {"drc": None, "lvs": None}

    def stage(name, at=None, **data):
        phase = {"starting": "startup", "deciding": "laya", "searching": "search",
                 "netlisting": "netlist", "simulating": "simulation", "checking": "results",
                 "layout": "layout", "drc": "layout", "lvs": "pex", "extracting": "pex",
                 "postsimulating": "postlayout"}.get(name)
        timing.move(phase, at)
        if any(checks.values()):
            data.setdefault("verification", dict(checks))
        emit("stage", stage=name, **data, **timing.snapshot())

    empty = ["v {xschem version=3.4.5 file_version=1.2}", "G {}", "K {}", "V {}", "S {}", "E {}",
             text("CHIPJEV / A FRESH DESIGN", 60, 60, 0.7),
             text("ChipLaya is reading the selected prompt.", 60, 140, 0.4),
             text("Live search candidates will appear here.", 60, 200, 0.4),
             "L 2 0 0 1600 0 {}", "L 2 0 900 1600 900 {}"]
    (directory / "step-0.sch").write_text("\n".join(empty) + "\n")
    screen = Screen(directory)
    renderer = ThreadPoolExecutor(max_workers=1)
    frame_update = None
    stage("starting", message="Starting a fresh design and private xschem + Magic displays",
          progress=2, example=example)
    try:
        screen.start()
        screen.show(0)
        stage("deciding", message="Loading ChipLaya and inferring typed design decisions",
              progress=5)
        model = design.load_model(device)
        answer = design.decide(model, example)
        metadata = published_model(model.metadata)
        answer.update(model=metadata, example=example, model_load_seconds=model.load_seconds)
        (directory / "decisions.json").write_text(json.dumps(answer, indent=2, allow_nan=False))
        ordered = sorted(zip(answer["search_topologies"], answer["search_prior"], strict=True),
                         key=lambda item: -item[1])
        stage("deciding", message="ChipLaya decisions now guide the topology and sizing search",
              progress=10, laya={"device": metadata["device"], "precision": metadata["precision"],
                  "release": metadata["release"],
                  "inference_seconds": answer["seconds"], "answers": answer["answers"],
                  "topologies": len(ordered), "leading_topologies": ordered[:3]})

        def observe(event):
            nonlocal frame_update
            info = {k: event[k] for k in ("round", "evaluations", "verifications") if k in event}
            if event["kind"] == "candidate":
                topology = lookup(example["cls"], event["topology"])
                builder = build(topology, event["values"], example["vdd"])
                index = event["round"] + 1
                atomic_write(directory / f"step-{index}.sch",
                             routed_schematic(builder, topology.id, example["vdd"]))
                # A slow video frame must not stall CUDA acquisition. Sample the
                # latest real candidates; at most one display update is in flight.
                if frame_update is None or frame_update.done():
                    if frame_update is not None:
                        frame_update.result()
                    frame_update = renderer.submit(screen.show, index)
                info.update(topology=topology.id, mosfets=len(builder.mos), source=event["source"])
                message = f"Round {index}: evaluating 8 candidates · {topology.id}"
            else:
                best = event["best"]
                info["best_gain_db"] = None if best is None else best["metrics"].get("gain_db")
                message = f"{event['evaluations']} circuits measured · " + (
                    "strictly verified design found" if best else "searching for a qualified design")
            stage("searching", message=message, search=info,
              progress=12 + round(48 * (event["round"] + 1) / design.ROUNDS))

        stage("searching", message="Starting ChipJev joint topology and sizing search", progress=12)
        selected, search_result = design.search(answer, example, model.laya.device, observe,
                                                physical_directory=directory / "physical-search")
        if frame_update is not None:
            frame_update.result()
        (directory / "search.json").write_text(json.dumps(search_result, indent=2, allow_nan=False))
        topology = lookup(example["cls"], selected["topology"])
        builder = build(topology, selected["values"], example["vdd"])
        schematic = routed_schematic(builder, topology.id, example["vdd"])
        final = directory / "circuit.sch"
        final.write_text(schematic)
        atomic_write(directory / "step-900.sch", schematic)
        screen.show(900)
        stage("netlisting", message="Verifying every xschem wire, device and size", progress=64,
              search={"topology": topology.id, "mosfets": len(builder.mos),
                      "evaluations": search_result["evaluations"]})
        netlist = xschem.netlist(final, directory / "netlist")
        ok, problems = xschem.check(builder, netlist, example["vdd"])
        if not ok:
            raise RuntimeError("xschem connectivity check failed: " + "; ".join(problems))
        (directory / "circuit.spice").write_text(netlist)
        stage("simulating", message="Schematic AC sweep + ±10 mV unity-buffer steps", progress=69)
        result = evaluate(topology, selected["values"], directory=directory, strict=True,
                          keep=True, vdd=example["vdd"], load_pf=example["load_pf"], quantize_geometry=True,
                          input_bias=selected.get("metrics",{}).get("vin_dc"))
        if result["error"]:
            raise RuntimeError(result["error"])
        live_layout = {}
        displayed_plan = None
        step_progress = {"layout": 72, "drc": 75, "lvs": 79, "extracting": 83, "postsimulating": 87}
        # One loop iteration = one batch of layout candidates (the seed plan, then ChipLaya's
        # proposals from the incumbent), verified in parallel. The steps follow the batch's
        # slowest candidate, so every iteration walks layout -> DRC -> LVS -> RC ->
        # post-layout simulation and then feeds back; DRC and LVS report per iteration.
        ranks = {"layout": 0, "drc": 1, "lvs": 3, "extracting": 5, "postsimulating": 6, "done": 7}
        wavefront = ("layout", "drc", "lvs", "lvs", "extracting", "extracting", "postsimulating",
                     "postsimulating")
        labels = {"layout": "placing matched SKY130 device rows, rails and routing",
                  "drc": "Magic DRC with the full SKY130 rule deck",
                  "lvs": "Netgen LVS against the schematic netlist",
                  "extracting": "Magic distributed RC extraction",
                  "postsimulating": "ngspice on the extracted RC netlists"}
        actions = {"aspect": "aspect ratio", "max_finger_um": "finger folding",
                   "pair_pattern": "matching pattern", "dummies": "edge dummies",
                   "single_dummies": "single-device dummies", "rail_um": "rail width",
                   "decap": "decoupling", "passives": "passive placement",
                   "shield_inputs": "grounded separator", "refinger": "re-fingering"}
        loop = {"iteration": 0, "members": [], "rank": {}, "generated": set(), "finished": set(),
                "drc": {}, "lvs": {}, "errors": {}, "counts": {}, "layouts": 0, "accepted": None,
                "incumbent": None, "evaluated": 0, "step": "layout", "stop": None}

        def span():
            return [loop["members"][0] + 1, loop["members"][-1] + 1] if loop["members"] else [0, 0]

        def gate(name):
            results = loop[name]
            size = sum(1 for i in loop["members"] if i in loop["generated"] or i not in loop["finished"])
            checked, passed = len(results), sum(results.values())
            if checked < size:
                status = "running" if checked or ranks[loop["step"]] >= ranks[name] else "pending"
            else:
                status = "passed" if size and passed == checked else "failed"
            state = {"status": status, "checked": checked, "passed": passed, "of": size,
                     "unrouted": len(loop["members"]) - size, "layouts": span(),
                     "iteration": loop["iteration"]}
            if name == "drc":
                state["errors"] = sum(loop["errors"].values())
            elif size == 1 and loop["counts"]:
                state["devices"], state["nets"] = next(iter(loop["counts"].values()))
            return state

        def publish(message, at=None, moved=False, **extra):
            data = {"message": message, "verification": {"drc": gate("drc"), "lvs": gate("lvs")},
                    "loop": {"iteration": loop["iteration"], "layouts": span(),
                             "size": len(loop["members"]), "total": loop["layouts"],
                             "finished": len(loop["finished"]), "evaluated": loop["evaluated"],
                             "accepted": loop["accepted"], "incumbent": loop["incumbent"],
                             "stop": loop["stop"]}, **extra}
            data.setdefault("progress", step_progress[loop["step"]])
            if moved:
                stage(loop["step"], at=at, **data)
            else:
                emit("stage", stage=loop["step"], **data, **timing.snapshot())

        def physical_stage(name, data):
            """One verification step of one candidate, streamed from the layout workers."""
            index, status = data["index"], data.get("status")
            if index not in loop["members"]:
                return
            rank = ranks[name] + (1 if name in ("drc", "lvs") and status != "running" else 0)
            loop["rank"][index] = max(loop["rank"][index], rank)
            number, message = index + 1, None
            if name == "drc":
                loop["generated"].add(index)
                if status != "running":
                    loop["drc"][index] = status == "passed"
                    loop["errors"][index] = data.get("errors") or 0
                    message = f"Layout {number}: " + ("DRC clean · 0 violations" if status == "passed"
                                                      else f"{data.get('errors')} DRC violations · rejected")
            elif name == "lvs" and status != "running":
                loop["lvs"][index] = status == "passed"
                loop["counts"][index] = (data.get("devices"), data.get("nets"))
                message = f"Layout {number}: " + (
                    f"LVS matched · {data.get('devices')} devices, {data.get('nets')} nets"
                    if status == "passed" else "LVS mismatch · rejected")
            elif name == "done":
                loop["finished"].add(index)
            shown = data["plan_id"] == displayed_plan and name != "done"
            if shown:
                live_layout["phase"] = name
            step = wavefront[min(loop["rank"][i] for i in loop["members"])]
            moved = step != loop["step"]
            if moved:
                loop["step"] = step
                first, last = span()
                message = (f"Iteration {loop['iteration']}: {labels[step]} · "
                           + (f"layouts {first}–{last}" if last > first else f"layout {first}"))
            if moved or message:
                publish(message, at=data.get("at"), moved=moved,
                        **({"layout_iteration": dict(live_layout)} if shown else {}))

        def physical_candidate(event):
            nonlocal live_layout, displayed_plan
            kind = event["kind"]
            if kind == "batch":
                indices = event["indices"]
                loop.update(iteration=event["iteration"], members=indices, rank=dict.fromkeys(indices, 0),
                            generated=set(), finished=set(), drc={}, lvs={}, errors={}, counts={},
                            accepted=None, incumbent=event["incumbent"], evaluated=0, step="layout")
                loop["layouts"] += len(indices)
                first, last = span()
                if event["incumbent"] is None:
                    message = f"Iteration 1: the initial layout plan · {labels['layout']}"
                else:
                    moves = ", ".join(actions.get(a, a) for a in event["actions"])
                    message = (f"Iteration {event['iteration']}: ChipLaya proposes layouts {first}–{last} "
                               f"({moves}) from incumbent layout {event['incumbent'] + 1}")
                publish(message, moved=True)
                return
            if kind == "stop":
                loop["stop"] = {k: event[k] for k in ("reason", "text", "iterations", "evaluations",
                                                      "max_evaluations", "patience", "budget_seconds")}
                publish(f"Layout loop stopped after {event['iterations']} iterations: {event['text']}")
                return
            if kind in {"rendered", "selected"}:
                screen.show_layout(event["directory"] / "layout.mag")
                displayed_plan = event["plan_id"]
            live_layout = {
                "index": event["index"], "action": event["action"],
                "plan_id": event["plan_id"], "status": kind,
                "accepted": bool(event.get("accepted")), "valid": event.get("valid"),
                "displayed": event["plan_id"] == displayed_plan,
                "area_um2": (event.get("quality") or {}).get("area_um2", event.get("area_um2")),
            }
            number = event["index"] + 1
            if kind == "selected":
                checks["drc"] = {"status": "passed" if event["drc"] == 0 else "failed",
                                 "errors": event["drc"], "layout": number, "selected": True}
                checks["lvs"] = {"status": "passed" if event["lvs"] else "failed", "layout": number,
                                 "devices": event.get("lvs_devices"), "nets": event.get("lvs_nets"),
                                 "selected": True}
                # No paths or Tcl are sent to the browser. The native viewer has
                # acknowledged the same geometry before its iteration is announced.
                emit("stage", stage=loop["step"], message=f"Layout {number}: selected layout restored in Magic",
                     progress=94, layout_iteration=live_layout, verification=dict(checks),
                     loop={"iteration": loop["iteration"], "total": loop["layouts"], "selected": number,
                           "done": True, "stop": loop["stop"]}, **timing.snapshot())
                return
            if kind == "evaluated":
                loop["finished"].add(event["index"])
                loop["evaluated"] += 1
                if event.get("accepted"):
                    loop["accepted"] = loop["incumbent"] = event["index"]
                outcome = ("accepted improvement" if event.get("accepted") else
                           "qualified; keeping incumbent" if event.get("valid") else
                           "rejected · verification error" if event.get("drc_errors") is None else
                           f"rejected · {event['drc_errors']} DRC violations" if event["drc_errors"] else
                           "rejected · LVS mismatch" if event.get("lvs") is False else
                           "rejected · post-layout checks")
            else:
                outcome = "DRC complete · opened in Magic"
            publish(f"Layout {number}: {outcome}", layout_iteration=live_layout,
                    **({"progress": 90} if kind == "evaluated" else {}))

        stage("layout", message="Starting the goal-driven layout loop: ChipLaya proposes, DRC, LVS "
              "and ngspice decide", progress=71)
        physical = physical_design(topology, selected["values"], directory / "physical",
                                   vdd=example["vdd"], load_pf=example["load_pf"],
                                   observer=physical_stage, prelayout=result, model=model,
                                   candidate_observer=physical_candidate,
                                   max_evaluations=13, budget_seconds=40, patience=2)
        screens = [json.loads(p.read_text()) for p in
                   sorted((directory / "physical-search").glob("*/physical.json"))]
        physical["search_screening"] = {
            "candidates": len(screens), "rejected": sum(not p["valid"] for p in screens),
            "seconds": sum(p["physical_seconds"] for p in screens),
        }
        physical["all_physical_seconds"] = (physical["total_seconds"] +
                                              physical["search_screening"]["seconds"])
        (directory / "physical/physical.json").write_text(json.dumps(physical, indent=2, allow_nan=False))
        if physical["recovery"]["changed"]:
            selected["values"] = physical["values"]
            builder = build(topology, selected["values"], example["vdd"])
            schematic = routed_schematic(builder, topology.id, example["vdd"])
            final.write_text(schematic)
            atomic_write(directory / "step-901.sch", schematic)
            screen.show(901)
            netlist = xschem.netlist(final, directory / "final-netlist")
            ok, problems = xschem.check(builder, netlist, example["vdd"])
            if not ok:
                raise RuntimeError("Refined schematic mismatch: " + "; ".join(problems))
            (directory / "circuit.spice").write_text(netlist)
            result = physical["prelayout"]
            # Regenerate matching schematic waves after an accepted sizing change.
            result = evaluate(topology, selected["values"], directory=directory,
                              strict=True, keep=True, vdd=example["vdd"], load_pf=example["load_pf"], quantize_geometry=True)
        stage("checking", message="Comparing schematic and extracted circuit performance", progress=96)
        waves = waveforms(directory, result)
        postwaves = waveforms(directory / "physical/postlayout", physical["postlayout"])
        emit("waveforms", **waves, postlayout=postwaves)
        plot(directory, waves)
        for name in ("layout.svg", "layout-intent.svg", "layout.mag", "layout.gds", "pex.spice", "physical.json", "optimization.json", "drc.txt", "lvs.log"):
            shutil.copy2(directory / "physical" / name, directory / name)
        with zipfile.ZipFile(directory / "physical-evidence.zip", "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted((directory / "physical").rglob("*")):
                if path.is_file() and path.suffix in {".mag", ".gds", ".spice", ".json", ".tcl", ".log", ".txt", ".tsv", ".cir"}:
                    archive.write(path, path.relative_to(directory / "physical"))
            for path in sorted((directory / "physical-search").rglob("*")):
                if path.is_file() and path.suffix in {".mag", ".gds", ".spice", ".json", ".tcl", ".log", ".txt", ".tsv", ".cir"}:
                    archive.write(path, Path("physical-search") / path.relative_to(directory / "physical-search"))
        screen.check()
        result.pop("pid", None)
        schematic_result = result
        result = dict(physical["postlayout"])
        result.update(valid=bool(physical["valid"] and schematic_result["valid"]),
                      prelayout=schematic_result, physical=physical)
        result.update(mode="live-design", topology=topology.id, values=selected["values"],
                      source_sha256=source_hashes,
                      example=example, model=metadata, netlist_match=ok, mosfets=len(builder.mos),
                      laya_inference_seconds=answer["seconds"], search={
                          k: search_result[k] for k in ("device", "acquisition_dtype", "wide_kernel",
                          "topologies", "typed_prior", "evaluations", "verifications",
                          "first_verified", "wall_seconds", "demo_stop_rule")})
        timing.move(None)
        result.update(timing.snapshot())
        (directory / "result.json").write_text(json.dumps(result, indent=2, allow_nan=False))
        emit("result", **streamed(result))
        stage("complete" if result["valid"] else "unqualified",
              message="All circuit checks passed" if result["valid"] else "Search budget exhausted; qualification failed",
              progress=100)
    finally:
        renderer.shutdown(wait=True, cancel_futures=True)
        screen.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--example", choices=EXAMPLES, default=DEFAULT_EXAMPLE)
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    args = parser.parse_args()
    args.directory.mkdir(parents=True, exist_ok=True)
    try:
        run(args.directory.resolve(), args.example, None if args.device == "auto" else args.device)
    except Exception:
        import traceback
        traceback.print_exc()
        emit("error", message="The live run failed. Please retry; diagnostic details are kept on the server.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
