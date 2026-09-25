"""Test VIX regime provider for FREE index-level volatility signals."""

from datetime import date
from pathlib import Path

import pytest

from src.backtesting.wheel_hybrid.vix_regime_provider import VixRegimeProvider


@pytest.fixture
def vix_provider(tmp_path):
    """Create VixRegimeProvider with temp cache."""
    return VixRegimeProvider(cache_dir=str(tmp_path / "vix_cache"))


def test_vix_provider_initialization(vix_provider):
    """Test that VixRegimeProvider initializes without error."""
    assert vix_provider is not None
    assert vix_provider.cache_dir.exists()


def test_vix_provider_downloads_and_caches(vix_provider):
    """Test that VIX data downloads and caches correctly."""
    # This will trigger download
    vix = vix_provider.get_vix(date(2023, 6, 1))
    
    assert vix is not None
    assert 0.05 < vix < 1.0  # VIX should be 5-100% (in decimal form)
    
    # Cache file should exist
    assert vix_provider.cache_file.exists()


def test_vix_provider_returns_none_for_future_date(vix_provider):
    """Test that VIX returns None for dates with no data."""
    # Far future date (VIX shouldn't have data)
    vix = vix_provider.get_vix(date(2030, 1, 1))
    assert vix is None


def test_vix_percentile(vix_provider):
    """Test VIX percentile calculation."""
    # Mid-2023 (should have ~1 year history)
    pct = vix_provider.get_vix_percentile(date(2023, 6, 1), lookback_days=252)
    
    if pct is not None:
        assert 0.0 <= pct <= 1.0


def test_index_vrp_calculation(vix_provider):
    """Test index VRP (VIX vs SPY RV) calculation."""
    # Typical SPY realized vol ~20% annualized
    spy_rv = 0.20
    
    vrp = vix_provider.compute_index_vrp(date(2023, 6, 1), spy_rv)
    
    if vrp is not None:
        # VRP should be reasonable (-100% to +200%)
        assert -1.0 < vrp < 2.0


def test_regime_intensity(vix_provider):
    """Test regime intensity calculation."""
    intensity = vix_provider.get_regime_intensity(date(2023, 6, 1), spy_realized_vol=0.20)
    
    # Intensity should be 0-1
    assert 0.0 <= intensity <= 1.0


def test_vix_provider_does_not_provide_name_iv(vix_provider):
    """
    CRITICAL: VixRegimeProvider does NOT provide name-level IV.
    
    VIX is an INDEX measure (SPX 30-day IV). It should NEVER be used
    as ticker-level IV for AAPL, MSFT, F, BAC, etc.
    
    This provider is for INDEX REGIME signals only:
    - VIX vs SPY realized vol (index VRP)
    - VIX percentile (vol regime)
    - Regime intensity (overwrite scaling)
    """
    # VixRegimeProvider does not have get_iv() method
    assert not hasattr(vix_provider, "get_iv")
    assert not hasattr(vix_provider, "get_atm_iv")
    
    # Only index-level methods
    assert hasattr(vix_provider, "get_vix")
    assert hasattr(vix_provider, "compute_index_vrp")
    assert hasattr(vix_provider, "get_regime_intensity")
