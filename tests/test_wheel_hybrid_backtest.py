"""Tests for wheel hybrid backtest with synthetic fixtures."""

import pytest
from datetime import date, timedelta
from pathlib import Path

from src.backtest.wheel_hybrid.engine import WheelHybridBacktest
from src.backtest.wheel_hybrid.portfolio import WheelPortfolio
from src.backtest.wheel_hybrid.premium_model import (
    black_scholes_call,
    black_scholes_put,
    realized_volatility,
    select_call_strike,
    select_put_strike,
)
from src.backtest.wheel_hybrid.metrics import calculate_metrics
from src.backtest.wheel_hybrid.universe import get_wheel_universe


class MockPrice:
    def __init__(self, time, close, high=None, low=None):
        self.time = time
        self.close = close
        self.high = high or close
        self.low = low or close


class MockDataProvider:
    """Mock data provider with synthetic price data."""
    
    def __init__(self):
        self.prices = {}
    
    def add_price_series(self, ticker, dates, prices):
        """Add synthetic price series."""
        self.prices[ticker] = [
            MockPrice(d, p) for d, p in zip(dates, prices)
        ]
    
    def get_prices(self, ticker, start_date, end_date):
        """Return synthetic prices."""
        return self.prices.get(ticker, [])


def test_black_scholes_call():
    """Test Black-Scholes call pricing."""
    S = 100.0
    K = 105.0
    T = 30 / 365.0
    r = 0.0
    sigma = 0.25
    
    premium = black_scholes_call(S, K, T, r, sigma)
    
    # Should be positive and less than intrinsic (OTM)
    assert premium > 0
    assert premium < 10  # Rough sanity check


def test_black_scholes_put():
    """Test Black-Scholes put pricing."""
    S = 100.0
    K = 95.0
    T = 30 / 365.0
    r = 0.0
    sigma = 0.25
    
    premium = black_scholes_put(S, K, T, r, sigma)
    
    # Should be positive and less than strike (OTM)
    assert premium > 0
    assert premium < 10


def test_realized_volatility():
    """Test realized volatility calculation."""
    # Synthetic prices with 20% annual vol
    prices = [100.0]
    for _ in range(30):
        # Daily return ~ 0.2 / sqrt(252) ≈ 1.26% std
        import random
        daily_ret = random.gauss(0, 0.2 / (252 ** 0.5))
        prices.append(prices[-1] * (1 + daily_ret))
    
    vol = realized_volatility(prices, window=21)
    
    assert vol is not None
    assert 0.1 < vol < 2.0  # Reasonable bounds


def test_select_call_strike():
    """Test call strike selection."""
    price = 20.0
    strike = select_call_strike(price, target_otm_pct=0.05)
    
    # Should be ~5% OTM
    assert strike > price
    assert strike < price * 1.10


def test_select_put_strike():
    """Test put strike selection."""
    price = 20.0
    strike = select_put_strike(price, csp_score=60)
    
    # Should be below price (OTM)
    assert strike < price
    assert strike > price * 0.85


def test_wheel_portfolio_lot():
    """Test equity lot management."""
    portfolio = WheelPortfolio(initial_cash=10000.0)
    
    # Buy lot
    success = portfolio.add_equity_lot("TEST", 100, 20.0, date.today())
    assert success
    assert portfolio.cash == 8000.0
    assert len(portfolio.equity_lots) == 1
    
    # Sell lot
    success = portfolio.sell_equity_lot("TEST", 100, 25.0, date.today())
    assert success
    assert portfolio.cash == 10500.0
    assert len(portfolio.equity_lots) == 0
    assert portfolio.realized_pnl == 500.0


