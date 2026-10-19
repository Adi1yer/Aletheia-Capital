"""Tests that read_only_fills_report makes zero order/cancel/replace calls."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest


def test_read_only_report_makes_no_order_calls():
    """Verify read_only_fills_report never calls submit/cancel/replace order methods."""
    
    # Mock broker with call tracking
    mock_broker = MagicMock()
    mock_broker.get_account.return_value = {
        "cash": 10000.0,
        "equity": 15000.0,
        "buying_power": 20000.0,
    }
    mock_broker.get_positions.return_value = {}
    mock_broker.get_option_positions.return_value = []
    mock_broker.get_recent_orders.return_value = []
    
    # Import and run the report main function
    import sys
    from io import StringIO
    
    with patch("sys.argv", ["script", "--date", "2026-10-14"]):
        with patch("src.broker.alpaca.AlpacaBroker", return_value=mock_broker):
            captured_output = StringIO()
            with patch("sys.stdout", captured_output):
                from scripts.read_only_fills_report import main
                exit_code = main()
    
    # Verify no order submission calls
    assert not mock_broker.submit_option_order.called
    assert not mock_broker.execute_order.called
    assert not hasattr(mock_broker, "cancel_order") or not mock_broker.cancel_order.called
    assert not hasattr(mock_broker, "replace_order") or not mock_broker.replace_order.called
    
    # Verify only read-only calls were made
    assert mock_broker.get_account.called
    assert mock_broker.get_positions.called
    assert mock_broker.get_option_positions.called
    assert mock_broker.get_recent_orders.called
    
    # Verify successful completion
    assert exit_code == 0
    
    # Verify output contains expected sections
    output = captured_output.getvalue()
    assert "read-only" in output.lower()
    assert "ACCOUNT INFO" in output
    assert "CURRENT POSITIONS" in output
    assert "FILLS ON" in output


def test_read_only_report_with_positions_and_fills():
    """Verify report correctly displays positions and fills (read-only)."""
    
    mock_broker = MagicMock()
    mock_broker.get_account.return_value = {
        "cash": 8500.0,
        "equity": 14500.0,
        "buying_power": 17000.0,
    }
    mock_broker.get_positions.return_value = {
        "NU": {
            "qty": 100,
            "market_value": 1450.0,
            "avg_entry_price": 14.50,
            "current_price": 14.50,
        }
    }
    mock_broker.get_option_positions.return_value = [
        {
            "symbol": "NU261106P00015000",
            "side": "short",
            "qty": -1,
            "market_value": -80.0,
            "avg_entry_price": 0.60,
            "current_price": 0.80,
        }
    ]
    mock_broker.get_recent_orders.return_value = [
        {
            "id": "6f9e2149-test",
            "symbol": "NU261106P00015000",
            "side": "buy",
            "filled_qty": 1,
            "filled_avg_price": 0.80,
            "filled_at": "2026-10-14T18:29:00Z",
            "status": "filled",
            "type": "market",
        }
    ]
    
    import sys
    from io import StringIO
    
    with patch("sys.argv", ["script", "--date", "2026-10-14"]):
        with patch("src.broker.alpaca.AlpacaBroker", return_value=mock_broker):
            captured_output = StringIO()
            with patch("sys.stdout", captured_output):
                from scripts.read_only_fills_report import main
                exit_code = main()
    
    # Verify no order calls
    assert not mock_broker.submit_option_order.called
    assert not mock_broker.execute_order.called
    
    # Verify successful completion
    assert exit_code == 0
    
    # Verify output shows positions and fills
    output = captured_output.getvalue()
    assert "NU" in output
    assert "NU261106P00015000" in output
    assert "6f9e2149" in output  # order ID prefix
    assert "zero orders placed" in output


def test_read_only_report_broker_import_failure_raises():
    """If broker cannot be imported, report should fail gracefully."""
    
    with patch("sys.argv", ["script", "--date", "2026-10-14"]):
        with patch("src.broker.alpaca.AlpacaBroker", side_effect=ImportError("test")):
            from scripts.read_only_fills_report import main
            # Script catches exceptions and re-raises, so it should fail
            with pytest.raises((ImportError, SystemExit)):
                main()


def test_read_only_script_has_no_submit_calls():
    """Static check: verify script source has no submit/cancel/replace calls."""
    
    from pathlib import Path
    script_path = Path(__file__).parent.parent / "scripts" / "read_only_fills_report.py"
    script_source = script_path.read_text()
    
    # Check that script doesn't call any order submission methods
    forbidden = [
        "submit_option_order",
        "submit_order",
        "execute_order",
        "cancel_order",
        "replace_order",
    ]
    
    for method in forbidden:
        # Allow mentions in comments/docstrings, but not actual calls
        # Check for method calls: broker.method( or client.method(
        assert f".{method}(" not in script_source, f"Script calls {method}!"
        assert f" {method}(" not in script_source, f"Script calls {method}!"


def test_read_only_report_account_fetch_failure_exits_nonzero():
    """When account fetch fails, script must print ERROR and exit non-zero."""
    
    mock_broker = MagicMock()
    mock_broker.get_account.side_effect = Exception("API timeout")
    
    import sys
    from io import StringIO
    
    with patch("sys.argv", ["script", "--date", "2026-10-14"]):
        with patch("src.broker.alpaca.AlpacaBroker", return_value=mock_broker):
            captured_output = StringIO()
            captured_error = StringIO()
            with patch("sys.stdout", captured_output):
                with patch("sys.stderr", captured_error):
                    from scripts.read_only_fills_report import main
                    exit_code = main()
    
    # Verify non-zero exit
    assert exit_code == 1
    
    # Verify ERROR message
    error_output = captured_error.getvalue()
    assert "ERROR" in error_output
    assert "account" in error_output.lower()
    
    # Verify no fake $0.00 in stdout
    stdout_output = captured_output.getvalue()
    assert "Cash:" not in stdout_output or "$0.00" not in stdout_output


def test_read_only_report_positions_fetch_failure_exits_nonzero():
    """When positions fetch fails, script must print ERROR and exit non-zero."""
    
    mock_broker = MagicMock()
    mock_broker.get_account.return_value = {
        "cash": 10000.0,
        "equity": 15000.0,
        "buying_power": 20000.0,
    }
    mock_broker.get_positions.side_effect = Exception("Connection error")
    
    import sys
    from io import StringIO
    
    with patch("sys.argv", ["script", "--date", "2026-10-14"]):
        with patch("src.broker.alpaca.AlpacaBroker", return_value=mock_broker):
            captured_output = StringIO()
            captured_error = StringIO()
            with patch("sys.stdout", captured_output):
                with patch("sys.stderr", captured_error):
                    from scripts.read_only_fills_report import main
                    exit_code = main()
    
    # Verify non-zero exit
    assert exit_code == 1
    
    # Verify ERROR message
    error_output = captured_error.getvalue()
    assert "ERROR" in error_output
    assert "positions" in error_output.lower()
    
    # Verify no empty position table printed as real data
    stdout_output = captured_output.getvalue()
    if "CURRENT POSITIONS" in stdout_output:
        # Should not have gotten past the error
        assert False, "Script printed positions section after fetch failure"


def test_read_only_report_fills_fetch_failure_exits_nonzero():
    """When fills/orders fetch fails, script must print ERROR and exit non-zero.
    
    This tests that get_recent_orders with strict=True raises and the script exits non-zero.
    """
    
    mock_broker = MagicMock()
    mock_broker.get_account.return_value = {
        "cash": 10000.0,
        "equity": 15000.0,
        "buying_power": 20000.0,
    }
    mock_broker.get_positions.return_value = {}
    mock_broker.get_option_positions.return_value = []
    mock_broker.get_recent_orders.side_effect = Exception("Rate limited")
    
    import sys
    from io import StringIO
    
    with patch("sys.argv", ["script", "--date", "2026-10-14"]):
        with patch("src.broker.alpaca.AlpacaBroker", return_value=mock_broker):
            captured_output = StringIO()
            captured_error = StringIO()
            with patch("sys.stdout", captured_output):
                with patch("sys.stderr", captured_error):
                    from scripts.read_only_fills_report import main
                    exit_code = main()
    
    # Verify non-zero exit
    assert exit_code == 1
    
    # Verify ERROR message
    error_output = captured_error.getvalue()
    assert "ERROR" in error_output
    assert "fills" in error_output.lower()
    
    # Verify no fills section with fake empty data
    stdout_output = captured_output.getvalue()
    if "FILLS ON" in stdout_output and "END OF REPORT" in stdout_output:
        # Should not have completed the report after fetch failure
        assert False, "Script completed report after fills fetch failure"


def test_read_only_report_all_fetches_succeed():
    """When all fetches succeed, script exits 0 with complete report."""
    
    mock_broker = MagicMock()
    mock_broker.get_account.return_value = {
        "cash": 10000.0,
        "equity": 15000.0,
        "buying_power": 20000.0,
    }
    mock_broker.get_positions.return_value = {}
    mock_broker.get_option_positions.return_value = []
    mock_broker.get_recent_orders.return_value = []
    
    import sys
    from io import StringIO
    
    with patch("sys.argv", ["script", "--date", "2026-10-14"]):
        with patch("src.broker.alpaca.AlpacaBroker", return_value=mock_broker):
            captured_output = StringIO()
            captured_error = StringIO()
            with patch("sys.stdout", captured_output):
                with patch("sys.stderr", captured_error):
                    from scripts.read_only_fills_report import main
                    exit_code = main()
    
    # Verify successful exit
    assert exit_code == 0
    
    # Verify no errors
    error_output = captured_error.getvalue()
    assert "ERROR" not in error_output
    
    # Verify complete report sections
    stdout_output = captured_output.getvalue()
    assert "ACCOUNT INFO" in stdout_output
    assert "CURRENT POSITIONS" in stdout_output
    assert "FILLS ON" in stdout_output
    assert "END OF REPORT" in stdout_output
    assert "zero orders placed" in stdout_output


def test_alpaca_broker_get_recent_orders_strict_raises_on_error():
    """AlpacaBroker.get_recent_orders with strict=True must raise when underlying client fails.
    
    This tests through the real AlpacaBroker error path by mocking the underlying Alpaca
    TradingClient's get_orders method (not get_recent_orders).
    """
    from src.broker.alpaca import AlpacaBroker
    
    # Create a real AlpacaBroker instance with mock credentials
    broker = AlpacaBroker(api_key="test_key", secret_key="test_secret")
    
    # Mock the underlying Alpaca TradingClient's get_orders method to raise
    broker.client.get_orders = MagicMock(side_effect=Exception("Connection timeout"))
    
    # Without strict, should return empty list
    result = broker.get_recent_orders(limit=20, strict=False)
    assert result == []
    
    # With strict=True, should raise
    with pytest.raises(Exception, match="Connection timeout"):
        broker.get_recent_orders(limit=20, strict=True)


def test_read_only_report_missing_filled_avg_price_exits_nonzero():
    """When filled_avg_price is None/missing, script must ERROR and exit non-zero."""
    
    mock_broker = MagicMock()
    mock_broker.get_account.return_value = {
        "cash": 10000.0,
        "equity": 15000.0,
        "buying_power": 20000.0,
    }
    mock_broker.get_positions.return_value = {}
    mock_broker.get_option_positions.return_value = []
    mock_broker.get_recent_orders.return_value = [
        {
            "id": "missing-price-order",
            "symbol": "AAPL",
            "side": "buy",
            "filled_qty": 10,
            "filled_avg_price": None,  # Missing price
            "filled_at": "2026-10-14T18:00:00Z",
            "status": "filled",
        }
    ]
    
    import sys
    from io import StringIO
    
    with patch("sys.argv", ["script", "--date", "2026-10-14"]):
        with patch("src.broker.alpaca.AlpacaBroker", return_value=mock_broker):
            captured_output = StringIO()
            captured_error = StringIO()
            with patch("sys.stdout", captured_output):
                with patch("sys.stderr", captured_error):
                    from scripts.read_only_fills_report import main
                    exit_code = main()
    
    # Verify non-zero exit
    assert exit_code == 1
    
    # Verify ERROR message about missing price
    error_output = captured_error.getvalue()
    assert "ERROR" in error_output
    assert "filled_avg_price" in error_output
    assert "AAPL" in error_output or "missing-price" in error_output
    
    # Verify no $0.00 price in output
    stdout_output = captured_output.getvalue()
    assert "$0.00" not in stdout_output


def test_read_only_report_unparseable_filled_at_shows_warning():
    """Orders with unparseable filled_at must appear as WARNING, not silently dropped."""
    
    mock_broker = MagicMock()
    mock_broker.get_account.return_value = {
        "cash": 10000.0,
        "equity": 15000.0,
        "buying_power": 20000.0,
    }
    mock_broker.get_positions.return_value = {}
    mock_broker.get_option_positions.return_value = []
    mock_broker.get_recent_orders.return_value = [
        {
            "id": "bad-timestamp",
            "symbol": "MSFT",
            "side": "sell",
            "filled_qty": 5,
            "filled_avg_price": 400.0,
            "filled_at": "invalid-timestamp",  # Unparseable
            "status": "filled",
        }
    ]
    
    import sys
    from io import StringIO
    
    with patch("sys.argv", ["script", "--date", "2026-10-14"]):
        with patch("src.broker.alpaca.AlpacaBroker", return_value=mock_broker):
            captured_output = StringIO()
            captured_error = StringIO()
            with patch("sys.stdout", captured_output):
                with patch("sys.stderr", captured_error):
                    from scripts.read_only_fills_report import main
                    exit_code = main()
    
    # Should still exit 0 (warnings don't fail the report)
    assert exit_code == 0
    
    # Verify WARNING appears in output
    stdout_output = captured_output.getvalue()
    assert "WARNING" in stdout_output or "WARNINGS" in stdout_output
    assert "MSFT" in stdout_output or "bad-timestamp" in stdout_output


def test_read_only_report_shows_nu_and_cpng_status():
    """Report must show explicit NU position status and CPNG cost basis lines."""
    
    mock_broker = MagicMock()
    mock_broker.get_account.return_value = {
        "cash": 10000.0,
        "equity": 15000.0,
        "buying_power": 20000.0,
    }
    mock_broker.get_positions.return_value = {
        "NU": {
            "qty": 100,
            "market_value": 1450.0,
            "avg_entry_price": 14.50,
            "current_price": 14.50,
        },
        "CPNG": {
            "qty": 50,
            "market_value": 900.0,
            "avg_entry_price": 18.00,
            "current_price": 18.00,
        }
    }
    mock_broker.get_option_positions.return_value = [
        {
            "symbol": "NU261106P00015000",
            "side": "short",
            "qty": 1,
            "market_value": -80.0,
            "avg_entry_price": 0.60,
            "current_price": 0.80,
        }
    ]
    mock_broker.get_recent_orders.return_value = []
    
    import sys
    from io import StringIO
    
    with patch("sys.argv", ["script", "--date", "2026-10-14"]):
        with patch("src.broker.alpaca.AlpacaBroker", return_value=mock_broker):
            captured_output = StringIO()
            with patch("sys.stdout", captured_output):
                from scripts.read_only_fills_report import main
                exit_code = main()
    
    # Verify successful exit
    assert exit_code == 0
    
    # Verify NU and CPNG lines appear
    stdout_output = captured_output.getvalue()
    assert "NU: OPEN" in stdout_output or "NU: FLAT" in stdout_output
    assert "CPNG cost basis" in stdout_output


def test_read_only_report_shows_fees_note():
    """Report must include note that fees aren't counted."""
    
    mock_broker = MagicMock()
    mock_broker.get_account.return_value = {
        "cash": 10000.0,
        "equity": 15000.0,
        "buying_power": 20000.0,
    }
    mock_broker.get_positions.return_value = {}
    mock_broker.get_option_positions.return_value = []
    mock_broker.get_recent_orders.return_value = [
        {
            "id": "test-order",
            "symbol": "AAPL",
            "side": "buy",
            "filled_qty": 10,
            "filled_avg_price": 150.0,
            "filled_at": "2026-10-14T18:00:00Z",
            "status": "filled",
        }
    ]
    
    import sys
    from io import StringIO
    
    with patch("sys.argv", ["script", "--date", "2026-10-14"]):
        with patch("src.broker.alpaca.AlpacaBroker", return_value=mock_broker):
            captured_output = StringIO()
            with patch("sys.stdout", captured_output):
                from scripts.read_only_fills_report import main
                exit_code = main()
    
    # Verify successful exit
    assert exit_code == 0
    
    # Verify fees note appears
    stdout_output = captured_output.getvalue()
    assert "fees" in stdout_output.lower() or "Fees" in stdout_output
    assert "not" in stdout_output.lower() and "reconcile" in stdout_output.lower()


