function getSelectedLimit() {
  const select = document.querySelector('select[name="limit"]');
  const val = select && select.value ? Number(select.value) : 25;
  return Number.isFinite(val) && val > 0 ? String(val) : "25";
}

async function fetchRecent(deviceId, limit) {
  const params = new URLSearchParams();
  params.set("limit", limit || "25");
  const res = await fetch(`/api/telemetry/recent?${params.toString()}`);
  if (!res.ok) throw new Error(`Failed to load telemetry (${res.status})`);
  const json = await res.json();
  return json.data || [];
}

function td(text, className) {
  const el = document.createElement("td");
  if (className) el.className = className;
  el.textContent = text ?? "—";
  return el;
}

function fmtLocalTimestamp(iso) {
  if (!iso) return "—";
  if (typeof iso !== "string") return String(iso);
  const d = new Date(iso);
  if (!Number.isNaN(d.getTime())) return d.toLocaleString();
  return iso;
}

function renderRows(rows) {
  const tbody = document.getElementById("telemetryTbody");
  if (!tbody) return;
  tbody.innerHTML = "";

  if (!rows.length) {
    const tr = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 6;
    cell.className = "empty";
    cell.textContent = "No telemetry samples found.";
    tr.appendChild(cell);
    tbody.appendChild(tr);
    return;
  }

  let idx = 1;
  for (const r of rows) {
    const tr = document.createElement("tr");
    tr.appendChild(td(String(idx), "col-idx"));
    tr.appendChild(td(fmtLocalTimestamp(r.timestamp), "mono"));
    tr.appendChild(td(r.collector || "—", "mono"));
    tr.appendChild(td(r["cpu_usage (%)"] ?? "—", "num"));
    tr.appendChild(td(r["memory_usage (%)"] ?? "—", "num"));
    tr.appendChild(td(r["disk_usage (%)"] ?? "—", "num"));
    tbody.appendChild(tr);
    idx += 1;
  }
}

async function refresh() {
  const limit = getSelectedLimit();
  const rows = await fetchRecent("", limit);
  renderRows(rows);

  // Keep "Last update" consistent with the table (browser-local time).
  const last = document.getElementById("lastUpdateTs");
  if (last) {
    const iso = rows && rows[0] ? rows[0].timestamp : (last.dataset ? last.dataset.ts : "");
    last.textContent = fmtLocalTimestamp(iso);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const btn = document.getElementById("refreshBtn");
  if (btn) {
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      try {
        await refresh();
      } finally {
        btn.disabled = false;
      }
    });
  }

  // Initial load
  refresh().catch(() => {});
});

