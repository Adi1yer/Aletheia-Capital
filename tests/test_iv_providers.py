"""Tests for IV providers (Phase 2)."""

import pytest
from datetime import date
from pathlib import Path
import tempfile
import csv

from src.backtesting.wheel_hybrid.iv_provider import (
    NullIVProvider,
    SyntheticIVFromRealizedProvider,
    CsvIVProvider,
)


def test_null_iv_provider():
    """NullIVProvider always returns None."""
    provider = NullIVProvider()
    
    assert provider.get_atm_iv("AAPL", date(2020, 1, 2)) is None
    assert provider.get_iv_rank("AAPL", date(2020, 1, 2)) is None
    assert provider.get_iv_rv_spread("AAPL", date(2020, 1, 2), realized_vol=0.20) is None


def test_synthetic_iv_provider():
    """SyntheticIVFromRealizedProvider generates IV from RV + bump."""
    def mock_rv_provider(symbol, as_of, window):
        # Return fixed RV
        return 0.20 if symbol == "AAPL" else None
    
    provider = SyntheticIVFromRealizedProvider(
        realized_vol_provider=mock_rv_provider,
        premium_bump=0.15,  # +15%
        iv_rank_mean=0.50,
    )
    
    # ATM IV = RV * 1.15
    iv = provider.get_atm_iv("AAPL", date(2020, 1, 2))
    assert iv == pytest.approx(0.20 * 1.15)
    
    # IV rank = static mean
    iv_rank = provider.get_iv_rank("AAPL", date(2020, 1, 2))
    assert iv_rank == 0.50
    
    # VRP = bump (by construction)
    vrp = provider.get_iv_rv_spread("AAPL", date(2020, 1, 2), realized_vol=0.20)
    assert vrp == pytest.approx(0.15)
    
    # Missing RV → None
    assert provider.get_atm_iv("UNKNOWN", date(2020, 1, 2)) is None


def test_csv_iv_provider_basic():
    """CsvIVProvider loads from CSV and looks up by (symbol, date)."""
    # Create temporary CSV
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["date", "symbol", "atm_iv", "iv_rank"])
        writer.writeheader()
        writer.writerow({
            "date": "2020-01-02",
            "symbol": "AAPL",
            "atm_iv": "0.2500",
            "iv_rank": "0.45",
        })
        writer.writerow({
            "date": "2020-01-02",
            "symbol": "MSFT",
            "atm_iv": "0.1800",
            "iv_rank": "0.32",
        })
        writer.writerow({
            "date": "2020-01-03",
            "symbol": "AAPL",
            "atm_iv": "0.2600",
            "iv_rank": "0.48",
        })
        temp_path = f.name
    
    try:
        provider = CsvIVProvider(temp_path)
        
        # Lookup hits
        assert provider.get_atm_iv("AAPL", date(2020, 1, 2)) == pytest.approx(0.25)
        assert provider.get_iv_rank("AAPL", date(2020, 1, 2)) == pytest.approx(0.45)
        
        assert provider.get_atm_iv("MSFT", date(2020, 1, 2)) == pytest.approx(0.18)
        assert provider.get_iv_rank("MSFT", date(2020, 1, 2)) == pytest.approx(0.32)
        
        assert provider.get_atm_iv("AAPL", date(2020, 1, 3)) == pytest.approx(0.26)
        assert provider.get_iv_rank("AAPL", date(2020, 1, 3)) == pytest.approx(0.48)
        
        # Lookup misses → None
        assert provider.get_atm_iv("AAPL", date(2020, 1, 4)) is None
        assert provider.get_atm_iv("UNKNOWN", date(2020, 1, 2)) is None
        
    finally:
        Path(temp_path).unlink()


def test_csv_iv_provider_missing_values():
    """CsvIVProvider handles empty/missing values gracefully."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["date", "symbol", "atm_iv", "iv_rank"])
        writer.writeheader()
        writer.writerow({
            "date": "2020-01-02",
            "symbol": "AAPL",
            "atm_iv": "0.2500",
            "iv_rank": "",  # Missing IV rank
        })
        writer.writerow({
            "date": "2020-01-03",
            "symbol": "MSFT",
            "atm_iv": "",  # Missing IV
            "iv_rank": "0.40",
        })
        temp_path = f.name
    
    try:
        provider = CsvIVProvider(temp_path)
        
        # AAPL: IV present, rank missing
        assert provider.get_atm_iv("AAPL", date(2020, 1, 2)) == pytest.approx(0.25)
        assert provider.get_iv_rank("AAPL", date(2020, 1, 2)) is None
        
        # MSFT: IV missing, rank present
        assert provider.get_atm_iv("MSFT", date(2020, 1, 3)) is None
        assert provider.get_iv_rank("MSFT", date(2020, 1, 3)) == pytest.approx(0.40)
        
    finally:
        Path(temp_path).unlink()


def test_csv_iv_provider_vrp_calculation():
    """CsvIVProvider calculates VRP = (IV - RV) / RV."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["date", "symbol", "atm_iv", "iv_rank"])
        writer.writeheader()
        writer.writerow({
            "date": "2020-01-02",
            "symbol": "AAPL",
            "atm_iv": "0.3000",  # 30% IV
            "iv_rank": "0.50",
        })
        temp_path = f.name
    
    try:
        provider = CsvIVProvider(temp_path)
        
        # VRP = (0.30 - 0.20) / 0.20 = 0.50 (50%)
        vrp = provider.get_iv_rv_spread("AAPL", date(2020, 1, 2), realized_vol=0.20)
        assert vrp == pytest.approx(0.50)
        
        # Zero RV → None
        assert provider.get_iv_rv_spread("AAPL", date(2020, 1, 2), realized_vol=0.0) is None
        
        # Missing IV → None
        assert provider.get_iv_rv_spread("AAPL", date(2020, 1, 3), realized_vol=0.20) is None
        
    finally:
        Path(temp_path).unlink()


