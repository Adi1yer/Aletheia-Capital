"""Outcome resolver closes rows when legs leave the book."""

from __future__ import annotations

from unittest.mock import MagicMock

from src.biotech.outcome_resolver import resolve_open_thesis_entries
from src.biotech.thesis_ledger import append_thesis_entry


def test_resolve_closes_when_legs_gone(tmp_path, monkeypatch):
    path = tmp_path / "thesis.jsonl"
    append_thesis_entry(
        {
            "trade_id": "t1",
            "ticker": "MRNA",
            "arm": "mechanical",
            "run_date": "2026-04-01",
            "entry_date": "2026-04-01",
            "nct_id": "NCT1",
            "status": "open",
            "premium_filled_usd": 400.0,
            "call_contract": "CALLSYM",
            "put_contract": "PUTSYM",
            "readout_date_expected": "2026-03-01",
            "underlying_px_entry": 100.0,
        },
        path=path,
    )
    broker = MagicMock()
    broker.get_option_positions.return_value = []
    broker.get_positions.return_value = {}

    monkeypatch.setattr(
        "src.biotech.outcome_resolver.refresh_trial_status",
        lambda nct, co: "Completed",
    )
    monkeypatch.setattr(
        "src.biotech.outcome_resolver._price_on_date",
        lambda t, d: 105.0,
    )

    n = resolve_open_thesis_entries(broker, path=path)
    assert n >= 1
    from src.biotech.thesis_ledger import _read_lines

    rows = _read_lines(path)
    row = next(r for r in rows if r.get("trade_id") == "t1")
    assert row.get("status") in ("closed", "expired")
    assert row.get("clinical_outcome") == "success"
