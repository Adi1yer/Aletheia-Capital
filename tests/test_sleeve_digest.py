from __future__ import annotations

import json

from src.fund.sleeve_digest import build_sleeve_digest, format_digest_markdown


def test_build_sleeve_digest_reads_ledger(tmp_path, monkeypatch):
    hedge_dir = tmp_path / "hedge"
    hedge_dir.mkdir()
    ledger = hedge_dir / "trades_ledger.jsonl"
    ledger.write_text(
        json.dumps({"run_date": "2026-06-08", "action": "skip", "reason": "regime_not_harvest"}) + "\n",
        encoding="utf-8",
    )

    class FakeWf:
        workflow_id = "hedge-weekly"
        label = "Beta hedge"
        data_dir = str(hedge_dir)
        enabled = True
        broker = "alpaca"

    monkeypatch.setattr(
        "src.fund.sleeve_digest.list_workflows",
        lambda enabled_only=True: [FakeWf()],
    )
    monkeypatch.setattr(
        "src.fund.sleeve_digest.workflow_credentials_configured",
        lambda wf: True,
    )
    monkeypatch.setattr(
        "src.fund.sleeve_digest.collect_workflow_equity",
        lambda: {"hedge-weekly": {"equity": 100000.0, "equity_delta_pct_1d": 0.1}},
    )

    digest = build_sleeve_digest(run_date="2026-06-08")
    assert digest["sections"][0]["action"] == "skip"
    md = format_digest_markdown(digest)
    assert "SATELLITE SLEEVE WEEKLY DIGEST" in md
    assert "Beta hedge" in md
