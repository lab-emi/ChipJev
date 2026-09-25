"""Monotonic worker phase measurements, including model loading, search and final simulation."""

import time


class RunTiming:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.started = self.entered = clock()
        self.phase = "startup"
        self.phases = {}

    def move(self, phase):
        now = self.clock()
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
