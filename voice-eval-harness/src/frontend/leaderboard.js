"use strict";

// ── State ─────────────────────────────────────────────────────────────────────

const state = {
  results: [],        // ScenarioResult[]
  trials: [],         // TrialResult[] (summary)
  filterPlatform: "", // "" = all
  filterScenario: "", // "" = all
  charts: {},
};

// ── Fetch helpers ─────────────────────────────────────────────────────────────

async function fetchJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

// ── Init ──────────────────────────────────────────────────────────────────────

async function init() {
  try {
    [state.results, state.trials] = await Promise.all([
      fetchJSON("/api/results"),
      fetchJSON("/api/trials"),
    ]);
  } catch (e) {
    document.getElementById("leaderboard").innerHTML =
      `<p class="empty">Could not load results: ${e.message}</p>`;
    return;
  }

  populateFilters();
  render();
}

// ── Filters ───────────────────────────────────────────────────────────────────

function populateFilters() {
  const platforms = [...new Set(state.results.map((r) => r.platform))].sort();
  const scenarios = [...new Set(state.results.map((r) => r.scenario_id))].sort();

  const pSel = document.getElementById("filter-platform");
  const sSel = document.getElementById("filter-scenario");

  platforms.forEach((p) => {
    const o = document.createElement("option");
    o.value = p;
    o.textContent = p;
    pSel.appendChild(o);
  });

  scenarios.forEach((s) => {
    const o = document.createElement("option");
    o.value = s;
    o.textContent = s;
    sSel.appendChild(o);
  });

  pSel.addEventListener("change", () => { state.filterPlatform = pSel.value; render(); });
  sSel.addEventListener("change", () => { state.filterScenario = sSel.value; render(); });
  document.getElementById("btn-refresh").addEventListener("click", () => location.reload());
}

function filteredResults() {
  return state.results.filter((r) => {
    if (state.filterPlatform && r.platform !== state.filterPlatform) return false;
    if (state.filterScenario && r.scenario_id !== state.filterScenario) return false;
    return true;
  });
}

function filteredTrials() {
  return state.trials.filter((t) => {
    if (state.filterPlatform && t.platform !== state.filterPlatform) return false;
    if (state.filterScenario && t.scenario_id !== state.filterScenario) return false;
    return true;
  });
}

// ── Render ────────────────────────────────────────────────────────────────────

function render() {
  renderLeaderboard();
  renderCharts();
  renderTrials();
}

// ── Leaderboard table ─────────────────────────────────────────────────────────

function msLabel(s) {
  if (s == null) return `<span class="na">—</span>`;
  const ms = Math.round(s * 1000);
  const cls = ms < 500 ? "good" : ms < 1000 ? "ok" : "bad";
  return `<span class="${cls}">${ms}</span>`;
}

function pctLabel(v) {
  if (v == null) return `<span class="na">—</span>`;
  const pct = Math.round(v * 100);
  const cls = pct >= 90 ? "good" : pct >= 70 ? "ok" : "bad";
  return `<span class="${cls}">${pct}%</span>`;
}

function renderLeaderboard() {
  const el = document.getElementById("leaderboard");
  const rows = filteredResults();

  if (rows.length === 0) {
    el.innerHTML = `<p class="empty">No results yet. Run the benchmark to populate the leaderboard.</p>`;
    return;
  }

  const headerHtml = `
    <div class="lb-row header-row">
      <span style="color:var(--muted);font-size:11px;font-weight:600;text-transform:uppercase">Platform</span>
      <span style="color:var(--muted);font-size:11px;font-weight:600;text-transform:uppercase">Scenario</span>
      <span style="color:var(--muted);font-size:11px;font-weight:600;text-transform:uppercase">TTFR median</span>
      <span style="color:var(--muted);font-size:11px;font-weight:600;text-transform:uppercase">Barge-in median</span>
      <span style="color:var(--muted);font-size:11px;font-weight:600;text-transform:uppercase">Tool accuracy</span>
      <span style="color:var(--muted);font-size:11px;font-weight:600;text-transform:uppercase">Turn completion</span>
    </div>
  `;

  const rowsHtml = rows
    .map(
      (r) => `
    <div class="lb-row" onclick="openScenario('${r.platform}','${r.scenario_id}')">
      <span class="platform">${r.platform}</span>
      <span class="scenario">${r.scenario_id}</span>
      <div class="metric-cell">
        <div class="val">${msLabel(r.ttfr?.median_s)}<span style="font-size:12px;font-weight:400;color:var(--muted)"> ms</span></div>
        <div class="p95">p95 ${r.ttfr?.p95_s != null ? Math.round(r.ttfr.p95_s * 1000) + " ms" : "—"}</div>
      </div>
      <div class="metric-cell">
        <div class="val">${msLabel(r.barge_in?.median_s)}<span style="font-size:12px;font-weight:400;color:var(--muted)"> ms</span></div>
        <div class="p95">p95 ${r.barge_in?.p95_s != null ? Math.round(r.barge_in.p95_s * 1000) + " ms" : "—"}</div>
      </div>
      <div class="metric-cell">
        <div class="val">${pctLabel(r.tool_call_accuracy_rate)}</div>
        <div class="sub">${r.trial_count} trials</div>
      </div>
      <div class="metric-cell">
        <div class="val">${pctLabel(r.turn_completion_rate)}</div>
      </div>
    </div>
  `
    )
    .join("");

  el.innerHTML = `<div class="leaderboard-grid">${headerHtml}${rowsHtml}</div>`;
}

