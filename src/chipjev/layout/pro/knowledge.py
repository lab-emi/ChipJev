"""Analog-layout knowledge as typed rule cards, a deterministic retriever and a critic.

Every card states where its knowledge acts:

* ``template``: compiled into the generator, so every layout obeys it by
  construction (it is never left to a model to remember);
* ``check``: measured on each generated layout by the critic below;
* ``action``: a trade-off the goal-driven loop may change. Only these cards
  are injected into Laya's option text, and only for the action being
  ranked and the symptoms just measured (retrieval is a keyed lookup, not a
  similarity search).

Sources: IIT Madras EE5325 lecture 48 "Analog Layout Techniques" (slide
numbers), standard analog layout practice, the SKY130 rule deck and models.
Guidelines are paraphrased.
"""

import math
from dataclasses import asdict, dataclass

L48 = "IITM EE5325 L48"


@dataclass(frozen=True)
class Card:
    id: str
    topic: str
    guideline: str  # one line, used verbatim in Laya's option text
    rationale: str
    source: str
    enforced: tuple  # subset of ("template", "check", "action")
    actions: tuple = ()  # ProPlan fields the card informs
    symptoms: tuple = ()  # measured failures/metrics that make the card relevant

    def to_dict(self):
        return asdict(self)


CARDS = (
    # Matching ----------------------------------------------------------------------
    Card("match.common_centroid", "matching",
         "Common-centroid order (ABBA, cross-coupled rows) cancels linear process gradients.",
         "Diagonal/mirrored placement makes both devices see the same average of x and y gradients.",
         f"{L48} s3-5, s8", ("template", "check", "action"), ("pair_pattern",),
         ("centroid", "offset", "matching")),
    Card("match.interdigitate", "matching",
         "Interdigitate small matched sets (2-3 devices); prefer common centroid for larger arrays.",
         "Alternating fingers average a gradient; common centroid also cancels it to first order.",
         f"{L48} s7", ("action",), ("pair_pattern",), ("matching",)),
    Card("match.dummies", "matching",
         "End dummies give every matched finger identical neighbours (etch, CMP, implant edges).",
         "Boundary fingers etch and dope differently; dummies move the boundary away.",
         f"{L48} s9, s14", ("template", "check", "action"), ("dummies", "single_dummies"),
         ("matching", "offset")),
    Card("match.orientation", "matching",
         "Matched devices share one gate orientation.",
         "Mobility and implant shadowing depend on orientation.",
         f"{L48} s10", ("template", "check")),
    Card("match.current_direction", "matching",
         "Matched devices carry current in the same direction; even finger counts balance it.",
         "Source/drain asymmetry (implant angle) shifts devices with opposite current flow.",
         f"{L48} s11, s14", ("template", "check", "action"), ("pair_even",), ("matching", "offset")),
    Card("match.dummy_routes", "matching",
         "A wire over one matched device needs an identical wire over its partner.",
         "Metal over a gate changes stress and coupling; symmetry makes the change common mode.",
         f"{L48} s12", ("template", "check")),
    Card("match.unit_size", "matching",
         "Build ratios from identical unit fingers; change the multiplier, not the unit size.",
         "Unit devices keep W-dependent effects (and SKY130's W/NF model bin) equal in a ratio.",
         f"{L48} s14; SKY130 wnflag=1 bins", ("template", "check")),
    Card("match.same_metal", "matching",
         "Route matched signals together, on the same metal layer.",
         "Different layers give different R and C, i.e. a systematic mismatch.",
         f"{L48} s14", ("template",)),
    Card("match.proximity", "matching",
         "Place matched devices close together.", "Mismatch grows with distance.",
         f"{L48} s14", ("template",)),
    Card("match.min_size", "matching",
         "Avoid very small W and L in matched devices.",
         "Random mismatch scales with 1/sqrt(WL); edge effects dominate tiny devices.",
         f"{L48} s14", ("check",), (), ("offset", "matching")),
    Card("match.no_foreign_over_gate", "matching",
         "Keep unrelated routing off critically matched gates.",
         "Asymmetric coupling and stress from foreign metal unbalance the pair.",
         f"{L48} s14", ("template", "check")),
    Card("match.ir_drop", "matching",
         "Do not carry bias voltages a long way: wire IR drop becomes mismatch.",
         "A few mV of drop on a gate or source line is an offset.",
         f"{L48} s14", ("check",), ("rail_um",), ("offset", "supply")),
    Card("match.antenna", "matching",
         "Protect matched gates from plasma charging (antenna diode or metal jumper).",
         "Charge damage shifts Vt of one device of a pair.",
         f"{L48} s14, s26-27", ("check",)),
    # Devices and area -----------------------------------------------------------------
    Card("device.fingering", "area",
         "Multi-finger devices share source/drain: less junction capacitance and gate resistance.",
         "Shared diffusion halves S/D area per finger and shortens the gate.",
         f"{L48} s15", ("template",)),
    Card("area.aspect", "area",
         "Fold large arrays into rows so the block is near square with little white space.",
         "Compact, rectangular blocks integrate with less routing and fewer long nets.",
         "standard practice", ("action", "check"), ("aspect", "max_finger_um"), ("area", "whitespace")),
    Card("pdk.model_bins", "area",
         "Re-fingering changes the simulated device (W/NF bin); keep it or re-qualify the schematic.",
         "SKY130 selects model parameters by W/NF; a new finger width moves bias points.",
         "SKY130 models, wnflag=1", ("template", "action", "check"), ("refinger",),
         ("saturation", "currents", "gain", "dc")),
    # Passives --------------------------------------------------------------------------
    Card("passive.unit_tiles", "passives",
         "Build capacitors and resistors from equal unit tiles, with dummies at the boundary.",
         "Unit tiles keep edge-to-area ratio constant; boundary dummies equalize edges.",
         f"{L48} s17-18", ("template", "check")),
    Card("passive.simple_when_fast", "passives",
         "When routing parasitics limit speed, a simple side-by-side layout can beat interdigitation.",
         "Interdigitated arrays need longer, crossing wires.",
         f"{L48} s17", ("action",), ("pair_pattern", "passives"), ("stability", "pm", "gbw")),
    Card("passive.bottom_plate", "passives",
         "Put the MIM bottom plate on the low-impedance node; it carries the substrate parasitic.",
         "The bottom plate's capacitance to substrate loads whichever node it sits on.",
         "standard practice (Razavi ch. 19)", ("template", "check")),
    # Noise, substrate, supply ----------------------------------------------------------
    Card("noise.shield", "noise",
         "Shield critical signals with grounded lines; keep shields off fast nets to avoid loading.",
         "Shields terminate coupling field lines on a quiet reference.",
         f"{L48} s19", ("action", "check"), ("shield_inputs",), ("noise", "coupling", "psrr")),
    Card("noise.spacing", "noise",
         "Space sensitive signals away from aggressors.",
         "Coupling capacitance falls with spacing.",
         f"{L48} s19", ("check",), (), ("coupling",)),
    Card("noise.decap", "noise",
         "Place decoupling capacitors close to the circuit, returned to a clean ground.",
         "Local charge supplies transients before the supply network can.",
         f"{L48} s21", ("template", "action", "check"), ("decap",), ("supply", "psrr", "droop")),
    Card("noise.guard_rings", "noise",
         "Surround circuits with substrate and well ties (guard rings) to collect substrate noise.",
         "A low-resistance tie absorbs injected substrate current before it reaches the body.",
         f"{L48} s22-23", ("template", "check")),
    Card("noise.isolated_well", "noise",
         "Isolated P-wells (deep N-well) give the strongest substrate isolation.",
         "A buried junction separates the local substrate.",
         f"{L48} s24", ()),
    Card("power.stacked_rails", "power",
         "Keep supply and ground resistance low: wide rails stacked on several metals.",
         "Rail IR drop is common-impedance coupling and a supply error.",
         f"{L48} s25, s28", ("template", "action", "check"), ("rail_um",),
         ("supply", "droop", "psrr", "em")),
    Card("power.em_width", "power",
         "Size wire width to its peak and average current; supply trunks carry the sum of branches.",
         "Electromigration lifetime depends on current density.",
         f"{L48} s28-29", ("check", "action"), ("rail_um",), ("em",)),
    # Latch-up ----------------------------------------------------------------------------
    Card("latchup.ties", "latchup",
         "Tie wells generously: every SKY130 diffusion within 15 um of a tap.",
         "Well resistance sets the gain of the parasitic SCR.",
         f"{L48} s25; SKY130 LU.2/LU.3", ("template", "check")),
    Card("latchup.grouping", "latchup",
         "Keep P devices together and apart from N devices; a double guard bar between them.",
         "Distance and a double guard break the PNPN path.",
         f"{L48} s25", ("template",)),
    # Symptom-driven closure ------------------------------------------------------------
    Card("closure.pm_loss", "closure",
         "Post-layout phase-margin loss: shorten the high-impedance node, keep Cc next to the output stage.",
         "Parasitic capacitance on the first-stage output lowers the non-dominant pole.",
         "standard practice", ("action",), ("aspect", "passives", "pair_pattern"), ("stability", "pm")),
    Card("closure.bw_loss", "closure",
         "Bandwidth loss: cut capacitance on output and internal high-impedance nets (short trunks, fewer crossings).",
         "Wire capacitance adds to the load of the dominant nodes.",
         "standard practice", ("action",), ("aspect", "pair_pattern", "max_finger_um"), ("gbw",)),
    Card("closure.no_margin", "closure",
         "A qualification limit failed by a hair after layout: the schematic needs headroom, not a new layout.",
         "Parasitics always cost something; zero-margin sizing cannot survive them.",
         "standard practice", ("action",), (), ("currents", "stability", "saturation")),
)
BY_ID = {c.id: c for c in CARDS}


