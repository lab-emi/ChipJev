"""Public prompts are an allowlist; visitors cannot submit executable tool input."""

EXAMPLES = {
    "opamp-gain": {
        "id": "opamp-gain", "title": "Two-stage · high gain", "cls": "opampN",
        "objective": "gain", "stages": 2, "min_mosfets": 13, "vdd": 1.8, "load_pf": 100.0,
        "prompt": "Design a complex SKY130 two-stage op-amp with at least 13 MOSFETs and maximum DC gain, at 1.8 V with a 100 pF load.",
    },
    "opamp-speed": {
        "id": "opamp-speed", "title": "Two-stage · wide bandwidth", "cls": "opampN",
        "objective": "gbw", "stages": 2, "vdd": 1.8, "load_pf": 100.0,
        "prompt": "Design a SKY130 two-stage op-amp with maximum gain-bandwidth product, at 1.8 V with a 100 pF load.",
    },
    "ota-efficient": {
        "id": "ota-efficient", "title": "Single-stage · power efficiency", "cls": "opamp1",
        "objective": "fom", "stages": 1, "vdd": 1.8, "load_pf": 100.0,
        "prompt": "Design a SKY130 single-stage differential OTA that maximizes GBW times load capacitance per unit power, at 1.8 V with a 100 pF load.",
    },
}
DEFAULT_EXAMPLE = "opamp-gain"
