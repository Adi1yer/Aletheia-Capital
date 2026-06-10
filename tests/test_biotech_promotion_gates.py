"""Biotech promotion gates on ledger holdout."""

from __future__ import annotations

from src.biotech.promotion_gates import evaluate_biotech_proposal


def test_promotion_insufficient_dates(tmp_path):
    result = evaluate_biotech_proposal({})
    assert result["promote"] is True
    assert "insufficient" in result["reason"]


def test_holdout_rejects_bad_llm_arm(monkeypatch):
    rows = [
        {
            "ticker": "MRNA",
            "arm": "llm_gated",
            "run_date": d,
            "nct_id": "NCT1",
            "status": "closed",
            "pnl_pct_of_premium": pnl,
        }
        for d, pnl in [
            ("2026-04-01", 30.0),
            ("2026-04-08", 25.0),
            ("2026-05-01", -40.0),
            ("2026-05-08", -35.0),
        ]
    ]
    import src.biotech.promotion_gates as pg

    monkeypatch.setattr(pg, "recent_entries", lambda weeks=24: rows)
    result = evaluate_biotech_proposal({"min_llm_prob_mid": 0.5})
    assert result["promote"] is False
