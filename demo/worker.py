"""One bounded live run: real xschem on a private X server, then real ngspice.

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
from chipjev.paths import ROOT
from chipjev.provenance import code_hashes
from chipjev.search.layout import optimize as physical_design
from chipjev.simulation.sky130 import evaluate
from demo import design
from demo.examples import DEFAULT_EXAMPLE, EXAMPLES
from demo.schematic import routed_schematic, text
from demo.timing import RunTiming

WIDTH, HEIGHT = 1440, 900


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
                         f"{WIDTH}x{HEIGHT}x24", "-nolisten", "tcp", "-extension", "GLX",
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
                      "set XSCHEM_LIBRARY_PATH {}\n"
                      "append XSCHEM_LIBRARY_PATH ${XSCHEM_SHAREDIR}/xschem_library\n"
                      f"append XSCHEM_LIBRARY_PATH :{xschem.library()}\n"
                      "set netlist_type spice\nset lvs_netlist 0\n"
                      "set dark_colorscheme 1\nset dark_gui_colorscheme 1\n"
                      "set draw_grid 0\nset autoload_new_window 0\nset zoom_full_center 1\n"
                      "set change_lw 0\nset line_width 1.8\n"
                      "set enable_layer(5) 0\n")
        driver = self.directory / "display.tcl"
        driver.write_text('''
wm geometry . 1440x900+0+0
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
            xschem zoom_full
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
        ffmpeg = self.launch(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
                              "-f", "x11grab", "-framerate", "8", "-video_size",
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
                            self.first_frame.set()
            except Exception as exc:
                self.capture_error = exc

        self.thread = threading.Thread(target=capture, daemon=True)
        self.thread.start()
        if not self.first_frame.wait(10):
            raise RuntimeError("No live display frame arrived")
        self.check()

    def check(self):
        if self.capture_error or any(p.poll() is not None for p in self.processes):
            raise RuntimeError("The live display stopped unexpectedly")

    def show(self, index):
        self.check()
        atomic_write(self.directory / "stage.txt", str(index))
        deadline = time.monotonic() + 3
        shown = self.directory / "shown.txt"
        while time.monotonic() < deadline:
            if shown.exists() and shown.read_text().strip() == str(index):
                return
            time.sleep(0.025)
        raise RuntimeError("xschem did not acknowledge the schematic update")

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


def run(directory, example_id=DEFAULT_EXAMPLE, device=None):
    timing = RunTiming()
    example = EXAMPLES[example_id]
    source_hashes = code_hashes()
    source_hashes.update({str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in sorted((ROOT / "demo").glob("*.py"))})

    def stage(name, **data):
        phase = {"starting": "startup", "deciding": "laya", "searching": "search",
                 "netlisting": "netlist", "simulating": "simulation", "checking": "results",
                 "layout": "layout", "extracting": "pex", "postsimulating": "postlayout"}.get(name)
        timing.move(phase)
        emit("stage", stage=name, **data, **timing.snapshot())

    empty = ["v {xschem version=3.4.5 file_version=1.2}", "G {}", "K {}", "V {}", "S {}", "E {}",
             text("CHIPJEV / A FRESH DESIGN", 60, 60, 0.7),
             text("Laya is reading the selected prompt.", 60, 140, 0.4),
             text("Live search candidates will appear here.", 60, 200, 0.4),
             "L 2 0 0 1600 0 {}", "L 2 0 900 1600 900 {}"]
    (directory / "step-0.sch").write_text("\n".join(empty) + "\n")
    screen = Screen(directory)
    renderer = ThreadPoolExecutor(max_workers=1)
    frame_update = None
    stage("starting", message="Starting a fresh design and private xschem display",
          progress=2, example=example)
    try:
        screen.start()
        screen.show(0)
        stage("deciding", message="Loading Laya and inferring typed design decisions", progress=5)
        model = design.load_model(device)
        answer = design.decide(model, example)
        metadata = dict(model.metadata)
        metadata["fine_tuned"] = {"sha256": model.metadata["fine_tuned"]["sha256"]}
        answer.update(model=metadata, example=example, model_load_seconds=model.load_seconds)
        (directory / "decisions.json").write_text(json.dumps(answer, indent=2, allow_nan=False))
        ordered = sorted(zip(answer["search_topologies"], answer["search_prior"], strict=True),
                         key=lambda item: -item[1])
        stage("deciding", message="Laya decisions now guide the topology and sizing search",
              progress=10, laya={"device": metadata["device"], "precision": metadata["precision"],
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
        def physical_stage(name, data):
            messages = {"layout": (75, "Generating SKY130 devices, routing and checking Magic DRC"),
                        "extracting": (82, "Netgen LVS and Magic distributed RC extraction"),
                        "postsimulating": (90, "Simulating the extracted RC netlist in ngspice")}
            progress, message = messages[name]
            stage(name, message=message, progress=progress)

        physical = physical_design(topology, selected["values"], directory / "physical",
                                   vdd=example["vdd"], load_pf=example["load_pf"],
                                   observer=physical_stage, prelayout=result, model=model,
                                   max_evaluations=6, budget_seconds=40)
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
        emit("result", **result)
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
