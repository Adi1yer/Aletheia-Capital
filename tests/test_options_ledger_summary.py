"""Tests for options ledger rolling summary."""

from __future__ import annotations

from src.performance.options_ledger import append_csp_results, recent_summary


def test_recent_summary_aggregates(tmp_path):
    path = tmp_path / "options.jsonl"
    append_csp_results(
        run_id="r1",
        run_date="2026-05-11",
        csp_results=[
            {"underlying": "AAPL", "status": "executed", "estimated_premium": 60, "strike": 150},
            {"underlying": "MSFT", "status": "executed", "estimated_premium": 100, "strike": 400},
        ],
        path=path,
    )
    summary = recent_summary(weeks=8, path=path)
    assert summary["csp_executed"] == 2
    assert summary["csp_avg_premium_usd"] == 80.0
    assert summary["csp_sub_floor_count"] >= 1
