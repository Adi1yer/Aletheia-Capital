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
        snapshot_subdir = "multi_sleeve"
        account_group = "multi_sleeve"
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
    assert digest["sections"][0]["reason"] == "regime_not_harvest"
    assert digest["total_satellite_equity"] == 100000.0
    md = format_digest_markdown(digest)
    assert "SATELLITE SLEEVE WEEKLY DIGEST" in md
    assert "Beta hedge" in md


def test_congressional_empty_picks_reason_no_picks(tmp_path, monkeypatch):
    cong_dir = tmp_path / "congressional"
    cong_dir.mkdir()
    ledger = cong_dir / "trades_ledger.jsonl"
    ledger.write_text(
        json.dumps({"run_date": "2026-06-15", "picks": [], "executed": False}) + "\n",
        encoding="utf-8",
    )

    class FakeWf:
        workflow_id = "congressional"
        label = "Congressional trades"
        data_dir = str(cong_dir)
        snapshot_subdir = "multi_sleeve"
        account_group = "multi_sleeve"
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
        lambda: {"congressional": {"equity": 50000.0}},
    )

    digest = build_sleeve_digest(run_date="2026-06-15")
    assert digest["sections"][0]["reason"] == "no_picks"
    md = format_digest_markdown(digest)
    assert "no_picks" in md
    assert "no_ledger" not in md


def test_missing_ledger_file_reason(tmp_path, monkeypatch):
    empty_dir = tmp_path / "crypto"
    empty_dir.mkdir()

    class FakeWf:
        workflow_id = "crypto-weekly"
        label = "Crypto momentum"
        data_dir = str(empty_dir)
        snapshot_subdir = "multi_sleeve"
        account_group = "multi_sleeve"
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
        lambda: {"crypto-weekly": {"equity": 0.0}},
    )

    digest = build_sleeve_digest(run_date="2026-06-15")
    assert digest["sections"][0]["reason"] == "no_ledger_file"


def test_total_equity_dedupes_shared_snapshot(tmp_path, monkeypatch):
    class FakeWf:
        def __init__(self, wid, label, data_dir):
            self.workflow_id = wid
            self.label = label
            self.data_dir = str(data_dir)
            self.snapshot_subdir = "multi_sleeve"
            self.account_group = "multi_sleeve"
            self.enabled = True
            self.broker = "alpaca"

    hedge_dir = tmp_path / "hedge"
    crypto_dir = tmp_path / "crypto"
    hedge_dir.mkdir()
    crypto_dir.mkdir()

    workflows = [
        FakeWf("hedge-weekly", "Beta hedge", hedge_dir),
        FakeWf("crypto-weekly", "Crypto", crypto_dir),
    ]

    monkeypatch.setattr(
        "src.fund.sleeve_digest.list_workflows",
        lambda enabled_only=True: workflows,
    )
    monkeypatch.setattr(
        "src.fund.sleeve_digest.workflow_credentials_configured",
        lambda wf: True,
    )
    monkeypatch.setattr(
        "src.fund.sleeve_digest.collect_workflow_equity",
        lambda: {
            "hedge-weekly": {"equity": 80000.0},
            "crypto-weekly": {"equity": 80000.0},
        },
    )

    digest = build_sleeve_digest(run_date="2026-06-15")
    assert digest["total_satellite_equity"] == 80000.0
