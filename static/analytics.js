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
});

