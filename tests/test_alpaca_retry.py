"""Tests for Alpaca transient retry helper."""

from __future__ import annotations

import pytest

from src.broker.alpaca import _is_transient_alpaca_error, alpaca_call_with_retry


def test_detects_alpaca_504_timeout():
    assert _is_transient_alpaca_error(Exception('{"code":50410000,"message":"request timed out"}'))
    assert _is_transient_alpaca_error(RuntimeError("Connection reset by peer"))
    assert not _is_transient_alpaca_error(RuntimeError("unauthorized"))


def test_retry_then_succeed(monkeypatch):
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError('{"code":50410000,"message":"request timed out"}')
        return {"ok": True}

    monkeypatch.setattr("src.broker.alpaca.time.sleep", lambda *_a, **_k: None)
    out = alpaca_call_with_retry(flaky, op="test", attempts=4, base_delay_sec=0.01)
    assert out == {"ok": True}
    assert calls["n"] == 3


def test_retry_exhausted_raises(monkeypatch):
    monkeypatch.setattr("src.broker.alpaca.time.sleep", lambda *_a, **_k: None)

    def always_timeout():
        raise RuntimeError('{"code":50410000,"message":"request timed out"}')

    with pytest.raises(RuntimeError, match="timed out"):
        alpaca_call_with_retry(always_timeout, op="test", attempts=3, base_delay_sec=0.01)
