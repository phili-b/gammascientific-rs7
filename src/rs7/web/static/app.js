"use strict";

const $ = (id) => document.getElementById(id);
const THROTTLE_MS = 150; // slider drags are sent at most this often
const POLL_MS = 2500;

let info = null; // /api/info
let state = null; // last /api/state
const sliders = {}; // channel -> {input, value}
const pending = {}; // channel -> power waiting to be sent
let pendingMain = null;
let flushTimer = null;
let sending = false;
let refreshing = false;
let refreshAgain = false;
let matching = false;
const held = new Set(); // sliders the user is holding ("main" or a channel number)

// ---- talking to the server -------------------------------------------------------------------

async function api(method, url, body) {
  const res = await fetch(url, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const d = data.detail;
    throw new Error(Array.isArray(d) ? d.map((e) => `${e.loc.slice(1).join(".")}: ${e.msg}`).join("; ") : d || res.statusText);
  }
  return data;
}

function setStatus(message, isError = false) {
  const el = $("status");
  el.textContent = message;
  el.classList.toggle("error", isError);
}

/** Run an action; show its message in the status line, or the error. Returns true on success. */
async function run(message, action) {
  try {
    await action();
    setStatus(message);
    return true;
  } catch (e) {
    setStatus(e.message, true);
    return false;
  }
}

function stateQuery() {
  const q = new URLSearchParams({
    plot_all: $("plot-all").checked,
    start: $("plot-start").value,
    end: $("plot-end").value,
    target: $("target").value.trim(),
    fit_start: $("fit-start").value,
    fit_end: $("fit-end").value,
  });
  return q.toString();
}

/** Read the unit's state and alarm and show them. Calls that arrive meanwhile are merged into one more round. */
async function refresh() {
  if (refreshing) {
    refreshAgain = true;
    return;
  }
  refreshing = true;
  try {
    do {
      refreshAgain = false;
      const [st, alarm] = await Promise.all([api("GET", "/api/state?" + stateQuery()), api("GET", "/api/alarm")]);
      state = st;
      showState();
      showAlarm(alarm.alarm);
    } while (refreshAgain);
  } catch (e) {
    setStatus(e.message, true);
  } finally {
    refreshing = false;
  }
}

// ---- sliders: send while moving, throttled, never echo what the program sets ------------------

function flushSoon(now = false) {
  if (flushTimer && !now) return;
  clearTimeout(flushTimer);
  flushTimer = setTimeout(flush, now ? 0 : THROTTLE_MS);
}

async function flush() {
  flushTimer = null;
  if (sending) {
    flushSoon();
    return;
  }
  const channels = Object.entries(pending);
  const main = pendingMain;
  for (const ch of Object.keys(pending)) delete pending[ch];
  pendingMain = null;
  sending = true;
  try {
    for (const [ch, power] of channels) {
      await api("POST", "/api/channel", { channel: Number(ch), power });
      setStatus(`Channel ${ch}: ${power.toFixed(2)} %`);
    }
    if (main !== null) {
      await api("POST", "/api/output", { level: main, keep_chromaticity: $("keep").checked });
      setStatus(`Main power: ${main.toFixed(2)} %`);
    }
  } catch (e) {
    setStatus(e.message, true);
  } finally {
    sending = false;
  }
  if (Object.keys(pending).length || pendingMain !== null) flushSoon();
  else refresh();
}

/** Wire a range input: ``moved(value)`` is only called for the user's moves (setting .value never fires "input"). */
function watchSlider(key, input, moved) {
  input.addEventListener("input", () => moved(Number(input.value)));
  input.addEventListener("change", () => flushSoon(true));
  input.addEventListener("pointerdown", () => held.add(key)); // released by the window listener below
}

function buildChannels() {
  const box = $("channels");
  for (const c of info.channels) {
    const row = document.createElement("div");
    row.className = "slider-row";
    const name = document.createElement("span");
    name.className = "name";
    name.title = `Channel ${c.channel}: ${c.wavelength} nm, FWHM ${c.fwhm} nm`;
    const swatch = document.createElement("span");
    swatch.className = "swatch";
    swatch.style.background = c.color;
    name.append(swatch, `${c.channel} · ${Math.round(c.wavelength)} nm`);
    const input = document.createElement("input");
    input.type = "range";
    input.min = 0;
    input.max = 100;
    input.step = 0.01;
    input.value = 0;
    input.style.accentColor = c.color;
    input.setAttribute("aria-label", `Channel ${c.channel}`);
    const value = document.createElement("output");
    value.textContent = "0.00";
    row.append(name, input, value);
    box.append(row);
    sliders[c.channel] = { input, value };
    watchSlider(c.channel, input, (v) => {
      value.textContent = v.toFixed(2);
      pending[c.channel] = v;
      flushSoon();
    });
  }
}

