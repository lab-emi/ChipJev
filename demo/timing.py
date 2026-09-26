"""Monotonic worker phase measurements, including model loading, search and final simulation."""

import time


class RunTiming:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.started = self.entered = clock()
        self.phase = "startup"
        self.phases = {}

    def move(self, phase, at=None):
        # ``at``: when the change actually happened on the same monotonic clock,
        # e.g. measured by a layout worker process whose report arrived later.
        now = self.clock() if at is None else min(max(at, self.entered), self.clock())
        if phase != self.phase:
            if self.phase:
                self.phases[self.phase] = self.phases.get(self.phase, 0) + now - self.entered
            self.phase, self.entered = phase, now

    def snapshot(self):
        now = self.clock()
        phases = dict(self.phases)
        if self.phase:
            phases[self.phase] = phases.get(self.phase, 0) + now - self.entered
        return {"timings_seconds": phases, "timing_phase": self.phase,
                "demo_seconds": sum(phases.values())}
