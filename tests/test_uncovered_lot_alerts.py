"""Test uncovered-lot coverage alerts (ITUB case regression)."""

from __future__ import annotations

from src.options.wheel_lifecycle import build_coverage_map
from src.portfolio.models import Portfolio, Position
from src.performance.official_track import _coverage_alerts


def test_uncovered_lot_flagged_in_coverage_map():
    """100-share lot with no covered call should be flagged as UNCOVERED."""
    portfolio = Portfolio(cash=5000.0)
    portfolio.positions = {
        "ITUB": Position(long=100, short=0, long_cost_basis=5.50, short_cost_basis=0.0),
    }
    
    # No option positions (no covered call)
    option_positions = []
    current_prices = {"ITUB": 6.00}
    
    coverage_map = build_coverage_map(
        portfolio,
        option_positions,
        current_prices,
        max_underlying_price=35.0,
    )
    
    # Should have one row for ITUB
    assert len(coverage_map) == 1
    row = coverage_map[0]
    assert row["ticker"] == "ITUB"
    assert row["shares"] == 100
    assert row["coverage"] == "UNCOVERED"


def test_uncovered_lot_generates_alert():
    """UNCOVERED lots should generate coverage alerts for email."""
    portfolio = Portfolio(cash=5000.0)
    portfolio.positions = {
        "ITUB": Position(long=100, short=0, long_cost_basis=5.50, short_cost_basis=0.0),
    }
    
    option_positions = []
    current_prices = {"ITUB": 6.00}
    
    coverage_map = build_coverage_map(
        portfolio,
        option_positions,
        current_prices,
        max_underlying_price=35.0,
    )
    
    # Build results dict with coverage_map
    results = {"coverage_map": coverage_map}
    
    # Extract alerts
    alerts = _coverage_alerts(results)
    
    # Should have one alert for ITUB:UNCOVERED
    assert len(alerts) == 1
    assert alerts[0] == "ITUB:UNCOVERED"


def test_multiple_uncovered_lots_multiple_alerts():
    """Multiple uncovered lots should generate multiple alerts."""
    portfolio = Portfolio(cash=10000.0)
    portfolio.positions = {
        "ITUB": Position(long=100, short=0, long_cost_basis=5.50, short_cost_basis=0.0),
        "F": Position(long=100, short=0, long_cost_basis=12.00, short_cost_basis=0.0),
        "SOFI": Position(long=200, short=0, long_cost_basis=8.50, short_cost_basis=0.0),
    }
    
    option_positions = []
    current_prices = {"ITUB": 6.00, "F": 12.50, "SOFI": 9.00}
    
    coverage_map = build_coverage_map(
        portfolio,
        option_positions,
        current_prices,
        max_underlying_price=35.0,
    )
    
    results = {"coverage_map": coverage_map}
    alerts = _coverage_alerts(results)
    
    # Should have 3 alerts
    assert len(alerts) == 3
    assert "ITUB:UNCOVERED" in alerts
    assert "F:UNCOVERED" in alerts
    assert "SOFI:UNCOVERED" in alerts


def test_covered_lot_no_alert():
    """Fully covered lot should NOT generate alert."""
    portfolio = Portfolio(cash=5000.0)
    portfolio.positions = {
        "ITUB": Position(long=100, short=0, long_cost_basis=5.50, short_cost_basis=0.0),
    }
    
    # Has covered call
    option_positions = [
        {
            "side": "short",
            "symbol": "ITUB241115C00007000",
            "underlying": "ITUB",
            "option_type": "call",
            "strike": 7.0,
            "expiry": "2024-11-15",
            "qty": 1,
        }
    ]
    current_prices = {"ITUB": 6.00}
    
    coverage_map = build_coverage_map(
        portfolio,
        option_positions,
        current_prices,
        max_underlying_price=35.0,
    )
    
    results = {"coverage_map": coverage_map}
    alerts = _coverage_alerts(results)
    
    # Should have NO alerts (fully covered)
    assert len(alerts) == 0
    
    # Verify coverage status is "covered"
    assert len(coverage_map) == 1
    assert coverage_map[0]["coverage"] == "covered"


