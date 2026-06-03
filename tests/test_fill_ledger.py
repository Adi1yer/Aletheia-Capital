"""Tests for fill ledger."""

from __future__ import annotations

from src.performance.fill_ledger import append_fills_from_run, slippage_by_reason_class


def test_append_fills_and_slippage(tmp_path, monkeypatch):
    path = tmp_path / "fills.jsonl"
    monkeypatch.setattr("src.performance.fill_ledger.LEDGER_PATH", path)
    n = append_fills_from_run(
        run_id="r1",
        run_date="2026-05-19",
        decisions={
            "AAPL": {
                "action": "buy",
                "quantity": 10,
                "reasoning": "Cash rotation: fund AAPL",
            }
        },
        risk_analysis={"AAPL": {"current_price": 100.0}},
        execution_results={
            "AAPL": {
                "status": "filled",
                "order_id": "o1",
                "filled_avg_price": 100.5,
                "filled_qty": 10,
            }
        },
        recent_orders=[],
        path=path,
    )
    assert n == 1
    slip = slippage_by_reason_class(weeks=12, path=path)
    assert slip.get("cash_rotation", 0) > 0
