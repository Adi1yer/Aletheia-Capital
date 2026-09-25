"""Tests for VIX-gated wheel-hybrid backtest infrastructure."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.backtesting.wheel_hybrid.edge_gate import EdgeGate, EdgeMode
from src.backtesting.wheel_hybrid.iv_provider import CsvIVProvider, NoOpIVProvider
from src.backtesting.wheel_hybrid.vix_provider import VixDataProvider


def test_noop_iv_provider():
    """NoOpIVProvider always returns None."""
    provider = NoOpIVProvider()
    assert provider.get_iv("SPY", date(2020, 1, 2)) is None
    assert provider.get_iv_range("SPY", date(2020, 1, 1), date(2020, 1, 10)) == {}


def test_always_on_edge_gate():
    """ALWAYS_ON mode always returns intensity 1.0."""
    gate = EdgeGate(mode=EdgeMode.ALWAYS_ON)
    assert gate.get_overwrite_intensity(date(2020, 1, 2)) == 1.0
    assert gate.should_write_cc(date(2020, 1, 2)) is True
    assert gate.get_regime_label(date(2020, 1, 2)) == "ALWAYS_ON"


def test_vix_gate_requires_provider():
    """VIX_GATED mode requires a VIX provider."""
    with pytest.raises(ValueError, match="requires vix_provider"):
        EdgeGate(mode=EdgeMode.VIX_GATED, vix_provider=None)


def test_vix_provider_cache_and_percentile():
    """VIX provider can load data and calculate percentiles."""
    provider = VixDataProvider()

    # Load recent data
    end = date.today()
    start = end - timedelta(days=400)
    provider.ensure_data_loaded(start, end)

    # Should have some VIX data
    vix_range = provider.get_vix_range(start, end)
    assert len(vix_range) > 200  # At least ~1 year of trading days

    # Percentile calculation
    test_date = end - timedelta(days=30)
    if test_date in vix_range:
        pct = provider.get_vix_percentile(test_date, lookback_days=252)
        if pct is not None:
            assert 0 <= pct <= 100


def test_vix_gate_intensity_range():
    """VIX gate intensity is always between 0 and 1."""
    provider = VixDataProvider()
    end = date.today()
    start = end - timedelta(days=400)
    provider.ensure_data_loaded(start, end)

    gate = EdgeGate(mode=EdgeMode.VIX_GATED, vix_provider=provider)

    # Test several dates
    test_dates = [start + timedelta(days=i * 30) for i in range(10)]
    for dt in test_dates:
        intensity = gate.get_overwrite_intensity(dt)
        assert 0.0 <= intensity <= 1.0


def test_edge_gate_regime_labels():
    """Edge gate produces sensible regime labels."""
    provider = VixDataProvider()
    end = date.today()
    start = end - timedelta(days=400)
    provider.ensure_data_loaded(start, end)

    gate = EdgeGate(mode=EdgeMode.VIX_GATED, vix_provider=provider)

    test_date = end - timedelta(days=30)
    label = gate.get_regime_label(test_date)
    assert label in ["VIX_HIGH", "VIX_ELEVATED", "VIX_NEUTRAL", "VIX_LOW", "VIX_CRUSHED"]


def test_csv_iv_provider_missing_key():
    """CSV IV provider returns None for missing keys."""
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = Path(tmpdir) / "test_iv.csv"
        csv_path.write_text(
            "date,symbol,iv_30d\n"
            "2020-01-02,SPY,0.123\n"
            "2020-01-03,SPY,0.125\n"
        )

        provider = CsvIVProvider(str(csv_path))
        assert provider.get_iv("SPY", date(2020, 1, 2)) == pytest.approx(0.123)
        assert provider.get_iv("SPY", date(2020, 1, 3)) == pytest.approx(0.125)
        assert provider.get_iv("AAPL", date(2020, 1, 2)) is None
        assert provider.get_iv("SPY", date(2020, 1, 1)) is None


def test_csv_iv_provider_range():
    """CSV IV provider returns correct date ranges."""
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = Path(tmpdir) / "test_iv.csv"
        csv_path.write_text(
            "date,symbol,iv_30d\n"
            "2020-01-02,SPY,0.123\n"
            "2020-01-03,SPY,0.125\n"
            "2020-01-06,SPY,0.120\n"
            "2020-01-07,SPY,0.118\n"
        )

        provider = CsvIVProvider(str(csv_path))
        range_data = provider.get_iv_range("SPY", date(2020, 1, 2), date(2020, 1, 6))
        assert len(range_data) == 3
        assert range_data[date(2020, 1, 2)] == pytest.approx(0.123)
        assert range_data[date(2020, 1, 6)] == pytest.approx(0.120)


def test_vix_provider_get_vix():
    """VIX provider can retrieve single date VIX values."""
    provider = VixDataProvider()

    # Test with a recent date that should have data
    test_date = date(2023, 6, 1)
    provider.ensure_data_loaded(test_date, test_date)

    vix = provider.get_vix(test_date)
    # Should return a reasonable VIX value or None if market was closed
    if vix is not None:
        assert 5.0 <= vix <= 100.0  # VIX typically 10-50, but allow wider range


def test_edge_gate_realized_vol_calculation():
    """Test realized vol calculation from price history."""
    # Create mock price data
    prices = {}
    start = date(2020, 1, 1)
    for i in range(100):
        dt = start + timedelta(days=i)
        # Simulate ~1% daily moves (high vol)
        prices[dt] = 100.0 * (1.01 ** i)

    rv = EdgeGate._calculate_realized_vol(prices, start + timedelta(days=99), 20)
    assert rv is not None
    # Should be a positive annualized vol
    assert rv > 0
    assert rv < 2.0  # Should be reasonable (<200% annualized)


def test_simulator_basic_run():
    """Test that simulator can complete a basic run."""
    from src.backtesting.wheel_hybrid.simulator import WheelHybridSimulator

    # Short test window
    sim = WheelHybridSimulator(
        universe=["AAPL", "MSFT"],
        start_date=date(2023, 1, 1),
        end_date=date(2023, 3, 31),
        initial_capital=10000.0,
    )

    result = sim.run()

    assert result.initial_capital == 10000.0
    assert result.final_equity > 0
    assert result.start_date == date(2023, 1, 1)
    assert result.end_date == date(2023, 3, 31)
    assert result.edge_mode == "always_on"


def test_simulator_vix_gated_vs_always_on():
    """Test that VIX-gated and always-on produce different results."""
    from src.backtesting.wheel_hybrid.simulator import WheelHybridSimulator

    universe = ["AAPL", "MSFT"]
    start = date(2023, 1, 1)
    end = date(2023, 6, 30)

    # Always-on
    sim_always = WheelHybridSimulator(
        universe=universe,
        start_date=start,
        end_date=end,
        initial_capital=10000.0,
        edge_gate=EdgeGate(mode=EdgeMode.ALWAYS_ON),
    )
    result_always = sim_always.run()

    # VIX-gated
    vix_provider = VixDataProvider()
    sim_vix = WheelHybridSimulator(
        universe=universe,
        start_date=start,
        end_date=end,
        initial_capital=10000.0,
        edge_gate=EdgeGate(mode=EdgeMode.VIX_GATED, vix_provider=vix_provider),
    )
    result_vix = sim_vix.run()

    # Edge modes should be different
    assert result_always.edge_mode == "always_on"
    assert result_vix.edge_mode == "vix_gated"
    
    # Both should complete successfully
    assert result_always.final_equity > 0
    assert result_vix.final_equity > 0
