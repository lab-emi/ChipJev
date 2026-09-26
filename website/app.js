import { RunClock } from "./run-clock.mjs";
const $ = (id) => document.getElementById(id);
const runButton = $("run");
const stageNames = ["deciding", "searching", "netlisting", "simulating", "layout", "extracting", "postsimulating", "checking"];
const clock = new RunClock();
let examples = [];
let api, socket, runId, lastEvent = 0, frameURL, reconnects = 0, running = false;
let timer, result, finished = false, expanded = false;
const runKey = "chipjev-live-run-v3";
let layoutURL, intentURL;

function saveRun(value) {
  try { value ? sessionStorage.setItem(runKey, value) : sessionStorage.removeItem(runKey); } catch { /* Storage is optional. */ }
}
function readRun() { try { return sessionStorage.getItem(runKey); } catch { return null; } }
function button(label, disabled = false) { runButton.querySelector("span").textContent = label; runButton.disabled = disabled; }
function error(message) { $("error").textContent = message; $("error").hidden = !message; }
function badge(text, style = "") { $("run-state").textContent = text; $("run-state").className = `state-badge ${style}`; }
function selectedExample() { return document.querySelector('input[name="example"]:checked').value; }
function applyExample(example) {
  const radio = [...document.querySelectorAll('input[name="example"]')].find((node) => node.value === example.id);
  if (radio) radio.checked = true;
  $("selected-prompt").textContent = example.prompt;
  $("circuit-title").textContent = example.stages === 2 ? "SKY130 two-stage op-amp" : "SKY130 single-stage OTA";
}
function renderTime() {
  const value = clock.sample(), phases = value.phases;
  $("button-timer").textContent = `${value.total.toFixed(1)} s`;
  $("elapsed").textContent = `${value.total.toFixed(2)} s`;
  const small = document.createElement("small"); small.textContent = "s";
  $("total-timer").replaceChildren(document.createTextNode(value.total.toFixed(2)), small);
  for (const [id, phase] of [["laya-timer", "laya"], ["build-timer", "search"], ["simulation-timer", "simulation"], ["layout-timer", "layout"], ["pex-timer", "pex"], ["postlayout-timer", "postlayout"]]) {
    $(id).textContent = phases[phase] === undefined ? "—" : `${phases[phase].toFixed(2)} s`;
  }
}
function startClock() {
  $("button-timer").hidden = false;
  clearInterval(timer); renderTime(); timer = setInterval(renderTime, 100);
}
function setView(layout, intent = false) {
  if (layout) $("layout-frame").src = intent ? intentURL : layoutURL;
  $("view-intent").setAttribute("aria-pressed", String(intent));
  $("frame").hidden = layout; $("layout-frame").hidden = !layout;
  $("view-schematic").setAttribute("aria-pressed", String(!layout));
  $("view-layout").setAttribute("aria-pressed", String(layout && !intent));
  if (layout) $("frame-note").textContent = "Exact physical geometry · PDK devices, contacts and routed metal";
  else if (finished) $("frame-note").textContent = "Final frame from this live xschem session";
}
function reset() {
  setView(false); $("view-layout").disabled = true; $("view-intent").disabled = true;
  $("analog-quality").hidden = true;
  if (intentURL) { URL.revokeObjectURL(intentURL); intentURL = null; }
  if (layoutURL) { URL.revokeObjectURL(layoutURL); layoutURL = null; }
  $("layout-frame").removeAttribute("src");
  for (const id of ["drc-result", "lvs-result", "pex-result", "area-result"]) $(id).textContent = "—";
  $("physical-status").textContent = "DRC, LVS and extracted measurements appear here.";
  const row = document.createElement("tr"), cell = document.createElement("td"); cell.colSpan = 4; cell.textContent = "Start a design to measure both circuits."; row.append(cell); $("comparison-body").replaceChildren(row);
  clock.reset(); renderTime();
  $("laya-decisions").hidden = true; $("laya-decisions").replaceChildren();
  $("laya-note").textContent = "Typed decisions → topology probabilities";
  $("search-note").textContent = "Joint topology + transistor sizing";
  $("topology-note").textContent = "A fresh topology and sizing search on every run";
  $("frame").src = "assets/circuit-preview.jpg";
  $("stream-label").textContent = "STARTING";
  error(""); result = null; lastEvent = 0; reconnects = 0; finished = false;
  $("downloads").hidden = true; $("progress").value = 0;
  $("screen-note").hidden = true; $("verification").className = "verification";
  $("verification").textContent = "Measurements appear after simulation.";
  $("result-note").textContent = "Plots and measurements come from the current ngspice run.";
  for (const [key, unit] of [["gain", "dB"], ["gbw", "MHz"], ["pm", "°"], ["power", "mW"]]) setMetric(key, null, unit);
  for (const node of document.querySelectorAll(".stages li")) node.className = "";
  for (const [key, text] of [["ac-plot", "Waiting for the AC sweep"], ["step-plot", "Waiting for the closed-loop steps"], ["post-ac-plot", "Waiting for the extracted AC sweep"], ["post-step-plot", "Waiting for the extracted closed-loop steps"]]) {
    const p = document.createElement("p"); p.textContent = text; $(key).replaceChildren(p);
  }
}

