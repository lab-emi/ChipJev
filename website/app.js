import { RunClock } from "./run-clock.mjs";
const $ = (id) => document.getElementById(id);
const runButton = $("run");
const stageNames = ["deciding", "searching", "netlisting", "simulating", "layout", "drc", "lvs", "extracting", "postsimulating", "checking"];
const checkNotes = {drc: "Magic DRC · full SKY130 rule deck", lvs: "Netgen LVS · every device and net"};
const layoutActions = {initial: "Initial plan", columns: "Floorplan", fingers_per_row: "Row packing", pattern: "Matching pattern", split: "Unit decomposition", rail_multiplier: "Power rails", shield_inputs: "Grounded separator", decap_pf: "Decoupling", decap_location: "Decap placement", dummies: "Edge dummies",
  seed: "Initial plan", aspect: "Aspect ratio", max_finger_um: "Finger folding", pair_pattern: "Matching pattern", single_dummies: "Single-device dummies", rail_um: "Power rail width", decap: "Decoupling", passives: "Passive placement", refinger: "Re-fingering"};
const clock = new RunClock();
let examples = [];
let api, socket, runId, lastEvent = 0, frameURL, reconnects = 0, running = false;
let timer, result, finished = false, expanded = false;
const runKey = "chipjev-live-run-v3";
let layoutURL, intentURL;
let gates = {drc: null, lvs: null}, currentStage = null, loopState = null;

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
const span = ([a, b]) => a === b ? `layout ${a}` : `layouts ${a}–${b}`;
function checkText(key, check) {
  const drc = key === "drc", counts = Number.isInteger(check.devices) && Number.isInteger(check.nets) ? ` · ${check.devices} devices, ${check.nets} nets` : "";
  if (check.selected || !check.layouts) {  // the selected layout's own reports
    const where = check.layout ? `${check.selected ? "selected " : ""}layout ${check.layout}` : "selected layout";
    if (drc) return check.status === "passed" ? `Passed · 0 violations · ${where}` : `${check.errors ?? "Unknown"} violations · ${where} rejected`;
    return check.status === "passed" ? `Matched${counts} · ${where}` : `Mismatch · ${where} rejected`;
  }
  const which = span(check.layouts);  // one loop iteration: a batch of candidate layouts
  if (check.status === "pending") return `Next: ${drc ? "Magic DRC" : "Netgen LVS"} on ${which}`;
  if (check.status === "running") return `Checking ${which} · ${check.checked}/${check.of} done`;
  if (check.of === 1) return drc ? (check.status === "passed" ? `Passed · 0 violations · ${which}` : `${check.errors} violations · ${which} rejected`) : (check.status === "passed" ? `Matched${counts} · ${which}` : `Mismatch · ${which} rejected`);
  const rejected = check.of - check.passed, unrouted = check.unrouted ? ` · ${check.unrouted} not routed` : "";
  return `${check.passed}/${check.of} ${drc ? "clean" : "matched"}${rejected ? ` · ${rejected} rejected` : ""}${unrouted} · ${which}`;
}
function loopNotes(stage) {
  const loop = loopState;
  if (!loop) return ["Laya-guided loop over steps 5–9", "ngspice AC and closed-loop steps"];
  if (loop.done) return [`${loop.iteration} iterations · ${loop.total} layouts · selected layout ${loop.selected}`, `Selected layout ${loop.selected} · after ${loop.iteration} iterations`];
  const first = loop.iteration === 1 ? "Iteration 1 · initial plan · layout 1" : `Iteration ${loop.iteration} · Laya proposed ${span(loop.layouts)}`;
  const post = Number.isInteger(loop.accepted) ? `Layout ${loop.accepted + 1} accepted → back to step 5` :
    loop.evaluated >= loop.size && Number.isInteger(loop.incumbent) ? `No gain · incumbent layout ${loop.incumbent + 1} kept → back to step 5` :
    stage === "postsimulating" ? `Simulating ${span(loop.layouts)} · ${Math.min(loop.finished, loop.size)}/${loop.size} done` : "ngspice AC and closed-loop steps";
  return [first, post];
}
function renderStages(stage = currentStage) {
  currentStage = stage;
  const index = stageNames.indexOf(stage), ended = ["complete", "unqualified"].includes(stage);
  const inLoop = index >= stageNames.indexOf("layout") && index <= stageNames.indexOf("postsimulating");
  const looping = Boolean(loopState && !loopState.done && inLoop && !ended);
  const feedback = looping && stage === "layout" && loopState.iteration > 1;  // the loop closes into step 5
  for (const [i, node] of [...document.querySelectorAll(".stages li")].entries()) {
    const key = node.dataset.stage, check = gates[key];
    node.className = ended || (index >= 0 && i < index) ? "done" : i === index ? "active" : "";
    if (i === index - 1 && !feedback && !ended) node.classList.add("feeds");
    // DRC and LVS show this iteration's verdict; the selected layout's own reports at the end.
    if (check && ["passed", "failed"].includes(check.status)) node.classList.add(check.status);
    if (key in checkNotes) $(`${key}-note`).textContent = check ? checkText(key, check) : checkNotes[key];
  }
  const [layoutNote, postNote] = loopNotes(stage);
  $("layout-note").textContent = layoutNote; $("post-note").textContent = postNote;
  $("stage-flow").classList.toggle("looping", looping); $("stage-flow").classList.toggle("feedback", feedback);
  $("loop-count").textContent = loopState ? loopState.iteration : "×";
  drawLoop();
}
// Feedback arrow from step 9 back into step 5, drawn at the steps' real positions.
function drawLoop() {
  const flow = $("stage-flow"), from = document.querySelector('.stages li[data-stage="postsimulating"] .step-number');
  const to = document.querySelector('.stages li[data-stage="layout"] .step-number'), box = flow.getBoundingClientRect();
  if (!box.width) return;
  const rem = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16, a = to.getBoundingClientRect(), b = from.getBoundingClientRect();
  const x = 0.55 * rem, r = 0.5 * rem, head = 0.34 * rem, y0 = a.top + a.height / 2 - box.top, y1 = b.top + b.height / 2 - box.top;
  // Tail and tip stay just outside the .18rem ring an active or checked step draws.
  const start = b.left - box.left - 0.2 * rem, end = a.left - box.left - 0.26 * rem;
  const svg = $("loop-arrow"); svg.setAttribute("viewBox", `0 0 ${box.width} ${box.height}`);
  svg.replaceChildren(svgNode("path", { d: `M${start},${y1} H${x + r} Q${x},${y1} ${x},${y1 - r} V${y0 + r} Q${x},${y0} ${x + r},${y0} H${end - head}` }),
    svgNode("path", { class: "head", d: `M${end - head},${y0 - 0.62 * head} L${end},${y0} L${end - head},${y0 + 0.62 * head} Z` }));
  $("loop-badge").style.top = `${(y0 + y1) / 2}px`;
}
new ResizeObserver(() => drawLoop()).observe(document.getElementById("stage-flow"));
// Fast loop steps (layout, DRC, LVS, RC take well under a second) stay on screen long enough
// to be seen; the display catches up during post-layout simulation. Replays skip the wait.
const dwell = {layout: 1100, drc: 450, lvs: 450, extracting: 350};
let pending = [], shownStage = null, shownAt = 0, stageTimer = null, replayUntil = 0;
function queueStage(snapshot) { pending.push(snapshot); pumpStages(); }
function applyStage(next) {
  if (next.stage !== shownStage) { shownStage = next.stage; shownAt = performance.now(); }
  if (next.gates) gates = next.gates;
  if (next.loop) loopState = next.loop;
  $("run-message").textContent = next.message; $("progress").value = next.progress;
  renderStages(next.stage);
}
function pumpStages(flush = false) {
  if (stageTimer && !flush) return;
  clearTimeout(stageTimer); stageTimer = null;
  while (pending.length) {
    const wait = (dwell[shownStage] || 0) - (performance.now() - shownAt);
    if (!flush && pending[0].stage !== shownStage && wait > 0 && performance.now() > replayUntil && pending.length < 12) {
      stageTimer = setTimeout(() => { stageTimer = null; pumpStages(); }, wait); return;
    }
    applyStage(pending.shift());
  }
}
function startClock() {
  $("button-timer").hidden = false;
  clearInterval(timer); renderTime(); timer = setInterval(renderTime, 100);
}
function setView(layout, intent = false) {
  if (layout) $("layout-frame").src = intent ? intentURL : layoutURL;
  $("view-intent").setAttribute("aria-pressed", String(intent));
  $("live-workspace").hidden = layout; $("layout-frame").hidden = !layout;
  $("screen").classList.toggle("static-view", layout);
  $("view-schematic").setAttribute("aria-pressed", String(!layout));
  $("view-layout").setAttribute("aria-pressed", String(layout && !intent));
  if (layout) $("frame-note").textContent = "Exact physical geometry · PDK devices, contacts and routed metal";
  else $("frame-note").textContent = finished ? "Final xschem + Magic frame · selected layout" : "Live xschem + Magic · synchronized capture · view-only";
}
function reset() {
  setView(false); $("view-layout").disabled = true; $("view-intent").disabled = true;
  $("analog-quality").hidden = true;
  if (intentURL) { URL.revokeObjectURL(intentURL); intentURL = null; }
  if (layoutURL) { URL.revokeObjectURL(layoutURL); layoutURL = null; }
  $("layout-frame").removeAttribute("src");
  for (const id of ["drc-result", "lvs-result", "pex-result", "area-result"]) { $(id).textContent = "—"; $(id).className = ""; }
  $("physical-status").textContent = "DRC, LVS and extracted measurements appear here.";
  const row = document.createElement("tr"), cell = document.createElement("td"); cell.colSpan = 4; cell.textContent = "Start a design to measure both circuits."; row.append(cell); $("comparison-body").replaceChildren(row);
  clock.reset(); renderTime();
  $("laya-decisions").hidden = true; $("laya-decisions").replaceChildren();
  $("laya-note").textContent = "Typed decisions → topology probabilities";
  $("search-note").textContent = "Joint topology + transistor sizing";
  $("topology-note").textContent = "A fresh topology and sizing search on every run";
  $("frame").src = $("magic-frame").src = "assets/workspace-preview.jpg?v=pro-1";
  $("schematic-live-status").textContent = "Starting xschem";
  $("schematic-live-note").textContent = "Live topology and sizing candidates appear here.";
  $("magic-live-status").textContent = "Waiting for layout";
  $("magic-live-note").textContent = "Placement, routing and acceptance update with each layout.";
  $("magic-waiting").hidden = false;
  $("stream-label").textContent = "STARTING";
  error(""); result = null; lastEvent = 0; reconnects = 0; finished = false;
  $("downloads").hidden = true; $("progress").value = 0;
  $("screen-note").hidden = true; $("verification").className = "verification";
  $("verification").textContent = "Measurements appear after simulation.";
  $("result-note").textContent = "Plots and measurements come from the current ngspice run.";
  for (const [key, unit] of [["gain", "dB"], ["gbw", "MHz"], ["pm", "°"], ["power", "mW"]]) { setMetric(key, null, unit); $(`${key}-delta`).textContent = ""; }
  pending = []; clearTimeout(stageTimer); stageTimer = null; shownStage = null;
  gates = {drc: null, lvs: null}; loopState = null; renderStages(null);
  for (const [key, text] of [["ac-plot", "Waiting for the AC sweep"], ["step-plot", "Waiting for the closed-loop steps"]]) {
    const p = document.createElement("p"); p.textContent = text; $(key).replaceChildren(p); drawn.delete(key);
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
    $("availability").textContent = state.active_run ? "A shared run is in progress · click to watch" : "Ready to design";
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
  for (const [key, metric, scale, unit] of [["gain", "gain_db", 1, "dB"], ["gbw", "gbw_mhz", 1, "MHz"], ["pm", "pm_deg", 1, "°"], ["power", "power_uw", 0.001, "mW"]]) {
    const before = data.prelayout.metrics[metric], after = data.metrics[metric];
    $(`${key}-delta`).textContent = Number.isFinite(before) && Number.isFinite(after) ? `${after >= before ? "+" : "−"}${Math.abs((after - before) * scale).toFixed(2)}${unit === "°" ? "" : " "}${unit} vs schematic` : "";
  }
  const physical = data.physical;
  pumpStages(true);  // the measured result supersedes any step still waiting to be shown
  const drcClean = physical.layout.drc_errors === 0, lvsMatched = physical.lvs.passed === true;
  $("drc-result").textContent = drcClean ? "✓ 0 errors" : `${physical.layout.drc_errors} errors`;
  $("drc-result").className = drcClean ? "pass" : "fail";
  $("lvs-result").textContent = lvsMatched ? "✓ Matched" : "Failed";
  $("lvs-result").className = lvsMatched ? "pass" : "fail";
  // The measured result is authoritative for the two gates: the selected layout's own checks.
  const chosen = Number(String(physical.optimization?.selected ?? "").split("-").pop());
  const layout = Number.isInteger(chosen) && physical.optimization?.selected ? chosen + 1 : gates.drc?.layout;
  if (loopState) loopState = {...loopState, done: true, selected: layout, total: physical.optimization?.evaluations ?? loopState.total};
  gates = {drc: {status: drcClean ? "passed" : "failed", errors: physical.layout.drc_errors, layout, selected: true},
            lvs: {status: lvsMatched ? "passed" : "failed", devices: physical.lvs.devices, nets: physical.lvs.nets, layout, selected: true}};
  renderStages();
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
  if (!trace) return;
  $("analog-quality").hidden = false;
  const plan = physical.layout.plan;
  $("layout-plan-note").textContent = plan.pair_pattern ?
    `${plan.pair_pattern === "abba" ? "Common-centroid pairs" : "Mirrored pairs"} · ${plan.rail_um} µm rails · ${plan.dummies ? "edge dummies" : "no dummies"}${plan.decap ? " · MOS decap" : ""}` :
    `${plan.pattern} · ${plan.columns} column(s) · ${plan.dummies ? "edge dummies" : "no dummies"}`;
  $("analog-facts").hidden = $("analog-waveforms").hidden = !bench;
  const area = row => row.quality?.area_um2 ?? row.area_um2;
  const first = trace.history.find(row => row.valid), chosen = physical.layout.area_um2;
  const delta = first ? (1 - chosen / area(first)) * 100 : 0;
  const clean = trace.history.filter(row => row.drc === 0).length, matched = trace.history.filter(row => row.lvs === true).length;
  $("optimization-summary").textContent = trace.pareto_plan_ids ?
    `${trace.evaluations} layouts evaluated in ${trace.wall_seconds.toFixed(2)} s · ${trace.first_feasible_seconds?.toFixed(2) ?? "—"} s to first qualified layout · ${delta.toFixed(1)}% area reduction from that layout · ${trace.pareto_plan_ids.length} Pareto candidates. Laya proposes actions; DRC, LVS and ngspice decide acceptance.` :
    `${trace.evaluations} layouts evaluated in ${trace.wall_seconds.toFixed(2)} s, ${trace.parallel} in parallel · ${clean}/${trace.evaluations} DRC clean · ${matched}/${trace.evaluations} LVS matched · ${delta.toFixed(1)}% area reduction from the first qualified layout. Laya and the layout knowledge cards propose actions; DRC, LVS and ngspice decide acceptance.`;
  $("physical-status").textContent = `${physical.layout.layout_seconds.toFixed(2)} s final layout + DRC · ${trace.wall_seconds.toFixed(2)} s complete layout optimization · fixed input bias ${trace.fixed_input_bias_v.toFixed(4)} V`;
  const rows = trace.history.map(item => {
    const row = document.createElement("tr");
    const reasons = Object.entries({...item.qualification_checks, ...item.checks}).filter(([, pass]) => !pass).map(([name]) => name).join(", ");
    const rejection = item.drc > 0 ? `${item.drc} DRC violations` : item.lvs === false ? "LVS mismatch" : item.error || reasons;
    const decision = item.valid ? item.accepted ? (item.index === 0 ? "Initial feasible layout" : "Accepted improvement") : "Qualified; retained incumbent" : `Rejected: ${rejection}`;
    const number = v => Number.isFinite(v) ? v.toFixed(2) : "—";
    const drc = Number.isInteger(item.drc) ? (item.drc === 0 ? "✓ 0 errors" : `✗ ${item.drc} errors`) : "—";
    const lvs = typeof item.lvs === "boolean" ? (item.lvs ? "✓ Matched" : "✗ Mismatch") : "—";
    for (const value of [`${item.index + 1} / ${layoutActions[item.action] || item.action}`, drc, lvs, number(area(item)), number(item.metrics?.gain_db), number(item.metrics?.gbw_mhz), decision]) {
      const cell = document.createElement("td"); cell.textContent = value; row.append(cell);
    }
    return row;
  });
  $("optimization-body").replaceChildren(...rows);
  const hotspots = Object.entries(physical.quality.net_capacitance_ff).filter(([n]) => !["vdd", "vss"].includes(n)).sort((a, b) => b[1] - a[1]).slice(0, 3);
  $("parasitic-note").textContent = `Largest node parasitics: ${hotspots.map(([n, c]) => `${n} ${c.toFixed(2)} fF`).join(" · ")}. Input capacitance imbalance: ${physical.quality.input_cap_imbalance_ff?.toFixed(2) ?? "—"} fF. Centroid error: ${physical.quality.centroid_error_um.toFixed(2)} µm (geometry only).`;
  if (!bench) return;
  const metrics = bench.metrics;
  for (const [id, key, scale, unit] of [["noise-result", "input_noise_rms_v", 1e6, "µV RMS"], ["psrr-result", "psrr_min_db", 1, "dB"], ["ir-result", "internal_supply_drop_v", 1e3, "mV"], ["ground-result", "internal_ground_rise_v", 1e3, "mV"]]) {
    $(id).textContent = Number.isFinite(metrics[key]) ? `${(metrics[key] * scale).toFixed(2)} ${unit}` : "Not measured";
  }
  const waves = bench.waveforms, x = waves.frequency_hz.map(Math.log10);
  const noise = waves.input_noise_v_sqrt_hz.map(v => v * 1e9), psrr = waves.psrr_db;
  chart("noise-plot", "Measured input noise density", "Frequency (Hz)", "nV/√Hz", [x[0], x.at(-1)], [0, Math.max(...noise) * 1.05], [[1, "10"], [3, "1k"], [6, "1M"]], [{x, y: noise, color: "#087ebd"}]);
  chart("psrr-plot", "Measured supply rejection", "Frequency (Hz)", "PSRR (dB)", [x[0], x.at(-1)], [Math.floor(Math.min(...psrr) / 10) * 10, Math.ceil(Math.max(...psrr) / 10) * 10 + 1], [[1, "10"], [3, "1k"], [6, "1M"]], [{x, y: psrr, color: "#087ebd"}]);
  const c = bench.conditions;
  $("analog-conditions").textContent = `Fixture: ${c.supply_resistance_ohm} Ω supply impedance, ${c.load_step_a * 1e6} µA load step, ${c.temperature_c} °C. Peak supply droop: ${(metrics.supply_droop_v * 1e3).toFixed(3)} mV. These measurements do not establish substrate-noise, thermal, EM or mismatch signoff.`;
}

function complete(ok) {
  pumpStages(true);
  finished = true; running = false; clock.stop(); clearInterval(timer); renderTime();
  $("examples").disabled = false;
  $("live-dot").classList.remove("active");
  $("stream-label").textContent = ok ? "RUN COMPLETE" : "RUN STOPPED";
  $("frame-note").textContent = ok ? "Final xschem + Magic frame · selected layout" : "Last received xschem + Magic frame";
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
      .then(blob => { if (completedId !== runId || !finished) return; if (layoutURL) URL.revokeObjectURL(layoutURL); layoutURL = URL.createObjectURL(blob); $("view-layout").disabled = false; })
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
      $("schematic-live-status").textContent = data.stage === "searching" ? `Search round ${(data.search.round ?? 0) + 1}` : "Selected circuit";
      if (data.search.topology) $("schematic-live-note").textContent = `${data.search.topology} · ${data.search.mosfets} MOSFETs`;
    }
    const iteration = data.layout_iteration;
    if (iteration && iteration.displayed !== false && Number.isInteger(iteration.index)) {
      $("magic-waiting").hidden = true;
      const phase = {layout: "Generating next layout", drc: "Magic DRC", lvs: "Netgen LVS", extracting: "RC extraction", postsimulating: "Post-layout simulation"};
      const decision = iteration.status === "selected" ? "Selected layout" : iteration.status === "evaluated" ?
        (iteration.accepted ? "Accepted improvement" : iteration.valid ? "Qualified · keeping incumbent" : "Rejected") : (phase[iteration.phase] || "Layout + DRC complete");
      $("magic-live-status").textContent = `Layout ${iteration.index + 1} · ${decision}`;
      $("magic-live-note").textContent = `${layoutActions[iteration.action] || iteration.action}${iteration.area_um2 == null ? "" : ` · ${iteration.area_um2.toFixed(0)} µm²`} · ${decision}`;
    }
    queueStage({stage: data.stage, message: data.message, progress: data.progress,
      gates: data.verification ? {...data.verification} : null, loop: data.loop ? {...data.loop} : null});
    badge(data.stage === "complete" ? "Verified" : data.stage === "unqualified" ? "Unqualified" : "Running", data.stage === "complete" ? "success" : "");
  } else if (data.type === "waveforms") drawResponses(data, data.postlayout);
  else if (data.type === "result") showResult(data);
  else if (data.type === "error") { error(data.message); complete(false); }
}

