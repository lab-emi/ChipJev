/** A click-to-finish clock with server-measured, independently frozen phases. */
export class RunClock {
  constructor(now = () => performance.now()) {
    this.now = now;
    this.reset();
  }
  reset() {
    this.total = 0; this.running = false; this.phase = null;
    this.phases = {}; this.at = this.now();
  }
  start() { this.reset(); this.running = true; }
  sample() {
    const delta = this.running ? Math.max(0, (this.now() - this.at) / 1000) : 0;
    const phases = { ...this.phases };
    if (this.phase) phases[this.phase] = (phases[this.phase] || 0) + delta;
    return { total: this.total + delta, phases };
  }
  observe(event) {
    // Replayed events can be old. They update phase snapshots, never rewind the
    // total clock. A joined session starts at the server run's elapsed time.
    const current = this.sample();
    this.total = Math.max(current.total, event.elapsed || 0, event.demo_seconds || 0);
    this.phases = current.phases;
    this.at = this.now();
    if (event.timings_seconds) {
      this.phases = { ...event.timings_seconds };
      this.phase = event.timing_phase || null;
    }
  }
  stop() {
    const value = this.sample();
    this.total = value.total; this.phases = value.phases;
    this.running = false; this.phase = null; this.at = this.now();
  }
  resume() { this.at = this.now(); this.running = true; }
}