async function request(path, options = {}) {
  const response = await fetch(`${api}${path}`, { ...options, credentials: "omit", cache: "no-store", signal: AbortSignal.timeout(10000) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "The simulation service is not ready. Please retry shortly.");
  return data;
}

async function health() {
  try {
    const state = await request("/api/health");
    $("compute-device").textContent = state.compute.device;
    $("availability").textContent = state.active_run ? "A shared run is in progress · click to watch" : `${state.compute.device} · ready to design`;
    return true;
  } catch {
    $("availability").textContent = "Live service unavailable · click to retry";
    $("compute-device").textContent = "Compute service offline";
    return false;
  }
}

function setMetric(key, value, unit) {
  const small = document.createElement("small"); small.textContent = unit;
  $(key).replaceChildren(document.createTextNode(Number.isFinite(value) ? value.toFixed(2) : "—"), small);
}

function showResult(data) {
  result = data; clock.stop(); renderTime();
  $("topology-note").textContent = `${data.topology} · ${data.mosfets} MOSFETs`;
  $("timing-note").textContent = "Completed. Laya time includes model loading; search includes candidate simulations.";
  setMetric("gain", data.metrics.gain_db, "dB");
  setMetric("gbw", data.metrics.gbw_mhz, "MHz");
  setMetric("pm", data.metrics.pm_deg, "°");
  setMetric("power", data.metrics.power_uw / 1000, "mW");
  const physical = data.physical;
  $("drc-result").textContent = `${physical.layout.drc_errors} errors`;
  $("lvs-result").textContent = physical.lvs.passed ? "Matched" : "Failed";
  $("pex-result").textContent = `${physical.pex.resistors} R / ${physical.pex.capacitors} C`;
  $("area-result").textContent = `${physical.layout.area_um2.toFixed(0)} µm²`;
  $("physical-status").textContent = `${physical.layout.layout_seconds.toFixed(2)} s final layout + DRC · ${(physical.all_physical_seconds ?? physical.total_seconds).toFixed(2)} s physical stages including candidate screening · ${physical.recovery.attempts.length} final sizing attempt(s)`;
  showQuality(physical);
  const rows = [];
  for (const [key, label, scale] of [["gain_db", "DC gain (dB)", 1], ["gbw_mhz", "Gain-bandwidth (MHz)", 1], ["pm_deg", "Phase margin (°)", 1], ["power_uw", "Power (mW)", 0.001], ["cmrr_db", "CMRR (dB)", 1], ["buffer_gain_error", "Closed-loop gain error (%)", 100], ["vin_dc", "Input bias (V)", 1]]) {
    const before = data.prelayout.metrics[key], after = data.metrics[key];
    const row = document.createElement("tr");
    for (const text of [label, Number.isFinite(before) ? (before * scale).toFixed(3) : "—", Number.isFinite(after) ? (after * scale).toFixed(3) : "—", Number.isFinite(before) && Number.isFinite(after) ? `${after >= before ? "+" : ""}${((after - before) * scale).toFixed(3)}` : "—"]) {
      const cell = document.createElement("td"); cell.textContent = text; row.append(cell);
    }
    rows.push(row);
  }
  $("comparison-body").replaceChildren(...rows);
  const checks = Object.values(data.checks);
  $("verification").textContent = data.valid ? `${checks.filter(Boolean).length}/${checks.length} post-layout checks passed · DRC clean · LVS matched` : "Qualification failed; inspect the downloaded results.";
  $("verification").className = `verification ${data.valid ? "success" : ""}`;
  $("result-note").textContent = `Fresh Laya inference ${(data.laya_inference_seconds * 1000).toFixed(0)} ms · ${data.search.evaluations} circuits measured · ${data.model.device} · post-layout ngspice ${data.wall_seconds.toFixed(2)} s. Final metrics above include the extracted RC network.`;
}

function showQuality(physical) {
  const trace = physical.optimization, bench = physical.analog;
  if (!trace || !bench) return;
  $("analog-quality").hidden = false;
  const plan = physical.layout.plan, metrics = bench.metrics;
  $("layout-plan-note").textContent = `${plan.pattern} · ${plan.columns} column(s) · ${plan.dummies ? "edge dummies" : "no dummies"}`;
  for (const [id, key, scale, unit] of [["noise-result", "input_noise_rms_v", 1e6, "µV RMS"], ["psrr-result", "psrr_min_db", 1, "dB"], ["ir-result", "internal_supply_drop_v", 1e3, "mV"], ["ground-result", "internal_ground_rise_v", 1e3, "mV"]]) {
    $(id).textContent = Number.isFinite(metrics[key]) ? `${(metrics[key] * scale).toFixed(2)} ${unit}` : "Not measured";
  }
  const first = trace.history.find(row => row.valid), chosen = physical.layout.area_um2;
  const delta = first ? (1 - chosen / first.quality.area_um2) * 100 : 0;
  $("optimization-summary").textContent = `${trace.evaluations} layouts evaluated in ${trace.wall_seconds.toFixed(2)} s · ${trace.first_feasible_seconds?.toFixed(2) ?? "—"} s to first qualified layout · ${delta.toFixed(1)}% area reduction from that layout · ${trace.pareto_plan_ids.length} Pareto candidates. Laya proposes actions; DRC, LVS and ngspice decide acceptance.`;
  $("physical-status").textContent = `${physical.layout.layout_seconds.toFixed(2)} s final layout + DRC · ${trace.wall_seconds.toFixed(2)} s complete layout optimization · fixed input bias ${trace.fixed_input_bias_v.toFixed(4)} V`;
  const labels = {initial: "Initial plan", columns: "Floorplan", fingers_per_row: "Row packing", pattern: "Matching pattern", split: "Unit decomposition", rail_multiplier: "Power rails", shield_inputs: "Grounded separator", decap_pf: "Decoupling", decap_location: "Decap placement", dummies: "Edge dummies"};
  const rows = trace.history.map(item => {
    const row = document.createElement("tr");
    const reasons = Object.entries({...item.qualification_checks, ...item.checks}).filter(([, pass]) => !pass).map(([name]) => name).join(", ");
    const decision = item.valid ? item.accepted ? (item.index === 0 ? "Initial feasible layout" : "Accepted improvement") : "Qualified; retained incumbent" : `Rejected: ${item.error || reasons}`;
    const number = v => Number.isFinite(v) ? v.toFixed(2) : "—";
    for (const value of [`${item.index + 1} / ${labels[item.action] || item.action}`, number(item.quality?.area_um2), number(item.metrics?.gain_db), number(item.metrics?.gbw_mhz), decision]) {
      const cell = document.createElement("td"); cell.textContent = value; row.append(cell);
    }
    return row;
  });
  $("optimization-body").replaceChildren(...rows);
  const hotspots = Object.entries(physical.quality.net_capacitance_ff).filter(([n]) => !["vdd", "vss"].includes(n)).sort((a, b) => b[1] - a[1]).slice(0, 3);
  $("parasitic-note").textContent = `Largest node parasitics: ${hotspots.map(([n, c]) => `${n} ${c.toFixed(2)} fF`).join(" · ")}. Input capacitance imbalance: ${physical.quality.input_cap_imbalance_ff?.toFixed(2) ?? "—"} fF. Centroid error: ${physical.quality.centroid_error_um.toFixed(2)} µm (geometry only).`;
  const waves = bench.waveforms, x = waves.frequency_hz.map(Math.log10);
  const noise = waves.input_noise_v_sqrt_hz.map(v => v * 1e9), psrr = waves.psrr_db;
  chart("noise-plot", "Measured input noise density", "Frequency (Hz)", "nV/√Hz", [x[0], x.at(-1)], [0, Math.max(...noise) * 1.05], [[1, "10"], [3, "1k"], [6, "1M"]], [{x, y: noise, color: "#087ebd"}]);
  chart("psrr-plot", "Measured supply rejection", "Frequency (Hz)", "PSRR (dB)", [x[0], x.at(-1)], [Math.floor(Math.min(...psrr) / 10) * 10, Math.ceil(Math.max(...psrr) / 10) * 10 + 1], [[1, "10"], [3, "1k"], [6, "1M"]], [{x, y: psrr, color: "#087ebd"}]);
  const c = bench.conditions;
  $("analog-conditions").textContent = `Fixture: ${c.supply_resistance_ohm} Ω supply impedance, ${c.load_step_a * 1e6} µA load step, ${c.temperature_c} °C. Peak supply droop: ${(metrics.supply_droop_v * 1e3).toFixed(3)} mV. These measurements do not establish substrate-noise, thermal, EM or mismatch signoff.`;
}

function complete(ok) {
  finished = true; running = false; clock.stop(); clearInterval(timer); renderTime();
  $("examples").disabled = false;
  $("live-dot").classList.remove("active");
  $("stream-label").textContent = ok ? "RUN COMPLETE" : "RUN STOPPED";
  $("frame-note").textContent = ok ? "Final frame from this live xschem session" : "Last received xschem frame";
  button("Run again");
  if (result) {
    badge(result.valid ? "Verified" : "Unqualified", result.valid ? "success" : "failed");
  } else if (!ok) badge("Stopped", "failed");
  if (ok && result) {
    for (const [id, name] of [["sch", "circuit.sch"], ["spice", "circuit.spice"], ["json", "result.json"], ["decisions", "decisions.json"], ["search", "search.json"], ["mag", "layout.mag"], ["gds", "layout.gds"], ["pex", "pex.spice"], ["physical", "physical.json"], ["optimization", "optimization.json"], ["evidence", "physical-evidence.zip"]]) {
      const link = $(`download-${id}`); link.href = `${api}/api/runs/${runId}/artifacts/${name}`; link.download = name;
    }
    $("downloads").hidden = false;
    const completedId = runId;
    fetch(`${api}/api/runs/${runId}/artifacts/layout.svg`, {credentials: "omit"})
      .then(response => { if (!response.ok) throw new Error("Layout image unavailable"); return response.blob(); })
      .then(blob => { if (completedId !== runId || !finished) return; if (layoutURL) URL.revokeObjectURL(layoutURL); layoutURL = URL.createObjectURL(blob); $("layout-frame").src = layoutURL; $("view-layout").disabled = false; setView(true); })
      .catch(() => { $("physical-status").textContent += " · Preview unavailable; download the Magic or GDS file."; });
    if (result.physical.optimization) fetch(`${api}/api/runs/${runId}/artifacts/layout-intent.svg`, {credentials: "omit"})
      .then(response => { if (!response.ok) throw new Error("Overlay unavailable"); return response.blob(); })
      .then(blob => { if (completedId !== runId || !finished) return; intentURL = URL.createObjectURL(blob); $("view-intent").disabled = false; }).catch(() => {});
    $("availability").textContent = "Run complete · 15-second cooldown before restarting";
  }
  saveRun(null);
}

function event(data) {
  if (data.type === "finished") { complete(data.status === "complete"); return; }
  if (data.id && data.id <= lastEvent) return;
  lastEvent = data.id || lastEvent;
  clock.observe(data); renderTime();
  if (data.type === "stage") {
    if (data.example) applyExample(data.example);
    if (data.laya) {
      $("compute-device").textContent = `${data.laya.device} · ${data.laya.precision}`;
      const decisions = $("laya-decisions"); decisions.replaceChildren(); decisions.hidden = false;
      const heading = document.createElement("strong"); heading.textContent = "Laya’s live decisions"; decisions.append(heading);
      const names = {ota5: "5-transistor OTA", cmota: "Current-mirror OTA", tele: "Telescopic cascode", fc: "Folded cascode", rload: "Resistor load", n: "NMOS", p: "PMOS", cs: "Common source", cas: "Cascode", inv: "Inverter", inv_cas: "Cascoded inverter", miller: "Miller capacitor", miller_rz: "Miller + nulling resistor", none: "No compensation"};
      for (const [key, label] of [["first", "Input"], ["polarity", "Polarity"], ["later", "Next stage"], ["comp", "Compensation"]]) {
        const answer = data.laya.answers[key]; if (!answer) continue;
        const node = document.createElement("span"); node.textContent = `${label}: ${names[answer.choice] || answer.choice}`; decisions.append(node);
      }
      $("laya-note").textContent = `${(data.laya.inference_seconds * 1000).toFixed(0)} ms inference · ${data.laya.topologies} allowed topologies`;
    }
    if (data.search) {
      $("search-note").textContent = `${data.search.evaluations} circuits measured${data.search.best_gain_db == null ? "" : ` · best ${data.search.best_gain_db.toFixed(1)} dB`}`;
      if (data.search.topology) $("topology-note").textContent = `${data.search.topology} · ${data.search.mosfets} MOSFETs`;
    }
    $("run-message").textContent = data.message; $("progress").value = data.progress;
    const index = stageNames.indexOf(data.stage);
    for (const [i, node] of [...document.querySelectorAll(".stages li")].entries()) {
      node.className = ["complete", "unqualified"].includes(data.stage) || i < index ? "done" : i === index ? "active" : "";
    }
    badge(data.stage === "complete" ? "Verified" : data.stage === "unqualified" ? "Unqualified" : "Running", data.stage === "complete" ? "success" : "");
  } else if (data.type === "waveforms") { drawWaveforms(data); if (data.postlayout) drawWaveforms(data.postlayout, "post-"); }
  else if (data.type === "result") showResult(data);
  else if (data.type === "error") { error(data.message); complete(false); }
}

function connect() {
  const url = new URL(`${api}/api/runs/${runId}/live`); url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  socket = new WebSocket(url); socket.binaryType = "blob";
  socket.onopen = () => { $("availability").textContent = "Connected to a live xschem session"; };
  socket.onmessage = ({ data }) => {
    if (data instanceof Blob) {
      const previous = frameURL; frameURL = URL.createObjectURL(data); $("frame").src = frameURL;
      $("frame").alt = "Live xschem screen from the current circuit simulation";
      if (previous) URL.revokeObjectURL(previous);
      $("stream-label").textContent = "LIVE XSCHEM"; $("live-dot").classList.add("active");
      $("frame-note").textContent = "Live capture · private virtual display · view-only";
    } else { try { event(JSON.parse(data)); } catch { error("A stream message could not be read. Reconnect to the run."); } }
  };
  socket.onclose = () => {
    if (finished || !running) return;
    $("live-dot").classList.remove("active"); $("stream-label").textContent = "RECONNECTING";
    if (++reconnects <= 3) {
      $("availability").textContent = "Connection interrupted · reconnecting to this run…";
      setTimeout(() => { if (!finished && running) connect(); }, Math.min(1000 * 2 ** reconnects, 8000));
    } else {
      error("The live connection was interrupted. The simulation may still be running; click Reconnect to recover it.");
      clock.stop(); clearInterval(timer); running = false; button("Reconnect to run");
      $("availability").textContent = "Live connection lost"; badge("Disconnected", "failed");
    }
  };
}

async function launch() {
  if (!api || running) return;
  button("Connecting…", true); error("");
  try {
    if (runId && !finished && lastEvent) {
      const state = await request(`/api/runs/${runId}`);
      if (["running", "complete"].includes(state.status)) { reconnects = 0; applyExample(state.example); clock.resume(); begin(); return; }
    }
    reset(); clock.start(); startClock(); $("examples").disabled = true;
    const response = await request("/api/runs", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({example: selectedExample()}) });
    runId = response.id; saveRun(runId); applyExample(response.example);
    $("run-message").textContent = response.joined ? "Joining the shared live design shown above…" : "Reading the selected prompt and starting a fresh design…";
    begin();
  } catch (err) {
    clock.stop(); clearInterval(timer); renderTime(); $("examples").disabled = false;
    error(err instanceof TypeError ? "The live design service could not be reached. Please retry shortly." : err.message);
    button("Retry design");
    $("availability").textContent = "Waiting for the design service";
    if (err.message.includes("expired")) { runId = null; lastEvent = 0; saveRun(null); }
  }
}
function begin() {
  running = true; finished = false; $("examples").disabled = true;
  if (!clock.running) clock.resume();
  button("Design running…", true); badge("Running"); startClock();
  $("timing-note").textContent = "From your click to the result. Search includes candidate simulations.";
  connect();
}

