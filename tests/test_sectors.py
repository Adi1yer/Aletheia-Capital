"""Sector resolution and concentration-cap helpers."""

from __future__ import annotations

from src.portfolio.sectors import (
    get_sector,
    normalize_sector,
    prefetch_sectors,
    resolve_sector,
)


def test_normalize_yahoo_financial_services():
    assert normalize_sector("Financial Services") == "Financials"
    assert normalize_sector("Information Technology") == "Information Technology"
    assert normalize_sector("Technology") == "Information Technology"
    assert normalize_sector(None) == "Unknown"


def test_static_map_covers_banks():
    assert get_sector("BMO") == "Financials"
    assert get_sector("JPM") == "Financials"
    assert get_sector("AAPL") == "Information Technology"


def test_resolve_sector_uses_dossier_hint(monkeypatch):
    monkeypatch.setattr(
        "src.portfolio.sectors._yahoo_sector",
        lambda t: (_ for _ in ()).throw(AssertionError("should not call yahoo")),
    )
    sec = resolve_sector(
        "FAKECO",
        dossier={"context": {"sector": "Health Care"}},
    )
    assert sec == "Health Care"


def test_prefetch_sectors_batch():
    out = prefetch_sectors(["BMO", "AAPL", "BNS"])
    assert out["BMO"] == "Financials"
    assert out["BNS"] == "Financials"
    assert out["AAPL"] == "Information Technology"
