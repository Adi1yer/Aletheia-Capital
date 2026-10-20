"""Tests for single-name concentration controls."""

import pytest
from unittest.mock import Mock, patch
from src.risk.concentration import (
    calculate_position_concentration,
    get_breaching_names,
    check_new_buy_gate,
    check_put_assignment_gate,
    calculate_unencumbered_shares,
    calculate_trim_size,
    generate_trim_orders,
)


def test_calculate_position_concentration():
    """Test concentration calculation."""
    positions = {
        "AAPL": {"qty": 100, "side": "long", "market_value": 15000},
        "MSFT": {"qty": 50, "side": "long", "market_value": 10000},
        "GOOGL": {"qty": 10, "side": "short", "market_value": 5000},  # Short - excluded
    }
    current_prices = {"AAPL": 150.0, "MSFT": 200.0, "GOOGL": 500.0}
    equity = 50000.0
    
    concentrations = calculate_position_concentration(positions, current_prices, equity)
    
    assert concentrations["AAPL"] == 30.0  # 15000 / 50000 * 100
    assert concentrations["MSFT"] == 20.0  # 10000 / 50000 * 100
    assert "GOOGL" not in concentrations  # Short excluded


def test_calculate_position_concentration_zero_equity():
    """Test with zero equity returns empty dict."""
    positions = {"AAPL": {"qty": 100, "side": "long", "market_value": 15000}}
    current_prices = {"AAPL": 150.0}
    
    concentrations = calculate_position_concentration(positions, current_prices, 0.0)
    
    assert concentrations == {}


def test_get_breaching_names():
    """Test identifying breaching names."""
    concentrations = {
        "AAPL": 30.0,
        "MSFT": 26.0,
        "GOOGL": 20.0,
        "TSLA": 15.0,
    }
    
    breaches = get_breaching_names(concentrations, threshold_pct=25.0)
    
    assert len(breaches) == 2
    assert breaches[0] == ("AAPL", 30.0)  # Highest first
    assert breaches[1] == ("MSFT", 26.0)


def test_check_new_buy_gate_allows_buy_under_threshold():
    """Test new-buy gate allows buys that stay under 25%."""
    positions = {"AAPL": {"qty": 100, "side": "long"}}
    current_prices = {"AAPL": 150.0}
    equity = 100000.0
    
    # Current: 15000 / 100000 = 15%
    # After +50 shares: 22500 / 100000 = 22.5% < 25%
    allowed, reason = check_new_buy_gate(
        ticker="AAPL",
        buy_qty=50,
        current_price=150.0,
        positions=positions,
        current_prices=current_prices,
        equity=equity,
        threshold_pct=25.0,
    )
    
    assert allowed is True
    assert reason is None


def test_check_new_buy_gate_blocks_buy_over_threshold():
    """Test new-buy gate blocks buys that would breach 25%."""
    positions = {"AAPL": {"qty": 100, "side": "long"}}
    current_prices = {"AAPL": 150.0}
    equity = 100000.0
    
    # Current: 15000 / 100000 = 15%
    # After +100 shares: 30000 / 100000 = 30% > 25%
    allowed, reason = check_new_buy_gate(
        ticker="AAPL",
        buy_qty=100,
        current_price=150.0,
        positions=positions,
        current_prices=current_prices,
        equity=equity,
        threshold_pct=25.0,
    )
    
    assert allowed is False
    assert reason == "would_breach_25%_concentration"


def test_check_new_buy_gate_exactly_at_threshold():
    """Test new-buy gate at exactly 25%."""
    positions = {}
    current_prices = {}
    equity = 100000.0
    
    # Exactly 25%: 25000 / 100000 = 25%
    # Should be blocked (threshold is >, not >=)
    allowed, reason = check_new_buy_gate(
        ticker="AAPL",
        buy_qty=166,
        current_price=150.60,  # 166 * 150.60 = 24999.60 ≈ 25000
        positions=positions,
        current_prices=current_prices,
        equity=equity,
        threshold_pct=25.0,
    )
    
    # At exactly 25%, should still be allowed (threshold is >25%, not >=25%)
    assert allowed is True


def test_check_new_buy_gate_just_over_threshold():
    """Test new-buy gate just over 25%."""
    positions = {}
    current_prices = {}
    equity = 100000.0
    
    # Just over 25%: 25100 / 100000 = 25.1%
    allowed, reason = check_new_buy_gate(
        ticker="AAPL",
        buy_qty=167,
        current_price=150.30,  # 167 * 150.30 = 25100.1
        positions=positions,
        current_prices=current_prices,
        equity=equity,
        threshold_pct=25.0,
    )
    
    assert allowed is False
    assert reason == "would_breach_25%_concentration"


