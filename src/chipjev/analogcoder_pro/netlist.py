"""LLM-generated PySpice netlists on the common testbench.

AnalogCoder-Pro's generator writes PySpice code; its parameterized form defines
``create_circuit(params)``. This adapter turns the printed SPICE netlist into the testbench's
Builder so that the same deck, bias search, checks and qualification apply to it as to the
grammar. Mapping, applied identically to every LLM design:

* Nodes are case-insensitive. Vdd -> vdd, ground/gnd/0 -> 0, Vin -> in, Vinp -> inp,
  Vinn -> inn and Vout -> out; other nodes are kept under an ``x_`` prefix.
* The supply source and the sources driving the input nodes are removed: the testbench
  supplies VDD and performs its own input bias search (as AnalogCoder-Pro's DC sweep does).
* Other DC voltage sources to ground become gate-bias sources (their power is counted like
  every bias source of the testbench). Floating voltage sources and DC current sources are
  kept as they are.
* Capacitors between the output and a rail are load capacitors; they are removed because
  the testbench attaches the task's load (100 pF). All other R and C elements are kept.
* MOSFETs keep their terminals, W and L, and use the testbench's PTM 45 nm card (the same
  card that is supplied to AnalogCoder-Pro's generator as ``nmos_params``/``pmos_params``).
* Other element types (subcircuits, diodes, controlled sources, inductors) are unsupported
  and make the design unevaluable, which counts as a failed design.
"""

import re

from ..circuits.grammar import Builder

SCALE = {
    "t": 1e12, "g": 1e9, "meg": 1e6, "k": 1e3, "m": 1e-3, "u": 1e-6, "µ": 1e-6, "μ": 1e-6,
    "n": 1e-9, "p": 1e-12, "f": 1e-15, "mil": 25.4e-6,
}
UNIT = re.compile(r"^([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)(meg|mil|[tgkmuµμnpf])?", re.I)


class NetlistError(ValueError):
    pass


def value(token):
    """SPICE number with optional scale suffix; trailing unit letters are ignored."""
    token = token.strip().lower().replace("dc", "").strip()
    match = UNIT.match(token)
    if not match:
        raise NetlistError(f"not a SPICE value: {token!r}")
    number = float(match.group(1))
    suffix = match.group(2)
    return number * SCALE[suffix.lower()] if suffix else number


def _node(name, differential):
    n = name.strip().lower()
    if n in ("0", "gnd", "ground", "vss"):
        return "0"
    if n == "vdd":
        return "vdd"
    if n == "vout":
        return "out"
    if differential and n == "vinp":
        return "inp"
    if differential and n == "vinn":
        return "inn"
    if not differential and n == "vin":
        return "in"
    return "x_" + re.sub(r"[^a-z0-9_]", "_", n)


def _params(tokens):
    out = {}
    for token in tokens:
        if "=" in token:
            key, raw = token.split("=", 1)
            out[key.strip().lower()] = raw.strip()
    return out


