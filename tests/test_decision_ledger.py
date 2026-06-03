"""Tests for decision attribution ledger."""

from __future__ import annotations

from src.performance.decision_ledger import (
    append_decisions_from_run,
    outcome_rows_for_email,
    parse_reason_class,
    resolve_pending_outcomes,
)


def test_parse_reason_class():
    assert parse_reason_class("Cash rotation: fund SMCI") == "cash_rotation"
    assert parse_reason_class("Rebalance: bearish signal") == "rebalance"
    assert parse_reason_class("Conviction sell on weak thesis") == "conviction"
    assert parse_reason_class("CC lot build for covered calls") == "cc_lot"


def test_resolve_only_prior_week(tmp_path):
    path = tmp_path / "decision_ledger.jsonl"
    for run_date in ("2026-05-01", "2026-05-08", "2026-05-15"):
        append_decisions_from_run(
            run_id=f"r-{run_date}",
            run_date=run_date,
            regime={"mode": "neutral"},
            decisions={
                "AAPL": {
                    "action": "buy",
                    "quantity": 1,
                    "confidence": 80,
                    "reasoning": "test",
                }
            },
            risk_analysis={"AAPL": {"current_price": 100.0}},
            agent_signals={},
            execution_results={},
            path=path,
        )
    n = resolve_pending_outcomes({"AAPL": 105.0}, "2026-05-22", path=path)
    assert n == 1


def test_append_and_resolve(tmp_path):
    path = tmp_path / "decision_ledger.jsonl"
    append_decisions_from_run(
        run_id="r1",
        run_date="2026-05-12",
        regime={"mode": "accumulate"},
        decisions={
            "AAPL": {
                "action": "buy",
                "quantity": 10,
                "confidence": 85,
                "reasoning": "Cash rotation: fund AAPL",
            }
        },
        risk_analysis={"AAPL": {"current_price": 100.0}},
        agent_signals={
            "growth": {"AAPL": {"signal": "bullish", "confidence": 90}},
        },
        execution_results={"AAPL": {"status": "filled"}},
        path=path,
    )
    n = resolve_pending_outcomes({"AAPL": 110.0}, "2026-05-19", path=path)
    assert n == 1
    rows = outcome_rows_for_email(path=path)
    assert rows[0]["ticker"] == "AAPL"
    assert rows[0]["return_pct"] == 10.0
