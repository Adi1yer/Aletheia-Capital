"""Ticker calibration from weekly ledger."""

from __future__ import annotations

from src.backtesting.learning_outcomes import rebuild_ticker_agent_calibration_from_ledger
from src.performance.weekly_ledger import append_ledger_entry


def test_rebuild_ticker_calibration_from_ledger(tmp_path, monkeypatch):
    ledger = tmp_path / "weekly_ledger.jsonl"
    for i, price in enumerate([50.0, 55.0], start=1):
        append_ledger_entry(
            run_id=f"r{i}",
            run_date=f"2026-05-{10+i}",
            active_agents=["growth"],
            regime="accumulate",
            tickers={
                "XYZ": {
                    "price": price,
                    "agent_signals": {
                        "growth": {"signal": "bullish", "confidence": 70},
                    },
                }
            },
            path=ledger,
        )
    out_path = tmp_path / "ticker_cal.json"
    payload = rebuild_ticker_agent_calibration_from_ledger(
        max_run_pairs=5,
        output_path=str(out_path),
        ledger_path=str(ledger),
    )
    assert payload.get("source") == "weekly_ledger"
    assert "growth|XYZ" in (payload.get("pairs") or {})