def test_alpaca_broker_get_recent_orders_with_date_filters():
    """AlpacaBroker.get_recent_orders must pass after/until date filters to Alpaca API."""
    from src.broker.alpaca import AlpacaBroker
    from datetime import date
    
    broker = AlpacaBroker(api_key="test_key", secret_key="test_secret")
    
    # Mock the underlying client's get_orders to capture the request
    mock_orders = []
    broker.client.get_orders = MagicMock(return_value=mock_orders)
    
    target_date = date(2026, 10, 14)
    result = broker.get_recent_orders(limit=100, after=target_date, until=target_date)
    
    # Verify get_orders was called
    assert broker.client.get_orders.called
    
    # Verify the request includes date filters
    call_args = broker.client.get_orders.call_args
    req = call_args[0][0]  # First positional argument is the GetOrdersRequest
    
    assert req.status == "closed"
    assert req.limit == 100
    # Verify after and until are set (as datetime objects)
    assert req.after is not None
    assert req.until is not None
    assert req.after.date() == target_date
    assert req.until.date() == target_date


def test_read_only_report_warns_on_truncated_results():
    """Report must emit WARNING when 500+ orders are fetched for a single date."""
    
    mock_broker = MagicMock()
    mock_broker.get_account.return_value = {
        "cash": 10000.0,
        "equity": 15000.0,
        "buying_power": 20000.0,
    }
    mock_broker.get_positions.return_value = {}
    mock_broker.get_option_positions.return_value = []
    
    # Return exactly 500 orders to trigger truncation warning
    mock_broker.get_recent_orders.return_value = [
        {
            "id": f"order-{i}",
            "symbol": "AAPL",
            "side": "buy",
            "filled_qty": 1,
            "filled_avg_price": 150.0,
            "filled_at": "2026-10-14T18:00:00Z",
            "status": "filled",
        }
        for i in range(500)
    ]
    
    import sys
    from io import StringIO
    
    with patch("sys.argv", ["script", "--date", "2026-10-14"]):
        with patch("src.broker.alpaca.AlpacaBroker", return_value=mock_broker):
            captured_output = StringIO()
            with patch("sys.stdout", captured_output):
                from scripts.read_only_fills_report import main
                exit_code = main()
    
    # Should still exit 0 (warnings don't fail the report)
    assert exit_code == 0
    
    # Verify truncation warning appears
    stdout_output = captured_output.getvalue()
    assert "WARNING" in stdout_output or "truncated" in stdout_output.lower()
    assert "500" in stdout_output or "pagination" in stdout_output.lower()


