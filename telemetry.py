import argparse
import ctypes
import os
import time
from datetime import datetime, timezone
from typing import Callable, Optional

import psutil
from pymongo import MongoClient
from pymongo.collection import Collection

from config import get as env_get

def _clamp_pct(x: float) -> float:
    if x < 0:
        return 0.0
    if x > 100:
        return 100.0
    return x


class _PdhDiskIdleCounter:
    """
    Windows PDH counter wrapper for:
      \\PhysicalDisk(_Total)\\% Idle Time

    Task Manager "Disk %" is roughly: 100 - % Idle Time
    """

    def __init__(self) -> None:
        if os.name != "nt":
            raise RuntimeError("PDH counter is only available on Windows")

        self._pdh = ctypes.WinDLL("pdh.dll")
        self._query = ctypes.c_void_p()
        self._counter = ctypes.c_void_p()

        # PDH constants
        self._PDH_FMT_DOUBLE = 0x00000200

        class _PDH_FMT_COUNTERVALUE(ctypes.Structure):
            _fields_ = [
                ("CStatus", ctypes.c_uint32),
                # Union field for double; this layout works for PDH_FMT_DOUBLE.
                ("doubleValue", ctypes.c_double),
            ]

        self._Value = _PDH_FMT_COUNTERVALUE

        # Signatures
        self._pdh.PdhOpenQueryW.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
        self._pdh.PdhOpenQueryW.restype = ctypes.c_uint32

        self._pdh.PdhAddEnglishCounterW.argtypes = [
            ctypes.c_void_p,
            ctypes.c_wchar_p,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        self._pdh.PdhAddEnglishCounterW.restype = ctypes.c_uint32

        self._pdh.PdhCollectQueryData.argtypes = [ctypes.c_void_p]
        self._pdh.PdhCollectQueryData.restype = ctypes.c_uint32

        self._pdh.PdhGetFormattedCounterValue.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(self._Value),
        ]
        self._pdh.PdhGetFormattedCounterValue.restype = ctypes.c_uint32

        self._pdh.PdhCloseQuery.argtypes = [ctypes.c_void_p]
        self._pdh.PdhCloseQuery.restype = ctypes.c_uint32

        status = self._pdh.PdhOpenQueryW(None, None, ctypes.byref(self._query))
        if status != 0:
            raise RuntimeError(f"PdhOpenQueryW failed: {status}")

        path = r"\PhysicalDisk(_Total)\% Idle Time"
        status = self._pdh.PdhAddEnglishCounterW(self._query, path, None, ctypes.byref(self._counter))
        if status != 0:
            self.close()
            raise RuntimeError(f"PdhAddEnglishCounterW failed: {status}")

        # Prime the counter (some counters need at least one collect).
        self._pdh.PdhCollectQueryData(self._query)

    def collect(self) -> None:
        self._pdh.PdhCollectQueryData(self._query)

    def get_idle_percent(self) -> float | None:
        try:
            typ = ctypes.c_uint32()
            val = self._Value()
            status = self._pdh.PdhGetFormattedCounterValue(
                self._counter, self._PDH_FMT_DOUBLE, ctypes.byref(typ), ctypes.byref(val)
            )
            if status != 0:
                return None
            return float(val.doubleValue)
        except Exception:
            return None

    def close(self) -> None:
        if getattr(self, "_query", None):
            try:
                self._pdh.PdhCloseQuery(self._query)
            except Exception:
                pass
            self._query = ctypes.c_void_p()
            self._counter = ctypes.c_void_p()