function setSlider(key, input, valueEl, percent) {
  if (held.has(key)) return; // never yank a slider out of the user's hand
  input.value = percent;
  valueEl.textContent = percent.toFixed(2);
}

// ---- showing the state ------------------------------------------------------------------------

const num = (v, digits) => (v === null || v === undefined ? "-" : v.toFixed(digits));
const prec = (v, digits) => (v === null || v === undefined ? "-" : v.toPrecision(digits));

function showState() {
  const st = state;
  for (const [ch, s] of Object.entries(sliders)) {
    if (ch in pending) continue; // a newer value is on its way
    setSlider(Number(ch), s.input, s.value, st.powers[ch] ?? 0);
  }
  if (pendingMain === null) setSlider("main", $("main"), $("main-value"), st.power);

  $("r-power").textContent = num(st.power, 3);
  $("r-rad").textContent = prec(st.rad, 4);
  $("r-lum").textContent = prec(st.lum, 4);
  $("r-cct").textContent = st.cct ? Math.round(st.cct) : "-";
  $("r-x").textContent = st.xy ? num(st.xy[0], 4) : "-";
  $("r-y").textContent = st.xy ? num(st.xy[1], 4) : "-";

  const rep = st.report;
  $("q-level").textContent = `${prec(rep.photometric, 4)} ${info.phot_unit}`;
  $("q-cct").textContent = `${num(rep.cct, 0)} K / ${rep.duv === null ? "-" : (rep.duv >= 0 ? "+" : "") + rep.duv.toFixed(4)}`;
  $("q-uv").textContent = rep.uv_prime ? `${num(rep.uv_prime[0], 4)}, ${num(rep.uv_prime[1], 4)}` : "-";
  $("q-cri").textContent = `${num(rep.cri_ra, 1)} / ${num(rep.cri_r?.["9"], 1)}`;
  $("q-cri").title = Object.entries(rep.cri_r || {}).map(([i, v]) => `R${i} ${v.toFixed(0)}`).join("  ");
  $("q-tm30").textContent = `${num(rep.tm30_rf, 1)} / ${num(rep.tm30_rg, 1)}`;

  const t = st.target;
  const delta = $("q-delta");
  delta.className = "";
  if (t) {
    $("q-target").textContent = `${t.description}: ${num(t.report.cct, 0)} K, Ra ${num(t.report.cri_ra, 0)}`;
    const d = t.comparison.delta_uv_prime;
    delta.textContent = num(d, 4);
    if (d !== null) delta.className = d < 0.001 ? "ok" : d < 0.005 ? "warn" : "bad";
    $("q-rms").textContent = `${num(t.comparison.spectral_rms, 1)} %`;
  } else {
    $("q-target").textContent = st.target_error || "-";
    delta.textContent = "-";
    $("q-rms").textContent = "-";
  }
  drawSpectrum();
  drawChart();
}

function showAlarm(alarm) {
  const active = alarm !== "NONE";
  $("alarm").textContent = active ? alarm : "No alarm";
  $("alarm").classList.toggle("active", active);
}

// ---- drawing: spectrum and CIE chart on <canvas> ----------------------------------------------

const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

function prepare(canvas) {
  const r = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.round(r.width * dpr);
  canvas.height = Math.round(r.height * dpr);
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.font = "11px system-ui, sans-serif";
  return { ctx, w: r.width, h: r.height };
}

function line(ctx, points, color, width = 1.5) {
  if (points.length < 2) return;
  ctx.beginPath();
  points.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
  ctx.strokeStyle = color;
  ctx.lineWidth = width;
  ctx.stroke();
}

