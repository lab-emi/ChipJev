"""Public prompts are an allowlist; visitors cannot submit executable tool input.

Each example is a fixed SKY130 design task. ``stages``, ``min_mosfets`` and the optional
``first`` (input-stage families), ``polarity`` (input pair), ``later`` (second stages) and
``comp`` (compensation) are hard constraints on the topology grammar, applied to Laya's
prior like the stage count; ``seed`` fixes the search's random stream and ``headroom``
reserves nominal margin for the physical layout. Every entry was run end to end.
"""

# Nominal margin reserved before layout, per objective (post-layout checks stay strict).
GAIN_HEADROOM = {"gain_db": 1, "pm_deg": 2, "cmrr_db": 1}


def _example(id, name, title, cls, objective, prompt, *, stages, load_pf=100.0, seed=0,
             headroom=None, **constraints):
    return {"id": id, "name": name, "title": title, "cls": cls, "objective": objective,
            "stages": stages, **constraints, "vdd": 1.8, "load_pf": load_pf, "seed": seed,
            "headroom": headroom if headroom is not None else
            (GAIN_HEADROOM if objective == "gain" else {"gain_db": 1} if objective == "fom" else {}),
            "prompt": prompt}


_EXAMPLES = [
    _example("opamp-gain", "Two-stage op-amp", "13+ MOSFETs · maximum DC gain", "opampN", "gain",
             "Design a complex SKY130 two-stage op-amp with at least 13 MOSFETs and maximum DC gain, "
             "at 1.8 V with a 100 pF load.", stages=2, min_mosfets=13),
    _example("opamp-speed", "Wideband op-amp", "Maximum gain-bandwidth", "opampN", "gbw",
             "Design a SKY130 two-stage op-amp with maximum gain-bandwidth product, at 1.8 V with a "
             "100 pF load.", stages=2, seed=2),
    _example("ota-efficient", "Efficient single-stage OTA", "Bandwidth per unit power", "opamp1", "fom",
             "Design a SKY130 single-stage differential OTA that maximizes GBW times load capacitance "
             "per unit power, at 1.8 V with a 100 pF load.", stages=1, seed=2),
    _example("opamp-efficient", "Low-power two-stage op-amp", "Bandwidth per unit power", "opampN", "fom",
             "Design a SKY130 two-stage op-amp that maximizes GBW times load capacitance per unit power, "
             "at 1.8 V with a 100 pF load.", stages=2),
    _example("opamp-nulling", "Miller op-amp with nulling resistor", "Miller + nulling resistor · maximum GBW",
             "opampN", "gbw",
             "Design a SKY130 two-stage op-amp with Miller compensation and a nulling resistor, for maximum "
             "gain-bandwidth product, at 1.8 V with a 100 pF load.", stages=2, comp=["miller_rz"]),
    _example("opamp-pmos", "PMOS-input op-amp", "PMOS input pair · maximum DC gain", "opampN", "gain",
             "Design a SKY130 two-stage op-amp with a PMOS input pair and maximum DC gain, at 1.8 V with "
             "a 100 pF load.", stages=2, polarity="p"),
    _example("opamp-folded", "Folded-cascode two-stage op-amp", "Folded-cascode input · maximum DC gain",
             "opampN", "gain",
             "Design a SKY130 two-stage op-amp with a folded-cascode input stage and maximum DC gain, at "
             "1.8 V with a 100 pF load.", stages=2, first=["fc"], seed=1,
             # Its layout costs ~8-10 degrees of phase margin: reserve it in the search.
             headroom={"gain_db": 1, "pm_deg": 10, "cmrr_db": 1}),
    _example("opamp-10pf", "Fast op-amp for 10 pF", "Maximum gain-bandwidth · 10 pF", "opampN", "gbw",
             "Design a SKY130 two-stage op-amp with maximum gain-bandwidth product, at 1.8 V with a 10 pF "
             "load.", stages=2, load_pf=10.0),
    _example("opamp-2pf", "On-chip op-amp", "Maximum DC gain · 2 pF", "opampN", "gain",
             "Design a SKY130 two-stage op-amp for an on-chip 2 pF load with maximum DC gain, at 1.8 V.",
             stages=2, load_pf=2.0),
    _example("ota-gain", "High-gain single-stage OTA", "Maximum DC gain", "opamp1", "gain",
             "Design a SKY130 single-stage differential OTA with maximum DC gain, at 1.8 V with a 100 pF "
             "load.", stages=1),
    _example("ota-folded", "Folded-cascode OTA", "Folded cascode · maximum DC gain", "opamp1", "gain",
             "Design a SKY130 folded-cascode OTA with maximum DC gain, at 1.8 V with a 100 pF load.",
             stages=1, first=["fc"]),
    _example("ota-telescopic", "Telescopic cascode OTA", "Telescopic cascode · maximum DC gain", "opamp1",
             "gain", "Design a SKY130 telescopic-cascode OTA with maximum DC gain, at 1.8 V with a 100 pF "
             "load.", stages=1, first=["tele"], seed=3),
    _example("ota-5t", "Five-transistor OTA", "Classic 5T OTA · maximum GBW · 10 pF", "opamp1", "gbw",
             "Design a SKY130 five-transistor differential OTA with maximum gain-bandwidth product, at "
             "1.8 V with a 10 pF load.", stages=1, first=["ota5"], load_pf=10.0),
    _example("ota-mirror", "Current-mirror OTA", "Current-mirror OTA · maximum GBW", "opamp1", "gbw",
             "Design a SKY130 current-mirror OTA with maximum gain-bandwidth product, at 1.8 V with a "
             "100 pF load.", stages=1, first=["cmota"]),
    _example("ota-1pf", "Wideband OTA for 1 pF", "Maximum GBW · 1 pF", "opamp1", "gbw",
             "Design a SKY130 single-stage differential OTA with maximum gain-bandwidth product, at 1.8 V "
             "with a 1 pF load.", stages=1, load_pf=1.0),
    _example("ota-pmos-efficient", "Low-power PMOS-input OTA", "PMOS input · bandwidth per power · 10 pF",
             "opamp1", "fom",
             "Design a SKY130 single-stage OTA with a PMOS input pair that maximizes GBW times load "
             "capacitance per unit power, at 1.8 V with a 10 pF load.", stages=1, polarity="p",
             load_pf=10.0),
    _example("ota-nmos-gain", "NMOS-input OTA", "NMOS input pair · maximum DC gain", "opamp1", "gain",
             "Design a SKY130 single-stage OTA with an NMOS input pair and maximum DC gain, at 1.8 V with "
             "a 100 pF load.", stages=1, polarity="n"),
]
EXAMPLES = {e["id"]: e for e in _EXAMPLES}
DEFAULT_EXAMPLE = "opamp-gain"


def allows(example, topology):
    """The example's hard grammar constraints (the stage count is checked separately)."""
    first, _, polarity = topology.stages[0].rpartition("_")
    return ((not example.get("first") or first in example["first"])
            and (not example.get("polarity") or polarity == example["polarity"])
            and (not example.get("later") or topology.stages[1] in example["later"])
            and (not example.get("comp") or topology.comp in example["comp"]))


if __name__ == "__main__":
    import json

    from chipjev.paths import ROOT

    # The site shows exactly the server's allowlist.
    (ROOT / "website/examples.json").write_text(json.dumps(list(EXAMPLES.values()), indent=2) + "\n")