def test_wheel_portfolio_covered_call():
    """Test covered call writing."""
    portfolio = WheelPortfolio(initial_cash=10000.0)
    
    # Buy lot first
    portfolio.add_equity_lot("TEST", 100, 20.0, date.today())
    
    # Write call
    success = portfolio.write_covered_call(
        "TEST",
        strike=21.0,
        expiry=date.today() + timedelta(days=30),
        premium_per_share=0.50,
        trade_date=date.today(),
    )
    
    assert success
    assert len(portfolio.short_calls) == 1
    assert portfolio.cash == 8050.0  # 8000 + 50 premium
    assert portfolio.premium_collected_total == 50.0


def test_wheel_portfolio_csp():
    """Test cash-secured put writing."""
    portfolio = WheelPortfolio(initial_cash=10000.0)
    
    # Write CSP
    success = portfolio.write_cash_secured_put(
        "TEST",
        strike=19.0,
        expiry=date.today() + timedelta(days=30),
        premium_per_share=0.40,
        trade_date=date.today(),
    )
    
    assert success
    assert len(portfolio.short_puts) == 1
    assert portfolio.cash == 10040.0  # Premium added
    assert portfolio.premium_collected_total == 40.0


def test_calculate_metrics():
    """Test metrics calculation."""
    equity_curve = [
        ("2020-01-01", 10000.0),
        ("2020-01-02", 10100.0),
        ("2020-01-03", 10050.0),
        ("2020-01-04", 10200.0),
        ("2020-01-05", 10300.0),
    ]
    
    spy_curve = [
        ("2020-01-01", 320.0),
        ("2020-01-02", 322.0),
        ("2020-01-03", 321.0),
        ("2020-01-04", 325.0),
        ("2020-01-05", 328.0),
    ]
    
    metrics = calculate_metrics(
        equity_curve,
        spy_curve,
        start_nav=10000.0,
        premium_collected=150.0,
        trades=[],
    )
    
    assert "abs_return_pct" in metrics
    assert "spy_return_pct" in metrics
    assert "excess_return_pct" in metrics
    assert metrics["start_nav"] == 10000.0
    assert metrics["end_nav"] == 10300.0
    assert metrics["abs_return_pct"] == 3.0


def test_get_wheel_universe():
    """Test universe selection."""
    universe = get_wheel_universe("2020-01-01")
    
    assert isinstance(universe, list)
    assert len(universe) > 0
    assert "F" in universe or "T" in universe


def test_backtest_engine_mock():
    """Test backtest engine with mock data provider."""
    # Create synthetic data
    start_date = "2020-01-01"
    end_date = "2020-01-10"
    
    provider = MockDataProvider()
    
    # Add prices for test ticker and SPY
    dates = [date(2020, 1, d) for d in range(1, 11)]
    test_prices = [20.0 + 0.1 * i for i in range(10)]
    spy_prices = [320.0 + 0.5 * i for i in range(10)]
    
    provider.add_price_series("TEST", dates, test_prices)
    provider.add_price_series("SPY", dates, spy_prices)
    
    # Run backtest
    backtest = WheelHybridBacktest(
        start_date=start_date,
        end_date=end_date,
        initial_nav=10000.0,
        wheel_pct=0.70,
        directional_pct=0.30,
    )
    
    results = backtest.run(["TEST"], provider)
    
    assert results is not None
    assert "summary" in results
    assert "equity_curve" in results
    assert len(results["equity_curve"]) == 10


def test_backtest_save_results(tmp_path):
    """Test saving backtest results."""
    # Create simple backtest
    backtest = WheelHybridBacktest(
        start_date="2020-01-01",
        end_date="2020-01-05",
        initial_nav=10000.0,
    )
    
    # Add synthetic data
    backtest.equity_curve = [
        ("2020-01-01", 10000.0),
        ("2020-01-02", 10100.0),
    ]
    backtest.spy_curve = [
        ("2020-01-01", 320.0),
        ("2020-01-02", 322.0),
    ]
    
    # Save
    output_dir = tmp_path / "test_results"
    backtest.save_results(output_dir)
    
    # Check files exist
    assert (output_dir / "equity_curve.csv").exists()
    assert (output_dir / "summary.json").exists()
    assert (output_dir / "assumptions.json").exists()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
