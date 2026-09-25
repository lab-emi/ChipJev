"""A wired, readable xschem layout for the fixed public-demo topology.

Device properties come from the research exporter unchanged. Signal connections
are xschem N primitives; labels name nets, they do not replace signal wiring.
Only MOS body terminals use the usual implicit supply connections.
"""

import re
from dataclasses import dataclass

from chipjev import xschem


@dataclass(frozen=True)
class Step:
    schematic: str
    message: str


# The four output devices share one drain/source column. The cascode gates
# face right so their bias wires do not run through the transistor symbols.
PLACEMENT = {
    "M1": (580, 590, 0, 0),
    "M2": (700, 420, 0, 0), "M3": (460, 420, 0, 0),
    "M4": (700, 210, 0, 0), "M5": (460, 210, 0, 0),
    "M6": (260, 210, 0, 1), "M7": (940, 210, 0, 0),
    "M8": (220, 590, 0, 0), "M9": (940, 590, 0, 0),
    "M10": (1260, 620, 0, 0), "M11": (1300, 480, 0, 1),
    "M12": (1300, 340, 0, 1), "M13": (1260, 190, 0, 0),
    "C14": (1440, 0, 1, 0),
    "VDD": (60, 390, 0, 0), "V_S1T": (500, 650, 0, 0),
    "V_S2CP": (1480, 340, 0, 0), "V_S2CN": (1600, 480, 0, 0),
}


def wire(*points):
    """An orthogonal polyline of electrical wires (not decorative lines)."""
    lines = []
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        if (x1, y1) == (x2, y2) or (x1 != x2 and y1 != y2):
            raise ValueError("Schematic wires must be nonzero and orthogonal")
        lines.append(f"N {x1} {y1} {x2} {y2} {{}}")
    return lines


def text(value, x, y, size=0.28, layer=3):
    return f"T {{{value}}} {x} {y} 0 0 {size} {size} {{layer={layer}}}"


