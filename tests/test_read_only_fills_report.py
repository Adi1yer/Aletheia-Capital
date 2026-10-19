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
    """When fills/orders fetch fails, script must print ERROR and exit non-zero."""
    
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
