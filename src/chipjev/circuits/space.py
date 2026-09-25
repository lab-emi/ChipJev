"""Joint topology x sizing space of one circuit class.

A design is (topology index, level vector over the class's role slots), with -1 for
slots the topology does not use. Features for the surrogate are grammar descriptors
(stage kinds, polarities, buffer, compensation) followed by normalized slot levels
(zero where inactive). Random candidates are generated directly on the accelerator.

Options (the defaults are the ChipJev search without typed decisions):

carry_sizes   True: topology mutations keep the levels of the role slots the two
              topologies share. False (ablation): mutated neighbours draw new sizes.
prior         probabilities over the class's topologies (typed decisions); uniform and
              device-side random candidates draw their topology from it (sizes stay
              uniform). None: uniform.
roles=False   (ablation) each topology writes its slot levels to a fixed topology-specific
              permutation of its active slot columns. Dimensions and within-topology
              information are unchanged, but a feature column no longer means the same role
              in different topologies, so the surrogate cannot share sizing knowledge across
              topologies. Mutations still carry sizes by role; only the representation
              changes.
"""

import hashlib

import numpy as np

from .grammar import (
    DIFF_STAGES,
    SE_STAGES,
    SYMMETRIC,
    level_count,
    library,
    slot_kind,
    value_of,
)

COMPS = ("none", "miller", "miller_rz", "miller2")
STEPS = (-8.0, -4.0, -2.0, -1.0, 1.0, 2.0, 4.0, 8.0)  # multi-scale local moves (levels)


def _kind_pol(stage):
    if stage in SYMMETRIC:
        return stage, 0.5
    kind, pol = stage.rsplit("_", 1)
    return kind, 0.0 if pol == "n" else 1.0


