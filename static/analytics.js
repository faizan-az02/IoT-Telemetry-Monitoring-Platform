function qs(sel) {
  return document.querySelector(sel);
}

function getSelectedDevice() {
  return (document.body && document.body.dataset && document.body.dataset.selectedDevice) || "";
}

function getSelectedLimit() {
  const select = document.querySelector('select[name="limit"]');
  const val = select && select.value ? Number(select.value) : Number(document.body.dataset.selectedLimit || 100);
  const capped = Math.max(1, Math.min(100, Number.isFinite(val) ? val : 100));
  return String(capped);
}

async function fetchRecent(deviceId, limit) {
  const params = new URLSearchParams();
  if (deviceId) params.set("device_id", deviceId);
  params.set("limit", limit || "100");
  const res = await fetch(`/api/telemetry/recent?${params.toString()}`);
  if (!res.ok) throw new Error(`Failed to load telemetry (${res.status})`);
  const json = await res.json();
  return json.data || [];
}

async function fetchNlQuery(text, deviceId, limit) {
  const payload = { text: text || "" };
  if (deviceId) payload.device_id = deviceId;
  if (limit) payload.limit = limit;

  const res = await fetch("/api/telemetry/nl_query", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const json = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(json.error || `NL query failed (${res.status})`);
  return json;
}

function toNumber(x) {
  const n = Number(x);
  return Number.isFinite(n) ? n : null;
}

function stat(vals) {
  const arr = vals.filter((v) => v !== null);
  if (!arr.length) return null;
  let min = arr[0];
  let max = arr[0];
  let sum = 0;
  for (const v of arr) {
    if (v < min) min = v;
    if (v > max) max = v;
    sum += v;
  }
  return { min, max, avg: sum / arr.length, count: arr.length };
}

function fmt(n) {
  return n === null || n === undefined ? "—" : `${n.toFixed(1)}%`;
}

function setText(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}

function setHtml(id, html) {
  const el = document.getElementById(id);
  if (el) el.innerHTML = html;
}

function td(text, className) {
  const el = document.createElement("td");
  if (className) el.className = className;
  el.textContent = text ?? "—";
  return el;
}

function renderNlTable(json) {
  const head = document.getElementById("nlTableHead");
  const body = document.getElementById("nlTableBody");
  if (!head || !body) return;

  const meta = json.meta || {};
  const mode = meta.mode || "raw";
  const bucket = meta.bucket || "none";
  const rollup = meta.rollup || "avg";
  const rows = json.data || [];

  body.innerHTML = "";

  if (!rows.length) {
    const tr = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 6;
    cell.className = "empty";
    cell.textContent = "No rows returned for this query.";
    tr.appendChild(cell);
    body.appendChild(tr);
    return;
  }

  if (mode === "bucketed") {
    head.innerHTML = `
      <tr>
        <th class="col-idx">#</th>
        <th>Bucket time</th>
        <th class="num">Count</th>
        <th class="num">CPU (${rollup})</th>
        <th class="num">Memory (${rollup})</th>
        <th class="num">Disk (${rollup})</th>
      </tr>
    `;
    let idx = 1;
    for (const r of rows) {
      const tr = document.createElement("tr");
      tr.appendChild(td(String(idx), "col-idx"));
      tr.appendChild(td(r.timestamp || "—", "mono"));
      tr.appendChild(td(String(r.count ?? "—"), "num"));
      tr.appendChild(td(r.cpu && r.cpu[rollup] != null ? Number(r.cpu[rollup]).toFixed(2) : "—", "num"));
      tr.appendChild(td(r.memory && r.memory[rollup] != null ? Number(r.memory[rollup]).toFixed(2) : "—", "num"));
      tr.appendChild(td(r.disk && r.disk[rollup] != null ? Number(r.disk[rollup]).toFixed(2) : "—", "num"));
      body.appendChild(tr);
      idx += 1;
    }
    return;
  }

  if (mode === "summary") {
    head.innerHTML = `
      <tr>
        <th>Metric</th>
        <th class="num">Value (${rollup})</th>
      </tr>
    `;
    const r = rows[0] || {};
    const metrics = [
      ["CPU (%)", r.cpu],
      ["Memory (%)", r.memory],
      ["Disk (%)", r.disk],
      ["Samples matched", r.count],
    ];
    for (const [k, v] of metrics) {
      const tr = document.createElement("tr");
      tr.appendChild(td(String(k), ""));
      tr.appendChild(td(v != null ? String(v) : "—", "num"));
      body.appendChild(tr);
    }
    return;
  }

  // raw
  head.innerHTML = `
    <tr>
      <th class="col-idx">#</th>
      <th>Timestamp</th>
      <th>Device</th>
      <th class="num">CPU (%)</th>
      <th class="num">Memory (%)</th>
      <th class="num">Disk (%)</th>
    </tr>
  `;
  let idx = 1;
  for (const r of rows) {
    const tr = document.createElement("tr");
    tr.appendChild(td(String(idx), "col-idx"));
    tr.appendChild(td(r.datetime_str || r.timestamp || "—", "mono"));
    tr.appendChild(td(r.device_id || "—", "mono"));
    tr.appendChild(td(r["cpu_usage (%)"] ?? "—", "num"));
    tr.appendChild(td(r["memory_usage (%)"] ?? "—", "num"));
    tr.appendChild(td(r["disk_usage (%)"] ?? "—", "num"));
    body.appendChild(tr);
    idx += 1;
  }
}

function polylinePoints(values, width, height, pad) {
  const vals = values.filter((v) => v !== null);
  if (!vals.length) return "";
  const min = Math.min(...vals);
  const max = Math.max(...vals);
  const w = width - pad * 2;
  const h = height - pad * 2;

  const normY = (v) => {
    if (max === min) return pad + h / 2;
    const t = (v - min) / (max - min);
    return pad + (1 - t) * h;
  };

  const n = values.length;
  const step = n <= 1 ? 0 : w / (n - 1);
  const pts = [];
  for (let i = 0; i < n; i++) {
    const v = values[i];
    const x = pad + step * i;
    const y = v === null ? null : normY(v);
    if (y === null) continue;
    pts.push(`${x.toFixed(2)},${y.toFixed(2)}`);
  }
  return pts.join(" ");
}

function normalizeNlResult(json) {
  const meta = json.meta || {};
  const mode = meta.mode || "raw";
  const bucket = meta.bucket || "none";
  const rollup = meta.rollup || "avg";
  const rows = json.data || [];

  if (mode === "summary" && rows[0]) {
    const r = rows[0];
    return {
      mode,
      bucket,
      rollup,
      count: r.count || 0,
      series: {
        cpu: [toNumber(r.cpu)],
        mem: [toNumber(r.memory)],
        disk: [toNumber(r.disk)],
      },
      newest: null,
      oldest: null,
    };
  }

  if (mode === "bucketed") {
    return {
      mode,
      bucket,
      rollup,
      count: rows.length,
      series: {
        cpu: rows.map((r) => toNumber(r && r.cpu && r.cpu[rollup])),
        mem: rows.map((r) => toNumber(r && r.memory && r.memory[rollup])),
        disk: rows.map((r) => toNumber(r && r.disk && r.disk[rollup])),
      },
      newest: rows[0] && rows[0].timestamp,
      oldest: rows[rows.length - 1] && rows[rows.length - 1].timestamp,
    };
  }

  return {
    mode: "raw",
    bucket,
    rollup,
    count: rows.length,
    series: {
      cpu: rows.map((r) => toNumber(r["cpu_usage (%)"])),
      mem: rows.map((r) => toNumber(r["memory_usage (%)"])),
      disk: rows.map((r) => toNumber(r["disk_usage (%)"])),
    },
    newest: rows[0] && (rows[0].datetime_str || rows[0].timestamp),
    oldest: rows[rows.length - 1] && (rows[rows.length - 1].datetime_str || rows[rows.length - 1].timestamp),
  };
}

async function runNlAnalytics() {
  const status = qs("#statusNote");
  const promptEl = qs("#nlPrompt");
  const btn = qs("#nlRunBtn");
  const text = promptEl && promptEl.value ? promptEl.value.trim() : "";
  if (!text) {
    if (status) status.textContent = "Enter a question above, then click Run.";
    return;
  }
  if (status) status.textContent = "Thinking…";
  if (btn) btn.disabled = true;
  try {
    const deviceId = getSelectedDevice();
    const limit = getSelectedLimit();
    const json = await fetchNlQuery(text, deviceId, limit);
    const norm = normalizeNlResult(json);
    renderNlTable(json);

    const cpu = norm.series.cpu;
    const mem = norm.series.mem;
    const disk = norm.series.disk;

    const cpuS = stat(cpu);
    const memS = stat(mem);
    const diskS = stat(disk);

    if (norm.mode === "summary") {
      setText("cpuStat", cpuS ? fmt(cpuS.max) : "—");
      setText("memStat", memS ? fmt(memS.max) : "—");
      setText("diskStat", diskS ? fmt(diskS.max) : "—");
    } else {
      setText("cpuStat", cpuS ? `${fmt(cpuS.avg)} / ${fmt(cpuS.min)} / ${fmt(cpuS.max)}` : "—");
      setText("memStat", memS ? `${fmt(memS.avg)} / ${fmt(memS.min)} / ${fmt(memS.max)}` : "—");
      setText("diskStat", diskS ? `${fmt(diskS.avg)} / ${fmt(diskS.min)} / ${fmt(diskS.max)}` : "—");
    }

    setText("cpuMeta", deviceId ? `Device: ${deviceId}` : "Device: all");
    setText("memMeta", `Mode: ${norm.mode}`);
    setText("diskMeta", norm.bucket && norm.bucket !== "none" ? `bucket=${norm.bucket} (${norm.rollup})` : `rollup=${norm.rollup}`);

    setText("countStat", String(norm.count));
    setText(
      "timeMeta",
      norm.newest || norm.oldest ? `Window: ${norm.newest || "—"} → ${norm.oldest || "—"}` : "Window: —"
    );

    const cpuPts = polylinePoints(cpu, 300, 64, 6);
    const memPts = polylinePoints(mem, 300, 64, 6);
    const diskPts = polylinePoints(disk, 300, 64, 6);
    const cpuLine = document.getElementById("cpuLine");
    const memLine = document.getElementById("memLine");
    const diskLine = document.getElementById("diskLine");
    if (cpuLine) cpuLine.setAttribute("points", cpuPts);
    if (memLine) memLine.setAttribute("points", memPts);
    if (diskLine) diskLine.setAttribute("points", diskPts);

    setText("cpuLegend", cpuS ? `avg ${fmt(cpuS.avg)} · min ${fmt(cpuS.min)} · max ${fmt(cpuS.max)}` : "—");
    setText("memLegend", memS ? `avg ${fmt(memS.avg)} · min ${fmt(memS.min)} · max ${fmt(memS.max)}` : "—");
    setText("diskLegend", diskS ? `avg ${fmt(diskS.avg)} · min ${fmt(diskS.min)} · max ${fmt(diskS.max)}` : "—");

    if (status) status.textContent = "Loaded (NL query).";
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function loadAnalytics() {
  const status = qs("#statusNote");
  if (status) status.textContent = "Loading…";

  const deviceId = getSelectedDevice();
  const limit = getSelectedLimit();

  const rows = await fetchRecent(deviceId, limit);
  // API returns newest first; keep that order for "most recent → oldest".

  const cpu = rows.map((r) => toNumber(r["cpu_usage (%)"]));
  const mem = rows.map((r) => toNumber(r["memory_usage (%)"]));
  const disk = rows.map((r) => toNumber(r["disk_usage (%)"]));

  const cpuS = stat(cpu);
  const memS = stat(mem);
  const diskS = stat(disk);

  setText("cpuStat", cpuS ? `${fmt(cpuS.avg)} / ${fmt(cpuS.min)} / ${fmt(cpuS.max)}` : "—");
  setText("memStat", memS ? `${fmt(memS.avg)} / ${fmt(memS.min)} / ${fmt(memS.max)}` : "—");
  setText("diskStat", diskS ? `${fmt(diskS.avg)} / ${fmt(diskS.min)} / ${fmt(diskS.max)}` : "—");

  setText("cpuMeta", deviceId ? `Device: ${deviceId}` : "Device: all");
  setText("memMeta", `N capped at 100`);
  setText("diskMeta", `N capped at 100`);
  setText("countStat", String(rows.length));

  const newest = rows[0] && (rows[0].datetime_str || rows[0].timestamp);
  const oldest = rows[rows.length - 1] && (rows[rows.length - 1].datetime_str || rows[rows.length - 1].timestamp);
  setText("timeMeta", rows.length ? `Window: ${newest || "—"} → ${oldest || "—"}` : "No data");

  const cpuPts = polylinePoints(cpu, 300, 64, 6);
  const memPts = polylinePoints(mem, 300, 64, 6);
  const diskPts = polylinePoints(disk, 300, 64, 6);
  const cpuLine = document.getElementById("cpuLine");
  const memLine = document.getElementById("memLine");
  const diskLine = document.getElementById("diskLine");
  if (cpuLine) cpuLine.setAttribute("points", cpuPts);
  if (memLine) memLine.setAttribute("points", memPts);
  if (diskLine) diskLine.setAttribute("points", diskPts);

  setText("cpuLegend", cpuS ? `avg ${fmt(cpuS.avg)} · min ${fmt(cpuS.min)} · max ${fmt(cpuS.max)}` : "—");
  setText("memLegend", memS ? `avg ${fmt(memS.avg)} · min ${fmt(memS.min)} · max ${fmt(memS.max)}` : "—");
  setText("diskLegend", diskS ? `avg ${fmt(diskS.avg)} · min ${fmt(diskS.min)} · max ${fmt(diskS.max)}` : "—");

  if (status) status.textContent = rows.length ? "Loaded." : "No data found (run telemetry collector).";
}

document.addEventListener("DOMContentLoaded", () => {
  const btn = qs("#reloadBtn");
  if (btn) {
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      try {
        await loadAnalytics();
      } finally {
        btn.disabled = false;
      }
    });
  }

  loadAnalytics().catch((e) => {
    const status = qs("#statusNote");
    if (status) status.textContent = `Error: ${e.message}`;
  });

  const nlBtn = qs("#nlRunBtn");
  if (nlBtn) {
    nlBtn.addEventListener("click", () => {
      runNlAnalytics().catch((e) => {
        const status = qs("#statusNote");
        if (status) status.textContent = `Error: ${e.message}`;
      });
    });
  }
});