const NS = "http://www.w3.org/2000/svg";
function svgNode(name, attrs = {}, text) {
  const node = document.createElementNS(NS, name);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  if (text !== undefined) node.textContent = text;
  return node;
}
function chart(container, title, xLabel, yLabel, xDomain, yDomain, xTicks, series, rightLabel) {
  const W = 600, H = 260, L = 52, R = rightLabel ? 52 : 20, T = 18, B = 45;
  const width = W - L - R, height = H - T - B;
  const sx = (x) => L + (x - xDomain[0]) / (xDomain[1] - xDomain[0]) * width;
  const sy = (y, domain = yDomain) => T + height - (y - domain[0]) / (domain[1] - domain[0]) * height;
  const svg = svgNode("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": title });
  const rightDomain = rightLabel ? series.find((line) => line.domain).domain : null;
  svg.append(svgNode("title", {}, title));
  const textStyle = { fill: "#697c8e", "font-size": 11, "font-family": "Arial, sans-serif" };
  for (let i = 0; i <= 4; i++) {
    const value = yDomain[0] + i * (yDomain[1] - yDomain[0]) / 4, y = sy(value);
    svg.append(svgNode("line", { x1: L, y1: y, x2: W - R, y2: y, stroke: "#e9eef3", "stroke-width": 1 }));
    svg.append(svgNode("text", { x: L - 9, y: y + 4, "text-anchor": "end", ...textStyle }, String(Math.round(value))));
    if (rightLabel) svg.append(svgNode("text", { x: W - R + 9, y: y + 4, ...textStyle }, String(Math.round(rightDomain[0] + i * (rightDomain[1] - rightDomain[0]) / 4))));
  }
  for (const [value, label] of xTicks) {
    svg.append(svgNode("line", { x1: sx(value), y1: T, x2: sx(value), y2: H - B, stroke: "#eef2f6" }));
    svg.append(svgNode("text", { x: sx(value), y: H - B + 19, "text-anchor": "middle", ...textStyle }, label));
  }
  for (const line of series) {
    const points = line.x.map((x, i) => `${i ? "L" : "M"}${sx(x).toFixed(2)},${sy(line.y[i], line.domain).toFixed(2)}`).join(" ");
    svg.append(svgNode("path", { d: points, fill: "none", stroke: line.color, "stroke-width": 2, "stroke-linejoin": "round", ...(line.dash ? { "stroke-dasharray": "5 4" } : {}) }));
  }
  svg.append(svgNode("text", { x: L + width / 2, y: H - 4, "text-anchor": "middle", ...textStyle }, xLabel));
  svg.append(svgNode("text", { x: L, y: 9, ...textStyle, "font-size": 10 }, yLabel));
  if (rightLabel) svg.append(svgNode("text", { x: W - R, y: 9, "text-anchor": "end", ...textStyle, "font-size": 10 }, rightLabel));
  $(container).replaceChildren(svg);
}
function drawWaveforms(data, prefix = "") {
  const frequency = data.frequency_hz.map(Math.log10);
  const gainMin = Math.floor(Math.min(...data.gain_db) / 20) * 20;
  const gainMax = Math.ceil(Math.max(...data.gain_db) / 20) * 20;
  const phaseDomain = [Math.floor(Math.min(...data.phase_deg) / 90) * 90, Math.ceil(Math.max(...data.phase_deg) / 90) * 90];
  chart(`${prefix}ac-plot`, "Measured open-loop gain and phase versus frequency", "Frequency (Hz)", "Gain (dB)", [0, 11], [gainMin, gainMax], [[0, "1"], [3, "1k"], [6, "1M"], [9, "1G"], [11, "100G"]], [
    { x: frequency, y: data.gain_db, color: "#087ebd" },
    { x: frequency, y: data.phase_deg, color: "#8b88b7", domain: phaseDomain, dash: true },
  ], "Phase (°)");
  const waves = data.steps.filter((step) => step.waveform);
  if (!waves.length) { const note = document.createElement("p"); note.textContent = "Closed-loop qualification did not produce a waveform"; $(`${prefix}step-plot`).replaceChildren(note); return; }
  const times = waves.flatMap((step) => step.waveform.t_us), low = Math.min(...times), high = Math.max(...times);
  const amplitude = Math.max(12, Math.ceil(Math.max(...waves.flatMap((step) => step.waveform.delta_mv.map(Math.abs))) / 2) * 2);
  const ticks = Array.from({ length: 5 }, (_, i) => { const n = i * high / 4; return [n, n.toFixed(1)]; });
  chart(`${prefix}step-plot`, "Measured positive and negative 10 millivolt unity-buffer step responses", "Time after input step (µs)", "Output change (mV)", [low, high], [-amplitude, amplitude], ticks,
    waves.map((step) => ({ x: step.waveform.t_us, y: step.waveform.delta_mv, color: step.direction > 0 ? "#087ebd" : "#de892f" })));
}

