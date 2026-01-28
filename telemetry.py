from pymongo import MongoClient
import argparse
import os
import time
from datetime import datetime
from typing import Callable, Optional

import psutil
from pymongo.collection import Collection


def collect_telemetry(
    collection: Collection,
    dataset_size: int,
    time_interval: float,
    device_id: Optional[str] = None,
    on_log: Optional[Callable[[str], None]] = None,
    on_progress: Optional[Callable[[int, int], None]] = None,
    stop_flag: Optional[Callable[[], bool]] = None,
) -> None:
    """
    Collect telemetry samples and write them to MongoDB.

    - collection: pymongo collection to insert into
    - dataset_size: number of samples
    - time_interval: seconds to sleep between samples (after each insert)
    - device_id: optional override (defaults to env DEVICE_ID or 'edge-1')
    - on_log: optional callback for log lines
    - on_progress: optional callback (current, total)
    - stop_flag: optional callback returning True to stop early
    """
    if dataset_size <= 0:
        raise ValueError("dataset_size must be > 0")
    if time_interval < 0:
        raise ValueError("time_interval must be >= 0")

    device_id = device_id or os.getenv("DEVICE_ID", "edge-1")
    disk_path = os.path.abspath(os.sep)  # Windows-safe (e.g. C:\)

    def log(msg: str) -> None:
        if on_log:
            on_log(msg)

    for i in range(dataset_size):
        if stop_flag and stop_flag():
            log("Telemetry data collection cancelled.")
            return

        now = datetime.now()

        telemetry_data = {
            "device_id": device_id,
            "cpu_usage (%)": psutil.cpu_percent(interval=1),
            "memory_usage (%)": psutil.virtual_memory().percent,
            "disk_usage (%)": psutil.disk_usage(disk_path).percent,
            "timestamp": now,
            "datetime_str": now.strftime("%Y-%m-%d %H:%M:%S"),
        }

        collection.insert_one(telemetry_data)

        current = i + 1
        if on_progress:
            on_progress(current, dataset_size)
        # Only log per-sample updates when no progress callback is provided.
        # The web UI renders progress via a progress bar, and the CLI can render
        # progress with carriage returns.
        if not on_progress:
            log(f"Sample {current}/{dataset_size} collected.")

        if time_interval:
            time.sleep(time_interval)

    log("Telemetry data collection complete.")


def _main() -> int:
    parser = argparse.ArgumentParser(description="Collect telemetry and write to MongoDB")
    parser.add_argument("--dataset-size", type=int, required=True, help="Number of samples to collect")
    parser.add_argument("--time-interval", type=float, required=True, help="Seconds between samples")
    parser.add_argument("--device-id", type=str, default=None, help="Device ID override")
    parser.add_argument("--mongo-uri", type=str, default=os.getenv("MONGO_URI", "mongodb://localhost:27017/"))
    parser.add_argument("--mongo-db", type=str, default=os.getenv("MONGO_DB", "telemetry_db"))
    parser.add_argument("--mongo-collection", type=str, default=os.getenv("MONGO_COLLECTION", "telemetry_data"))
    args = parser.parse_args()

    client = MongoClient(args.mongo_uri)
    collection = client[args.mongo_db][args.mongo_collection]

    def on_log(msg: str) -> None:
        print(msg)

    def on_progress(cur: int, total: int) -> None:
        print(f"Sample {cur}/{total} collected.", end="\r")

    collect_telemetry(
        collection=collection,
        dataset_size=args.dataset_size,
        time_interval=args.time_interval,
        device_id=args.device_id,
        on_log=on_log,
        on_progress=on_progress,
    )
    print()  # newline after carriage-return progress
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())