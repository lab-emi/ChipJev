"""One bounded live run: real xschem on a private X server, then real ngspice.

Only the server starts this process. No browser-supplied paths, Tcl, SPICE, or
parameters reach it. stdout is a JSON-lines event channel; tool logs stay local.
"""

import argparse
import json
import os
import secrets
import select
import subprocess
import threading
import time
from pathlib import Path

import numpy as np

from chipjev import xschem
from chipjev.circuits.published import lookup
from chipjev.circuits.sky130_devices import build
from chipjev.paths import ROOT
from chipjev.simulation.sky130 import evaluate

FIXTURE = ROOT / "demo/fixtures/sky130-opamp.json"
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


def schematic_steps(builder, fixture):
    """Keep each real device and its net labels together, preserving the exporter."""
    full = xschem.schematic(builder, fixture["topology"], fixture["vdd"])
    header, groups = [], []
    for line in full.splitlines():
        if line.startswith("C ") and "devices/lab_pin.sym" not in line:
            groups.append([line])
        elif groups:
            groups[-1].append(line)
        else:
            header.append(line)
    # Compact the rows without changing a device, pin offset or electrical value.
    for i, group in enumerate(groups):
        shift = (i // xschem.COLUMNS) * 50
        for j, line in enumerate(group):
            if line.startswith("C "):
                fields = line.split(" ", 5)
                fields[3] = str(int(fields[3]) - shift)
                group[j] = " ".join(fields)
    # A fixed viewport keeps symbols in place as the circuit is assembled.
    rows = (len(groups) + xschem.COLUMNS - 1) // xschem.COLUMNS
    bottom = (rows - 1) * 150 + 80
    header += ["L 4 -120 -200 1530 -200 {dash=4}",
               f"L 4 -120 {bottom} 1530 {bottom} {{dash=4}}"]
    steps = ["\n".join(header) + "\n"]
    for group in groups:
        steps.append(steps[-1] + "\n".join(group) + "\n")
    return steps


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
                      "set draw_grid 0\nset autoload_new_window 0\n")
        driver = self.directory / "display.tcl"
        driver.write_text('''
wm geometry . 1440x900+0+0
wm title . {ChipJev | LIVE xschem | SKY130}
set chipjev_stage -1
set chipjev_plot 0
proc chipjev_tick {} {
    global chipjev_stage chipjev_plot
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
    if {!$chipjev_plot && [file exists plots.png]} {
        set chipjev_plot 1
        wm geometry . 1440x600+0+0
        update idletasks
        xschem zoom_full
        xschem redraw
        toplevel .chipjev_plots
        wm overrideredirect .chipjev_plots 1
        wm geometry .chipjev_plots 1440x300+0+600
        image create photo chipjev_plots -file plots.png
        label .chipjev_plots.image -image chipjev_plots -borderwidth 0
        pack .chipjev_plots.image -fill both -expand 1
        raise .chipjev_plots
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


def run(directory):
    start = time.monotonic()
    fixture = json.loads(FIXTURE.read_text())
    topology = lookup(fixture["cls"], fixture["topology"])
    builder = build(topology, fixture["values"], fixture["vdd"])
    steps = schematic_steps(builder, fixture)
    for i, text in enumerate(steps):
        (directory / f"step-{i}.sch").write_text(text)
    screen = Screen(directory)
    emit("stage", stage="starting", message="Starting a private xschem display", progress=2)
    try:
        screen.start()
        screen.show(0)
        emit("stage", stage="building", message="Empty canvas · placing SKY130 devices", progress=5)
        time.sleep(0.25)
        for i in range(1, len(steps)):
            screen.show(i)
            emit("stage", stage="building", message=f"Placed device {i} of {len(steps) - 1}",
                 placed=i, total=len(steps) - 1, progress=5 + round(48 * i / (len(steps) - 1)))
            # Pacing is for legible viewing, and is included in total wall time.
            time.sleep(0.14)
        final = directory / "circuit.sch"
        final.write_text(steps[-1])
        emit("stage", stage="netlisting", message="xschem is netlisting the assembled circuit",
             progress=58)
        netlist = xschem.netlist(final, directory / "netlist")
        ok, problems = xschem.check(builder, netlist, fixture["vdd"])
        if not ok:
            raise RuntimeError("xschem connectivity check failed: " + "; ".join(problems))
        (directory / "circuit.spice").write_text(netlist)
        emit("stage", stage="simulating", message="ngspice · AC sweep + ±10 mV unity-buffer steps",
             progress=72)
        result = evaluate(topology, fixture["values"], directory=directory, strict=True,
                          keep=True, vdd=fixture["vdd"], load_pf=fixture["load_pf"])
        if result["error"]:
            raise RuntimeError(result["error"])
        waves = waveforms(directory, result)
        emit("waveforms", **waves)
        emit("stage", stage="checking", message="Checking gain, stability and closed-loop operation",
             progress=92)
        plot(directory, waves)
        screen.check()
        result.pop("pid", None)
        result.update(mode="live-resimulation", topology=fixture["topology"],
                      source=fixture["source"], source_sha256=fixture["source_sha256"],
                      netlist_match=ok)
        # Include display pacing, validation and plotting in the displayed elapsed time.
        time.sleep(0.6)
        result["demo_seconds"] = time.monotonic() - start
        (directory / "result.json").write_text(json.dumps(result, indent=2, allow_nan=False))
        emit("result", **result)
        emit("stage", stage="complete" if result["valid"] else "unqualified",
             message="All circuit checks passed" if result["valid"] else "Simulation finished; qualification failed",
             progress=100)
    finally:
        screen.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    args.directory.mkdir(parents=True, exist_ok=True)
    try:
        run(args.directory.resolve())
    except Exception:
        import traceback
        traceback.print_exc()
        emit("error", message="The live run failed. Please retry; diagnostic details are kept on the server.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