$("view-schematic").addEventListener("click", () => setView(false));
$("view-layout").addEventListener("click", () => setView(true));
$("view-intent").addEventListener("click", () => setView(true, true));
runButton.addEventListener("click", launch);
$("examples").addEventListener("change", () => {
  const example = examples.find((item) => item.id === selectedExample());
  if (example && !running) {
    reset(); applyExample(example); $("button-timer").hidden = true;
    $("stream-label").textContent = "REFERENCE CAPTURE";
    $("frame-note").textContent = "Idle reference capture · replaced when you start";
    badge("Ready"); button("Start design");
  }
});
$("expand").addEventListener("click", async () => {
  const viewer = document.querySelector(".viewer");
  if (document.fullscreenElement) { await document.exitFullscreen(); return; }
  if (viewer.requestFullscreen) { try { await viewer.requestFullscreen(); return; } catch { /* Embedded browsers may disallow fullscreen. */ } }
  expanded = !expanded; viewer.classList.toggle("expanded", expanded);
  $("expand").setAttribute("aria-label", expanded ? "Exit expanded view" : "Expand live circuit view");
});
document.addEventListener("keydown", (event) => { if (event.key === "Escape" && expanded) { expanded = false; document.querySelector(".viewer").classList.remove("expanded"); } });
window.addEventListener("pagehide", () => { running = false; clearInterval(timer); socket?.close(); if (frameURL) URL.revokeObjectURL(frameURL); if (layoutURL) URL.revokeObjectURL(layoutURL); if (intentURL) URL.revokeObjectURL(intentURL); });

try {
  const config = await fetch("config.json", { cache: "no-store" }).then((response) => { if (!response.ok) throw new Error("Missing demo configuration"); return response.json(); });
  const local = ["localhost", "127.0.0.1"].includes(location.hostname);
  api = local ? location.origin : new URL(config.apiBase).origin;
  if (!local && !api.startsWith("https://")) throw new Error("The demo API must use HTTPS.");
  examples = await fetch("examples.json").then((response) => response.json());
  applyExample(examples.find((item) => item.id === selectedExample()));
  await health();
  const previous = readRun();
  if (previous && /^[0-9a-f]{32}$/.test(previous)) {
    try { const state = await request(`/api/runs/${previous}`); reset(); applyExample(state.example); runId = previous; begin(); }
    catch { saveRun(null); }
  }
} catch { error("The demo configuration could not be loaded. Please reload this page."); button("Demo unavailable", true); }