def test_read_only_report_missing_equity_price_shows_warning():
    """Equity positions with missing current_price must show 'n/a' and WARNING."""
    
    mock_broker = MagicMock()
    mock_broker.get_account.return_value = {
        "cash": 10000.0,
        "equity": 15000.0,
        "buying_power": 20000.0,
    }
    mock_broker.get_positions.return_value = {
        "AAPL": {
            "qty": 10,
            "market_value": 1500.0,
            "avg_entry_price": 150.0,
            "current_price": None,  # Missing price
            "mark_price": None,
        }
    }
    mock_broker.get_option_positions.return_value = []
    mock_broker.get_recent_orders.return_value = []
    
    import sys
    from io import StringIO
    
    with patch("sys.argv", ["script", "--date", "2026-10-14"]):
        with patch("src.broker.alpaca.AlpacaBroker", return_value=mock_broker):
            captured_output = StringIO()
            captured_error = StringIO()
            with patch("sys.stdout", captured_output):
                with patch("sys.stderr", captured_error):
                    from scripts.read_only_fills_report import main
                    exit_code = main()
    
    # Should exit 0 (equity price warnings don't fail)
    assert exit_code == 0
    
    # Verify WARNING appears for missing price
    stdout_output = captured_output.getvalue()
    assert "WARNING" in stdout_output or "WARNINGS" in stdout_output
    assert "AAPL" in stdout_output
    assert "missing" in stdout_output.lower() or "invalid" in stdout_output.lower()
    
    # Verify "n/a" appears instead of $0.00
    assert "n/a" in stdout_output
    assert "$0.00" not in stdout_output.split("mark=")[1].split()[0] if "mark=" in stdout_output else True


