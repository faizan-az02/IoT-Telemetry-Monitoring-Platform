from __future__ import annotations

import os
from pathlib import Path

_DEFAULT_ENV_PATH = Path(__file__).resolve().parent / ".env"


def _env_path() -> Path:
    """
    Resolve which env file to read.

    - Default: repo-root `.env`
    - Override (optional): set ENV_FILE to a path (absolute or relative to repo root)
      This is useful for running a host agent with a different Mongo URI than Docker.
    """
    raw = (os.getenv("ENV_FILE") or "").strip()
    if not raw:
        return _DEFAULT_ENV_PATH
    p = Path(raw)
    if p.is_absolute():
        return p
    return _DEFAULT_ENV_PATH.parent / p


def _strip_quotes(s: str) -> str:
    if len(s) >= 2 and ((s[0] == s[-1] == '"') or (s[0] == s[-1] == "'")):
        return s[1:-1]
    return s


def load_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        raise RuntimeError(
            f"Missing required .env file at: {path}\n"
            "Create `.env` in the repo root and add required variables."
        )

    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        key = k.strip()
        val = _strip_quotes(v.strip())
        out[key] = val
    return out


_ENV_CACHE: dict[str, str] | None = None
_ENV_MTIME_NS: int | None = None
_ENV_LAST_PATH: Path | None = None


def _load_if_needed() -> dict[str, str]:
    """
    Read the env file from disk and cache it.
    If the file changes (mtime), reload automatically.
    """
    global _ENV_CACHE, _ENV_MTIME_NS, _ENV_LAST_PATH
    path = _env_path()
    st = path.stat() if path.exists() else None
    mtime_ns = st.st_mtime_ns if st else None
    if _ENV_CACHE is None or _ENV_MTIME_NS != mtime_ns or _ENV_LAST_PATH != path:
        _ENV_CACHE = load_env_file(path)
        _ENV_MTIME_NS = mtime_ns
        _ENV_LAST_PATH = path
    return _ENV_CACHE


def get(key: str, default: str | None = None, *, required: bool = False) -> str | None:
    env = _load_if_needed()
    if key in env:
        val = env[key]
        # Treat empty string as "unset"
        if val != "":
            return val
    if required and default is None:
        raise RuntimeError(f"Missing required config key in .env: {key}")
    return default


def get_int(key: str, default: int | None = None, *, required: bool = False) -> int | None:
    v = get(key, None, required=required)
    if v is None:
        return default
    try:
        return int(v)
    except Exception:
        if required:
            raise RuntimeError(f"Invalid int for {key} in .env: {v!r}")
        return default


def get_bool(key: str, default: bool = False) -> bool:
    v = get(key, None, required=False)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "y", "on"}

