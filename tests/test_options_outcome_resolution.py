"""Tests for options outcome resolution."""

from __future__ import annotations

from src.performance.options_ledger import append_csp_results, resolve_option_outcomes


def test_resolve_expired_csp(tmp_path):
    path = tmp_path / "opts.jsonl"
    append_csp_results(
        run_id="r1",
        run_date="2026-05-01",
        csp_results=[
            {
                "underlying": "AAPL",
                "status": "executed",
                "estimated_premium": 100,
                "strike": 150,
                "expiry": "2026-05-15",
                "contracts": 1,
                "contract_symbol": "AAPL250515C00150000",
            }
        ],
        path=path,
    )
    n = resolve_option_outcomes(
        "2026-05-20",
        current_prices={"AAPL": 140.0},
        path=path,
    )
    assert n == 1