def test_underhedged_lot_generates_alert():
    """Underhedged lot (200 shares, 1 call) should generate alert."""
    portfolio = Portfolio(cash=5000.0)
    portfolio.positions = {
        "TEST": Position(long=200, short=0, long_cost_basis=10.00, short_cost_basis=0.0),
    }
    
    # Only 1 call for 200 shares
    option_positions = [
        {
            "side": "short",
            "symbol": "TEST241115C00012000",
            "underlying": "TEST",
            "option_type": "call",
            "strike": 12.0,
            "expiry": "2024-11-15",
            "qty": 1,
        }
    ]
    current_prices = {"TEST": 11.00}
    
    coverage_map = build_coverage_map(
        portfolio,
        option_positions,
        current_prices,
        max_underlying_price=35.0,
    )
    
    results = {"coverage_map": coverage_map}
    alerts = _coverage_alerts(results)
    
    # Should have one alert for UNDERHEDGED
    assert len(alerts) == 1
    assert alerts[0] == "TEST:UNDERHEDGED"
    
    # Verify coverage status
    assert len(coverage_map) == 1
    assert coverage_map[0]["coverage"] == "UNDERHEDGED"
    assert coverage_map[0]["shares"] == 200
    assert coverage_map[0]["short_contracts"] == 1


def test_zero_qty_short_call_treated_as_uncovered():
    """Short call with qty=0 should be treated as UNCOVERED (defensive check)."""
    portfolio = Portfolio(cash=5000.0)
    portfolio.positions = {
        "ITUB": Position(long=100, short=0, long_cost_basis=5.50, short_cost_basis=0.0),
    }
    
    # Malformed option position with qty=0
    option_positions = [
        {
            "side": "short",
            "symbol": "ITUB241115C00007000",
            "underlying": "ITUB",
            "option_type": "call",
            "strike": 7.0,
            "expiry": "2024-11-15",
            "qty": 0,  # Zero qty - should be treated as no coverage
        }
    ]
    current_prices = {"ITUB": 6.00}
    
    coverage_map = build_coverage_map(
        portfolio,
        option_positions,
        current_prices,
        max_underlying_price=35.0,
    )
    
    results = {"coverage_map": coverage_map}
    alerts = _coverage_alerts(results)
    
    # Should flag as UNCOVERED despite having an option position entry
    assert len(alerts) == 1
    assert alerts[0] == "ITUB:UNCOVERED"
    assert coverage_map[0]["coverage"] == "UNCOVERED"


def test_itub_case_regression():
    """ITUB case: 100 shares with no covered call should show in email alerts."""
    # Simulate ITUB case exactly
    portfolio = Portfolio(cash=5000.0)
    portfolio.positions = {
        "ITUB": Position(long=100, short=0, long_cost_basis=5.50, short_cost_basis=0.0),
        # Other positions that ARE covered
        "F": Position(long=100, short=0, long_cost_basis=12.00, short_cost_basis=0.0),
    }
    
    # F has a covered call, ITUB does not
    option_positions = [
        {
            "side": "short",
            "symbol": "F241115C00014000",
            "underlying": "F",
            "option_type": "call",
            "strike": 14.0,
            "expiry": "2024-11-15",
            "qty": 1,
        }
    ]
    current_prices = {"ITUB": 6.00, "F": 12.50}
    
    coverage_map = build_coverage_map(
        portfolio,
        option_positions,
        current_prices,
        max_underlying_price=35.0,
    )
    
    results = {"coverage_map": coverage_map}
    alerts = _coverage_alerts(results)
    
    # Should have exactly 1 alert for ITUB
    assert len(alerts) == 1
    assert "ITUB:UNCOVERED" in alerts
    
    # Verify coverage map
    itub_row = [r for r in coverage_map if r["ticker"] == "ITUB"]
    assert len(itub_row) == 1
    assert itub_row[0]["coverage"] == "UNCOVERED"
    
    f_row = [r for r in coverage_map if r["ticker"] == "F"]
    assert len(f_row) == 1
    assert f_row[0]["coverage"] == "covered"


def test_ops_health_includes_coverage_alerts():
    """ops_health dict should include coverage_alerts from coverage_map."""
    from src.performance.official_track import build_ops_health
    
    # Build results with coverage_map containing UNCOVERED lot
    portfolio = Portfolio(cash=5000.0)
    portfolio.positions = {
        "ITUB": Position(long=100, short=0, long_cost_basis=5.50, short_cost_basis=0.0),
    }
    
    option_positions = []
    current_prices = {"ITUB": 6.00}
    
    coverage_map = build_coverage_map(
        portfolio,
        option_positions,
        current_prices,
        max_underlying_price=35.0,
    )
    
    results = {
        "coverage_map": coverage_map,
        "short_put_map": [],
        "portfolio": {"equity": 10000.0, "cash": 5000.0},
        "execution_status": {},
        "timestamp": "2024-10-06T14:30:00Z",
    }
    
    ops_health = build_ops_health(results)
    
    # Should have coverage_alerts in ops_health
    assert "coverage_alerts" in ops_health
    assert len(ops_health["coverage_alerts"]) == 1
    assert ops_health["coverage_alerts"][0] == "ITUB:UNCOVERED"
