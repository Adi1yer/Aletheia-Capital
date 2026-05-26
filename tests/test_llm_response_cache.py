"""Tests for LLM response cache."""

import json
from datetime import datetime, timedelta

from src.llm.response_cache import (
    LlmCacheContext,
    build_cache_key,
    get_cached_response,
    set_cached_response,
    _cache_path,
)


def test_cache_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr("src.llm.response_cache.CACHE_DIR", tmp_path)
    ctx = LlmCacheContext(
        agent_key="warren_buffett",
        ticker="AAPL",
        end_date="2026-05-26",
        dossier_fingerprint="abc123",
    )
    key = build_cache_key(ctx, "AgentSignal")
    set_cached_response(key, '{"signal":"bullish","confidence":80,"reasoning":"test"}')
    assert get_cached_response(key) is not None


def test_cache_expired(tmp_path, monkeypatch):
    monkeypatch.setattr("src.llm.response_cache.CACHE_DIR", tmp_path)
    key = "deadbeef"
    path = _cache_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    old = (datetime.now() - timedelta(days=30)).isoformat()
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"created_at": old, "response_text": "{}"}, f)
    assert get_cached_response(key, ttl_days=7) is None