function drawSpectrum() {
  if (!state) return;
  const { ctx, w, h } = prepare($("spectrum"));
  const start = Number($("plot-start").value);
  const end = Number($("plot-end").value);
  const series = [{ data: state.spec, color: css("--fg"), width: 2 }];
  for (const [ch, data] of Object.entries(state.chan_specs || {})) {
    series.push({ data, color: info.channels.find((c) => c.channel === Number(ch))?.color || "red", width: 1 });
  }
  if (state.target) series.push({ data: state.target.spectrum.filter(([nm]) => nm >= start && nm <= end), color: css("--target"), width: 1.5 });

  const left = 50, right = 10, top = 10, bottom = 24;
  const ymax = Math.max(...series.flatMap((s) => s.data.map(([, v]) => v)), 0) || 1;
  const x = (nm) => left + ((nm - start) / Math.max(end - start, 1)) * (w - left - right);
  const y = (v) => h - bottom - (v / ymax) * (h - bottom - top);

  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = css("--muted");
  ctx.strokeStyle = css("--line");
  ctx.lineWidth = 1;
  ctx.textAlign = "right";
  for (let i = 0; i <= 4; i++) {
    const v = (ymax * i) / 4;
    ctx.beginPath();
    ctx.moveTo(left, y(v));
    ctx.lineTo(w - right, y(v));
    ctx.stroke();
    ctx.fillText(v.toPrecision(2), left - 6, y(v) + 4);
  }
  ctx.textAlign = "center";
  for (let nm = start - (start % 50) + 50; nm < end; nm += 50) ctx.fillText(nm, x(nm), h - bottom + 15);
  for (const s of series) line(ctx, s.data.map(([nm, v]) => [x(nm), y(v)]), s.color, s.width);

  ctx.textAlign = "right";
  ctx.fillStyle = css("--fg");
  ctx.fillText("output", w - right, top + 10);
  if (state.target) {
    ctx.fillStyle = css("--target");
    ctx.fillText(state.target.description, w - right, top + 24);
  }
  $("spectrum-caption").textContent = `µW/cm²/nm${info.phot_unit === "lux" ? "" : " per sr"}`;
}

function drawChart() {
  if (!state || !info) return;
  const { ctx, w, h } = prepare($("cie"));
  const X_MAX = 0.8, Y_MAX = 0.9, pad = 10;
  const px = ([x, y]) => [pad + (x / X_MAX) * (w - 2 * pad), h - pad - (y / Y_MAX) * (h - 2 * pad)];

  ctx.clearRect(0, 0, w, h);
  ctx.beginPath();
  info.locus.forEach(([, x, y], i) => (i ? ctx.lineTo(...px([x, y])) : ctx.moveTo(...px([x, y]))));
  ctx.closePath();
  ctx.fillStyle = css("--canvas");
  ctx.fill();
  ctx.strokeStyle = css("--muted");
  ctx.lineWidth = 1;
  ctx.stroke();

  ctx.fillStyle = css("--muted");
  ctx.textAlign = "center";
  for (const [nm, x, y] of info.locus) {
    if (nm >= 460 && nm <= 620 && nm % 20 === 0) {
      const [cx, cy] = px([x, y]);
      ctx.fillText(nm, cx + (x < 0.3 ? -14 : 14), cy + 4);
    }
  }
  line(ctx, info.planckian.map(px), css("--muted"), 1);
  for (const [label, x, y] of info.planckian_marks) {
    const [cx, cy] = px([x, y]);
    ctx.fillText(label, cx, cy + 14);
  }

  if (state.target?.report.xy) {
    const [cx, cy] = px(state.target.report.xy);
    line(ctx, [[cx - 6, cy - 6], [cx + 6, cy + 6]], css("--target"), 2);
    line(ctx, [[cx - 6, cy + 6], [cx + 6, cy - 6]], css("--target"), 2);
  }
  if (state.xy) {
    const [cx, cy] = px(state.xy);
    ctx.beginPath();
    ctx.arc(cx, cy, 5, 0, 2 * Math.PI);
    ctx.strokeStyle = css("--fg");
    ctx.lineWidth = 2;
    ctx.stroke();
  }
}

// ---- presets ----------------------------------------------------------------------------------

async function loadPresets() {
  try {
    const { presets, current } = await api("GET", "/api/presets");
    const select = $("presets");
    select.replaceChildren();
    for (const p of presets) {
      const option = new Option(`${p.number} - ${p.name}${p.number === current ? "  (loaded)" : ""}`, p.number);
      option.selected = p.number === current;
      select.append(option);
    }
    const used = new Set(presets.map((p) => p.number));
    let free = 1;
    while (used.has(free) && free < 99) free++;
    $("store-number").value = free;
  } catch (e) {
    setStatus(e.message, true);
  }
}

