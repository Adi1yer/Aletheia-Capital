"""Tests for regime and wash-sale helpers."""

from datetime import datetime, timedelta

from src.portfolio.regime import apply_regime_to_run_config, detect_regime
from src.portfolio.wash_sale import blocked_tickers, record_sell


class _FakePrices:
    def __init__(self, closes):
        import pandas as pd

        self._closes = closes
        self.iloc = closes

    def __getitem__(self, key):
        import pandas as pd

        return pd.Series(self._closes)


class _FakeProvider:
    def __init__(self, last, sma):
        import pandas as pd

        n = 220
        base = [sma] * (n - 1) + [last]
        self._df = pd.DataFrame({"close": base})

    def get_prices(self, sym, start, end):
        return self._df


def test_detect_regime_harvest():
    reg = detect_regime(_FakeProvider(90, 100), "2026-01-01", "2026-05-26")
    assert reg["mode"] == "harvest"


def test_apply_regime_harvest_raises_buy_threshold():
    cfg = {"regime_mode": "auto", "min_buy_confidence": 50, "max_buy_tickers": 30}
    out = apply_regime_to_run_config(cfg, {"mode": "harvest"})
    assert out["min_buy_confidence"] > 50


def test_wash_sale_blocks_recent_sell():
    record_sell("ZZZZ", sold_at=datetime.utcnow().strftime("%Y-%m-%d"))
    assert "ZZZZ" in blocked_tickers(31)
