"""Tests for global DRY_RUN mode that blocks all order submissions."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from src.broker.alpaca import AlpacaBroker
from src.portfolio.manager import PortfolioDecision


# Dummy credentials for tests
TEST_API_KEY = "test-api-key"
TEST_SECRET_KEY = "test-secret-key"


def test_dry_run_mode_initialization():
    """Broker initializes with DRY_RUN flag from environment."""
    with patch.dict(os.environ, {"DRY_RUN": "1"}):
        broker = AlpacaBroker(api_key=TEST_API_KEY, secret_key=TEST_SECRET_KEY)
        assert broker._dry_run is True
    
    with patch.dict(os.environ, {"DRY_RUN": "0"}):
        broker = AlpacaBroker(api_key=TEST_API_KEY, secret_key=TEST_SECRET_KEY)
        assert broker._dry_run is False
    
    with patch.dict(os.environ, {}, clear=True):
        if "DRY_RUN" in os.environ:
            del os.environ["DRY_RUN"]
        broker = AlpacaBroker(api_key=TEST_API_KEY, secret_key=TEST_SECRET_KEY)
        assert broker._dry_run is False


def test_dry_run_blocks_equity_order():
    """DRY_RUN blocks execute_order from submitting."""
    with patch.dict(os.environ, {"DRY_RUN": "1"}):
        broker = AlpacaBroker(api_key=TEST_API_KEY, secret_key=TEST_SECRET_KEY)
        
        decision = PortfolioDecision(
            action="buy",
            quantity=100,
            confidence=90,
            reasoning="Test buy",
        )
        
        result = broker.execute_order("AAPL", decision, current_price=150.0)
        
        assert result is not None
        assert result.get("dry_run") is True
        assert result.get("status") == "dry_run"
        assert result.get("success") is False
        
        # Verify no order was actually submitted to Alpaca
        # (client.submit_order should never be called)


def test_dry_run_blocks_option_order():
    """DRY_RUN blocks submit_option_order from submitting."""
    with patch.dict(os.environ, {"DRY_RUN": "1"}):
        broker = AlpacaBroker(api_key=TEST_API_KEY, secret_key=TEST_SECRET_KEY)
        
        result = broker.submit_option_order(
            contract_symbol="SPY241115C00450000",
            qty=1,
            side="sell",
            order_type="limit",
            limit_price=2.50,
        )
        
        assert result is not None
        assert result.get("dry_run") is True
        assert result.get("status") == "dry_run"
        assert result.get("submitted") is False


def test_dry_run_blocks_order_cancellation():
    """DRY_RUN blocks cancel_order from cancelling."""
    with patch.dict(os.environ, {"DRY_RUN": "1"}):
        broker = AlpacaBroker(api_key=TEST_API_KEY, secret_key=TEST_SECRET_KEY)
        
        result = broker.cancel_order("test-order-123")
        
        # Should return False (not cancelled)
        assert result is False


def test_non_dry_run_allows_orders():
    """Without DRY_RUN, orders are submitted normally."""
    with patch.dict(os.environ, {"DRY_RUN": "0"}):
        broker = AlpacaBroker(api_key=TEST_API_KEY, secret_key=TEST_SECRET_KEY)
        assert broker._dry_run is False
        
        # Mock the client.submit_order to avoid real API calls
        mock_order = MagicMock()
        mock_order.id = "test-123"
        mock_order.symbol = "AAPL"
        mock_order.qty = 100
        mock_order.side = MagicMock()
        mock_order.side.value = "buy"
        mock_order.status = MagicMock()
        mock_order.status.value = "accepted"
        
        broker.client.submit_order = MagicMock(return_value=mock_order)
        
        decision = PortfolioDecision(
            action="buy",
            quantity=100,
            confidence=90,
            reasoning="Test buy",
        )
        
        result = broker.execute_order("AAPL", decision, current_price=150.0)
        
        assert result is not None
        assert result.get("success") is True
        assert "dry_run" not in result or result.get("dry_run") is False
        
        # Verify submit_order was called
        broker.client.submit_order.assert_called_once()


def test_dry_run_in_window_still_blocks():
    """DRY_RUN blocks orders even during market hours."""
    with patch.dict(os.environ, {"DRY_RUN": "1"}):
        broker = AlpacaBroker(api_key=TEST_API_KEY, secret_key=TEST_SECRET_KEY)
        
        # Even with force execute or in-window, dry run should block
        decision = PortfolioDecision(
            action="sell",
            quantity=50,
            confidence=85,
            reasoning="Test sell",
        )
        
        result = broker.execute_order("TSLA", decision, current_price=250.0)
        
        assert result.get("dry_run") is True
        assert result.get("success") is False


def test_dry_run_close_list_generated():
    """DRY_RUN mode generates CFO-readable close list for put buyback."""
    from src.options.auto_put_buyback import (
        format_close_list_for_cfo,
        write_close_list_artifact,
    )
    
    close_list = [
        {
            "symbol": "SPY241115P00450000",
            "underlying": "SPY",
            "strike": 450.0,
            "expiry": "2024-11-15",
            "qty": 1,
            "quote": {
                "bid": 1.90,
                "ask": 2.10,
                "limit_price": 2.21,
                "live": True,
            },
            "cost_with_fees": 221.65,
            "collateral": 45000.0,
        }
    ]
    
    free_cash_before = -1000.0
    total_cost = 221.65
    total_collateral_freed = 45000.0
    
    report = format_close_list_for_cfo(
        close_list,
        free_cash_before,
        total_cost,
        total_collateral_freed,
    )
    
    # Verify report contains key info
    assert "AUTO PUT BUYBACK CLOSE LIST" in report
    assert "SPY241115P00450000" in report
    assert "SPY" in report
    assert "$450.00" in report
    assert "LIVE" in report
    assert "$221.65" in report
    assert "$45,000.00" in report


def test_dry_run_artifact_written():
    """DRY_RUN mode writes JSON artifact."""
    from src.options.auto_put_buyback import write_close_list_artifact
    from pathlib import Path
    import json
    
    close_list = [
        {
            "symbol": "TEST241115P00020000",
            "underlying": "TEST",
            "strike": 20.0,
            "expiry": "2024-11-15",
            "qty": 1,
            "quote": {
                "bid": 1.80,
                "ask": 2.00,
                "limit_price": 2.10,
                "live": True,
            },
            "cost_with_fees": 210.65,
            "collateral": 2000.0,
        }
    ]
    
    free_cash_before = -500.0
    total_cost = 210.65
    total_collateral_freed = 2000.0
    
    artifact_path = write_close_list_artifact(
        close_list,
        free_cash_before,
        total_cost,
        total_collateral_freed,
    )
    
    assert artifact_path.exists()
    assert artifact_path.name == "put_buyback_close_list.json"
    
    with open(artifact_path) as f:
        artifact = json.load(f)
    
    assert artifact["free_cash_before"] == -500.0
    assert artifact["total_cost"] == 210.65
    assert artifact["total_collateral_freed"] == 2000.0
    assert len(artifact["contracts"]) == 1
    assert artifact["contracts"][0]["symbol"] == "TEST241115P00020000"
    
    # Clean up
    artifact_path.unlink()


def test_dry_run_env_parsing():
    """Test various DRY_RUN environment values."""
    test_cases = [
        ("1", True),
        ("true", True),
        ("True", True),
        ("TRUE", True),
        ("yes", True),
        ("0", False),
        ("false", False),
        ("False", False),
        ("", False),
    ]
    
    for value, expected in test_cases:
        with patch.dict(os.environ, {"DRY_RUN": value}):
            broker = AlpacaBroker(api_key=TEST_API_KEY, secret_key=TEST_SECRET_KEY)
            assert broker._dry_run is expected, f"DRY_RUN={value} should be {expected}"