function connect() {
  const url = new URL(`${api}/api/runs/${runId}/live`); url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  socket = new WebSocket(url); socket.binaryType = "blob";
  socket.onopen = () => { replayUntil = performance.now() + 1500; $("availability").textContent = "Connected to live xschem + Magic"; };
  socket.onmessage = ({ data }) => {
    if (data instanceof Blob) {
      const previous = frameURL; frameURL = URL.createObjectURL(data);
      $("frame").src = $("magic-frame").src = frameURL;
      $("frame").alt = "Live native xschem editor showing this run’s circuit";
      $("magic-frame").alt = "Live native Magic editor showing this run’s layout candidate";
      if (previous) URL.revokeObjectURL(previous);
      $("stream-label").textContent = "LIVE XSCHEM + MAGIC"; $("live-dot").classList.add("active");
      $("frame-note").textContent = "Synchronized capture · private virtual display · view-only";
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
const drawn = new Map();  // plot id -> its latest chart arguments, redrawn when the plot is resized
const resized = new ResizeObserver((entries) => {
  for (const entry of entries) { const args = drawn.get(entry.target.id); if (args) requestAnimationFrame(() => chart(...args)); }
});
function svgNode(name, attrs = {}, text) {
  const node = document.createElementNS(NS, name);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  if (text !== undefined) node.textContent = text;
  return node;
}
function chart(container, title, xLabel, yLabel, xDomain, yDomain, xTicks, series, rightLabel) {
  const node = $(container), box = node.getBoundingClientRect();
  drawn.set(container, [container, title, xLabel, yLabel, xDomain, yDomain, xTicks, series, rightLabel]); resized.observe(node);
  const rem = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16, size = Math.max(9, 0.64 * rem);
  const W = Math.max(box.width, 240), H = Math.max(box.height, 120);
  const L = 3.2 * size, R = rightLabel ? 3.2 * size : 1.4 * size, T = 1.5 * size, B = 3 * size;
  const width = W - L - R, height = H - T - B;
  const sx = (x) => L + (x - xDomain[0]) / (xDomain[1] - xDomain[0]) * width;
  const sy = (y, domain = yDomain) => T + height - (y - domain[0]) / (domain[1] - domain[0]) * height;
  const svg = svgNode("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": title });
  const rightDomain = rightLabel ? series.find((line) => line.domain).domain : null;
  svg.append(svgNode("title", {}, title));
  const textStyle = { fill: "#697c8e", "font-size": size, "font-family": "Arial, sans-serif" };
  for (let i = 0; i <= 4; i++) {
    const value = yDomain[0] + i * (yDomain[1] - yDomain[0]) / 4, y = sy(value);
    svg.append(svgNode("line", { x1: L, y1: y, x2: W - R, y2: y, stroke: "#e9eef3", "stroke-width": 1 }));
    svg.append(svgNode("text", { x: L - 0.7 * size, y: y + 0.35 * size, "text-anchor": "end", ...textStyle }, String(Math.round(value))));
    if (rightLabel) svg.append(svgNode("text", { x: W - R + 0.7 * size, y: y + 0.35 * size, ...textStyle }, String(Math.round(rightDomain[0] + i * (rightDomain[1] - rightDomain[0]) / 4))));
  }
  for (const [value, label] of xTicks) {
    svg.append(svgNode("line", { x1: sx(value), y1: T, x2: sx(value), y2: H - B, stroke: "#eef2f6" }));
    svg.append(svgNode("text", { x: sx(value), y: H - B + 1.5 * size, "text-anchor": "middle", ...textStyle }, label));
  }
  for (const line of series) {
    const points = line.x.map((x, i) => `${i ? "L" : "M"}${sx(x).toFixed(2)},${sy(line.y[i], line.domain).toFixed(2)}`).join(" ");
    svg.append(svgNode("path", { d: points, fill: "none", stroke: line.color, "stroke-width": line.dash ? 1.6 : 2, "stroke-linejoin": "round", ...(line.dash ? { "stroke-dasharray": "5 4" } : {}) }));
  }
  svg.append(svgNode("text", { x: L + width / 2, y: H - 0.4 * size, "text-anchor": "middle", ...textStyle }, xLabel));
  svg.append(svgNode("text", { x: L - 2.6 * size, y: 0.9 * size, ...textStyle }, yLabel));
  if (rightLabel) svg.append(svgNode("text", { x: W, y: 0.9 * size, "text-anchor": "end", ...textStyle }, rightLabel));
  node.replaceChildren(svg);
}
// Schematic (dashed, lighter) and after RC extraction (solid) on the same axes.
function drawResponses(pre, post) {
  const runs = post ? [[pre, true], [post, false]] : [[pre, false]];
  const gains = runs.flatMap(([d]) => d.gain_db), phases = runs.flatMap(([d]) => d.phase_deg);
  const phaseDomain = [Math.floor(Math.min(...phases) / 90) * 90, Math.ceil(Math.max(...phases) / 90) * 90];
  chart("ac-plot", "Measured open-loop gain and phase versus frequency, schematic dashed and after RC extraction solid", "Frequency (Hz)", "Gain (dB)", [0, 11],
    [Math.floor(Math.min(...gains) / 20) * 20, Math.ceil(Math.max(...gains) / 20) * 20], [[0, "1"], [3, "1k"], [6, "1M"], [9, "1G"], [11, "100G"]],
    runs.flatMap(([d, dash]) => { const f = d.frequency_hz.map(Math.log10); return [
      { x: f, y: d.gain_db, color: dash ? "#8fc2e2" : "#087ebd", dash },
      { x: f, y: d.phase_deg, color: dash ? "#c3c1de" : "#8b88b7", domain: phaseDomain, dash },
    ]; }), "Phase (°)");
  const waves = runs.flatMap(([d, dash]) => d.steps.filter((step) => step.waveform).map((step) => ({ ...step, dash })));
  if (!waves.length) { const note = document.createElement("p"); note.textContent = "Closed-loop qualification did not produce a waveform"; $("step-plot").replaceChildren(note); drawn.delete("step-plot"); return; }
  const times = waves.flatMap((step) => step.waveform.t_us), low = Math.min(...times), high = Math.max(...times);
  const amplitude = Math.max(12, Math.ceil(Math.max(...waves.flatMap((step) => step.waveform.delta_mv.map(Math.abs))) / 2) * 2);
  const ticks = Array.from({ length: 5 }, (_, i) => { const n = i * high / 4; return [n, n.toFixed(1)]; });
  chart("step-plot", "Measured positive and negative 10 millivolt unity-buffer step responses, schematic dashed and after RC extraction solid", "Time after input step (µs)", "Output change (mV)", [low, high], [-amplitude, amplitude], ticks,
    waves.map((step) => ({ x: step.waveform.t_us, y: step.waveform.delta_mv, dash: step.dash,
      color: step.direction > 0 ? (step.dash ? "#8fc2e2" : "#087ebd") : (step.dash ? "#efbd8c" : "#de892f") })));
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
    $("magic-waiting").hidden = true;
    $("schematic-live-status").textContent = "Reference schematic";
    $("magic-live-status").textContent = "Reference layout";
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
