from __future__ import annotations

from types import SimpleNamespace

import daily_health_check as dhc


def test_main_continues_when_one_account_raises(monkeypatch):
    wf_ok = SimpleNamespace(
        workflow_id="weekly-scan",
        snapshot_subdir="stock",
        label="Equity",
        broker="alpaca",
        physical_account_key="equity",
    )
    wf_bad = SimpleNamespace(
        workflow_id="hedge-weekly",
        snapshot_subdir="multi_sleeve",
        label="Hedge",
        broker="alpaca",
        physical_account_key="multi_sleeve",
    )

    class OkBroker:
        def get_account(self):
            return {"equity": 100000, "cash": 50000, "buying_power": 50000}

        def get_positions(self):
            return {}

        def disconnect(self):
            pass

    class BadBroker:
        def get_account(self):
            raise RuntimeError("unauthorized")

        def disconnect(self):
            pass

    monkeypatch.setattr(dhc, "_resolve_accounts_arg", lambda arg: [wf_ok, wf_bad])
    monkeypatch.setattr(dhc, "workflow_credentials_configured", lambda wf: True)
    monkeypatch.setattr(
        dhc,
        "try_get_broker",
        lambda wid: OkBroker() if wid == "weekly-scan" else BadBroker(),
    )
    monkeypatch.setattr(dhc, "enrich_payload_with_prior_day_lifecycle", lambda *a, **k: None)
    monkeypatch.setattr(dhc, "save_snapshot", lambda subdir, payload: f"/tmp/{subdir}.json")

    rc = dhc.main(["--account", "all"])
    assert rc == 0


def test_main_returns_one_when_all_accounts_fail(monkeypatch):
    wf = SimpleNamespace(
        workflow_id="weekly-scan",
        snapshot_subdir="stock",
        label="Equity",
        broker="alpaca",
        physical_account_key="equity",
    )

    class BadBroker:
        def get_account(self):
            raise RuntimeError("unauthorized")

        def disconnect(self):
            pass

    monkeypatch.setattr(dhc, "_resolve_accounts_arg", lambda arg: [wf])
    monkeypatch.setattr(dhc, "workflow_credentials_configured", lambda wf: True)
    monkeypatch.setattr(dhc, "try_get_broker", lambda wid: BadBroker())
    monkeypatch.setattr(dhc, "enrich_payload_with_prior_day_lifecycle", lambda *a, **k: None)

    rc = dhc.main(["--account", "all"])
    assert rc == 1
