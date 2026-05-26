"""Tests for ticker dossier v2."""

from datetime import datetime

from src.data.models import FinancialMetrics, Price
from src.data.ticker_dossier import build_ticker_dossier, cap_bucket, _yoy_pct


def test_cap_bucket():
    assert cap_bucket(300e9) == "mega"
    assert cap_bucket(50e9) == "large"
    assert cap_bucket(5e9) == "mid"
    assert cap_bucket(1e9) == "small"


def test_yoy_pct():
    assert _yoy_pct(110, 100) == 10.0
    assert _yoy_pct(100, 0) is None


def test_build_dossier_v2_structure():
    class MockProvider:
        def get_prices(self, ticker, start, end):
            base = datetime(2026, 1, 1)
            return [
                Price(
                    time=base,
                    open=100,
                    high=101,
                    low=99,
                    close=100 + i,
                    volume=1_000_000,
                )
                for i in range(60)
            ]

        def get_financial_metrics(self, ticker, end_date, limit=5):
            return [
                FinancialMetrics(
                    ticker=ticker,
                    report_period=datetime(2026, 5, 1),
                    market_cap=500e9,
                    sector="Technology",
                    pe_ratio=25.0,
                    price_to_book_ratio=5.0,
                    roe=0.2,
                    debt_to_equity=0.5,
                )
            ]

        def get_line_items(self, ticker, fields, end_date, limit=5):
            return []

        def get_insider_trades(self, *a, **k):
            return []

        def get_company_news(self, *a, **k):
            return []

        def get_market_cap(self, ticker, end_date):
            return 500e9

    d = build_ticker_dossier(MockProvider(), "AAPL", "2026-01-01", "2026-05-26", financial_limit=1)
    assert d["version"] == 2
    assert d["context"]["cap_bucket"] == "mega"
    assert d["prices"]["last_close"] is not None
    assert "technicals" in d