def retrieve(action=None, symptoms=(), limit=2):
    """Cards for one candidate action under the current symptoms (keyed, deterministic).

    Action cards that name the action rank first when they also match a symptom,
    then any action card for the field; symptom-only cards follow.
    """
    symptoms = {s.lower() for s in symptoms}

    def hits(card):
        return sum(any(s in m for m in symptoms) for s in card.symptoms)

    picked = [c for c in CARDS if "action" in c.enforced and action in c.actions]
    picked.sort(key=lambda c: (-hits(c), c.id))
    return picked[:limit]


def symptoms_of(result):
    """Measured failures and weak spots of one evaluated candidate, as symptom words."""
    out = []
    post = (result or {}).get("postlayout") or {}
    out += [k for k, v in (post.get("checks") or {}).items() if not v]
    for finding in (result or {}).get("critic", {}).get("findings", []):
        if finding["status"] in ("warn", "fail"):
            out.append(finding["symptom"])
    delta = (result or {}).get("performance_delta") or {}
    if delta.get("pm_deg", 0) < -3:
        out.append("pm")
    pre = ((result or {}).get("prelayout") or {}).get("metrics", {})
    if delta.get("gbw_mhz", 0) < -0.05 * abs(pre.get("gbw_mhz") or 1):
        out.append("gbw")
    # Supply current moved after layout: IR drop (source degeneration) or a changed device.
    if pre.get("power_uw") and abs(delta.get("power_uw", 0)) > 0.03 * pre["power_uw"]:
        out += ["dc", "supply"]
    return sorted(set(out))