def schematic_steps(builder, fixture):
    if fixture["topology"] != "cmota_n+inv_cas+miller":
        raise ValueError("This layout is for the public demo's fixed topology")
    # Reuse exact model, geometry, finger and source properties from the exporter.
    devices = {}
    for line in xschem.schematic(builder, fixture["topology"], fixture["vdd"]).splitlines():
        if line.startswith("C ") and "devices/lab_pin.sym" not in line:
            name = re.search(r"\{name=(\S+)", line)[1]
            devices[name] = line
    if devices.keys() != PLACEMENT.keys():
        raise ValueError("The fixture's devices no longer match the wired layout")
    label_index = 0

    def label(net, x, y, hidden=False):
        nonlocal label_index
        label_index += 1
        return (f"C {{devices/lab_wire.sym}} {x} {y} 0 0 "
                f"{{name=net{label_index} sig_type=std_logic lab={net}"
                f"{' hide_texts=true' if hidden else ''}}}")

    def device(name):
        x, y, rotation, flip = PLACEMENT[name]
        fields = devices[name].split(" ", 6)
        fields[2:6] = map(str, (x, y, rotation, flip))
        lines = [" ".join(fields)[:-1] + " hide_texts=true}"]
        if name.startswith("M"):
            # Body ties are conventional global rail labels; every signal pin
            # and source/drain path is physically wired below.
            kind = "p" if "pfet" in devices[name] else "n"
            body_x = x - 20 if flip else x + 20
            lines.append(label("vdd" if kind == "p" else "0", body_x, y, True))
            # Hide PDK debug readouts and annotate cleanly without editing symbols.
            tx = x - 115 if flip else x + 45
            lines.append(text(name, tx, y - 18, 0.3))
            width = re.search(r" W=(\S+)", devices[name])[1]
            length = re.search(r" L=(\S+)", devices[name])[1]
            lines.append(text(f"{width}/{length}", tx, y + 6, 0.18, 14))
        elif name == "C14":
            lines += [text("C14  /  MILLER FEEDBACK", x - 105, y - 52, 0.28, 6),
                      text("177 fF", x - 25, y + 22, 0.22)]
        else:
            volts = re.search(r" value=(\S+)", devices[name])[1]
            lines += [text(name.replace("V_", ""), x + 35, y - 24, 0.23),
                      text(f"{volts} V", x + 35, y + 3, 0.21, 14)]
        return lines

    content = ["v {xschem version=3.4.5 file_version=1.2}", "G {}", "K {}", "V {}", "S {}", "E {}",
               text("CHIPJEV  /  SKY130 TWO-STAGE OP-AMP", 30, -145, 0.48),
               text("01  DIFFERENTIAL INPUT + CURRENT MIRRORS", 220, -82, 0.3, 6),
               text("02  CASCODED INVERTER", 1170, -82, 0.3, 6),
               text("13 MOSFETs  /  1.8 V  /  W/L in um  /  body terminals tied to supply rails",
                    220, 740, 0.25, 14),
               # Fixed extent prevents zoom jumps during assembly. These two
               # unobtrusive drawing lines are not used as electrical wires.
               "L 2 0 -170 1790 -170 {}", "L 2 0 785 1790 785 {}"]
    steps = [Step("\n".join(content) + "\n", "Empty canvas · ready to connect the topology")]

    def add(message, *groups):
        for group in groups:
            content.extend(group if isinstance(group, list) else [group])
        steps.append(Step("\n".join(content) + "\n", message))

    add("Route the shared VDD and ground rails", device("VDD"),
        wire((60, 360), (60, 100), (1280, 100)),
        wire((60, 420), (60, 680), (1600, 680)),
        label("vdd", 100, 100), label("0", 100, 680))
    add("Connect the tail-current bias", device("V_S1T"), device("M1"),
        wire((500, 620), (500, 590), (560, 590)),
        wire((600, 620), (600, 680)), label("s1t", 530, 590))
    add("Build the differential pair around a common tail node", device("M3"), device("M2"),
        wire((480, 450), (480, 490), (600, 490), (720, 490), (720, 450)),
        wire((600, 490), (600, 560)),
        wire((400, 420), (440, 420)), wire((640, 420), (680, 420)),
        label("inn", 400, 420), label("inp", 640, 420), label("t1", 630, 490))
    add("Wire the diode-connected PMOS load on the negative input", device("M5"),
        wire((480, 100), (480, 180)), wire((480, 240), (480, 390)),
        wire((480, 280), (400, 280), (400, 210), (440, 210)), label("x2", 480, 310))
    add("Wire the matching PMOS load on the positive input", device("M4"),
        wire((720, 100), (720, 180)), wire((720, 240), (720, 390)),
        wire((720, 280), (640, 280), (640, 210), (680, 210)), label("x1", 720, 310))
    add("Extend the left PMOS current mirror", device("M6"),
        wire((240, 100), (240, 180)), wire((280, 210), (400, 210)))
    add("Extend the right PMOS current mirror", device("M7"),
        wire((960, 100), (960, 180)),
        wire((720, 280), (880, 280), (880, 210), (920, 210)))
    add("Close the NMOS mirror reference branch", device("M8"),
        wire((240, 240), (240, 560)), wire((240, 620), (240, 680)),
        wire((240, 510), (180, 510), (180, 590), (200, 590)), label("y1", 240, 390))
    add("Connect both mirror branches to the first-stage output", device("M9"),
        wire((960, 240), (960, 560)), wire((960, 620), (960, 680)),
        wire((180, 530), (900, 530), (900, 590), (920, 590)), label("o1", 1010, 410),
        wire((960, 410), (1160, 410)))
    add("Connect the second-stage NMOS input device", device("M10"),
        wire((1280, 650), (1280, 680)),
        wire((1160, 410), (1160, 620), (1240, 620)))
    add("Add the NMOS cascode in the output stack", device("M11"),
        wire((1280, 510), (1280, 590)), label("s2a", 1280, 550))
    add("Add the PMOS cascode and join the output node", device("M12"),
        wire((1280, 370), (1280, 450)),
        wire((1280, 410), (1760, 410)), label("out", 1760, 410))
    add("Close the PMOS stack and connect the interstage drive", device("M13"),
        wire((1280, 100), (1280, 160)), wire((1280, 220), (1280, 310)),
        wire((1160, 410), (1160, 190), (1240, 190)), label("s2c", 1280, 270))
    add("Wire the upper cascode bias", device("V_S2CP"),
        wire((1480, 310), (1400, 310), (1400, 340), (1320, 340)),
        wire((1480, 370), (1480, 680)), label("s2cp", 1360, 340))
    add("Wire the lower cascode bias", device("V_S2CN"),
        wire((1600, 450), (1360, 450), (1360, 480), (1320, 480)),
        wire((1600, 510), (1600, 680)), label("s2cn", 1360, 480))
    add("Close the Miller compensation loop from output to interstage", device("C14"),
        wire((1160, 190), (1160, 0), (1410, 0)),
        wire((1470, 0), (1720, 0), (1720, 410)))
    return steps
