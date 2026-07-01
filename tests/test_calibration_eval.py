"""Calibration eval on/off delta tests."""

from __future__ import annotations

import json

import scripts.calibration_eval as ce
from src.performance import weekly_ledger as wl
from src.performance.weekly_ledger import append_ledger_entry


def test_on_off_differ_with_calibration_penalty(tmp_path, monkeypatch):
    ledger = tmp_path / "weekly_ledger.jsonl"
    cal_path = tmp_path / "ticker_calibration.json"
    cal_path.write_text(
        json.dumps(
            {
                "pairs": {
                    "growth|ZZZ": [
                        {"directionally_correct": False},
                        {"directionally_correct": False},
                        {"directionally_correct": False},
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(ce, "load_ticker_calibration", lambda path=None: json.loads(cal_path.read_text()))
    monkeypatch.setattr(
        ce,
        "composite_for_agent",
        lambda agent_key, path=None: 0.30 if agent_key == "growth" else 0.80,
    )

    for run_date, price in (("2026-05-11", 100.0), ("2026-05-18", 90.0)):
        append_ledger_entry(
            run_id=f"r-{run_date}",
            run_date=run_date,
            active_agents=["growth"],
            regime="neutral",
            tickers={
                "ZZZ": {
                    "price": price,
                    "agent_signals": {
                        "growth": {"signal": "bullish", "confidence": 85},
                    },
                }
            },
            path=ledger,
        )

    monkeypatch.setattr(ce, "read_ledger_lines", lambda: wl._read_lines(ledger))
    payload = ce._eval_from_ledger(max_pairs=4)
    off = payload["off_calibration"]
    on = payload["on_calibration"]
    assert payload["pairs_used"] >= 1
    assert off["confidence_weighted_return"] != on["confidence_weighted_return"]


def test_eval_from_ledger_produces_delta(tmp_path, monkeypatch):
    ledger = tmp_path / "weekly_ledger.jsonl"
    append_ledger_entry(
        run_id="r1",
        run_date="2026-05-11",
        active_agents=["growth"],
        regime="neutral",
        tickers={
            "ZZZ": {
                "price": 100.0,
                "agent_signals": {"growth": {"signal": "bullish", "confidence": 70}},
            }
        },
        path=ledger,
    )
    append_ledger_entry(
        run_id="r2",
        run_date="2026-05-18",
        active_agents=["growth"],
        regime="neutral",
        tickers={
            "ZZZ": {
                "price": 105.0,
                "agent_signals": {"growth": {"signal": "bullish", "confidence": 70}},
            }
        },
        path=ledger,
    )
    monkeypatch.setattr(ce, "read_ledger_lines", lambda: wl._read_lines(ledger))
    payload = ce._eval_from_ledger(max_pairs=4)
    assert payload.get("pairs_used", 0) >= 1
    assert "off_calibration" in payload


def test_run_eval_skips_when_insufficient_history(monkeypatch):
    monkeypatch.setattr(ce, "_eval_from_scan_cache", lambda max_pairs=8: {"error": "insufficient_scan_cache_runs", "pairs": 0})
    monkeypatch.setattr(ce, "_eval_from_ledger", lambda max_pairs=8: {"error": "insufficient_ledger_rows", "pairs": 0})
    payload = ce.run_eval(source="scan_cache", max_pairs=8)
    assert payload.get("status") == "skipped"
    assert payload.get("skip_reason") == "insufficient_ledger_rows"
    assert payload.get("fallback_from") == "insufficient_scan_cache_runs"
