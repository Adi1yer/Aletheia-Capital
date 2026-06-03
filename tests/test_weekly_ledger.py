"""Tests for compact weekly ledger fallback learning."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.performance import weekly_ledger as wl


@pytest.fixture
def ledger_path(tmp_path: Path) -> Path:
    return tmp_path / "weekly_ledger.jsonl"


def test_append_and_scorecard_from_two_lines(ledger_path: Path):
    wl.append_ledger_entry(
        run_id="run_a",
        run_date="2026-05-12",
        active_agents=["agent_a"],
        tickers={
            "AAA": {
                "price": 100.0,
                "agent_signals": {
                    "agent_a": {"signal": "bullish", "confidence": 80},
                },
            }
        },
        path=ledger_path,
    )
    wl.append_ledger_entry(
        run_id="run_b",
        run_date="2026-05-19",
        active_agents=["agent_a"],
        tickers={
            "AAA": {
                "price": 110.0,
                "agent_signals": {
                    "agent_a": {"signal": "bullish", "confidence": 80},
                },
            }
        },
        path=ledger_path,
    )

    assert wl.ledger_run_count(ledger_path) == 2
    sc = wl.evaluate_ledger_scorecard(path=ledger_path)
    assert sc.get("source") == "weekly_ledger"
    assert "agent_a" in (sc.get("agents") or {})
    assert sc["agents"]["agent_a"]["directional_accuracy"] == 1.0


def test_feedback_uses_ledger_when_scan_cache_empty(tmp_path: Path, monkeypatch):
    ledger_path = tmp_path / "weekly_ledger.jsonl"
    for i, price in enumerate([50.0, 55.0], start=1):
        wl.append_ledger_entry(
            run_id=f"r{i}",
            run_date=f"2026-05-{10 + i}",
            active_agents=["growth"],
            tickers={
                "XYZ": {
                    "price": price,
                    "agent_signals": {
                        "growth": {"signal": "bullish", "confidence": 70},
                    },
                }
            },
            path=ledger_path,
        )

    class EmptyCache:
        def list_runs(self, limit=500):
            return []

    monkeypatch.setattr(wl, "LEDGER_PATH", ledger_path)
    from src.backtesting import feedback

    monkeypatch.setattr(feedback, "SCORECARD_PATH", str(tmp_path / "agent_scorecard.json"))
    monkeypatch.setattr(feedback, "DEFAULT_FEEDBACK_PATH", str(tmp_path / "agent_feedback.json"))

    meta = feedback.refresh_feedback_from_cache(EmptyCache())
    assert meta["scan_cache_run_count"] == 0
    assert meta["ledger_run_count"] == 2
    assert meta["wrote_scorecard_file"] is True
    assert meta["scorecard_source"] == "weekly_ledger"

    with open(tmp_path / "agent_scorecard.json") as f:
        saved = json.load(f)
    assert saved.get("source") == "weekly_ledger"
