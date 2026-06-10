"""Past trades context for LLM."""

from __future__ import annotations

from src.biotech.thesis_ledger import append_thesis_entry, format_past_trades_context


def test_format_past_trades_nonempty(tmp_path):
    path = tmp_path / "t.jsonl"
    append_thesis_entry(
        {
            "ticker": "MRNA",
            "arm": "mechanical",
            "run_date": "2026-05-01",
            "status": "closed",
            "pnl_pct_of_premium": 22.0,
            "phase": "Phase 3",
            "underlying_px_entry": 50.0,
            "underlying_px_5d": 55.0,
            "clinical_outcome": "success",
            "llm_prob_low": 0.4,
            "llm_prob_high": 0.6,
        },
        path=path,
    )
    ctx = format_past_trades_context(weeks=12, path=path)
    assert "PAST_RESOLVED_TRADES" in ctx
    assert "MRNA" in ctx
