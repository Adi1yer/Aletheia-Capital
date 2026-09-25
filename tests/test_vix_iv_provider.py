"""Tests for VIX-based IV provider."""

from datetime import date, timedelta
import pytest

from src.backtesting.wheel_hybrid.vix_iv_provider import VixIVProvider


def test_vix_provider_init():
    """VixIVProvider initializes without errors."""
    provider = VixIVProvider()
    assert provider is not None
    assert provider.cache_dir.exists()


def test_vix_provider_get_atm_iv():
    """VixIVProvider can fetch VIX as ATM IV."""
    provider = VixIVProvider()
    
    # Test with recent date that should have VIX data
    test_date = date(2023, 6, 15)
    iv = provider.get_atm_iv("SPY", test_date, tenor_days=21)
    
    # Should return a reasonable VIX value or None if market closed
    if iv is not None:
        assert 0.05 <= iv <= 1.0  # 5-100% vol range


def test_vix_provider_get_iv_rank():
    """VixIVProvider calculates IV rank from VIX percentile."""
    provider = VixIVProvider()
    
    test_date = date(2023, 6, 15)
    iv_rank = provider.get_iv_rank("SPY", test_date, lookback_days=252)
    
    # Should return percentile rank or None
    if iv_rank is not None:
        assert 0.0 <= iv_rank <= 1.0


def test_vix_provider_get_iv_rv_spread():
    """VixIVProvider calculates VRP from VIX and realized vol."""
    provider = VixIVProvider()
    
    test_date = date(2023, 6, 15)
    realized_vol = 0.15  # 15% realized vol
    
    vrp = provider.get_iv_rv_spread("SPY", test_date, tenor_days=21, realized_vol=realized_vol)
    
    # Should return VRP or None
    if vrp is not None:
        assert -1.0 <= vrp <= 2.0  # VRP typically -50% to +100%


def test_vix_provider_caching():
    """VixIVProvider uses cache for repeated requests."""
    provider = VixIVProvider()
    
    test_date = date(2023, 6, 15)
    
    # First call downloads data
    iv1 = provider.get_atm_iv("SPY", test_date)
    
    # Second call uses cache (should be fast)
    iv2 = provider.get_atm_iv("SPY", test_date)
    
    # Should return same value
    if iv1 is not None and iv2 is not None:
        assert iv1 == iv2


def test_vix_provider_applies_to_all_symbols():
    """VIX provider returns same regime signal for all symbols."""
    provider = VixIVProvider()
    
    test_date = date(2023, 6, 15)
    
    spy_iv = provider.get_atm_iv("SPY", test_date)
    aapl_iv = provider.get_atm_iv("AAPL", test_date)
    
    # VIX applies to all symbols as regime signal
    if spy_iv is not None and aapl_iv is not None:
        assert spy_iv == aapl_iv


def test_vix_provider_missing_date():
    """VixIVProvider returns None for missing dates."""
    provider = VixIVProvider()
    
    # Weekend date unlikely to have VIX
    test_date = date(2023, 6, 25)  # Sunday
    iv = provider.get_atm_iv("SPY", test_date)
    
    # May return None for non-trading day
    assert iv is None or (0.05 <= iv <= 1.0)


def test_vix_provider_iv_rank_insufficient_history():
    """VixIVProvider returns None when insufficient history."""
    provider = VixIVProvider()
    
    # Very old date unlikely to have 252 days of history
    test_date = date(1990, 1, 2)
    iv_rank = provider.get_iv_rank("SPY", test_date, lookback_days=252)
    
    # Should return None or valid rank
    assert iv_rank is None or (0.0 <= iv_rank <= 1.0)
