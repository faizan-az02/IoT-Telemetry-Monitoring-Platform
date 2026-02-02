from __future__ import annotations

import json
import queue
import threading
import time
import uuid
from datetime import datetime

from flask import Flask, Response, jsonify, request
from pymongo import MongoClient

from telemetry import collect_telemetry


def _sse(event: str, data: str) -> str:
    safe = (data or "").replace("\r", "").split("\n")
    lines = [f"event: {event}"]
    for part in safe:
        lines.append(f"data: {part}")
    lines.append("")
    return "\n".join(lines) + "\n"


def create_agent() -> Flask:
    app = Flask(__name__)

    # Fixed host agent configuration (keep simple/portable).
    # Mongo is published from Docker to host as 27018:27017 (see compose.yaml).
    MONGO_URI = "mongodb://localhost:27018/"
    MONGO_DB = "telemetry_db"
    MONGO_COLLECTION = "telemetry_data"

    # In-memory job registry (single-process agent)
    jobs_lock = threading.Lock()
    jobs: dict[str, dict] = {}

    @app.after_request
    def _cors(resp):
        # Allow the UI (localhost:5000) to call the agent (localhost:8765)
        origin = request.headers.get("Origin") or ""
        if origin.startswith("http://localhost") or origin.startswith("http://127.0.0.1"):
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Vary"] = "Origin"
        else:
            # Safe default for local-only usage
            resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        resp.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
        return resp

    @app.route("/health", methods=["GET"])
    def health():
        return jsonify({"ok": True, "ts": datetime.now().isoformat()})

    @app.route("/collect/start", methods=["OPTIONS"])
    def collect_start_options():
        return ("", 204)

    @app.route("/collect/start", methods=["POST"])
    def collect_start():
        payload = request.get_json(silent=True) or {}
        dataset_size = int(payload.get("dataset_size", 25))
        time_interval = float(payload.get("time_interval", 1))

        dataset_size = max(1, min(1000, dataset_size))
        time_interval = max(0.0, min(60 * 60, time_interval))

        client = MongoClient(MONGO_URI)
        collection = client[MONGO_DB][MONGO_COLLECTION]

        job_id = uuid.uuid4().hex
        q: queue.Queue[tuple[str, str]] = queue.Queue()

        with jobs_lock:
            jobs[job_id] = {
                "id": job_id,
                "status": "running",
                "created_at": time.time(),
                "done_at": None,
                "dataset_size": dataset_size,
                "time_interval": time_interval,
                "queue": q,
            }

        def put(event: str, payload: str) -> None:
            q.put((event, payload))

        def on_log(msg: str) -> None:
            put("log", msg)

        def on_progress(cur: int, total: int) -> None:
            put("progress", json.dumps({"current": cur, "total": total}))

        def run() -> None:
            put("log", "Starting host telemetry collection…")
            try:
                collect_telemetry(
                    collection=collection,
                    dataset_size=dataset_size,
                    time_interval=time_interval,
                    collector="Host",
                    on_log=on_log,
                    on_progress=on_progress,
                    stop_flag=None,
                )
                with jobs_lock:
                    if jobs.get(job_id):
                        jobs[job_id]["status"] = "done"
                        jobs[job_id]["done_at"] = time.time()
                put("done", "complete")
            except Exception as e:
                with jobs_lock:
                    if jobs.get(job_id):
                        jobs[job_id]["status"] = "error"
                        jobs[job_id]["done_at"] = time.time()
                        jobs[job_id]["error"] = str(e)
                put("error", str(e))

        threading.Thread(target=run, daemon=True).start()

        # Return absolute URL for EventSource
        stream_url = request.host_url.rstrip("/") + f"/collect/stream/{job_id}"
        return jsonify({"job_id": job_id, "stream_url": stream_url})

    @app.route("/collect/stream/<job_id>", methods=["GET"])
    def collect_stream(job_id: str):
        with jobs_lock:
            job = jobs.get(job_id)
        if not job:
            return Response(_sse("error", "Unknown job id"), mimetype="text/event-stream")

        q: queue.Queue[tuple[str, str]] = job["queue"]

        def gen():
            # Send metadata first.
            yield _sse(
                "meta",
                json.dumps(
                    {
                        "job_id": job_id,
                        "dataset_size": job.get("dataset_size"),
                        "time_interval": job.get("time_interval"),
                    }
                ),
            )
            while True:
                try:
                    event, payload = q.get(timeout=10)
                    yield _sse(event, payload)
                    if event in {"done", "error"}:
                        return
                except queue.Empty:
                    yield ": ping\n\n"

        return Response(gen(), mimetype="text/event-stream")

    return app


if __name__ == "__main__":
    app = create_agent()
    # Local-only
    app.run(host="127.0.0.1", port=8765, debug=False)

