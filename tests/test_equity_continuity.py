"""Tests for equity continuity / stale-cache guards."""

from src.performance.equity_continuity import compatible_prior_equity, sanitize_prior_context
from src.performance.benchmark_report import build_benchmark_report, enrich_results_benchmark


def test_rejects_account_reset_scale_jump():
    assert compatible_prior_equity(10000.0, 102000.0) is None
    assert compatible_prior_equity(10000.0, 9500.0) == 9500.0
    assert compatible_prior_equity(10000.0, None) is None


def test_sanitize_prior_drops_do_nothing_on_reject():
    prior = {
        "prev_equity": 102000.0,
        "do_nothing_return_pct": 1.5,
        "prev_run_id": "old",
    }
    out = sanitize_prior_context(prior, equity_now=10000.0)
    assert out["prev_equity"] is None
    assert out["do_nothing_return_pct"] is None
    assert out["prior_equity_rejected"] is True


def test_benchmark_skips_poisoned_prev():
    report = build_benchmark_report(equity_now=10000.0, equity_prev=None)
    assert report["equity_delta_pct"] is None
    assert report["active_vs_spy_pct"] is None


def test_enrich_rejects_learning_prev_equity():
    results = {
        "run_id": "curr",
        "portfolio": {"equity": 10000.0},
        "learning_context": {"prev_equity": 102137.0, "do_nothing_return_pct": 2.0},
    }
    enrich_results_benchmark(results, data_provider=None, scan_cache=None)
    assert results["learning_context"]["prev_equity"] is None
    assert results["benchmark"]["equity_delta_pct"] is None