def test_check_put_assignment_gate_allows_put_under_threshold():
    """Test put assignment gate allows puts that would stay under 25%."""
    positions = {"AAPL": {"qty": 100, "side": "long"}}
    current_prices = {"AAPL": 150.0}
    equity = 100000.0
    
    # Current: 100 * 150 = 15000 (15%)
    # After assignment: 15000 + (100 * 140) = 29000 (29%) > 25%
    # But let's test one that's OK:
    # After assignment with strike 50: 15000 + (100 * 50) = 20000 (20%)
    allowed, reason = check_put_assignment_gate(
        ticker="AAPL",
        strike=50.0,
        put_qty=1,
        current_price=150.0,
        positions=positions,
        current_prices=current_prices,
        equity=equity,
        threshold_pct=25.0,
    )
    
    assert allowed is True
    assert reason is None


def test_check_put_assignment_gate_blocks_put_over_threshold():
    """Test put assignment gate blocks puts that would breach 25%."""
    positions = {"AAPL": {"qty": 100, "side": "long"}}
    current_prices = {"AAPL": 150.0}
    equity = 100000.0
    
    # Current: 100 * 150 = 15000 (15%)
    # After assignment: 15000 + (100 * 140) = 29000 (29%) > 25%
    allowed, reason = check_put_assignment_gate(
        ticker="AAPL",
        strike=140.0,
        put_qty=1,
        current_price=150.0,
        positions=positions,
        current_prices=current_prices,
        equity=equity,
        threshold_pct=25.0,
    )
    
    assert allowed is False
    assert reason == "assignment_would_breach_25%_concentration"


def test_calculate_unencumbered_shares_no_encumbrance():
    """Test unencumbered shares with no short calls or working orders."""
    ticker = "AAPL"
    long_shares = 300
    open_orders = []
    option_positions = []
    
    unencumbered = calculate_unencumbered_shares(ticker, long_shares, open_orders, option_positions)
    
    assert unencumbered == 300


def test_calculate_unencumbered_shares_with_short_calls():
    """Test unencumbered shares with short calls."""
    ticker = "AAPL"
    long_shares = 300
    open_orders = []
    option_positions = [
        {
            "symbol": "AAPL241220C00150000",  # 1 short call
            "side": "short",
            "qty": 2,
            "underlying": "AAPL",
        }
    ]
    
    unencumbered = calculate_unencumbered_shares(ticker, long_shares, open_orders, option_positions)
    
    assert unencumbered == 100  # 300 - (2 * 100)


def test_calculate_unencumbered_shares_with_working_sell_orders():
    """Test unencumbered shares with working sell orders."""
    ticker = "AAPL"
    long_shares = 300
    open_orders = [
        {"symbol": "AAPL", "side": "sell", "qty": 50, "filled_qty": 0, "status": "accepted"}
    ]
    option_positions = []
    
    unencumbered = calculate_unencumbered_shares(ticker, long_shares, open_orders, option_positions)
    
    assert unencumbered == 250  # 300 - 50


def test_calculate_unencumbered_shares_combined_encumbrance():
    """Test unencumbered shares with both short calls and working orders."""
    ticker = "AAPL"
    long_shares = 300
    open_orders = [
        {"symbol": "AAPL", "side": "sell", "qty": 50, "filled_qty": 0, "status": "accepted"}
    ]
    option_positions = [
        {
            "symbol": "AAPL241220C00150000",
            "side": "short",
            "qty": 1,
            "underlying": "AAPL",
        }
    ]
    
    unencumbered = calculate_unencumbered_shares(ticker, long_shares, open_orders, option_positions)
    
    assert unencumbered == 150  # 300 - 100 (1 call) - 50 (working order)


def test_calculate_trim_size_normal_trim():
    """Test trim size calculation for normal case."""
    ticker = "AAPL"
    current_pct = 30.0
    bid_price = 150.0
    equity = 100000.0
    market_value = 30000.0  # 200 shares * 150
    unencumbered_shares = 200
    
    # Target 22%: 22000
    # Excess: 30000 - 22000 = 8000
    # Shares: floor(8000 / 150) = 53
    shares, reason = calculate_trim_size(
        ticker, current_pct, bid_price, equity, market_value, unencumbered_shares,
        target_pct=22.0,
    )
    
    assert shares == 53
    assert reason is None


