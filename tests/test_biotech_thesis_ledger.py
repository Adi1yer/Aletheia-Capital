"""Thesis ledger append, dedupe, scorecard."""

from __future__ import annotations

from src.biotech.thesis_ledger import append_thesis_entry, scorecard


def test_append_dedupe_same_week(tmp_path):
    path = tmp_path / "thesis.jsonl"
    base = {
        "ticker": "MRNA",
        "arm": "mechanical",
        "run_date": "2026-06-01",
        "nct_id": "NCT0001",
        "status": "open",
        "premium_filled_usd": 500.0,
    }
    id1 = append_thesis_entry(dict(base), path=path)
    id2 = append_thesis_entry(dict(base), path=path)
    assert id1 == id2
    sc = scorecard(weeks=12, path=path)
    assert sc["open_count"] == 1


def test_scorecard_closed_win_rate(tmp_path):
    path = tmp_path / "thesis.jsonl"
    append_thesis_entry(
        {
            "ticker": "X",
            "arm": "mechanical",
            "run_date": "2026-05-01",
            "nct_id": "A",
            "status": "closed",
            "premium_filled_usd": 100.0,
            "pnl_pct_of_premium": 25.0,
            "underlying_px_entry": 10.0,
            "underlying_px_5d": 11.0,
            "llm_prob_high": 0.7,
            "resolved_at": "2026-05-10T00:00:00Z",
        },
        path=path,
    )
    append_thesis_entry(
        {
            "ticker": "Y",
            "arm": "mechanical",
            "run_date": "2026-05-08",
            "nct_id": "B",
            "status": "closed",
            "premium_filled_usd": 100.0,
            "pnl_pct_of_premium": -50.0,
            "underlying_px_entry": 20.0,
            "underlying_px_5d": 19.0,
            "llm_prob_high": 0.3,
            "resolved_at": "2026-05-15T00:00:00Z",
        },
        path=path,
    )
    sc = scorecard(weeks=52, path=path)
    mech = sc["mechanical"]
    assert mech["closed_count"] == 2
    assert mech["win_rate_pct"] == 50.0