// ── Charts ────────────────────────────────────────────────────────────────────

function renderCharts() {
  const rows = filteredResults();
  if (rows.length === 0) {
    document.getElementById("charts-section").style.display = "none";
    return;
  }
  document.getElementById("charts-section").style.display = "";

  const labels = rows.map((r) => `${r.platform}\n${r.scenario_id}`);

  drawBarChart("chart-ttfr", "Time-to-First-Response (ms)", labels, {
    median: rows.map((r) => r.ttfr?.median_s != null ? Math.round(r.ttfr.median_s * 1000) : null),
    p95: rows.map((r) => r.ttfr?.p95_s != null ? Math.round(r.ttfr.p95_s * 1000) : null),
  });

  drawBarChart("chart-barge", "Barge-in Response Time (ms)", labels, {
    median: rows.map((r) => r.barge_in?.median_s != null ? Math.round(r.barge_in.median_s * 1000) : null),
    p95: rows.map((r) => r.barge_in?.p95_s != null ? Math.round(r.barge_in.p95_s * 1000) : null),
  });

  drawRateChart("chart-toolacc", "Tool Call Accuracy", labels,
    rows.map((r) => r.tool_call_accuracy_rate != null ? Math.round(r.tool_call_accuracy_rate * 100) : null));

  drawRateChart("chart-completion", "Turn Completion Rate", labels,
    rows.map((r) => r.turn_completion_rate != null ? Math.round(r.turn_completion_rate * 100) : null));
}

