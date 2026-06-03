"""Learning changelog and weight gates."""

from __future__ import annotations

from src.performance.learning_changelog import append_changelog_entry, latest_entry
from src.performance.tracker import PerformanceTracker


def test_weight_gates_skip_low_observations(tmp_path):
    pt = PerformanceTracker(data_dir=str(tmp_path / "perf"))
    metrics = {
        "agent_a": {"directional_accuracy": 0.9, "directional_observations": 5, "confidence_weighted_return_pct": 2.0},
    }
    new_w, meta = pt.calculate_weights_from_performance(
        scorecard_metrics=metrics,
        current_weights={"agent_a": 1.0},
        min_observations_for_move=15,
        max_weight_delta_per_run=0.15,
    )
    assert new_w["agent_a"] == 1.0
    assert meta["weight_skips"][0]["reason"] == "insufficient_observations"


def test_changelog_append(tmp_path):
    path = tmp_path / "changelog.jsonl"
    append_changelog_entry(
        run_id="r1",
        run_date="2026-05-19",
        weight_changes=[{"agent": "a", "old": 1.0, "new": 1.1, "observations": 20}],
        path=path,
    )
    entry = latest_entry(path)
    assert entry["weight_changes"][0]["agent"] == "a"


def test_load_from_weekly_ledger(tmp_path):
    from src.performance.weekly_ledger import append_ledger_entry

    ledger = tmp_path / "weekly_ledger.jsonl"
    for run_date, price in (("2026-05-11", 100.0), ("2026-05-18", 110.0)):
        append_ledger_entry(
            run_id=f"r-{run_date}",
            run_date=run_date,
            active_agents=["growth"],
            regime="neutral",
            tickers={
                "AAPL": {
                    "price": price,
                    "agent_signals": {"growth": {"signal": "bullish", "confidence": 80}},
                }
            },
            path=ledger,
        )
    pt = PerformanceTracker(data_dir=str(tmp_path / "perf"))
    added = pt.load_from_weekly_ledger(limit_pairs=5, path=str(ledger))
    assert added >= 1
