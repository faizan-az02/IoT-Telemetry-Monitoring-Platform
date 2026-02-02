function qs(sel) {
  return document.querySelector(sel);
}

function appendLog(line) {
  const box = qs("#logBox");
  if (!box) return;
  box.textContent += (box.textContent ? "\n" : "") + line;
  box.scrollTop = box.scrollHeight;
}

function setStatus(text) {
  const el = qs("#statusText");
  if (el) el.textContent = text;
}

function setProgress(cur, total) {
  const txt = qs("#progressText");
  if (txt) txt.textContent = `${cur}/${total}`;
  const fill = qs("#progressFill");
  if (fill) {
    const pct = total > 0 ? Math.round((cur / total) * 100) : 0;
    fill.style.width = `${pct}%`;
  }
}

async function detectCollectorBase() {
  // Prefer host agent (host metrics) if running, otherwise fall back to container endpoint.
  const agentBase = `http://${location.hostname}:8765`;
  try {
    const ping = await fetch(`${agentBase}/health`, { method: "GET" });
    if (ping.ok) {
      return { base: agentBase, label: "Host" };
    }
  } catch {
    // ignore
  }
  return { base: "", label: "Docker Container" };
}

async function startJob() {
  const form = qs("#collectForm");
  const startBtn = qs("#startBtn");
  if (!form || !startBtn) return;

  const data = Object.fromEntries(new FormData(form).entries());
  const dataset_size = Number(data.dataset_size || 25);
  const time_interval = Number(data.time_interval || 1);

  startBtn.disabled = true;
  qs("#logBox").textContent = "";
  setStatus("Starting…");
  setProgress(0, 0);

  const detected = await detectCollectorBase();
  const base = detected.base;
  const collectorLabel = detected.label;

  const res = await fetch(`${base}/collect/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ dataset_size, time_interval }),
  });
  if (!res.ok) throw new Error(`Failed to start job (${res.status})`);
  const json = await res.json();

  const es = new EventSource(json.stream_url);

  es.addEventListener("meta", (e) => {
    try {
      const meta = JSON.parse(e.data);
      appendLog(`Collector: ${collectorLabel}`);
      appendLog(`Dataset size: ${meta.dataset_size}`);
      appendLog(`Interval: ${meta.time_interval}s`);
    } catch {
      // ignore
    }
  });

  es.addEventListener("log", (e) => {
    appendLog(e.data);
  });

  es.addEventListener("progress", (e) => {
    try {
      const p = JSON.parse(e.data);
      setProgress(p.current || 0, p.total || 0);
      setStatus("Running");
    } catch {
      // ignore
    }
  });

  es.addEventListener("done", () => {
    setStatus("Complete");
    appendLog("Done.");
    es.close();
    startBtn.disabled = false;
  });

  es.addEventListener("error", (e) => {
    setStatus("Error");
    appendLog(`Error: ${e.data || "stream error"}`);
    es.close();
    startBtn.disabled = false;
  });
}

document.addEventListener("DOMContentLoaded", () => {
  // Warm up detection (no UI output needed)
  detectCollectorBase().catch(() => {});
  const startBtn = qs("#startBtn");
  if (startBtn) {
    startBtn.addEventListener("click", () => {
      startJob().catch((e) => {
        setStatus("Error");
        appendLog(`Error: ${e.message}`);
        startBtn.disabled = false;
      });
    });
  }
});

