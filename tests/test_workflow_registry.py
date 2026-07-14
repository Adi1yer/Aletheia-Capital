"""Workflow account registry tests."""

from src.broker.registry import load_workflow_registry, resolve_snapshot_subdir


def test_registry_loads():
    reg = load_workflow_registry()
    assert "weekly-scan" in reg
    assert "biotech-catalyst" in reg
    assert reg["weekly-scan"].snapshot_subdir == "stock"
    assert reg["weekly-scan"].env_prefix == "ALPACA"
    assert reg["weekly-scan"].account_group == "primary"


def test_resolve_legacy_stock():
    assert resolve_snapshot_subdir("stock") == "stock"
    assert resolve_snapshot_subdir("weekly-scan") == "stock"


def test_single_primary_account_group():
    reg = load_workflow_registry()
    enabled = [w for w in reg.values() if w.enabled]
    assert len(enabled) == 1
    assert enabled[0].workflow_id == "weekly-scan"
    assert reg["hedge-weekly"].account_group == "primary"
    assert reg["options-income"].account_group == "primary"


def test_api_secret_key_naming(monkeypatch):
    from src.broker.registry import _get_alpaca_secret, resolve_alpaca_env_prefix

    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
    monkeypatch.setenv("ALPACA_API_KEY", "k")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "secret")
    wf = load_workflow_registry()["weekly-scan"]
    assert _get_alpaca_secret("ALPACA") == "secret"
    assert resolve_alpaca_env_prefix(wf) == "ALPACA"


def test_list_physical_accounts_dedupes_primary(monkeypatch):
    from src.broker.registry import list_physical_accounts

    monkeypatch.setenv("ALPACA_API_KEY", "k")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "s")
    physical = list_physical_accounts(enabled_only=True)
    primary = [w for w in physical if w.account_group == "primary"]
    assert len(primary) == 1
    assert primary[0].workflow_id == "weekly-scan"
