"""Simple file-backed GET cache for respectful EDGAR / ClinicalTrials usage."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Optional

import requests
import structlog

logger = structlog.get_logger()

DEFAULT_UA = "AI-Hedge-Fund-BiotechBot/1.0 (research; contact: local)"


def _cache_path(base: Path, key: str) -> Path:
    h = hashlib.sha256(key.encode()).hexdigest()[:24]
    return base / f"{h}.json"


def cached_get_json(
    url: str,
    cache_dir: str = "data/biotech_cache/http",
    ttl_seconds: int = 86400,
    headers: Optional[dict] = None,
) -> Any:
    """GET JSON with day-long default cache."""
    base = Path(cache_dir)
    base.mkdir(parents=True, exist_ok=True)
    p = _cache_path(base, url)
    import time

    if p.exists():
        try:
            meta = json.loads(p.read_text())
            if time.time() - meta.get("ts", 0) < ttl_seconds:
                return meta.get("data")
        except Exception:
            pass

    h = dict(headers or {})
    h.setdefault("User-Agent", DEFAULT_UA)
    h.setdefault("Accept", "application/json")
    r = requests.get(url, headers=h, timeout=60)
    r.raise_for_status()
    data = r.json()
    p.write_text(json.dumps({"ts": time.time(), "data": data}, default=str))
    return data


def cached_get_text(
    url: str,
    cache_dir: str = "data/biotech_cache/http",
    ttl_seconds: int = 86400,
    headers: Optional[dict] = None,
) -> str:
    base = Path(cache_dir)
    base.mkdir(parents=True, exist_ok=True)
    p = _cache_path(base, "text:" + url)
    import time

    if p.exists():
        try:
            meta = json.loads(p.read_text())
            if time.time() - meta.get("ts", 0) < ttl_seconds:
                return str(meta.get("data", ""))
        except Exception:
            pass

    h = dict(headers or {})
    h.setdefault("User-Agent", DEFAULT_UA)
    r = requests.get(url, headers=h, timeout=60)
    r.raise_for_status()
    text = r.text
    p.write_text(json.dumps({"ts": time.time(), "data": text}))
    return text
