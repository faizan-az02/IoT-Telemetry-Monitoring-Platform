"""
LangChain playground (GitHub Models via OpenAI-compatible API): natural language -> SAFE Mongo query plan.

This file is intentionally NOT wired into Flask yet.

Why not "LLM generates arbitrary Python code"?
----------------------------------------------
Letting an LLM generate arbitrary Python to run against your DB is effectively
remote code execution. Even if you say "parameterized", the model can still
emit code that deletes data, reads files, or makes network calls.

Instead, we ask the model to output a restricted JSON "plan" (validated),
then we compile that plan into MongoDB query parts ourselves.

Install:
  pip install langchain langchain-openai pydantic pymongo

Env (GitHub Models):
  set GITHUB_MODELS_TOKEN=...        (your GitHub Models token)
  set GITHUB_MODELS_ENDPOINT=https://models.inference.ai.azure.com   (optional)
  set GITHUB_MODEL=gpt-4o-mini       (optional)

Env (OpenAI direct, optional):
  set OPENAI_API_KEY=...
  set OPENAI_MODEL=gpt-4o-mini       (optional)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# TEMP TOKEN PLACEHOLDER (for local experimentation only)
#
# Prefer setting GITHUB_MODELS_TOKEN as an environment variable.
# If you paste a token here, DO NOT commit it to git.
# ---------------------------------------------------------------------------
GITHUB_MODELS_TOKEN = ""  # <-- paste your GitHub Models token here temporarily (or leave blank to use env var)

# GitHub Models OpenAI-compatible endpoint.
GITHUB_MODELS_ENDPOINT = "https://models.inference.ai.azure.com"

# ---- Defaults ----
DEFAULT_MAX_LIMIT = 100
DEFAULT_DEFAULT_LIMIT = 100

# ---- Query plan schema (what the LLM is allowed to output) ----
Op = Literal["eq", "ne", "gt", "gte", "lt", "lte", "between"]
SortDir = Literal["asc", "desc"]
Bucket = Literal["none", "1m", "5m", "1h", "1d"]
Rollup = Literal["avg", "min", "max"]


class TimeRange(BaseModel):
    """
    ISO-8601 timestamps (prefer UTC with 'Z').
    Examples:
      - 2026-01-29T10:30:00Z
      - 2026-01-29T10:30:00+00:00
      - 2026-01-29T10:30:00
    """

    start: Optional[str] = Field(default=None, description="ISO timestamp start (inclusive)")
    end: Optional[str] = Field(default=None, description="ISO timestamp end (inclusive)")


class FilterClause(BaseModel):
    # We only permit the fields you actually store.
    field: Literal["device_id", "timestamp", "cpu", "memory", "disk"]
    op: Op
    # IMPORTANT: Keep these as strings for LLM schema compatibility.
    # We'll parse to float/datetime in compile_plan_to_mongo() based on `field`.
    value: Optional[str] = None
    value2: Optional[str] = None


class NLQueryPlan(BaseModel):
    """
    Restricted plan that can be safely compiled to Mongo queries/pipelines.
    """

    device_id: Optional[str] = Field(default=None, description="Exact device_id match (optional)")
    time: Optional[TimeRange] = Field(default=None, description="Optional ISO time window")
    filters: list[FilterClause] = Field(default_factory=list, description="Additional filters")
    sort: SortDir = Field(default="desc", description="Sort by timestamp")
    limit: Optional[int] = Field(default=DEFAULT_DEFAULT_LIMIT, description="Max docs/buckets to return")
    bucket: Bucket = Field(default="none", description="Aggregation bucket size")
    rollup: Rollup = Field(default="avg", description="When bucket != none, choose rollup")


# ---- Mapping from plan fields to your Mongo schema ----
PLAN_FIELD_TO_MONGO_FIELD = {
    "device_id": "device_id",
    "timestamp": "timestamp",
    "cpu": "cpu_usage (%)",
    "memory": "memory_usage (%)",
    "disk": "disk_usage (%)",
}


def _default_model() -> str:
    import os

    return os.getenv("GITHUB_MODEL") or os.getenv("OPENAI_MODEL", "gpt-4o-mini")


def _parse_iso_to_utc_naive(iso: str) -> datetime:
    """
    Parse ISO string to a UTC datetime, then convert to naive UTC.
    This repo stores naive datetimes in Mongo (telemetry.py uses datetime.now()).
    """
    s = iso.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.replace(tzinfo=None)


def _clamp_limit(limit: Optional[int], *, max_limit: int) -> int:
    if limit is None:
        return max_limit
    try:
        n = int(limit)
    except Exception:
        return max_limit
    if n <= 0:
        return 1
    return min(n, max_limit)


def compile_plan_to_mongo(plan: NLQueryPlan, *, max_limit: int = DEFAULT_MAX_LIMIT) -> dict[str, Any]:
    """
    Compile a validated NLQueryPlan into query parts:
      - filter: dict
      - sort: ("timestamp", +/-1)
      - limit: int (always capped)
      - bucket/rollup: for optional aggregation
    """
    limit = _clamp_limit(plan.limit, max_limit=max_limit)
    q: dict[str, Any] = {}

    if plan.device_id:
        q["device_id"] = plan.device_id

    # Time range
    if plan.time and (plan.time.start or plan.time.end):
        rng: dict[str, Any] = {}
        if plan.time.start:
            rng["$gte"] = _parse_iso_to_utc_naive(plan.time.start)
        if plan.time.end:
            rng["$lte"] = _parse_iso_to_utc_naive(plan.time.end)
        q["timestamp"] = rng

    # Additional filters
    for f in plan.filters:
        field = PLAN_FIELD_TO_MONGO_FIELD.get(f.field)
        if not field:
            continue

        if f.op == "between":
            if f.value is None or f.value2 is None:
                continue
            # timestamps are special: parse iso -> datetime
            if f.field == "timestamp":
                v1 = _parse_iso_to_utc_naive(f.value)
                v2 = _parse_iso_to_utc_naive(f.value2)
                q[field] = {"$gte": v1, "$lte": v2}
            else:
                try:
                    v1n = float(f.value)
                    v2n = float(f.value2)
                except Exception:
                    continue
                q[field] = {"$gte": v1n, "$lte": v2n}
            continue

        if f.value is None:
            continue

        if f.field == "timestamp":
            v = _parse_iso_to_utc_naive(f.value)
        elif f.field == "device_id":
            v = f.value
        else:
            try:
                v = float(f.value)
            except Exception:
                continue

        op_map = {
            "eq": None,
            "ne": "$ne",
            "gt": "$gt",
            "gte": "$gte",
            "lt": "$lt",
            "lte": "$lte",
        }
        mongo_op = op_map.get(f.op)
        if mongo_op is None:
            q[field] = v
        else:
            q[field] = {mongo_op: v}

    sort_dir = 1 if plan.sort == "asc" else -1

    return {
        "filter": q,
        "sort": ("timestamp", sort_dir),
        "limit": limit,
        "bucket": plan.bucket,
        "rollup": plan.rollup,
    }


@dataclass(frozen=True)
class LangChainConfig:
    model: str
    temperature: float = 0.0


def build_chain(config: Optional[LangChainConfig] = None):
    """
    Returns a callable: (text, now_iso?) -> NLQueryPlan
    """
    try:
        from langchain_openai import ChatOpenAI  # pip install langchain-openai
    except ModuleNotFoundError as e:
        raise ModuleNotFoundError(
            "Missing dependency: langchain_openai.\n\n"
            "Install it with:\n"
            "  pip install langchain-openai\n\n"
            "If you're using a virtualenv/conda env, make sure it's activated before installing."
        ) from e

    # --- GitHub Models (OpenAI-compatible) ---
    #
    # GitHub Models uses an OpenAI-compatible API surface, but with:
    # - base URL: https://models.inference.ai.azure.com
    # - token: a GitHub Models token (NOT an OpenAI key)
    #
    # We configure via environment variables so langchain-openai + openai SDK use them.
    import os

    token = os.getenv("GITHUB_MODELS_TOKEN") or GITHUB_MODELS_TOKEN
    endpoint = os.getenv("GITHUB_MODELS_ENDPOINT") or GITHUB_MODELS_ENDPOINT

    if not token:
        raise RuntimeError(
            "Missing GitHub Models token.\n\n"
            "Set it in PowerShell (current session):\n"
            "  $env:GITHUB_MODELS_TOKEN = \"github_...\"\n"
            "  $env:GITHUB_MODEL = \"gpt-4o-mini\"   # optional\n"
            "  python nl_query_langchain.py\n\n"
            "Or set permanently:\n"
            "  setx GITHUB_MODELS_TOKEN \"github_...\"\n"
            "Then restart your terminal/IDE."
        )

    cfg = config or LangChainConfig(model=_default_model())
    # Pass explicitly so we don't rely on OPENAI_API_KEY being present in the parent process env.
    llm = ChatOpenAI(model=cfg.model, temperature=cfg.temperature, api_key=token, base_url=endpoint)

    system = (
        "You translate plain-English analytics requests into a STRICT JSON plan.\n"
        "You MUST follow the provided JSON schema exactly.\n"
        "You are querying MongoDB telemetry documents with fields:\n"
        "- device_id (string)\n"
        "- timestamp (datetime)\n"
        "- cpu_usage (%) (number)\n"
        "- memory_usage (%) (number)\n"
        "- disk_usage (%) (number)\n\n"
        "Rules:\n"
        "- Read-only queries only. Never request updates/deletes.\n"
        "- If the user asks for 'all data', still use limit=100.\n"
        "- Use ISO timestamps; prefer UTC with Z.\n"
        "- Use cpu/memory/disk for thresholds.\n"
    )

    # GitHub Models / OpenAI-compatible endpoints may reject strict JSON schema
    # if it contains unsupported constructs. Function calling is more tolerant.
    chain = llm.with_structured_output(NLQueryPlan, method="function_calling")

    def invoke(text: str, *, now_iso: Optional[str] = None) -> NLQueryPlan:
        user = f"Request: {text.strip()}"
        if now_iso:
            user += f"\nCurrent time (ISO): {now_iso}"
        return chain.invoke(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]
        )

    return invoke


def nl_to_mongo_query(
    text: str,
    *,
    max_limit: int = DEFAULT_MAX_LIMIT,
    now: Optional[datetime] = None,
    config: Optional[LangChainConfig] = None,
) -> dict[str, Any]:
    """
    High-level helper:
      text -> NLQueryPlan (LLM) -> compiled Mongo query parts
    """
    now_iso = None
    if now:
        now_iso = now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    invoke = build_chain(config=config)
    plan = invoke(text, now_iso=now_iso)
    compiled = compile_plan_to_mongo(plan, max_limit=max_limit)
    return {"plan": plan, "compiled": compiled}


if __name__ == "__main__":
    # Dry-run playground (no DB). Prints the plan + compiled query.
    import json as _json

    prompt = "Show me last 24 hours for device edge-1 where cpu > 60, newest first"
    out = nl_to_mongo_query(prompt, max_limit=100, now=datetime.now(timezone.utc))

    print("PLAN:")
    print(out["plan"].model_dump_json(indent=2))

    print("\nCOMPILED:")
    compiled = dict(out["compiled"])
    f = compiled.get("filter", {})
    # JSON-print friendly
    if isinstance(f, dict) and "timestamp" in f and isinstance(f["timestamp"], dict):
        ts = f["timestamp"]
        compiled["filter"] = {**f, "timestamp": {k: v.isoformat() for k, v in ts.items()}}
    print(_json.dumps(compiled, indent=2))

