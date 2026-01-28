import os
from datetime import datetime

from flask import Flask, jsonify, redirect, render_template, request, url_for
from pymongo import MongoClient


def create_app() -> Flask:
    app = Flask(__name__)

    MAX_LIMIT = 100

    mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
    mongo_db = os.getenv("MONGO_DB", "telemetry_db")
    mongo_collection = os.getenv("MONGO_COLLECTION", "telemetry_data")

    client = MongoClient(mongo_uri)
    collection = client[mongo_db][mongo_collection]

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

        # For initial render we just provide devices/selected values;
        # charts/stats are computed client-side via /api/telemetry/recent.
        devices = sorted(collection.distinct("device_id"))

        return render_template(
            "analytics.html",
            devices=devices,
            selected_device=device_id or "",
            selected_limit=limit,
        )

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

    return app


if __name__ == "__main__":
    app = create_app()
    # Use FLASK_DEBUG=1 for debug; host/port configurable via env.
    host = os.getenv("FLASK_HOST", "127.0.0.1")
    port = int(os.getenv("FLASK_PORT", "5000"))
    debug = os.getenv("FLASK_DEBUG", "").strip() in {"1", "true", "True", "yes", "YES"}
    app.run(host=host, port=port, debug=debug)