class ClassSpace:
    def __init__(self, cls, topologies=None, carry_sizes=True, prior=None, roles=True):
        self.cls = cls
        self.topologies = tuple(topologies or library(cls))
        self.index = {t.id: i for i, t in enumerate(self.topologies)}
        slots = []
        for t in self.topologies:
            for s in t.slots():
                if s not in slots:
                    slots.append(s)
        self.slots = tuple(sorted(slots, key=_slot_order))
        self.slot_index = {s: j for j, s in enumerate(self.slots)}
        self.levels = np.array([level_count(s) for s in self.slots], dtype=np.int64)
        self.active = np.zeros((len(self.topologies), len(self.slots)), dtype=bool)
        for i, t in enumerate(self.topologies):
            for s in t.slots():
                self.active[i, self.slot_index[s]] = True
        self.positions = max(len(t.stages) for t in self.topologies)
        self.differential = self.topologies[0].differential
        self._build_descriptors()
        self.dimension = self.descriptors.shape[1] + len(self.slots)
        self._device_tables = {}
        self.carry_sizes = carry_sizes
        self.roles = roles
        self.prior = None
        if prior is not None:
            prior = np.asarray(prior, dtype=float)
            if prior.shape != (len(self.topologies),) or not np.all(prior >= 0):
                raise ValueError("prior must be a distribution over the class's topologies")
            self.prior = prior / prior.sum()
        # gather[i, c]: canonical slot whose level feature column c holds for topology i.
        self.gather = np.tile(np.arange(len(self.slots)), (len(self.topologies), 1))
        if not roles:
            for i, topology in enumerate(self.topologies):
                active = np.nonzero(self.active[i])[0]
                seed = int(hashlib.sha256(topology.id.encode()).hexdigest()[:8], 16)
                self.gather[i, active] = np.random.default_rng(seed).permutation(active)

    # -- descriptors ------------------------------------------------------------------
    def _build_descriptors(self):
        kinds = []
        for k in range(self.positions):
            table = DIFF_STAGES if (k == 0 and self.differential) else SE_STAGES
            names = sorted(
                {_kind_pol(t.stages[k])[0] for t in self.topologies if len(t.stages) > k}
                & set(table)
            )
            kinds.append(names)
        self.kinds = kinds
        buffers = sorted({t.buffer for t in self.topologies})
        comps = [c for c in COMPS if any(t.comp == c for t in self.topologies)]
        self.buffers, self.comps = buffers, comps
        columns = []
        for k, names in enumerate(kinds):
            if k > 0 and any(len(t.stages) <= k for t in self.topologies):
                columns.append(f"s{k + 1}:present")
            columns += [f"s{k + 1}:{n}" for n in names]
            columns.append(f"s{k + 1}:pol")
        if len(buffers) > 1:
            columns += [f"buf:{b}" for b in buffers if b != "none"]
        if len(comps) > 1:
            columns += [f"comp:{c}" for c in comps if c != "none"]
        self.descriptor_names = tuple(columns)
        col = {c: j for j, c in enumerate(columns)}
        d = np.zeros((len(self.topologies), len(columns)), dtype=np.float32)
        for i, t in enumerate(self.topologies):
            for k, stage in enumerate(t.stages):
                kind, pol = _kind_pol(stage)
                d[i, col[f"s{k + 1}:{kind}"]] = 1.0
                d[i, col[f"s{k + 1}:pol"]] = pol
                if f"s{k + 1}:present" in col:
                    d[i, col[f"s{k + 1}:present"]] = 1.0
            if t.buffer != "none" and f"buf:{t.buffer}" in col:
                d[i, col[f"buf:{t.buffer}"]] = 1.0
            if t.comp != "none" and f"comp:{t.comp}" in col:
                d[i, col[f"comp:{t.comp}"]] = 1.0
        self.descriptors = d

    # -- designs ----------------------------------------------------------------------
    def canonical(self, topology_id, levels=None):
        """Design for a topology id with mid-grid levels (or given slot->level dict)."""
        i = self.index[topology_id]
        vec = np.full(len(self.slots), -1, dtype=np.int64)
        for j in np.nonzero(self.active[i])[0]:
            vec[j] = self.levels[j] // 2
        for slot, level in (levels or {}).items():
            vec[self.slot_index[slot]] = level
        return (i, tuple(int(x) for x in vec))

    def values(self, design):
        i, vec = design
        return {s: value_of(s, vec[j]) for j, s in enumerate(self.slots) if self.active[i, j]}

    def topology(self, design):
        return self.topologies[design[0]]

    def features(self, designs):
        """[N, dimension] float32 features on the host."""
        t = np.array([d[0] for d in designs], dtype=np.int64)
        lv = np.array([d[1] for d in designs], dtype=np.float32)
        norm = np.where(lv >= 0, lv / (self.levels - 1), 0.0).astype(np.float32)
        if not self.roles:
            norm = np.take_along_axis(norm, self.gather[t], axis=1)
        return np.concatenate([self.descriptors[t], norm], axis=1)

    def random(self, rng, n):
        if self.prior is None:
            t = rng.integers(len(self.topologies), size=n)
        else:
            t = rng.choice(len(self.topologies), size=n, p=self.prior)
        lv = (rng.random((n, len(self.slots))) * self.levels).astype(np.int64)
        lv = np.where(self.active[t], lv, -1)
        return [(int(a), tuple(int(x) for x in row)) for a, row in zip(t, lv, strict=True)]

    def neighbors(self, design, rng, perturb=64, mutations=2):
        """Local moves: every single-slot step of 1 or 4 levels, random multi-slot steps,
        and topology mutations that keep shared role-slot levels (with carry_sizes=False,
        mutated neighbours draw new sizes instead)."""
        i, vec = design
        vec = np.array(vec, dtype=np.int64)
        out = []
        act = np.nonzero(self.active[i])[0]
        for j in act:
            for step in (-4, -1, 1, 4):
                v = vec.copy()
                v[j] += step
                if 0 <= v[j] < self.levels[j]:
                    out.append((i, tuple(int(x) for x in v)))
        for _ in range(perturb):
            v = vec.copy()
            chosen = rng.choice(act, size=min(len(act), int(rng.integers(2, 5))), replace=False)
            for j in chosen:
                v[j] = int(np.clip(v[j] + rng.choice(STEPS), 0, self.levels[j] - 1))
            out.append((i, tuple(int(x) for x in v)))
        for other in self.mutations(i):
            for _ in range(mutations):
                v = np.full(len(self.slots), -1, dtype=np.int64)
                for j in np.nonzero(self.active[other])[0]:
                    v[j] = vec[j] if vec[j] >= 0 else int(rng.integers(self.levels[j]))
                out.append((other, tuple(int(x) for x in v)))
        if self.carry_sizes:
            return out
        reset = []
        for index, levels in out:
            if index != i:
                values = np.full(len(self.slots), -1, dtype=np.int64)
                for j in np.nonzero(self.active[index])[0]:
                    values[j] = int(rng.integers(self.levels[j]))
                levels = tuple(int(v) for v in values)
            reset.append((index, levels))
        return reset

    def mutations(self, i):
        """Topologies differing from topology i in exactly one grammar choice: one stage,
        the buffer or the compensation, or one stage appended/removed at the end."""
        if not hasattr(self, "_mutations"):
            self._mutations = {}
        if i not in self._mutations:
            a = self.topologies[i]
            result = []
            for j, b in enumerate(self.topologies):
                if j == i:
                    continue
                if len(a.stages) == len(b.stages):
                    diff = sum(x != y for x, y in zip(a.stages, b.stages, strict=True))
                    diff += (a.buffer != b.buffer) + (a.comp != b.comp)
                    if diff == 1:
                        result.append(j)
                elif abs(len(a.stages) - len(b.stages)) == 1:
                    short, long_ = (a, b) if len(a.stages) < len(b.stages) else (b, a)
                    if (
                        long_.stages[:-1] == short.stages
                        and long_.buffer == short.buffer
                        and long_.comp == short.comp
                    ):
                        result.append(j)
            self._mutations[i] = result
        return self._mutations[i]

    # -- accelerator-side random candidates ---------------------------------------------
    def device_tables(self, device, dtype):
        import torch

        key = (str(device), dtype)
        if key not in self._device_tables:
            self._device_tables[key] = (
                torch.as_tensor(self.descriptors, device=device, dtype=dtype),
                torch.as_tensor(self.active, device=device),
                torch.as_tensor(self.levels, device=device, dtype=dtype),
            )
        return self._device_tables[key]

    def perturb_on_device(
        self, topologies, levels, count, generator, device, dtype, jump=0.5, changes=(4,)
    ):
        """`count` perturbations of each incumbent (topology ids [K], levels [K,S]) on the
        device. Each candidate draws an expected number of changed slots c from `changes`
        and changes each active slot with probability min(1, c/active); a change is a
        step of +/-1, 2, 4 or 8 levels (multi-scale), or (probability `jump`) a uniformly
        drawn level."""
        import torch

        desc, active, lv_max = self.device_tables(device, dtype)
        t = torch.as_tensor(topologies, device=device).repeat_interleave(count)
        lv = torch.as_tensor(levels, device=device, dtype=dtype).repeat_interleave(count, 0)
        mask = active[t]
        n = mask.sum(1, keepdim=True).clamp_min(1).to(dtype)
        shape = (len(t), len(self.slots))
        choices = torch.tensor(changes, device=device, dtype=dtype)
        expected = choices[
            torch.randint(len(changes), (len(t), 1), device=device, generator=generator)
        ]
        change = torch.rand(shape, device=device, generator=generator, dtype=dtype) < expected / n
        change &= mask
        # Every candidate changes at least one slot (a copy of the incumbent is wasted).
        pick = torch.rand(shape, device=device, generator=generator, dtype=dtype)
        pick = pick.masked_fill(~mask, -1.0).argmax(1, keepdim=True)
        forced = torch.zeros_like(change).scatter_(1, pick, True)
        change = torch.where(change.any(1, keepdim=True), change, forced)
        steps = torch.tensor(STEPS, device=device, dtype=dtype)
        step = steps[torch.randint(len(STEPS), shape, device=device, generator=generator)]
        uniform = torch.floor(
            torch.rand(shape, device=device, generator=generator, dtype=dtype) * lv_max
        ).clamp_max(lv_max - 1)
        jumped = torch.rand(shape, device=device, generator=generator, dtype=dtype) < jump
        moved = torch.where(
            jumped, uniform, torch.minimum(torch.clamp(lv + step, min=0), lv_max - 1)
        )
        lv = torch.where(change, moved, lv)
        if not self.roles:
            return self._reencode(t, lv, device, dtype), t, lv
        norm = torch.where(mask, lv / (lv_max - 1), torch.zeros_like(lv))
        return torch.cat([desc[t], norm], dim=1), t, lv

    def random_on_device(self, count, generator, device, dtype):
        """(features [N,D], topology [N], levels [N,S]) sampled on the device: topologies
        uniformly or from the prior, levels uniformly."""
        import torch

        desc, active, levels = self.device_tables(device, dtype)
        if self.prior is None:
            t = torch.randint(len(self.topologies), (count,), device=device, generator=generator)
        else:
            key = ("prior", str(device))
            if key not in self._device_tables:
                self._device_tables[key] = torch.as_tensor(
                    self.prior, device=device, dtype=torch.float32
                )
            t = torch.multinomial(
                self._device_tables[key], count, replacement=True, generator=generator
            )
        u = torch.rand((count, len(self.slots)), device=device, generator=generator, dtype=dtype)
        lv = torch.floor(u * levels).clamp_max(levels - 1)
        mask = active[t]
        lv = torch.where(mask, lv, torch.full_like(lv, -1))
        return self._reencode(t, lv, device, dtype), t, lv

    def _device_gather(self, device):
        import torch

        key = ("gather", str(device))
        if key not in self._device_tables:
            self._device_tables[key] = torch.as_tensor(self.gather, device=device)
        return self._device_tables[key]

    def _reencode(self, t, lv, device, dtype):
        """Features [N, D] of device-side designs under this space's representation."""
        import torch

        desc, active, lv_max = self.device_tables(device, dtype)
        mask = active[t]
        norm = torch.where(mask, lv / (lv_max - 1), torch.zeros_like(lv))
        if not self.roles:
            norm = torch.gather(norm, 1, self._device_gather(device)[t])
        return torch.cat([desc[t], norm], dim=1)


def _slot_order(slot):
    stage, name = slot.split(".", 1)
    order = {"b": 8, "c": 9}.get(stage)
    return (order if order is not None else int(stage), slot_kind(slot), name)
