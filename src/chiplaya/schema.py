"""ChipLaya's question schema: the typed questions of an analog amplifier design request.

Every question is typed: its answer is a probability distribution over a closed set of
options ("option cards", short textbook descriptions), never generated text. Parse
questions recover the circuit class and objective of a free-text request; the
class-conditional topology questions ask for one decision each of a topology grammar
(input stage, input device, stage count, later stages, compensation, output buffer).
ChipLaya v1 was fine-tuned on exactly these questions: they are part of the model's
interface, so their wording is frozen with the weights.
"""

# -------------------------------------------------------------------------- questions

INPUT = {
    "single": "a single-ended input: one input terminal, a voltage amplifier",
    "differential": "a differential input pair: two input terminals, an op-amp or OTA",
}
STAGES = {
    "one": "one gain stage (a single-stage circuit)",
    "several": "two or more cascaded gain stages (a multi-stage circuit)",
}
OBJECTIVE = {
    "gain": "the low-frequency (DC) voltage gain",
    "gbw": "the gain-bandwidth product (GBW)",
    "fom": "the figure of merit FoM = GBW x load capacitance / power (power efficiency)",
}
CLASS_OF = {
    ("single", "one"): "amp1",
    ("differential", "one"): "opamp1",
    ("single", "several"): "ampN",
    ("differential", "several"): "opampN",
}

# Short textbook descriptions of the grammar's options ("option cards").
SE_KINDS = {
    "r": "resistor-loaded common source: low gain, wide bandwidth",
    "diode": "common source with a diode-connected load: low, well-defined gain, very fast",
    "cs": "common source with a current-source load: gain gm*ro",
    "cas": "cascode common source: high output resistance and gain (gm*ro)^2",
    "tele": "telescopic cascode: very high gain at low power, small output swing",
    "inv": "CMOS inverter: both devices amplify, high gm per current",
    "inv_cas": "cascoded CMOS inverter: very high gain and gm efficiency",
    "fold": "folded cascode: high gain, wider input range, more current",
    "sf": "source follower: gain below one, low output impedance",
}
DIFF_KINDS = {
    "ota5": "five-transistor OTA with a current-mirror load: moderate gain, fast",
    "tele": "telescopic cascode OTA: very high gain at low power, small swing",
    "fc": "folded-cascode OTA: high gain, wide input range, more power",
    "cmota": "current-mirror OTA: mirror gain raises bandwidth and slew rate",
    "rload": "resistor-loaded differential pair: low gain, wide bandwidth",
}
GAIN_KINDS = {k: SE_KINDS[k] for k in ("cs", "cas", "inv", "inv_cas")}
POLARITY = {
    "n": "NMOS input device: higher mobility and transconductance",
    "p": "PMOS input device: lower flicker noise, input near ground",
}
COUNT = {
    "2": "two gain stages: easier to stabilize",
    "3": "three gain stages: more gain, harder to stabilize",
}
COMP = {
    "none": "no compensation capacitor",
    "miller": "a Miller capacitor across the last stage (pole splitting)",
    "miller_rz": "a Miller capacitor with a nulling resistor (cancels the right-half-plane zero)",
    "miller2": "nested Miller compensation across the last two stages (three stages only)",
}
BUFFER = {
    "none": "no output buffer",
    "sf_n": "an NMOS source-follower output buffer",
    "sf_p": "a PMOS source-follower output buffer",
}


def _choice(instructions, criteria):
    return {"type": "choice", "instructions": instructions, "criteria": criteria}


PARSE_QUESTIONS = {
    "input": _choice("What kind of input does the requested circuit have?", INPUT),
    "stages": _choice("How many gain stages does the requested circuit have?", STAGES),
    "objective": _choice("Which quantity does the request ask to maximize?", OBJECTIVE),
}


GOAL = {
    "gain": "the highest DC voltage gain",
    "gbw": "the highest gain-bandwidth product",
    "fom": "the best FoM (GBW x load capacitance / power)",
}


def topology_questions(cls, objective):
    """Typed grammar questions for one circuit class and objective. The objective is part
    of each question, so the answers are conditioned on the parsed objective."""
    goal = GOAL[objective]
    differential = cls.startswith("opamp")
    first = DIFF_KINDS if differential else (SE_KINDS if cls == "amp1" else GAIN_KINDS)
    what = "differential input stage" if differential else "first (input) stage"
    questions = {
        "first": _choice(f"Which {what} gives {goal}?", first),
        "polarity": _choice(f"Which input device type gives {goal}?", POLARITY),
    }
    if cls in ("ampN", "opampN"):
        questions["count"] = _choice(f"How many gain stages give {goal}?", COUNT)
        questions["later"] = _choice(
            f"Which gain stage after the first stage gives {goal}?", GAIN_KINDS
        )
        questions["later_polarity"] = _choice(
            f"Which input device type of the following gain stages gives {goal}?", POLARITY
        )
        questions["comp"] = _choice(f"Which frequency compensation gives {goal}?", COMP)
    if cls == "ampN":
        questions["buffer"] = _choice(f"Which output buffer gives {goal}?", BUFFER)
    return questions


def state_text(request, vdd=None, load_pf=None):
    """The decision state: the designer's request plus the testbench conditions."""
    text = request.strip()
    if vdd is not None and load_pf is not None:
        text += f" Testbench: VDD = {vdd:g} V, load capacitance CL = {load_pf:g} pF."
    return text
