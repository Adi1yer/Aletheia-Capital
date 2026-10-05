"""Unit tests for drip email footer fix (Oct 5 2026 production issue)."""

import pytest
from src.utils.drip_email import build_drip_daily_email


def test_email_footer_no_trades():
    """Test footer when no trades executed."""
    positions = {"AAPL": {"qty": 10, "market_value": 1500.0}}
    
    subject, body = build_drip_daily_email(
        nav=10000.0,
        cash=500.0,
        positions=positions,
    )
    
    # Footer should say no trades executed
    assert "No trades executed" in body


def test_email_footer_with_drip_buys_only():
    """Test footer correctly reports drip buys."""
    positions = {"AAPL": {"qty": 10, "market_value": 1500.0}}
    drip_buys = [
        {"ticker": "AAPL", "shares": 5, "drip_amount": 750.0},
        {"ticker": "MSFT", "shares": 3, "drip_amount": 600.0},
    ]
    
    subject, body = build_drip_daily_email(
        nav=10000.0,
        cash=500.0,
        positions=positions,
        drip_buys=drip_buys,
    )
    
    # Footer should mention drip trades
    assert "Trades executed" in body
    assert "2 dividend drip" in body
    assert "No trades executed" not in body


def test_email_footer_with_residual_buys_only():
    """Test footer correctly reports residual cash deployment (Oct 5 2026 fix)."""
    positions = {"AAPL": {"qty": 10, "market_value": 1500.0}}
    residual_buys = [
        {"ticker": "AAPL", "shares": 5, "allocated_usd": 750.0},
        {"ticker": "MSFT", "shares": 3, "allocated_usd": 600.0},
        {"ticker": "GOOGL", "shares": 2, "allocated_usd": 400.0},
    ]
    
    subject, body = build_drip_daily_email(
        nav=10000.0,
        cash=500.0,
        positions=positions,
        residual_buys=residual_buys,
    )
    
    # Footer should mention residual deployment (this was the bug - it said "No trades")
    assert "Trades executed" in body
    assert "3 residual cash deployment" in body
    assert "No trades executed" not in body


def test_email_footer_with_both_trade_types():
    """Test footer correctly reports both drip and residual trades."""
    positions = {"AAPL": {"qty": 10, "market_value": 1500.0}}
    drip_buys = [
        {"ticker": "AAPL", "shares": 5, "drip_amount": 750.0},
    ]
    residual_buys = [
        {"ticker": "MSFT", "shares": 3, "allocated_usd": 600.0},
        {"ticker": "GOOGL", "shares": 2, "allocated_usd": 400.0},
    ]
    
    subject, body = build_drip_daily_email(
        nav=10000.0,
        cash=500.0,
        positions=positions,
        drip_buys=drip_buys,
        residual_buys=residual_buys,
    )
    
    # Footer should mention both trade types
    assert "Trades executed" in body
    assert "1 dividend drip" in body
    assert "2 residual cash deployment" in body
    assert "No trades executed" not in body


def test_email_contains_residual_cash_section():
    """Test that email includes residual cash deployment section."""
    positions = {"AAPL": {"qty": 10, "market_value": 1500.0}}
    residual_buys = [
        {"ticker": "AAPL", "shares": 5, "allocated_usd": 750.0},
        {"ticker": "MSFT", "shares": 3, "allocated_usd": 600.0},
    ]
    
    subject, body = build_drip_daily_email(
        nav=10000.0,
        cash=500.0,
        positions=positions,
        residual_buys=residual_buys,
    )
    
    # Should show residual cash deployment section
    assert "RESIDUAL CASH DEPLOYMENT" in body
    assert "Buys executed: 2" in body
    assert "Total deployed: $1,350" in body or "Total deployed: $1350" in body
    assert "AAPL: 5 shares" in body
    assert "MSFT: 3 shares" in body


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
