"""Counterfactual ledger for blocked trades."""

from __future__ import annotations

from src.biotech.counterfactual_ledger import append_counterfactual, resolve_counterfactuals
from src.biotech.models import BiotechAnalysisOutput


def test_counterfactual_dedupe(tmp_path):
    path = tmp_path / "cf.jsonl"
    import src.biotech.counterfactual_ledger as cf

    a = BiotechAnalysisOutput(no_trade=True, no_trade_reasons=["test"])
    append_counterfactual(
        run_id="r1",
        run_date="2026-06-01",
        ticker="X",
        catalyst={"nct_id": "NCT1"},
        analysis=a,
        gate_reasons=["no_trade"],
        path=path,
    )
    append_counterfactual(
        run_id="r1",
        run_date="2026-06-01",
        ticker="X",
        catalyst={"nct_id": "NCT1"},
        analysis=a,
        gate_reasons=["no_trade"],
        path=path,
    )
    rows = cf._read_lines(path)
    assert len(rows) == 1


def test_resolve_counterfactual(monkeypatch, tmp_path):
    import json
    from datetime import date

    path = tmp_path / "cf.jsonl"
    import src.biotech.counterfactual_ledger as cf
    import src.biotech.outcome_resolver as or_

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "run_id": "r1",
                "run_date": "2020-01-01",
                "ticker": "MRNA",
                "premium_est_usd": 500,
                "resolved": False,
                "saved_at": "2020-01-01T00:00:00Z",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        or_,
        "_price_on_date",
        lambda t, d: 100.0 if d.day <= 6 else 105.0,
    )
    n = resolve_counterfactuals(today=date(2020, 1, 10), path=path)
    assert n == 1
    row = cf._read_lines(path)[0]
    assert row.get("resolved") is True