def parse(text, differential, vdd):
    """Builder of a PySpice/SPICE netlist; raises NetlistError for unsupported content."""
    models, elements = {}, []
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("*"):
            continue
        if line.startswith("+") and lines:
            lines[-1] += " " + line[1:]
        else:
            lines.append(line)
    for line in lines:
        low = line.lower()
        if low.startswith((".title", ".end", ".include", ".lib", ".options", ".temp")):
            continue
        if low.startswith(".model"):
            parts = line.replace("(", " ").replace(")", " ").split()
            if len(parts) < 3:
                raise NetlistError(f"bad model line: {line}")
            kind = parts[2].lower()
            if kind not in ("nmos", "pmos"):
                raise NetlistError(f"unsupported model type {kind}")
            models[parts[1].lower()] = kind
            continue
        if low.startswith("."):
            raise NetlistError(f"unsupported control line: {line}")
        elements.append(line)

    b = Builder(vdd)
    inputs = {"inp", "inn"} if differential else {"in"}
    count = {"m": 0, "r": 0, "c": 0, "i": 0, "v": 0}
    for line in elements:
        parts = line.split()
        name, kind = parts[0], parts[0][0].lower()
        if kind == "m":
            if len(parts) < 6:
                raise NetlistError(f"bad MOSFET: {line}")
            d, g, s, bulk = (_node(x, differential) for x in parts[1:5])
            model = models.get(parts[5].lower())
            if model is None:
                model = {"nmos": "nmos", "pmos": "pmos"}.get(parts[5].lower())
            if model is None:
                raise NetlistError(f"unknown MOSFET model {parts[5]}")
            p = _params(parts[6:])
            if "w" not in p or "l" not in p:
                raise NetlistError(f"MOSFET without W and L: {line}")
            width, length = value(p["w"]), value(p["l"])
            if not (width > 0 and length > 0):
                raise NetlistError(f"nonpositive MOSFET size: {line}")
            multiplier = value(p["m"]) if "m" in p else 1.0
            count["m"] += 1
            mos = f"m{count['m']}"
            extra = f" m={multiplier:.6g}" if multiplier != 1.0 else ""
            b.lines.append(f"{mos} {d} {g} {s} {bulk} {model} W={width:.6g} L={length:.6g}{extra}")
            b.mos.append((mos, d, g, s, model[0]))
            b.nodes.update(n for n in (d, g, s, bulk) if n != "0")
        elif kind in ("r", "c"):
            if len(parts) < 4:
                raise NetlistError(f"bad passive: {line}")
            a, c = _node(parts[1], differential), _node(parts[2], differential)
            v = value(parts[3])
            if kind == "c" and "out" in (a, c) and ({a, c} - {"out"}) <= {"0", "vdd"}:
                continue  # load capacitor: the testbench attaches the task's load
            if kind == "r" and v <= 0:
                raise NetlistError(f"nonpositive resistor: {line}")
            count[kind] += 1
            b.lines.append(f"{kind}{count[kind]}_llm {a} {c} {v:.6g}")
            b.nodes.update(n for n in (a, c) if n != "0")
        elif kind == "v":
            a, c = _node(parts[1], differential), _node(parts[2], differential)
            dc = _dc(parts[3:])
            if {a, c} == {"vdd", "0"}:
                continue  # supply: provided by the testbench
            if a in inputs or c in inputs:
                continue  # input source: the testbench drives and biases the inputs
            if c == "0" and a not in ("vdd", "out"):
                b.bias[a] = min(max(dc, 0.0), vdd)
                b.nodes.add(a)
            elif a == "0" and c not in ("vdd", "out"):
                b.bias[c] = min(max(-dc, 0.0), vdd)
                b.nodes.add(c)
            else:
                count["v"] += 1
                b.lines.append(f"vx{count['v']} {a} {c} DC {dc:.6g}")
                b.nodes.update(n for n in (a, c) if n != "0")
        elif kind == "i":
            a, c = _node(parts[1], differential), _node(parts[2], differential)
            count["i"] += 1
            b.lines.append(f"ix{count['i']} {a} {c} DC {_dc(parts[3:]):.6g}")
            b.nodes.update(n for n in (a, c) if n != "0")
        else:
            raise NetlistError(f"unsupported element {name}")
    if not b.mos:
        raise NetlistError("no transistors")
    used = set()
    for _, d, g, s, _kind in b.mos:
        used.update((d, g, s))
    for line in b.lines:
        used.update(line.split()[1:3])
    if "out" not in used:
        raise NetlistError("the output node Vout is not connected")
    missing = inputs - used
    if missing:
        raise NetlistError(f"input nodes not connected: {sorted(missing)}")
    return b


def _dc(tokens):
    tokens = [t for t in tokens if t.lower() not in ("dc",)]
    for t in tokens:
        if "=" in t or t.lower().startswith(("ac", "sin", "pulse", "pwl")):
            continue
        try:
            return value(t)
        except NetlistError:
            continue
    return 0.0


class NetlistTopology:
    """A generated design that the common testbench can evaluate like a grammar member."""

    construct = True  # marks a non-grammar topology for circuits.grammar.build

    def __init__(self, cls, identifier, factory):
        self.cls = cls
        self.id = identifier
        self.factory = factory  # params -> SPICE netlist text
        self.stages = ()

    @property
    def differential(self):
        return self.cls.startswith("opamp")

    def slots(self):
        return ()

    def build(self, values, vdd):
        return parse(self.factory(values), self.differential, vdd)


class FrozenNetlist(NetlistTopology):
    """A stored netlist (for re-evaluation, e.g. robustness checks)."""

    def __init__(self, cls, identifier, text):
        super().__init__(cls, identifier, lambda values: text)
        self.text = text