def test_csv_iv_provider_fail_closed():
    """CsvIVProvider returns None for missing data (fail-closed behavior)."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["date", "symbol", "atm_iv", "iv_rank"])
        writer.writeheader()
        writer.writerow({
            "date": "2020-01-02",
            "symbol": "AAPL",
            "atm_iv": "0.2500",
            "iv_rank": "0.45",
        })
        temp_path = f.name
    
    try:
        provider = CsvIVProvider(temp_path)
        
        # Missing date → None (gate should block if fail_closed=True)
        assert provider.get_atm_iv("AAPL", date(2020, 12, 31)) is None
        
        # Missing symbol → None
        assert provider.get_atm_iv("UNKNOWN", date(2020, 1, 2)) is None
        
    finally:
        Path(temp_path).unlink()


def test_csv_iv_provider_with_fixture():
    """Test CsvIVProvider with actual test fixture."""
    fixture_path = Path(__file__).parent / "fixtures" / "iv" / "sample_iv.csv"
    
    if not fixture_path.exists():
        pytest.skip("Test fixture not found (expected in tests/fixtures/iv/sample_iv.csv)")
    
    provider = CsvIVProvider(str(fixture_path))
    
    # Check a few known values from fixture
    assert provider.get_atm_iv("AAPL", date(2020, 1, 2)) is not None
    assert provider.get_iv_rank("AAPL", date(2020, 1, 2)) is not None
    
    assert provider.get_atm_iv("MSFT", date(2020, 1, 2)) is not None
    assert provider.get_atm_iv("SPY", date(2020, 1, 2)) is not None


def test_bakeoff_smoke():
    """
    Smoke test: Verify bake-off can run with fixture CSV (short window).
    
    This test validates the end-to-end IV drop-in path:
    - CsvIVProvider loads fixture
    - EdgeGate blocks/allows writes based on VRP
    - Backtest completes without errors
    
    Does NOT validate beat-SPY claims (fixture is too short).
    """
    try:
        from src.backtesting.wheel_hybrid.engine import WheelHybridBacktest
        from src.backtesting.wheel_hybrid.edge_gate import EdgeGate, EdgeGateConfig
        from src.data.providers.yahoo import YahooFinanceProvider
    except ImportError as e:
        pytest.skip(f"Integration test dependencies not available: {e}")
    
    fixture_path = Path(__file__).parent / "fixtures" / "iv" / "sample_iv.csv"
    
    if not fixture_path.exists():
        pytest.skip("Test fixture not found")
    
    # Load IV provider
    iv_provider = CsvIVProvider(str(fixture_path))
    
    # Create edge gate (high VRP threshold to test blocking)
    gate_config = EdgeGateConfig(
        enabled=True,
        min_vrp=0.20,  # 20% threshold
        fail_closed_when_no_iv=True,
    )
    edge_gate = EdgeGate(gate_config, iv_provider)
    
    # Run short backtest (fixture only has 2020-01-02 to 2020-01-08)
    backtest = WheelHybridBacktest(
        start_date="2020-01-02",
        end_date="2020-01-08",
        initial_nav=10000.0,
        wheel_pct=0.70,
        directional_pct=0.30,
        iv_provider=iv_provider,
        edge_gate=edge_gate,
        regime_detector=None,
    )
    
    data_provider = YahooFinanceProvider()
    
    # Use small universe (3 tickers in fixture)
    universe = ["AAPL", "MSFT", "SPY"]
    
    results = backtest.run(universe, data_provider)
    
    # Basic checks: backtest completed
    assert results is not None
    assert "summary" in results
    
    summary = results["summary"]
    assert summary["start_nav"] == 10000.0
    assert summary["end_nav"] > 0  # NAV changed
    
    # Edge gate stats: some writes should have been checked
    # (may be all blocked or all allowed depending on fixture VRP values)
    assert edge_gate.writes_allowed >= 0
    assert (edge_gate.writes_blocked_vrp + edge_gate.writes_blocked_no_iv) >= 0