function drawBarChart(canvasId, title, labels, data) {
  const ctx = document.getElementById(canvasId)?.getContext("2d");
  if (!ctx) return;

  if (state.charts[canvasId]) state.charts[canvasId].destroy();

  state.charts[canvasId] = new Chart(ctx, {
    type: "bar",
    data: {
      labels,
      datasets: [
        {
          label: "Median",
          data: data.median,
          backgroundColor: "rgba(99,102,241,0.7)",
          borderRadius: 4,
        },
        {
          label: "p95",
          data: data.p95,
          backgroundColor: "rgba(99,102,241,0.3)",
          borderRadius: 4,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { labels: { color: "#94a3b8", font: { size: 11 } } } },
      scales: {
        x: { ticks: { color: "#64748b", font: { size: 11 } }, grid: { color: "#1e2330" } },
        y: { ticks: { color: "#64748b", font: { size: 11 } }, grid: { color: "#1e2330" } },
      },
    },
  });
}

function drawRateChart(canvasId, title, labels, data) {
  const ctx = document.getElementById(canvasId)?.getContext("2d");
  if (!ctx) return;

  if (state.charts[canvasId]) state.charts[canvasId].destroy();

  state.charts[canvasId] = new Chart(ctx, {
    type: "bar",
    data: {
      labels,
      datasets: [
        {
          label: title,
          data,
          backgroundColor: data.map((v) =>
            v == null ? "#334155" : v >= 90 ? "rgba(34,197,94,0.7)" : v >= 70 ? "rgba(234,179,8,0.7)" : "rgba(239,68,68,0.7)"
          ),
          borderRadius: 4,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { color: "#64748b", font: { size: 11 } }, grid: { color: "#1e2330" } },
        y: { min: 0, max: 100, ticks: { color: "#64748b", font: { size: 11 }, callback: (v) => v + "%" }, grid: { color: "#1e2330" } },
      },
    },
  });
}

// ── Trial list ────────────────────────────────────────────────────────────────

function renderTrials() {
  const el = document.getElementById("trials-list");
  const trials = filteredTrials().slice(0, 50);

  if (trials.length === 0) {
    el.innerHTML = `<p class="empty">No trials yet.</p>`;
    return;
  }

  el.innerHTML = trials
    .map((t) => {
      const pass = !t.error && t.turn_completion === 1.0;
      const label = t.error ? "ERROR" : pass ? "PASS" : "FAIL";
      const cls = t.error ? "fail" : pass ? "pass" : "fail";
      const ttfr = t.ttfr_measurements?.length
        ? Math.round(t.ttfr_measurements.reduce((a, b) => a + b, 0) / t.ttfr_measurements.length * 1000) + " ms avg"
        : "—";
      return `
        <div class="trial-row" onclick="openTrial('${t.trial_id}')">
          <span class="${cls}">${label}</span>
          <span>${t.platform} / ${t.scenario_id}</span>
          <span style="color:var(--muted)">TTFR ${ttfr}</span>
          <span class="tid">${t.trial_id.substring(0, 8)}…</span>
        </div>
      `;
    })
    .join("");
}

// ── Trial detail panel ────────────────────────────────────────────────────────

function openScenario(platform, scenarioId) {
  state.filterPlatform = platform;
  state.filterScenario = scenarioId;
  document.getElementById("filter-platform").value = platform;
  document.getElementById("filter-scenario").value = scenarioId;
  render();
}

async function openTrial(trialId) {
  const panel = document.getElementById("trial-panel");
  panel.innerHTML = `<div class="loading">Loading…</div>`;
  panel.classList.add("open");

  try {
    const trial = await fetchJSON(`/api/trials/${trialId}`);
    renderTrialPanel(trial);
  } catch (e) {
    panel.innerHTML = `<p class="empty">Failed to load trial: ${e.message}</p>`;
  }
}

function renderTrialPanel(trial) {
  const panel = document.getElementById("trial-panel");
  const events = trial.canonical_events || [];

  const eventRows = events
    .map(
      (e) => `
      <div class="event-row">
        <span class="ts">${e.timestamp.toFixed(3)}s</span>
        <span class="type ${e.type}">${e.type}</span>
        ${e.payload && Object.keys(e.payload).length > 0
          ? `<span style="color:var(--muted);font-size:11px">${JSON.stringify(e.payload).substring(0, 60)}</span>`
          : ""}
      </div>
    `
    )
    .join("");

  const pass = !trial.error && trial.turn_completion === 1.0;

  panel.innerHTML = `
    <button class="close-btn" onclick="closeTrial()">✕ Close</button>
    <h3>${trial.platform} / ${trial.scenario_id}</h3>
    <div style="color:var(--muted);font-size:12px;margin-top:4px">
      Trial #${trial.trial_num} &middot; ${trial.trial_id.substring(0, 16)}…
    </div>
    ${trial.error ? `<div style="color:var(--red);margin-top:12px;font-size:13px">${trial.error}</div>` : ""}
    <div style="margin-top:16px;display:flex;gap:20px">
      <div>
        <div style="font-size:11px;color:var(--muted)">RESULT</div>
        <div class="${pass ? "pass" : "fail"}" style="font-size:18px;font-weight:700">${pass ? "PASS" : "FAIL"}</div>
      </div>
      <div>
        <div style="font-size:11px;color:var(--muted)">TOOL ACC</div>
        <div style="font-size:18px;font-weight:700">${trial.tool_call_accuracy != null ? Math.round(trial.tool_call_accuracy * 100) + "%" : "—"}</div>
      </div>
      <div>
        <div style="font-size:11px;color:var(--muted)">TTFR (avg)</div>
        <div style="font-size:18px;font-weight:700;font-family:var(--mono)">
          ${trial.ttfr_measurements?.length
            ? Math.round(trial.ttfr_measurements.reduce((a,b)=>a+b,0)/trial.ttfr_measurements.length*1000) + " ms"
            : "—"}
        </div>
      </div>
    </div>
    <div style="margin-top:20px;font-size:12px;color:var(--muted);font-weight:600;text-transform:uppercase;letter-spacing:.08em">Event timeline</div>
    <div class="event-timeline">${eventRows || '<p class="empty">No events recorded.</p>'}</div>
  `;
}

function closeTrial() {
  document.getElementById("trial-panel").classList.remove("open");
}

// ── Boot ──────────────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", init);