def test_calculate_trim_size_caps_at_unencumbered():
    """Test trim size is capped at unencumbered shares."""
    ticker = "AAPL"
    current_pct = 30.0
    bid_price = 150.0
    equity = 100000.0
    market_value = 30000.0
    unencumbered_shares = 20  # Very low
    
    shares, reason = calculate_trim_size(
        ticker, current_pct, bid_price, equity, market_value, unencumbered_shares,
        target_pct=22.0,
    )
    
    assert shares == 20  # Capped
    assert reason is None


def test_calculate_trim_size_under_1_share():
    """Test trim size skips when under 1 share."""
    ticker = "AAPL"
    current_pct = 25.5  # Just barely over
    bid_price = 10000.0  # Very high price
    equity = 100000.0
    market_value = 25500.0
    unencumbered_shares = 100
    
    # Target 22%: 22000
    # Excess: 25500 - 22000 = 3500
    # Shares: floor(3500 / 10000) = 0
    shares, reason = calculate_trim_size(
        ticker, current_pct, bid_price, equity, market_value, unencumbered_shares,
        target_pct=22.0,
    )
    
    assert shares == 0
    assert reason == "under_1_share"


def test_calculate_trim_size_no_unencumbered_shares():
    """Test trim size when no unencumbered shares."""
    ticker = "AAPL"
    current_pct = 30.0
    bid_price = 150.0
    equity = 100000.0
    market_value = 30000.0
    unencumbered_shares = 0
    
    shares, reason = calculate_trim_size(
        ticker, current_pct, bid_price, equity, market_value, unencumbered_shares,
        target_pct=22.0,
    )
    
    assert shares == 0
    assert reason == "no_unencumbered_shares"


def test_generate_trim_orders_no_breaches():
    """Test trim orders when no concentration breaches."""
    broker = Mock()
    positions = {"AAPL": {"qty": 100, "side": "long"}}
    current_prices = {"AAPL": 150.0}
    equity = 100000.0  # AAPL is 15%, under 25%
    open_orders = []
    
    results = generate_trim_orders(
        broker, positions, current_prices, equity, open_orders,
        breach_threshold_pct=25.0,
        target_pct=22.0,
        dry_run=True,
    )
    
    assert len(results) == 0


def test_generate_trim_orders_dry_run():
    """Test trim orders in dry run mode."""
    broker = Mock()
    broker._api_key = "test_key"
    broker._secret_key = "test_secret"
    
    # Mock the quote fetch
    mock_quote = Mock()
    mock_quote.bid_price = 148.0
    mock_client = Mock()
    mock_client.get_stock_latest_quote = Mock(return_value={"AAPL": mock_quote})
    
    positions = {"AAPL": {"qty": 200, "side": "long"}}
    current_prices = {"AAPL": 150.0}
    equity = 100000.0  # AAPL is 30%, over 25%
    open_orders = []
    
    with patch("src.risk.concentration.StockHistoricalDataClient", return_value=mock_client):
        with patch("src.risk.concentration.alpaca_call_with_retry", return_value={"AAPL": mock_quote}):
            results = generate_trim_orders(
                broker, positions, current_prices, equity, open_orders,
                breach_threshold_pct=25.0,
                target_pct=22.0,
                dry_run=True,
            )
    
    assert len(results) == 1
    assert results[0]["ticker"] == "AAPL"
    assert results[0]["action"] == "dry_run"
    assert results[0]["current_pct"] == 30.0
    assert results[0]["target_pct"] == 22.0
    assert results[0]["shares"] > 0


@pytest.fixture
def mock_broker():
    """Create a mock broker for testing."""
    broker = Mock()
    broker.get_account = Mock(return_value={"equity": 100000.0})
    broker.get_positions = Mock(return_value={
        "NOK": {"qty": 200, "side": "long", "market_value": 30000.0}
    })
    broker.get_open_orders = Mock(return_value=[])
    broker.get_option_positions = Mock(return_value=[])
    return broker


