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


def test_finnhub_is_non_failing_when_key_missing(monkeypatch):
    monkeypatch.setattr(preflight.settings, "finnhub_api_key", None)

    def _unexpected_request(*args, **kwargs):
        raise AssertionError("requests.get should not run without FINNHUB_API_KEY")

    monkeypatch.setattr(preflight.requests, "get", _unexpected_request)
    preflight._check_finnhub()
