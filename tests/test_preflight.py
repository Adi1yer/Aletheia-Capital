from __future__ import annotations

import preflight


def test_main_returns_zero_when_all_checks_pass(monkeypatch):
    calls: list[str] = []

    monkeypatch.setattr(preflight, "_check_main_alpaca", lambda: calls.append("main"))
    monkeypatch.setattr(preflight, "_check_biotech_alpaca", lambda: calls.append("biotech"))
    monkeypatch.setattr(preflight, "_check_deepseek", lambda: calls.append("deepseek"))
    monkeypatch.setattr(preflight, "_check_smtp", lambda: calls.append("smtp"))
    monkeypatch.setattr(preflight, "_check_finnhub", lambda: calls.append("finnhub"))

    rc = preflight.main([])

    assert rc == 0
    assert calls == ["main", "biotech", "deepseek", "smtp", "finnhub"]


def test_main_returns_one_when_required_check_fails(monkeypatch):
    monkeypatch.setattr(preflight, "_check_main_alpaca", lambda: None)

    def _boom() -> None:
        raise RuntimeError("bad biotech creds")

    monkeypatch.setattr(preflight, "_check_biotech_alpaca", _boom)
    monkeypatch.setattr(preflight, "_check_deepseek", lambda: None)
    monkeypatch.setattr(preflight, "_check_smtp", lambda: None)
    monkeypatch.setattr(preflight, "_check_finnhub", lambda: None)

    rc = preflight.main([])

    assert rc == 1


def test_skip_flags_omit_optional_checks(monkeypatch):
    calls: list[str] = []

    monkeypatch.setattr(preflight, "_check_main_alpaca", lambda: calls.append("main"))
    monkeypatch.setattr(preflight, "_check_biotech_alpaca", lambda: calls.append("biotech"))
    monkeypatch.setattr(preflight, "_check_deepseek", lambda: calls.append("deepseek"))
    monkeypatch.setattr(preflight, "_check_smtp", lambda: calls.append("smtp"))
    monkeypatch.setattr(preflight, "_check_finnhub", lambda: calls.append("finnhub"))

    rc = preflight.main(["--skip-deepseek", "--skip-smtp", "--skip-finnhub"])

    assert rc == 0
    assert calls == ["main", "biotech"]


def test_skip_main_omits_main_check(monkeypatch):
    calls: list[str] = []

    monkeypatch.setattr(preflight, "_check_main_alpaca", lambda: calls.append("main"))
    monkeypatch.setattr(preflight, "_check_biotech_alpaca", lambda: calls.append("biotech"))
    monkeypatch.setattr(preflight, "_check_deepseek", lambda: calls.append("deepseek"))
    monkeypatch.setattr(preflight, "_check_smtp", lambda: calls.append("smtp"))
    monkeypatch.setattr(preflight, "_check_finnhub", lambda: calls.append("finnhub"))

    rc = preflight.main(["--skip-main", "--skip-deepseek", "--skip-smtp", "--skip-finnhub"])

    assert rc == 0
    assert calls == ["biotech"]


def test_skip_biotech_omits_biotech_check(monkeypatch):
    calls: list[str] = []

    monkeypatch.setattr(preflight, "_check_main_alpaca", lambda: calls.append("main"))
    monkeypatch.setattr(preflight, "_check_biotech_alpaca", lambda: calls.append("biotech"))
    monkeypatch.setattr(preflight, "_check_deepseek", lambda: calls.append("deepseek"))
    monkeypatch.setattr(preflight, "_check_smtp", lambda: calls.append("smtp"))
    monkeypatch.setattr(preflight, "_check_finnhub", lambda: calls.append("finnhub"))

    rc = preflight.main(["--skip-biotech", "--skip-deepseek", "--skip-smtp", "--skip-finnhub"])

    assert rc == 0
    assert calls == ["main"]


def test_finnhub_is_non_failing_when_key_missing(monkeypatch):
    monkeypatch.setattr(preflight.settings, "finnhub_api_key", None)

    def _unexpected_request(*args, **kwargs):
        raise AssertionError("requests.get should not run without FINNHUB_API_KEY")

    monkeypatch.setattr(preflight.requests, "get", _unexpected_request)
    preflight._check_finnhub()


def test_satellite_only_flag(monkeypatch):
    calls: list[str] = []

    monkeypatch.setattr(
        preflight,
        "_check_satellite_alpaca",
        lambda: calls.append("satellite"),
    )
    monkeypatch.setattr(preflight, "_check_deepseek", lambda: calls.append("deepseek"))
    monkeypatch.setattr(preflight, "_check_smtp", lambda: calls.append("smtp"))
    monkeypatch.setattr(preflight, "_check_finnhub", lambda: calls.append("finnhub"))

    rc = preflight.main(["--satellite-only", "--skip-deepseek", "--skip-smtp", "--skip-finnhub"])

    assert rc == 0
    assert calls == ["satellite"]


def test_satellite_only_skips_when_sleeves_disabled(monkeypatch):
    """Single-account mode: no enabled satellite workflows → soft skip."""
    from src.broker.registry import WorkflowAccount

    monkeypatch.setattr(
        "src.broker.registry.list_workflows",
        lambda enabled_only=True: [
            WorkflowAccount(
                "weekly-scan",
                "alpaca",
                "ALPACA",
                "stock",
                "data/performance",
                account_group="primary",
                enabled=True,
            )
        ],
    )
    # Should not raise
    preflight._check_satellite_alpaca()


def test_all_workflows_uses_api_secret_key_env(monkeypatch):
    """Satellite workflows store secrets as {PREFIX}_API_SECRET_KEY in GitHub."""
    from src.broker.registry import WorkflowAccount

    wf = WorkflowAccount(
        workflow_id="congressional",
        broker="alpaca",
        env_prefix="MULTI_SLEEVE_ALPACA",
        snapshot_subdir="multi_sleeve",
        data_dir="data/congressional",
        account_group="multi_sleeve",
    )
    calls: list[tuple[str, str, str]] = []

    monkeypatch.setenv("MULTI_SLEEVE_ALPACA_API_KEY", "pk-test")
    monkeypatch.setenv("MULTI_SLEEVE_ALPACA_API_SECRET_KEY", "sk-test")
    monkeypatch.delenv("MULTI_SLEEVE_ALPACA_SECRET_KEY", raising=False)
    monkeypatch.setattr(
        preflight,
        "list_physical_accounts",
        lambda enabled_only=True: [wf],
    )
    monkeypatch.setattr(
        preflight,
        "_check_workflow_alpaca",
        lambda wid, key, sec: calls.append((wid, key, sec)),
    )

    preflight._check_all_configured_alpaca()

    assert calls == [("congressional", "pk-test", "sk-test")]