def test_read_only_report_missing_option_price_shows_error():
    """Option positions with missing current_price must show ERROR and exit non-zero."""
    
    mock_broker = MagicMock()
    mock_broker.get_account.return_value = {
        "cash": 10000.0,
        "equity": 15000.0,
        "buying_power": 20000.0,
    }
    mock_broker.get_positions.return_value = {}
    mock_broker.get_option_positions.return_value = [
        {
            "symbol": "AAPL261106C00150000",
            "side": "short",
            "qty": 1,
            "market_value": -500.0,
            "avg_entry_price": 5.0,
            "current_price": None,  # Missing price
            "mark_price": None,
        }
    ]
    mock_broker.get_recent_orders.return_value = []
    
    import sys
    from io import StringIO
    
    with patch("sys.argv", ["script", "--date", "2026-10-14"]):
        with patch("src.broker.alpaca.AlpacaBroker", return_value=mock_broker):
            captured_output = StringIO()
            captured_error = StringIO()
            with patch("sys.stdout", captured_output):
                with patch("sys.stderr", captured_error):
                    from scripts.read_only_fills_report import main
                    exit_code = main()
    
    # Should exit non-zero (option price errors fail)
    assert exit_code == 1
    
    # Verify ERROR appears for missing option price
    error_output = captured_error.getvalue()
    assert "ERROR" in error_output
    assert "AAPL261106C00150000" in error_output or "Option" in error_output
    assert "missing" in error_output.lower() or "invalid" in error_output.lower()
