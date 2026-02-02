import json
import os
import queue
import threading
import time
import uuid
from datetime import datetime

from flask import Flask, Response, jsonify, redirect, render_template, request, url_for
from pymongo import MongoClient


def create_app() -> Flask:
    app = Flask(__name__)

    MAX_LIMIT = 100
    MAX_COLLECT_SAMPLES = 1000
    MAX_COLLECT_INTERVAL_SEC = 60 * 60

    mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
    mongo_db = os.getenv("MONGO_DB", "telemetry_db")
    mongo_collection = os.getenv("MONGO_COLLECTION", "telemetry_data")

    client = MongoClient(mongo_uri)
    collection = client[mongo_db][mongo_collection]

    # --- In-memory job registry for telemetry collection (simple, single-process) ---
    jobs_lock = threading.Lock()
    jobs: dict[str, dict] = {}

    def _sse(event: str, data: str) -> str:
        # SSE format: each event ends with a blank line; data may not contain raw newlines.
        safe = (data or "").replace("\r", "").split("\n")
        lines = [f"event: {event}"]
        for part in safe:
            lines.append(f"data: {part}")
        lines.append("")
        return "\n".join(lines) + "\n"

    def _start_collect_job(dataset_size: int, time_interval: float, device_id: str | None) -> str:
        job_id = uuid.uuid4().hex
        q: queue.Queue[tuple[str, str]] = queue.Queue()
        resolved_device_id = device_id or os.getenv("DEVICE_ID", "edge-1")

        with jobs_lock:
            jobs[job_id] = {
                "id": job_id,
                "status": "running",
                "created_at": time.time(),
                "done_at": None,
                "dataset_size": dataset_size,
                "time_interval": time_interval,
                "device_id": resolved_device_id,
                "queue": q,
                "stop": False,
            }

        def put(event: str, payload: str) -> None:
            q.put((event, payload))

        def run() -> None:
            put("log", f"Starting collection: dataset_size={dataset_size}, time_interval={time_interval}s")

            try:
                from telemetry import collect_telemetry

                def on_log(msg: str) -> None:
                    put("log", msg)

                def on_progress(cur: int, total: int) -> None:
                    put("progress", json.dumps({"current": cur, "total": total}))

                def stop_flag() -> bool:
                    with jobs_lock:
                        return bool(jobs.get(job_id, {}).get("stop"))

                collect_telemetry(
                    collection=collection,
                    dataset_size=dataset_size,
                    time_interval=time_interval,
                    device_id=device_id or None,
                    on_log=on_log,
                    on_progress=on_progress,
                    stop_flag=stop_flag,
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

        t = threading.Thread(target=run, daemon=True)
        t.start()

        return job_id

    def _safe_float(value):
        try:
            return float(value)
        except Exception:
            return None

    def _serialize_doc(doc: dict) -> dict:
        # Mongo adds _id (ObjectId) which isn't JSON serializable by default.
        doc = dict(doc)
        doc["_id"] = str(doc.get("_id"))
        ts = doc.get("timestamp")
        if isinstance(ts, datetime):
            doc["timestamp"] = ts.isoformat()
        return doc

    def _to_jsonable(value):
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, list):
            return [_to_jsonable(v) for v in value]
        if isinstance(value, tuple):
            return [_to_jsonable(v) for v in value]
        if isinstance(value, dict):
            return {k: _to_jsonable(v) for k, v in value.items()}
        return value

    @app.get("/")
    def index():
        # Default landing page: show latest 25 samples.
        return redirect(url_for("dashboard"))

    @app.get("/dashboard")
    def dashboard():
        device_id = request.args.get("device_id")  # optional filter
        limit = min(int(request.args.get("limit", "25")), MAX_LIMIT)

        query = {}
        if device_id:
            query["device_id"] = device_id

        rows = list(collection.find(query).sort("timestamp", -1).limit(limit))

        latest = rows[0] if rows else None
        latest_metrics = None
        if latest:
            latest_metrics = {
                "device_id": latest.get("device_id"),
                "cpu": _safe_float(latest.get("cpu_usage (%)")),
                "memory": _safe_float(latest.get("memory_usage (%)")),
                "disk": _safe_float(latest.get("disk_usage (%)")),
                "datetime_str": latest.get("datetime_str"),
            }

        # Compute simple averages for the table footer/summary.
        cpu_vals = [_safe_float(r.get("cpu_usage (%)")) for r in rows]
        mem_vals = [_safe_float(r.get("memory_usage (%)")) for r in rows]
        disk_vals = [_safe_float(r.get("disk_usage (%)")) for r in rows]
        cpu_vals = [v for v in cpu_vals if v is not None]
        mem_vals = [v for v in mem_vals if v is not None]
        disk_vals = [v for v in disk_vals if v is not None]

        def _avg(vals):
            return (sum(vals) / len(vals)) if vals else None

        summary = {
            "count": len(rows),
            "cpu_avg": _avg(cpu_vals),
            "memory_avg": _avg(mem_vals),
            "disk_avg": _avg(disk_vals),
        }

        # Grab a list of known devices for a simple selector.
        devices = sorted(collection.distinct("device_id"))

        return render_template(
            "dashboard.html",
            devices=devices,
            selected_device=device_id or "",
            selected_limit=limit,
            latest=latest_metrics,
            rows=rows,
            summary=summary,
        )

    @app.get("/analytics")
    def analytics():
        device_id = request.args.get("device_id")  # optional filter
        limit = min(int(request.args.get("limit", "100")), MAX_LIMIT)

        devices = sorted(collection.distinct("device_id"))

        return render_template(
            "analytics.html",
            devices=devices,
            selected_device=device_id or "",
            selected_limit=limit,
        )

    @app.get("/admin")
    def admin():
        devices = sorted(collection.distinct("device_id"))
        total_records = collection.count_documents({})
        latest = collection.find_one(sort=[("timestamp", -1)])
        latest_ts = None
        if latest:
            ts = latest.get("datetime_str") or latest.get("timestamp")
            if isinstance(ts, datetime):
                latest_ts = ts.strftime("%Y-%m-%d %H:%M:%S")
            else:
                latest_ts = str(ts) if ts is not None else None

        cleared = request.args.get("cleared")
        try:
            cleared_count = int(cleared) if cleared is not None else None
        except Exception:
            cleared_count = None

        return render_template(
            "admin.html",
            devices_count=len(devices),
            mongo_db=os.getenv("MONGO_DB", "telemetry_db"),
            mongo_collection=os.getenv("MONGO_COLLECTION", "telemetry_data"),
            max_limit=MAX_LIMIT,
            total_records=total_records,
            latest_timestamp=latest_ts,
            cleared_count=cleared_count,
        )

    @app.post("/admin/clear")
    def admin_clear():
        # Minimal safety: require an explicit confirm flag from the form.
        if (request.form.get("confirm") or "").strip() != "1":
            return jsonify({"error": "Confirmation required."}), 400
        res = collection.delete_many({})
        return redirect(url_for("admin", cleared=res.deleted_count))

    @app.get("/api/telemetry/latest")
    def api_latest():
        device_id = request.args.get("device_id")
        query = {"device_id": device_id} if device_id else {}
        doc = collection.find_one(query, sort=[("timestamp", -1)])
        return jsonify({"data": _serialize_doc(doc)} if doc else {"data": None})

    @app.get("/api/telemetry/recent")
    def api_recent():
        device_id = request.args.get("device_id")
        limit = min(int(request.args.get("limit", "25")), MAX_LIMIT)
        query = {"device_id": device_id} if device_id else {}
        docs = list(collection.find(query).sort("timestamp", -1).limit(limit))
        return jsonify({"data": [_serialize_doc(d) for d in docs]})

    @app.post("/api/telemetry/nl_query")
    def api_nl_query():
        payload = request.get_json(silent=True) or {}
        text = (payload.get("text") or "").strip()
        if not text:
            return jsonify({"error": "Missing required field: text"}), 400

        # Optional: let the UI pass a device_id to constrain results if the prompt didn't.
        device_hint = (payload.get("device_id") or "").strip() or None

        try:
            from nl_query_langchain import nl_to_mongo_query
        except Exception as e:
            return jsonify({"error": "NL query module unavailable.", "details": str(e)}), 500

        try:
            out = nl_to_mongo_query(text, max_limit=MAX_LIMIT, now=datetime.now().astimezone())
            plan = out["plan"]
            compiled = out["compiled"]
        except Exception as e:
            return jsonify({"error": "Failed to build query from text.", "details": str(e)}), 400

        # If UI provided a device, and plan didn't set one, add it.
        try:
            plan_device = getattr(plan, "device_id", None)
        except Exception:
            plan_device = None
        if device_hint and not plan_device:
            try:
                plan.device_id = device_hint  # pydantic model is mutable by default
                from nl_query_langchain import compile_plan_to_mongo

                compiled = compile_plan_to_mongo(plan, max_limit=MAX_LIMIT)
            except Exception:
                pass

        bucket = compiled.get("bucket") or "none"
        rollup = compiled.get("rollup") or "avg"
        flt = compiled.get("filter") or {}
        sort = compiled.get("sort") or ("timestamp", -1)
        limit = int(compiled.get("limit") or MAX_LIMIT)

        # Execute against the existing app Mongo collection (no new connection).
        mode = "raw"
        data = []

        if (bucket in (None, "none")) and (rollup in {"max", "min"}):
            mode = "summary"
            op = "$max" if rollup == "max" else "$min"

            def _conv(field: str):
                return {"$convert": {"input": f"${field}", "to": "double", "onError": None, "onNull": None}}

            pipeline = [
                {"$match": flt},
                {
                    "$group": {
                        "_id": None,
                        "count": {"$sum": 1},
                        "cpu": {op: _conv("cpu_usage (%)")},
                        "memory": {op: _conv("memory_usage (%)")},
                        "disk": {op: _conv("disk_usage (%)")},
                    }
                },
            ]
            rows = list(collection.aggregate(pipeline))
            r = rows[0] if rows else {}
            data = [
                {
                    "count": int(r.get("count") or 0),
                    "cpu": r.get("cpu"),
                    "memory": r.get("memory"),
                    "disk": r.get("disk"),
                    "rollup_selected": rollup,
                }
            ]
        elif bucket in (None, "none"):
            mode = "raw"
            docs = list(collection.find(flt).sort(sort[0], int(sort[1])).limit(limit))
            data = [_serialize_doc(d) for d in docs]
        else:
            mode = "bucketed"
            bucket_ms_map = {"1m": 60_000, "5m": 300_000, "1h": 3_600_000, "1d": 86_400_000}
            if bucket not in bucket_ms_map:
                return jsonify({"error": f"Unsupported bucket: {bucket}"}), 400
            bucket_ms = bucket_ms_map[bucket]
            sort_dir = int(sort[1]) if isinstance(sort, (list, tuple)) and len(sort) >= 2 else -1

            bucket_expr = {
                "$toDate": {
                    "$subtract": [
                        {"$toLong": "$timestamp"},
                        {"$mod": [{"$toLong": "$timestamp"}, bucket_ms]},
                    ]
                }
            }

            def _conv(field: str):
                return {"$convert": {"input": f"${field}", "to": "double", "onError": None, "onNull": None}}

            pipeline = [
                {"$match": flt},
                {
                    "$group": {
                        "_id": bucket_expr,
                        "count": {"$sum": 1},
                        "cpu_avg": {"$avg": _conv("cpu_usage (%)")},
                        "cpu_min": {"$min": _conv("cpu_usage (%)")},
                        "cpu_max": {"$max": _conv("cpu_usage (%)")},
                        "memory_avg": {"$avg": _conv("memory_usage (%)")},
                        "memory_min": {"$min": _conv("memory_usage (%)")},
                        "memory_max": {"$max": _conv("memory_usage (%)")},
                        "disk_avg": {"$avg": _conv("disk_usage (%)")},
                        "disk_min": {"$min": _conv("disk_usage (%)")},
                        "disk_max": {"$max": _conv("disk_usage (%)")},
                    }
                },
                {"$sort": {"_id": sort_dir}},
                {"$limit": limit},
            ]
            rows = list(collection.aggregate(pipeline))
            out_rows = []
            for r in rows:
                ts = r.get("_id")
                if isinstance(ts, datetime):
                    ts = ts.isoformat()
                out_rows.append(
                    {
                        "timestamp": ts,
                        "count": int(r.get("count") or 0),
                        "cpu": {"avg": r.get("cpu_avg"), "min": r.get("cpu_min"), "max": r.get("cpu_max")},
                        "memory": {"avg": r.get("memory_avg"), "min": r.get("memory_min"), "max": r.get("memory_max")},
                        "disk": {"avg": r.get("disk_avg"), "min": r.get("disk_min"), "max": r.get("disk_max")},
                        "rollup_selected": rollup,
                    }
                )
            data = out_rows

        plan_json = plan.model_dump() if hasattr(plan, "model_dump") else plan
        compiled_json = _to_jsonable(compiled)

        return jsonify(
            {
                "plan": plan_json,
                "compiled": compiled_json,
                "meta": {"mode": mode, "bucket": bucket, "rollup": rollup, "limit": limit},
                "data": data,
            }
        )

    @app.get("/collect")
    def collect():
        devices = sorted(collection.distinct("device_id"))
        return render_template(
            "collect.html",
            devices=devices,
            default_device=os.getenv("DEVICE_ID", "edge-1"),
            default_dataset_size=25,
            default_time_interval=1,
        )

    @app.post("/collect/start")
    def collect_start():
        # Accept either form-encoded or JSON.
        payload = request.get_json(silent=True) or request.form
        dataset_size = int(payload.get("dataset_size", 25))
        time_interval = float(payload.get("time_interval", 1))
        # Device ID is taken from environment variables by the collector.
        device_id = None

        dataset_size = max(1, min(MAX_COLLECT_SAMPLES, dataset_size))
        time_interval = max(0.0, min(MAX_COLLECT_INTERVAL_SEC, time_interval))

        job_id = _start_collect_job(dataset_size=dataset_size, time_interval=time_interval, device_id=device_id)
        return jsonify(
            {
                "job_id": job_id,
                "stream_url": url_for("collect_stream", job_id=job_id),
            }
        )

    @app.get("/collect/stream/<job_id>")
    def collect_stream(job_id: str):
        with jobs_lock:
            job = jobs.get(job_id)
        if not job:
            return Response(_sse("error", "Unknown job id"), mimetype="text/event-stream")

        q: queue.Queue[tuple[str, str]] = job["queue"]

        def gen():
            # Immediately send metadata.
            yield _sse(
                "meta",
                json.dumps(
                    {
                        "job_id": job_id,
                        "dataset_size": job.get("dataset_size"),
                        "time_interval": job.get("time_interval"),
                        "device_id": job.get("device_id"),
                    }
                ),
            )
            # Stream queue events until done/error.
            while True:
                try:
                    event, payload = q.get(timeout=10)
                    yield _sse(event, payload)
                    if event in {"done", "error"}:
                        return
                except queue.Empty:
                    # Keep connection alive.
                    yield ": ping\n\n"

        return Response(gen(), mimetype="text/event-stream")

    return app


if __name__ == "__main__":
    app = create_app()
    # Use FLASK_DEBUG=1 for debug; host/port configurable via env.
    host = os.getenv("FLASK_HOST", "127.0.0.1")
    port = int(os.getenv("FLASK_PORT", "5000"))
    debug = os.getenv("FLASK_DEBUG", "").strip() in {"1", "true", "True", "yes", "YES"}
    app.run(host=host, port=port, debug=False)