def test_broker_get_open_orders_pagination(mock_broker):
    """Test that get_open_orders paginates correctly."""
    from src.broker.alpaca import AlpacaBroker, BrokerDataError
    
    broker = AlpacaBroker(api_key="test", secret_key="test")
    
    # Mock client that returns 100 orders, then 50, then 0
    page1 = [Mock(id=f"order{i}", symbol="AAPL", side=Mock(value="buy"), qty=10, filled_qty=0, status=Mock(value="new"), submitted_at=None, type=Mock(value="market")) for i in range(100)]
    page2 = [Mock(id=f"order{i+100}", symbol="AAPL", side=Mock(value="buy"), qty=10, filled_qty=0, status=Mock(value="new"), submitted_at=None, type=Mock(value="market")) for i in range(50)]
    page3 = []
    
    broker.client.get_orders = Mock(side_effect=[page1, page2, page3])
    
    orders = broker.get_open_orders(limit=200)
    
    assert len(orders) == 150
    assert broker.client.get_orders.call_count == 2  # Stops after page2 (< 100 orders)


def test_broker_get_open_orders_fails_closed():
    """Test that get_open_orders raises on error (fail-closed)."""
    from src.broker.alpaca import AlpacaBroker, BrokerDataError
    
    broker = AlpacaBroker(api_key="test", secret_key="test")
    broker.client.get_orders = Mock(side_effect=Exception("Network error"))
    
    with pytest.raises(BrokerDataError, match="open orders unavailable"):
        broker.get_open_orders(limit=50)


def test_concentration_trim_disabled_by_default():
    """Test that concentration trim is disabled when ENABLE_CONCENTRATION_TRIM!=1."""
    from src.risk.concentration import run_concentration_trim_workflow
    
    broker = Mock()
    
    with patch.dict("os.environ", {"ENABLE_CONCENTRATION_TRIM": "0"}):
        result = run_concentration_trim_workflow(broker)
    
    assert result["trimmed"] is False
    assert "not_enabled" in result["reason"]


def test_concentration_trim_only_on_scheduled_runs():
    """Test that concentration trim only runs on scheduled runs."""
    from src.risk.concentration import run_concentration_trim_workflow
    
    broker = Mock()
    
    with patch.dict("os.environ", {"ENABLE_CONCENTRATION_TRIM": "1", "GITHUB_EVENT_NAME": "workflow_dispatch"}):
        result = run_concentration_trim_workflow(broker)
    
    assert result["trimmed"] is False
    assert result["reason"] == "not_scheduled_run"


def test_concentration_trim_only_in_market_hours():
    """Test that concentration trim only runs during market hours."""
    from src.risk.concentration import run_concentration_trim_workflow
    
    broker = Mock()
    
    with patch.dict("os.environ", {"ENABLE_CONCENTRATION_TRIM": "1", "GITHUB_EVENT_NAME": "schedule"}):
        with patch("src.risk.concentration.is_regular_market_hours", return_value=False):
            result = run_concentration_trim_workflow(broker)
    
    assert result["trimmed"] is False
    assert result["reason"] == "not_regular_market_hours"


def test_concentration_trim_fails_closed_on_account_error():
    """Test that trim fails closed when account fetch fails."""
    from src.risk.concentration import run_concentration_trim_workflow
    
    broker = Mock()
    broker.get_account = Mock(side_effect=Exception("Network error"))
    
    with patch.dict("os.environ", {"ENABLE_CONCENTRATION_TRIM": "1", "GITHUB_EVENT_NAME": "schedule"}):
        with patch("src.risk.concentration.is_regular_market_hours", return_value=True):
            result = run_concentration_trim_workflow(broker)
    
    assert result["trimmed"] is False
    assert result["reason"] == "account_unavailable"


def test_concentration_trim_fails_closed_on_open_orders_error():
    """Test that trim fails closed when open orders fetch fails."""
    from src.risk.concentration import run_concentration_trim_workflow
    from src.broker.alpaca import BrokerDataError
    
    broker = Mock()
    broker.get_account = Mock(return_value={"equity": 100000.0})
    broker.get_positions = Mock(return_value={"NOK": {"qty": 200, "side": "long", "market_value": 30000.0}})
    broker.get_open_orders = Mock(side_effect=BrokerDataError("Network error"))
    
    with patch.dict("os.environ", {"ENABLE_CONCENTRATION_TRIM": "1", "GITHUB_EVENT_NAME": "schedule"}):
        with patch("src.risk.concentration.is_regular_market_hours", return_value=True):
            result = run_concentration_trim_workflow(broker)
    
    assert result["trimmed"] is False
    assert result["reason"] == "open_orders_unavailable"
