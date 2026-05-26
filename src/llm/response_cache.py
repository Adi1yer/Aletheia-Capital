"""Disk-backed LLM response cache for weekly runs."""

from __future__ import annotations

import hashlib
import json
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import structlog

logger = structlog.get_logger()

CACHE_DIR = Path("data/llm_cache")
DEFAULT_TTL_DAYS = 7

_llm_cache_ctx: ContextVar[Optional["LlmCacheContext"]] = ContextVar("llm_cache_ctx", default=None)


@dataclass
class LlmCacheContext:
    enabled: bool = True
    agent_key: str = ""
    ticker: str = ""
    end_date: str = ""
    dossier_fingerprint: str = ""
    prompt_version: str = "v1"


def set_llm_cache_context(ctx: Optional[LlmCacheContext]) -> None:
    _llm_cache_ctx.set(ctx)


def get_llm_cache_context() -> Optional[LlmCacheContext]:
    return _llm_cache_ctx.get()


def dossier_fingerprint(dossier: Optional[dict]) -> str:
    if not dossier:
        return ""
    parts = [
        str(dossier.get("last_price", "")),
        str(dossier.get("news_count", "")),
        str(dossier.get("metrics_summary", "")),
    ]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


def build_cache_key(ctx: LlmCacheContext, output_model_name: str) -> str:
    raw = "|".join(
        [
            ctx.agent_key,
            ctx.ticker,
            ctx.end_date,
            ctx.prompt_version,
            ctx.dossier_fingerprint,
            output_model_name,
        ]
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def _cache_path(key: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{key}.json"


def get_cached_response(key: str, ttl_days: int = DEFAULT_TTL_DAYS) -> Optional[str]:
    path = _cache_path(key)
    if not path.is_file():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        created = datetime.fromisoformat(data.get("created_at", "1970-01-01"))
        if datetime.now() - created > timedelta(days=ttl_days):
            return None
        return data.get("response_text")
    except Exception as e:
        logger.debug("LLM cache read failed", key=key[:12], error=str(e))
        return None


def set_cached_response(key: str, response_text: str, meta: Optional[dict] = None) -> None:
    path = _cache_path(key)
    payload = {
        "created_at": datetime.now().isoformat(),
        "response_text": response_text,
        "meta": meta or {},
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f)


def cache_enabled_globally() -> bool:
    ctx = get_llm_cache_context()
    return bool(ctx and ctx.enabled)
