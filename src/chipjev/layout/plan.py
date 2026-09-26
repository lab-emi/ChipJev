"""Immutable, bounded physical design choices. All choices are part of identity."""

import hashlib
import json
from dataclasses import asdict, dataclass, replace


@dataclass(frozen=True)
class LayoutPlan:
    pattern: str = "interdigitated"
    fingers_per_row: int = 12
    columns: int = 2
    split: int = 1
    rail_multiplier: int = 1
    dummies: bool = True
    shield_inputs: bool = False
    decap_pf: float = 0.0
    decap_location: str = "supply"

    def __post_init__(self):
        if type(self.dummies) is not bool or type(self.shield_inputs) is not bool:
            raise ValueError("Dummy and shield options must be booleans")
        if self.pattern not in ("interdigitated", "centroid", "clustered"):
            raise ValueError("Unsupported matching pattern")
        if self.fingers_per_row not in (8, 12, 20, 32) or self.columns not in (1, 2):
            raise ValueError("Unsupported floorplan")
        if self.split not in (1, 2) or self.rail_multiplier not in (1, 2, 3):
            raise ValueError("Unsupported device/rail sizing")
        if self.decap_pf not in (0.0, 2.0, 5.0) or self.decap_location not in ("supply", "output"):
            raise ValueError("Unsupported decap option")

    def to_dict(self):
        return asdict(self)

    @property
    def id(self):
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()[:16]

    def validate(self, builder, intent):
        for group in intent["groups"]:
            if len(group["members"]) != 2:
                continue
            width, _, nf = builder.geometry[group["members"][0]]
            if width / nf / self.split < 0.42:
                raise ValueError("Split would violate the minimum physical unit width")
            if self.pattern == "centroid" and (nf * self.split) % 2:
                raise ValueError("Centroid pattern requires even unit counts in every matched pair")

    def neighbors(self):
        for field, choices in {
            "pattern": ("interdigitated", "centroid", "clustered"),
            "fingers_per_row": (8, 12, 20, 32),
            "columns": (1, 2),
            "split": (1, 2),
            "rail_multiplier": (1, 2, 3),
            "dummies": (False, True),
            "shield_inputs": (False, True),
            "decap_pf": (0.0, 2.0, 5.0),
            "decap_location": ("supply", "output"),
        }.items():
            if field == "decap_location" and (not self.decap_pf or self.columns == 1):
                continue
            for value in choices:
                if value != getattr(self, field):
                    yield field, replace(self, **{field: value})

    def estimate(self, builder, intent):
        """Cheap floorplan proxy, never a reported physical area or acceptance gate.

        Uses the requested geometry and conservative access/channel allowances.
        Full PCell compilation and extraction remain authoritative.
        """
        domains = []
        for kind in ("n", "p"):
            rows, row_width, row_height = [], 0.0, 0.0
            for group in intent["groups"]:
                if group["kind"] != kind:
                    continue
                matched = len(group["members"]) == 2
                width, length, nf = builder.geometry[group["members"][0]]
                count = nf * (self.split if matched else 1)
                chunks = (
                    arrangement(
                        list(range(count)), list(range(count)), self.pattern, self.fingers_per_row
                    )
                    if matched
                    else [
                        list(range(i, min(i + self.fingers_per_row, count)))
                        for i in range(0, count, self.fingers_per_row)
                    ]
                )
                for chunk in chunks:
                    n = len(chunk) + (2 if matched and self.dummies else 0)
                    w = n * (length + 3.3)
                    h = width / count + 8 + 3 * self.rail_multiplier
                    if self.pattern == "centroid" or row_width + w > self.fingers_per_row * 4:
                        if row_width:
                            rows.append((row_width, row_height))
                        row_width, row_height = 0.0, 0.0
                    row_width += w
                    row_height = max(row_height, h)
                    if self.pattern == "centroid":
                        rows.append((row_width, row_height))
                        row_width, row_height = 0.0, 0.0
            if row_width:
                rows.append((row_width, row_height))
            if rows:
                domains.append((max(w for w, _ in rows) + 6, sum(h for _, h in rows) + 6))
        channel = len(intent["net_classes"]) * 2.4 + 6
        if self.columns == 1:
            width = max(w for w, _ in domains) + channel
            height = sum(h for _, h in domains) + 4
        else:
            width = sum(w + channel for w, _ in domains)
            height = max(h for _, h in domains) + 4 * len(intent["net_classes"])
        return {
            "area_um2_proxy": width * height + self.decap_pf * 600,
            "fidelity": "uncalibrated geometry proxy; excludes passive placement detail",
            "centroid_exact_by_construction": self.pattern == "centroid",
        }


def arrangement(a, b, pattern, per_row):
    """One-to-one unit mapping; exact 2-D centroid when that pattern is legal."""
    if len(a) != len(b):
        raise ValueError("Matched groups must have equal unit counts")
    if pattern == "centroid":
        if len(a) % 2:
            raise ValueError("Even unit count required")
        # Every 2x2 tile has identical A/B first spatial moments.
        top, bottom = [], []
        for i in range(0, len(a), 2):
            top += [a[i], b[i]]
            bottom += [b[i + 1], a[i + 1]]
        rows = []
        for start in range(0, len(top), per_row):
            rows += [top[start : start + per_row], bottom[start : start + per_row]]
        return rows
    flat = [*a, *b] if pattern == "clustered" else [n for pair in zip(a, b) for n in pair]
    return [flat[i : i + per_row] for i in range(0, len(flat), per_row)]