function selectedPreset() {
  const v = $("presets").value;
  if (v === "") setStatus("Select a preset first", true);
  return v === "" ? null : Number(v);
}

$("recall").addEventListener("click", async () => {
  const n = selectedPreset();
  if (n !== null && (await run(`Preset ${n} loaded`, () => api("POST", `/api/presets/${n}/recall`)))) {
    loadPresets();
    refresh();
  }
});

$("delete").addEventListener("click", async () => {
  const n = selectedPreset();
  if (n !== null && confirm(`Delete preset ${n}?`) && (await run(`Preset ${n} deleted`, () => api("DELETE", `/api/presets/${n}`)))) {
    loadPresets();
  }
});

$("store-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const n = Number($("store-number").value);
  const taken = [...$("presets").options].some((o) => Number(o.value) === n);
  if (taken && !confirm(`Preset ${n} exists. Overwrite it?`)) return;
  const name = $("store-name").value;
  if (await run(`Preset ${n} stored`, () => api("PUT", `/api/presets/${n}`, { name }))) loadPresets();
});

// ---- target match -----------------------------------------------------------------------------

$("match-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const level = $("level").value.trim();
  const body = {
    target: $("target").value.trim(),
    level: level === "" ? null : Number(level),
    units: $("level-units").value,
    at_max: $("at-max").checked,
    start: Number($("fit-start").value),
    end: Number($("fit-end").value),
    method: $("method").value,
    correct_chromaticity: $("correct").checked,
  };
  matching = true;
  $("match-button").disabled = true;
  $("match-result").textContent = "matching...";
  setStatus(body.method === "local" ? "Matching... (the first local fit measures every channel, about 25 s)" : "Matching...");
  try {
    const r = await api("POST", "/api/match", body);
    const c = r.comparison;
    const unitRms = r.unit_rms_error === null ? "" : `, unit RMS error ${r.unit_rms_error.toFixed(1)} %`;
    $("match-result").textContent =
      `Matched ${r.description} at ${prec(r.output.photometric, 4)} ${info.phot_unit}: ` +
      `Δu'v' ${num(c.delta_uv_prime, 4)}, spectral RMS ${num(c.spectral_rms, 1)} %${unitRms}`;
    setStatus("Match done");
  } catch (e) {
    $("match-result").textContent = "";
    setStatus(e.message, true);
  } finally {
    matching = false;
    $("match-button").disabled = false;
  }
  refresh();
});

$("at-max").addEventListener("change", () => ($("level").disabled = $("at-max").checked));

// ---- start ------------------------------------------------------------------------------------

watchSlider("main", $("main"), (v) => {
  $("main-value").textContent = v.toFixed(2);
  pendingMain = v;
  flushSoon();
});

$("all-off").addEventListener("click", async () => {
  if (await run("All channels off", () => api("POST", "/api/all_off"))) refresh();
});

$("alarm").addEventListener("click", async () => {
  try {
    showAlarm((await api("POST", "/api/alarm")).alarm);
  } catch (e) {
    setStatus(e.message, true);
  }
});

// changing what is shown reads the state again
for (const id of ["plot-start", "plot-end", "plot-all", "target", "fit-start", "fit-end"]) $(id).addEventListener("change", refresh);

window.addEventListener("resize", () => {
  drawSpectrum();
  drawChart();
});
window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
  drawSpectrum();
  drawChart();
});
for (const type of ["pointerup", "pointercancel"]) window.addEventListener(type, () => held.clear());

setInterval(() => {
  if (info && !sending && !flushTimer && !matching && held.size === 0) refresh();
}, POLL_MS);

(async () => {
  try {
    info = await api("GET", "/api/info");
  } catch (e) {
    setStatus(e.message, true);
    return;
  }
  $("unit").textContent = `firmware ${info.version} · LED board ${info.serial}`;
  $("l-rad").textContent = info.rad_label;
  $("l-lum").textContent = info.lum_label;
  $("u-lum").textContent = info.phot_unit;
  $("illuminants").replaceChildren(...info.illuminants.map((name) => new Option(name)));
  buildChannels();
  await loadPresets();
  await refresh();
  if (!$("status").classList.contains("error")) setStatus("Connected");
})();
