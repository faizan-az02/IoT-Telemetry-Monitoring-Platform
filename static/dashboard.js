async function fetchRecent(deviceId) {
  const params = new URLSearchParams();
  if (deviceId) params.set("device_id", deviceId);
  params.set("limit", "50");
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

function renderRows(rows) {
  const tbody = document.getElementById("telemetryTbody");
  if (!tbody) return;
  tbody.innerHTML = "";

  if (!rows.length) {
    const tr = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 5;
    cell.className = "empty";
    cell.textContent = "No telemetry samples found.";
    tr.appendChild(cell);
    tbody.appendChild(tr);
    return;
  }

  for (const r of rows) {
    const tr = document.createElement("tr");
    tr.appendChild(td(r.datetime_str || r.timestamp || "—", "mono"));
    tr.appendChild(td(r.device_id || "—", "mono"));
    tr.appendChild(td(r["cpu_usage (%)"] ?? "—", "num"));
    tr.appendChild(td(r["memory_usage (%)"] ?? "—", "num"));
    tr.appendChild(td(r["disk_usage (%)"] ?? "—", "num"));
    tbody.appendChild(tr);
  }
}

async function refresh() {
  const deviceId = (window.__DASHBOARD__ && window.__DASHBOARD__.selectedDevice) || "";
  const rows = await fetchRecent(deviceId);
  renderRows(rows);
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
});

