"""Connected analog stage layouts for the public SKY130 grammar.

Only placement and routing are specified here. Every device, polarity, dimension,
source value and net name comes from the newly generated ChipJev circuit.
"""

import re

from chipjev import xschem
from chipjev.circuits.published import lookup


def analog_schematic(builder, topology_id, vdd):
    # Import inside the function to keep the shared drawing primitives in one place.
    from demo.schematic import text, wire

    cls = "opampN" if "+" in topology_id else "opamp1"
    top = lookup(cls, topology_id)
    if len(top.stages) > 2 or top.buffer != "none":
        raise ValueError("The public analog layout supports one or two gain stages")
    raw = {}
    for line in xschem.schematic(builder, topology_id, vdd).splitlines():
        if line.startswith("C ") and "lab_pin.sym" not in line:
            raw[re.search(r"\{name=(\S+)", line)[1]] = line
    parsed = {name.upper(): (kind, nodes, props)
              for kind, name, nodes, props in map(xschem._parse, builder.lines)}
    drawing, wires, named, biases, placed = [], [], set(), {}, set()
    mirrored = False

    def point(xy):
        return (xy[0], 1000 - xy[1]) if mirrored else xy

    def netname(net):
        if mirrored and net in ("0", "vdd"):
            return "vdd" if net == "0" else "0"
        return net

    def label(net, xy, hidden=False):
        x, y = xy
        drawing.append(f"C {{devices/lab_wire.sym}} {x} {y} 0 0 "
                       f"{{name=net{len(drawing)} lab={net}{' hide_texts=true' if hidden else ''}}}")

    def connect(net, *points):
        actual = netname(net)
        points = [point(p) for p in points]
        wires.extend(wire(*points))
        if actual not in named:
            label(actual, points[0])
            named.add(actual)

    def device(name, x, y, flip=0, rotation=0):
        name = name.upper()
        x, y = point((x, y))
        fields = raw[name].split(" ", 6)
        kind = parsed.get(name, ("v",))[0]
        if mirrored and kind not in ("n", "p"):
            rotation = (2 - rotation) % 4
        fields[2:6] = map(str, (x, y, rotation, flip))
        drawing.append(" ".join(fields)[:-1] + " hide_texts=true}")
        placed.add(name)
        if kind in ("n", "p"):
            _, nodes, props = parsed[name]
            label(nodes[3], (x - 20 if flip else x + 20, y), True)
            tx = x - 115 if flip else x + 45
            drawing.extend([text(name, tx, y - 18, 0.29),
                            text(f"{float(props['w']):.3g}/{float(props['l']):.3g}", tx, y + 7, 0.2, 14)])
        else:
            value = re.search(r" value=(\S+)", raw[name])[1]
            drawing.extend([text(name, x + 35, y - 24, 0.25), text(value, x + 35, y + 3, 0.21, 14)])

    def bias(net, gate, escape_x):
        connect(net, gate, (escape_x, gate[1]))
        biases[net] = point((escape_x, gate[1]))

    multi = len(top.stages) == 2
    right = 1940 if multi else 1120
    device("VDD", 40, 500)
    connect("vdd", (40, 100), (right, 100))
    connect("vdd", (40, 100), (40, 470))
    connect("0", (40, 900), (right, 900))
    connect("0", (40, 530), (40, 900))
    first, polarity = top.stages[0].rsplit("_", 1)
    mirrored = polarity == "p"
    out1 = "o1" if multi else "out"
    device("M1", 560, 800)
    connect("0", (580, 830), (580, 900))
    bias("s1t", (540, 800), 500)

    if first in ("ota5", "rload", "cmota"):
        device("M2", 700, 600)
        device("M3", 460, 600)
        connect("t1", (580, 740), (580, 770))
        connect("t1", (480, 630), (480, 740), (720, 740), (720, 630))
        connect("inp", (640, 600), (680, 600))
        connect("inn", (400, 600), (440, 600))
        if first == "rload":
            device("R4", 720, 300, rotation=2)
            device("R5", 480, 300, rotation=2)
            connect("vdd", (720, 100), (720, 270))
            connect("vdd", (480, 100), (480, 270))
            connect("x1", (720, 330), (720, 570))
            connect(out1, (480, 330), (480, 570))
            connect(out1, (480, 500), (1100, 500))
            mos_count = 3
        else:
            device("M4", 700, 240)
            device("M5", 460, 240)
            connect("vdd", (720, 100), (720, 210))
            connect("vdd", (480, 100), (480, 210))
            connect("x1", (720, 270), (720, 570))
            connect("x1", (720, 340), (640, 340), (640, 240), (680, 240))
            if first == "ota5":
                connect(out1, (480, 270), (480, 570))
                connect("x1", (640, 340), (400, 340), (400, 240), (440, 240))
                connect(out1, (480, 500), (1100, 500))
                mos_count = 5
            else:
                connect("x2", (480, 270), (480, 570))
                connect("x2", (480, 380), (400, 380), (400, 240), (440, 240))
                device("M6", 240, 240, flip=1)
                device("M7", 960, 240)
                device("M8", 200, 800)
                device("M9", 960, 800)
                connect("vdd", (220, 100), (220, 210))
                connect("vdd", (980, 100), (980, 210))
                connect("x2", (260, 240), (400, 240))
                connect("x1", (720, 340), (900, 340), (900, 240), (940, 240))
                connect("y1", (220, 270), (220, 770))
                connect("0", (220, 830), (220, 900))
                connect("y1", (220, 690), (160, 690), (160, 800), (180, 800))
                connect("y1", (160, 850), (160, 800))
                connect("y1", (160, 850), (900, 850), (900, 800), (940, 800))
                connect(out1, (980, 270), (980, 770))
                connect(out1, (980, 500), (1100, 500))
                connect("0", (980, 830), (980, 900))
                mos_count = 9
    elif first == "tele":
        device("M2", 460, 680)
        device("M3", 780, 680)
        device("M4", 460, 560)
        device("M5", 780, 560)
        device("M6", 460, 400)
        device("M7", 780, 400)
        device("M8", 460, 220)
        device("M9", 780, 220)
        connect("t1", (480, 710), (480, 740), (800, 740), (800, 710))
        connect("t1", (580, 740), (580, 770))
        connect("inp", (400, 680), (440, 680))
        connect("inn", (720, 680), (760, 680))
        for x, suffix in ((480, "1"), (800, "2")):
            connect("a" + suffix, (x, 590), (x, 650))
            connect("c" + suffix, (x, 250), (x, 370))
            connect("vdd", (x, 100), (x, 190))
            connect("x1" if suffix == "1" else out1, (x, 430), (x, 530))
        connect(out1, (800, 500), (1100, 500))
        connect("x1", (480, 470), (360, 470), (360, 220), (440, 220))
        connect("x1", (360, 300), (700, 300), (700, 220), (760, 220))
        connect("s1cn", (440, 560), (320, 560), (320, 620), (740, 620), (740, 560), (760, 560))
        bias("s1cn", (320, 620), 280)
        connect("s1cp", (440, 400), (340, 400), (340, 350), (720, 350), (720, 400), (760, 400))
        bias("s1cp", (340, 350), 260)
        mos_count = 9
    elif first == "fc":
        for name, x, y in (("M2",460,650),("M3",700,650),("M4",460,220),("M5",700,220),
                           ("M6",300,400),("M7",960,400),("M8",300,600),("M9",960,600),
                           ("M10",300,800),("M11",960,800)):
            device(name,x,y)
        connect("t1", (480,680),(480,740),(720,740),(720,680))
        connect("t1", (580,740),(580,770))
        connect("inp", (400,650),(440,650))
        connect("inn", (640,650),(680,650))
        connect("vdd", (480,100),(480,190))
        connect("vdd", (720,100),(720,190))
        connect("f1", (480,250),(480,620))
        connect("f2", (720,250),(720,620))
        connect("f1", (480,300),(320,300),(320,370))
        connect("f2", (720,300),(980,300),(980,370))
        connect("x1", (320,430),(320,570))
        connect(out1, (980,430),(980,570))
        connect(out1, (980,500),(1100,500))
        connect("e1", (320,630),(320,770))
        connect("e2", (980,630),(980,770))
        connect("0", (320,830),(320,900))
        connect("0", (980,830),(980,900))
        connect("x1", (320,500),(220,500),(220,800),(280,800))
        connect("x1", (220,800),(220,850),(900,850),(900,800),(940,800))
        connect("s1s", (440,220),(400,220),(400,150),(640,150),(640,220),(680,220))
        bias("s1s", (400,150),120)
        connect("s1cp", (280,400),(260,400),(260,330),(920,330),(920,400),(940,400))
        bias("s1cp", (260,330),180)
        connect("s1cn", (280,600),(240,600),(240,540),(900,540),(900,600),(940,600))
        bias("s1cn", (240,540),140)
        mos_count = 11
    else:
        raise ValueError(first)

    mirrored = False
    if multi:
        second = top.stages[1]
        mirrored = second.endswith("_p")
        offset = mos_count
        def mos(n, x, y, flip=0):
            device(f"M{offset+n}", x, y, flip)
        mos(1,1440,800)
        connect("0", (1460,830),(1460,900))
        connect("o1", (1100,500),(1200,500),(1200,800),(1420,800))
        if second.startswith("cs_") or second == "inv":
            mos(2,1440,220)
            connect("vdd", (1460,100),(1460,190))
            connect("out", (1460,250),(1460,770))
            if second == "inv":
                connect("o1", (1200,500),(1200,220),(1420,220))
            else:
                bias("s2ld",(1420,220),1340)
        elif second.startswith("cas_"):
            mos(2,1480,600,1)
            mos(3,1480,220,1)
            connect("vdd", (1460,100),(1460,190))
            connect("s2a", (1460,630),(1460,770))
            connect("out", (1460,250),(1460,570))
            bias("s2cn",(1500,600),1680)
            bias("s2ld",(1500,220),1780)
        elif second == "inv_cas":
            mos(2,1480,620,1)
            mos(3,1480,380,1)
            mos(4,1440,200)
            connect("vdd", (1460,100),(1460,170))
            connect("s2a", (1460,650),(1460,770))
            connect("s2c", (1460,230),(1460,350))
            connect("out", (1460,410),(1460,590))
            connect("o1", (1200,500),(1200,200),(1420,200))
            bias("s2cn",(1500,620),1680)
            bias("s2cp",(1500,380),1780)
        else:
            raise ValueError(second)
        connect("out", (1460,500),(1880,500))
        mirrored = False
        if top.comp != "none":
            cap = next(name for name, (kind, _, _) in parsed.items() if kind == "c")
            device(cap,1450,0,rotation=1)
            connect("o1", (1200,500),(1200,0),(1420,0))
            if top.comp == "miller":
                connect("out", (1480,0),(1880,0),(1880,500))
            else:
                resistor = next(name for name, (kind,nodes,_) in parsed.items() if kind == "r" and "cz" in nodes)
                device(resistor,1660,0,rotation=1)
                connect("cz", (1480,0),(1630,0))
                connect("out", (1690,0),(1880,0),(1880,500))
    # Sources are driven by their measured bias voltages, with explicit return wiring.
    rows = []
    ground_y = 1260
    for net, (x,y) in sorted(biases.items(), key=lambda item:item[1][0]):
        row = 0
        while any(abs(x-other_x)<110 and row==other_row for other_x,other_row in rows):
            row += 1
        rows.append((x,row))
        sy = 1040 + row*100
        device("V_"+net.upper(),x,sy)
        connect(net, (x,y),(x,sy-30))
        connect("0", (x,sy+30),(x,ground_y))
    connect("0", (40,900),(40,ground_y),(right,ground_y))
    if placed != raw.keys():
        raise ValueError(f"Unplaced circuit devices: {raw.keys()-placed}")
    header = ["v {xschem version=3.4.5 file_version=1.2}","G {}","K {}","V {}","S {}","E {}",
              text(f"CHIPJEV / {topology_id}",40,-180,0.52),
              text("01  DIFFERENTIAL INPUT + ACTIVE LOAD",220,-100,0.32,6),
              text("02  GAIN + COMPENSATION" if multi else "SINGLE-STAGE OTA",1230 if multi else 650,-100,0.32,6),
              text(f"SKY130 / {len(builder.mos)} MOSFETs / W/L in um / live candidate",40,1320,0.28,14)]
    return "\n".join(header+wires+drawing)+"\n"