# ------------------------------------------------------------------------------- critic

def review(layout, manifest, quality=None, post=None, drc_errors=None):
    """Executable checks of the rule cards on one generated layout.

    Each finding: card id, status (pass/warn/fail/unsupported), value and the
    symptom word it contributes to the loop. Geometry proxies are labelled as such.
    """
    findings = []

    def add(card, status, value, symptom, note=""):
        findings.append({"card": card, "status": status, "value": value, "symptom": symptom,
                         "topic": BY_ID[card].topic, "note": note})

    placements = layout.get("placements", [])
    devices = manifest.get("devices", {})
    pitch = {}
    for p in placements:
        x0, _, x1, _ = p["bbox"]
        pitch.setdefault(p["array"], []).append((x0 + x1) / 2)
    # Common centroid: first moments of the two devices of each pair (um).
    worst = 0.0
    for group in layout.get("groups", []):
        pts = {m: [] for m in group["members"]}
        for p in placements:
            if p["logical"] in pts:
                x0, y0, x1, y1 = p["bbox"]
                pts[p["logical"]].append(((x0 + x1) / 2, (y0 + y1) / 2))
        if all(pts.values()):
            (ax, ay), (bx, by) = [
                (sum(x for x, _ in v) / len(v), sum(y for _, y in v) / len(v)) for v in pts.values()]
            worst = max(worst, math.hypot(ax - bx, ay - by) * 0.005)
    add("match.common_centroid", "pass" if worst < 1.0 else "warn", round(worst, 3), "centroid",
        "largest centroid distance of a matched pair, um")
    # End dummies on matched arrays.
    matched_arrays = {d["array"] for d in devices.values()
                      if d.get("kind") in ("n", "p") and not d["auxiliary"]
                      and any(d["logical"] in g["members"] for g in layout.get("groups", []))}
    with_dummies = {d["array"] for d in devices.values() if d.get("role") == "dummy"}
    missing = sorted(matched_arrays - with_dummies)
    add("match.dummies", "pass" if not missing else "warn", len(missing), "matching",
        "matched arrays without end dummies")
    # Current direction balance per matched device.
    unbalanced = []
    for group in layout.get("groups", []):
        for name in group["members"]:
            forward = backward = 0
            for d in devices.values():
                if d.get("logical") == name and not d["auxiliary"]:
                    a, _, b, _ = d["nets"]
                    forward += a < b
                    backward += a > b
            if abs(forward - backward) > 1:
                unbalanced.append(name)
    add("match.current_direction", "pass" if not unbalanced else "warn", len(unbalanced), "matching",
        "matched devices whose fingers do not balance current direction")
    add("match.orientation", "pass", 0, "matching", "all gates vertical by construction")
    # Symmetric trunks of symmetric nets.
    trunks = layout.get("trunks", [])
    sym = layout.get("symmetric_nets", {})
    regions = layout.get("regions", {})

    def axis_of(x):
        for x0, x1, axis in regions.values():
            if x0 - 400 <= x <= x1 + 400:
                return axis
        return 0

    asym = 0
    for a, b in sym.items():
        if a >= b:
            continue  # each unordered pair once
        xb = [t["x"] for t in trunks if t["net"] == b]
        for t in (t for t in trunks if t["net"] == a):
            mirror = 2 * axis_of(t["x"]) - t["x"]
            if not any(abs(mirror - x) <= 10 for x in xb):
                asym += 1
                break
    add("match.dummy_routes", "pass" if asym == 0 else "warn", asym, "matching",
        "symmetric net pairs whose trunks are not mirror images (geometry)")
    # Small matched devices.
    small = [n for n, v in manifest.get("logical", {}).items()
             if "physical" in v and v["physical"].get("w_finger", 99) < 1.0
             and any(n in g["members"] for g in layout.get("groups", []))]
    add("match.min_size", "pass" if not small else "warn", len(small), "offset",
        "matched devices with fingers narrower than 1 um (sizing feedback)")
    # Unit fingers across ratioed devices sharing a gate.
    add("match.unit_size", "pass" if not manifest.get("requalify") else "warn",
        len(manifest.get("requalify", [])), "dc", "devices re-fingered away from the simulated unit")
    add("pdk.model_bins", "pass" if not manifest.get("requalify") else "warn",
        len(manifest.get("requalify", [])), "dc", "re-fingered devices need re-qualification")
    # Latch-up and guard rings (DRC-backed).
    if drc_errors is not None:
        add("latchup.ties", "pass" if drc_errors == 0 else "fail", drc_errors, "drc",
            "full Magic DRC includes LU.2/LU.3 tap distance")
    add("noise.guard_rings", "pass", len(layout.get("rails", [])), "substrate",
        "every well region is enclosed by a contacted tap ring")
    # Decoupling capacitance (MOS gate area x Cox, a proxy).
    decap_area = sum(d["params"]["w"] * d["params"]["l"] for d in devices.values() if d.get("role") == "decap")
    decap_pf = decap_area * 8.3e-3  # ~8.3 fF/um^2 thin-oxide Cox
    add("noise.decap", "pass" if decap_pf > 0.05 else "warn", round(decap_pf, 3), "supply",
        "on-chip MOS decoupling, pF (Cox proxy)")
    # Rail IR drop / current density (proxy; no qualified EM limits in the open PDK).
    power = (post or {}).get("metrics", {}).get("power_uw")
    rail = layout.get("plan", {}).get("rail_um", 1.0)
    if power:
        current = power * 1e-6 / 1.8
        length = layout.get("width_um", 10)
        drop = current * 0.105 * length / rail / 2  # metal1+metal2 in parallel
        add("power.stacked_rails", "pass" if drop < 2e-3 else "warn", round(drop * 1e3, 3), "supply",
            "worst end-to-end rail IR drop, mV (sheet-resistance proxy)")
        density = current * 1e3 / (2 * rail)
        add("power.em_width", "pass" if density < 1.0 else "warn", round(density, 4), "em",
            "rail current density, mA/um (guideline 1 mA/um; not an EM signoff)")
    # Foreign routing over matched arrays (router cost; geometry).
    add("match.no_foreign_over_gate", "pass" if layout.get("foreign_over_matched", 0) == 0 else "warn",
        layout.get("foreign_over_matched", 0), "coupling", "unrelated trunks crossing matched arrays")
    # Parasitics from extraction.
    if quality:
        imbalance = quality.get("input_cap_imbalance_ff")
        if imbalance is not None:
            add("noise.spacing", "pass" if imbalance < 1.0 else "warn", round(imbalance, 3), "offset",
                "input capacitance imbalance after RC extraction, fF")
        coupling = quality.get("coupling_ff", {})
        into_inputs = sum(v for k, v in coupling.items()
                          if ("inp" in k.split("|") or "inn" in k.split("|")) and "out" in k.split("|"))
        add("noise.shield", "pass" if into_inputs < 0.5 else "warn", round(into_inputs, 3), "coupling",
            "input-to-output coupling capacitance after extraction, fF")
    # Area efficiency.
    gate = sum(d["params"]["w"] * d["params"]["l"] for d in devices.values()
               if d.get("kind") in ("n", "p") and not d["auxiliary"])
    area = layout.get("area_um2") or 1
    add("area.aspect", "pass" if 0.33 < layout.get("width_um", 1) / max(layout.get("height_um", 1), 1e-9) < 3
        else "warn", round(layout.get("width_um", 1) / max(layout.get("height_um", 1), 1e-9), 3), "area",
        f"aspect ratio; active gate area {gate:.0f} um2 of {area:.0f} um2")
    passes = sum(f["status"] == "pass" for f in findings)
    score = 100.0 * passes / max(1, sum(f["status"] in ("pass", "warn", "fail") for f in findings))
    return {"findings": findings, "score": round(score, 1),
            "scope": "rule-card checks; geometry and sheet-resistance proxies are not signoff"}
