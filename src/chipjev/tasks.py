"""AnalogCoder-Pro's twelve unified topology-generation-and-optimization tasks (ids 51-62).

tasks.json is the benchmark specification of both studies: {single-stage, multi-stage} x
{amplifier, op-amp} x {maximum gain, GBW, FoM}, 1.2 V and 100 pF on PTM 45 nm (the SKY130
study uses the same tasks at 1.8 V). It is byte-identical to the file that the frozen
protocols hashed as experiments/topo-v1/tasks-test.json. ``statement`` rebuilds
AnalogCoder-Pro's own task statements ("Design <Circuit>." from its problem_set.tsv), which
the typed decisions read in the paper's runs; they are recorded in
experiments/ptm45/protocol.json.
"""

import json
from pathlib import Path

CLASSES = ("amp1", "opamp1", "ampN", "opampN")
OBJECTIVES = ("gain", "gbw", "fom")
CLASS_TEXT = {
    "amp1": "single-stage amplifier",
    "opamp1": "single-stage opamp",
    "ampN": "multi-stage amplifier",
    "opampN": "multi-stage opamp",
}
OBJECTIVE_TEXT = {
    "gain": "voltage gain",
    "gbw": "Gain-Bandwidth Product (GBW)",
    "fom": "GBW/Power (FoM)",
}
# AnalogCoder-Pro's task id of each (class, objective).
ANALOGCODER_PRO_ID = {(c, o): 51 + 4 * OBJECTIVES.index(o) + CLASSES.index(c)
                      for c in CLASSES for o in OBJECTIVES}


def statement(cls, objective):
    """AnalogCoder-Pro's statement of the task for one class and objective."""
    return (f"Design a {CLASS_TEXT[cls]} topology that maximizes {OBJECTIVE_TEXT[objective]} "
            "(preventing positive feedback).")


def tasks():
    """The twelve tasks: id (e.g. "opampN-gbw"), cls, target, vdd, load_pf, AnalogCoder-Pro's
    task id and statement."""
    data = json.loads(Path(__file__).with_name("tasks.json").read_text())["tasks"]
    return [dict(t, acpro_id=ANALOGCODER_PRO_ID[(t["cls"], t["target"])],
                 statement=statement(t["cls"], t["target"])) for t in data]


def task(identifier):
    """One task by id ("opampN-gbw") or AnalogCoder-Pro task id (58)."""
    for t in tasks():
        if str(identifier) in (t["id"], str(t["acpro_id"])):
            return t
    raise KeyError(f"unknown task {identifier!r}; see `chipjev tasks`")