def _disk_active_percent_fallback(prev_io, cur_io, dt_sec: float) -> float:
    """
    Cross-platform fallback for disk "active time %".
    Uses busy_time when available; else read_time+write_time.
    """
    try:
        dt_ms = max(1.0, float(dt_sec) * 1000.0)
        busy0 = getattr(prev_io, "busy_time", None)
        busy1 = getattr(cur_io, "busy_time", None)
        if busy0 is not None and busy1 is not None:
            active_ms = float(busy1) - float(busy0)
            return _clamp_pct((active_ms / dt_ms) * 100.0)

        r0 = getattr(prev_io, "read_time", None)
        w0 = getattr(prev_io, "write_time", None)
        r1 = getattr(cur_io, "read_time", None)
        w1 = getattr(cur_io, "write_time", None)
        if None not in (r0, w0, r1, w1):
            active_ms = (float(r1) - float(r0)) + (float(w1) - float(w0))
            return _clamp_pct((active_ms / dt_ms) * 100.0)

        return 0.0
    except Exception:
        return 0.0


def collect_telemetry(
    collection: Collection,
    dataset_size: int,
    time_interval: float,
    collector: str = "Host",
    on_log: Optional[Callable[[str], None]] = None,
    on_progress: Optional[Callable[[int, int], None]] = None,
    stop_flag: Optional[Callable[[], bool]] = None,
) -> None:

    if dataset_size <= 0:
        raise ValueError("dataset_size must be > 0")
    if time_interval < 0:
        raise ValueError("time_interval must be >= 0")

    def log(msg: str) -> None:
        if on_log:
            on_log(msg)

    sample_sec = 1.0
    psutil.cpu_percent(interval=None)  # prime

    pdh = None
    if os.name == "nt":
        try:
            pdh = _PdhDiskIdleCounter()
        except Exception:
            pdh = None

    prev_io = psutil.disk_io_counters()

    for i in range(dataset_size):
        if stop_flag and stop_flag():
            log("Telemetry data collection cancelled.")
            return

        # Store UTC in Mongo to avoid host timezone skew.
        # (PyMongo treats naive datetimes as UTC. If we used datetime.now() on a non-UTC machine,
        #  the stored timestamps would appear "in the future".)
        now_utc = datetime.now(timezone.utc)
        now_local = datetime.now()
        # Start disk sampling window
        if pdh:
            pdh.collect()
        io0 = prev_io
        t0 = time.monotonic()

        # CPU sampled over the same 1s window.
        cpu_pct = psutil.cpu_percent(interval=sample_sec)

        t1 = time.monotonic()
        dt = max(0.001, t1 - t0)

        # End disk sampling window
        io1 = psutil.disk_io_counters()
        prev_io = io1
        if pdh:
            pdh.collect()
            idle = pdh.get_idle_percent()
            disk_pct = _clamp_pct(100.0 - float(idle)) if idle is not None else _disk_active_percent_fallback(io0, io1, dt)
        else:
            disk_pct = _disk_active_percent_fallback(io0, io1, dt)

        telemetry_data = {
            "collector": collector,
            "cpu_usage (%)": cpu_pct,
            "memory_usage (%)": psutil.virtual_memory().percent,
            "disk_usage (%)": round(float(disk_pct), 2),
            "timestamp": now_utc,
            "datetime_str": now_local.strftime("%Y-%m-%d %H:%M:%S"),
        }

        collection.insert_one(telemetry_data)

        current = i + 1
        if on_progress:
            on_progress(current, dataset_size)
        if not on_progress:
            log(f"Sample {current}/{dataset_size} collected.")

        if time_interval:
            time.sleep(time_interval)

    log("Telemetry data collection complete.")
    if pdh:
        pdh.close()


def _main() -> int:
    parser = argparse.ArgumentParser(description="Collect telemetry and write to MongoDB")
    parser.add_argument("--dataset-size", type=int, default=25, help="Number of samples to collect (default: 25)")
    parser.add_argument("--time-interval", type=float, default=1.0, help="Seconds between samples (default: 1.0)")
    parser.add_argument("--mongo-uri", type=str, default=env_get("MONGO_URI", "mongodb://localhost:27017/"))
    parser.add_argument("--mongo-db", type=str, default=env_get("MONGO_DB", "telemetry_db"))
    parser.add_argument("--mongo-collection", type=str, default=env_get("MONGO_COLLECTION", "telemetry_data"))
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
        collector="Host",
        on_log=on_log,
        on_progress=on_progress,
    )
    print()  # newline after carriage-return progress
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())