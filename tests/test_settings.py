"""Settings must tolerate empty env strings (GitHub Actions missing secrets)."""

from __future__ import annotations

from src.config.settings import Settings


def test_empty_env_strings_fall_back_to_defaults(monkeypatch):
    # GitHub Actions injects missing secrets as empty strings.
    monkeypatch.setenv("IBKR_GATEWAY_PORT", "")
    monkeypatch.setenv("IBKR_GATEWAY_HOST", "")
    monkeypatch.setenv("SMTP_PORT", "")
    monkeypatch.setenv("HEDGE_ALPACA_API_KEY", "")

    s = Settings()

    assert s.ibkr_gateway_port == 4002
    assert s.smtp_port == 587
    assert s.ibkr_gateway_host is None


def test_non_empty_env_values_still_apply(monkeypatch):
    monkeypatch.setenv("IBKR_GATEWAY_PORT", "4001")
    monkeypatch.setenv("SMTP_PORT", "465")

    s = Settings()

    assert s.ibkr_gateway_port == 4001
    assert s.smtp_port == 465
