"""Workflow account registry tests."""

from pathlib import Path

from src.broker.registry import load_workflow_registry, resolve_snapshot_subdir


def test_registry_loads():
    reg = load_workflow_registry()
    assert "weekly-scan" in reg
    assert "biotech-catalyst" in reg
    assert reg["weekly-scan"].snapshot_subdir == "stock"


def test_resolve_legacy_stock():
    assert resolve_snapshot_subdir("stock") == "stock"
    assert resolve_snapshot_subdir("weekly-scan") == "stock"


def test_multi_sleeve_shared_account_group():
    reg = load_workflow_registry()
    hedge = reg["hedge-weekly"]
    options = reg["options-income"]
    assert hedge.env_prefix == "MULTI_SLEEVE_ALPACA"
    assert hedge.account_group == options.account_group == "multi_sleeve"
    assert hedge.snapshot_subdir == "multi_sleeve"


def test_api_secret_key_naming(monkeypatch):
    import os

    from src.broker.registry import _get_alpaca_secret, resolve_alpaca_env_prefix

    monkeypatch.delenv("MULTI_SLEEVE_ALPACA_SECRET_KEY", raising=False)
    monkeypatch.setenv("MULTI_SLEEVE_ALPACA_API_KEY", "k")
    monkeypatch.setenv("MULTI_SLEEVE_ALPACA_API_SECRET_KEY", "secret")
    wf = load_workflow_registry()["hedge-weekly"]
    assert _get_alpaca_secret("MULTI_SLEEVE_ALPACA") == "secret"
    assert resolve_alpaca_env_prefix(wf) == "MULTI_SLEEVE_ALPACA"


def test_list_physical_accounts_dedupes_multi_sleeve(monkeypatch):
    import os

    from src.broker.registry import list_physical_accounts

    monkeypatch.setenv("MULTI_SLEEVE_ALPACA_API_KEY", "k")
    monkeypatch.setenv("MULTI_SLEEVE_ALPACA_API_SECRET_KEY", "s")
    physical = list_physical_accounts(enabled_only=True)
    multi = [w for w in physical if w.account_group == "multi_sleeve"]
    assert len(multi) == 1
