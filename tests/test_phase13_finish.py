"""Tests for Phase 13 finish-up wiring."""

from __future__ import annotations

from datetime import date, timedelta

from src.biotech.ghost_prune import _row_looks_ghost
from src.biotech.fills_reconcile import reconcile_straddle_orders
from src.fund.orchestrator import default_allocation, load_sleeve_budget_targets
from src.performance.benchmark_report import build_benchmark_report
from src.performance.prior_run import _equity_from_portfolio


def test_fills_reconcile_alias_imports():
    assert callable(reconcile_straddle_orders)


def test_sleeve_budget_targets_loaded():
    t = load_sleeve_budget_targets()
    assert t.get("weekly-scan", 0) >= 0.5
    assert t.get("hedge-weekly", 0) > 0


def test_default_allocation_uses_sleeve_budgets():
    alloc = default_allocation()
    assert "targets" in alloc
    assert abs(sum(alloc["targets"].values()) - 1.0) < 0.05


def test_benchmark_active_vs_spy():
    r = build_benchmark_report(
        equity_now=110.0,
        equity_prev=100.0,
        prior_portfolio_return_pct=5.0,
        data_provider=None,
    )
    assert r["equity_delta_pct"] == 10.0
    assert r["active_vs_do_nothing_pct"] == 5.0


def test_equity_from_portfolio_overrides():
    port = {"cash": 10.0, "positions": {"AAA": {"long": 2, "long_cost_basis": 5.0}}}
    eq = _equity_from_portfolio(port, price_overrides={"AAA": 20.0})
    assert eq == 50.0


def test_ghost_row_detection():
    past = (date.today() - timedelta(days=20)).isoformat()
    assert _row_looks_ghost({"readout_date": past, "has_results": False}, date.today())
    assert not _row_looks_ghost(
        {"readout_date": past, "has_results": True, "results_first_posted": past},
        date.today(),
    )
