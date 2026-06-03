"""Tests for portfolio attribution ledger."""

from __future__ import annotations

from src.performance.portfolio_attribution import append_weekly_attribution, attribution_week_count


def test_weekly_attribution_row(tmp_path):
    path = tmp_path / "attr.jsonl"
    row = append_weekly_attribution(
        run_id="r1",
        run_date="2026-05-19",
        portfolio_before={"cash": 10000, "positions": {}},
        portfolio_after={"cash": 9500, "equity": 10100, "positions": {}},
        risk_analysis={},
        fills=[],
        options_premium_usd=150.0,
        path=path,
    )
    assert row["equity_delta_usd"] == 100.0
    assert row["options_premium_usd"] == 150.0
    assert attribution_week_count(path=path) == 1
