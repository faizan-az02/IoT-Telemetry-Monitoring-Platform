from __future__ import annotations
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parent / ".env"

def _strip_quotes(s: str) -> str:
    if len(s) >= 2 and ((s[0] == s[-1] == '"') or (s[0] == s[-1] == "'")):
        return s[1:-1]
    return s


def load_env_file(path: Path = ENV_PATH) -> dict[str, str]:
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


_ENV = load_env_file()


def get(key: str, default: str | None = None, *, required: bool = False) -> str | None:
    if key in _ENV:
        val = _ENV[key]
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

