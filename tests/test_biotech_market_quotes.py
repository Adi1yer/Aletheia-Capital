from __future__ import annotations

from src.biotech import market_quotes as mq


def test_get_last_price_prefers_alpaca_over_yfinance(monkeypatch):
    monkeypatch.setattr(mq, "_price_from_alpaca", lambda t, k, s: 42.5)
    monkeypatch.setattr(mq, "_price_from_finnhub", lambda t: None)
    monkeypatch.setattr(mq, "_price_from_yfinance", lambda t: None)
    assert mq.get_last_price("ALKS") == 42.5


def test_get_last_price_falls_back_to_finnhub(monkeypatch):
    monkeypatch.setattr(mq, "_price_from_alpaca", lambda t, k, s: None)
    monkeypatch.setattr(mq, "_price_from_finnhub", lambda t: 18.25)
    monkeypatch.setattr(mq, "_price_from_yfinance", lambda t: None)
    assert mq.get_last_price("ADMA") == 18.25


def test_get_last_price_falls_back_to_yfinance(monkeypatch):
    monkeypatch.setattr(mq, "_price_from_alpaca", lambda t, k, s: None)
    monkeypatch.setattr(mq, "_price_from_finnhub", lambda t: None)
    monkeypatch.setattr(mq, "_price_from_yfinance", lambda t: 21.0)
    assert mq.get_last_price("ACAD") == 21.0


def test_get_ticker_profile_uses_quote_price(monkeypatch):
    monkeypatch.setattr(
        mq,
        "_profile_from_finnhub",
        lambda t: {
            "name": "Acme Bio",
            "finnhubIndustry": "Biotechnology",
            "gsector": "Health Care",
            "marketCapitalization": 2_000_000_000,
        },
    )
    monkeypatch.setattr(mq, "_profile_from_yfinance", lambda t: {})
    monkeypatch.setattr(mq, "get_last_price", lambda t, **kw: 33.3)
    prof = mq.get_ticker_profile("ACME")
    assert prof["last_price"] == 33.3
    assert prof["is_biotech"] is True
    assert prof["market_cap"] == 2_000_000_000
