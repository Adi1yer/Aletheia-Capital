"""Unit tests for Alpaca account activities (dividend fetch)."""

from unittest.mock import MagicMock, patch
from datetime import date
import pytest

from src.broker.alpaca import AlpacaBroker


class TestAccountActivities:
    """Tests for get_account_activities method."""

    def test_get_account_activities_imports_correctly(self):
        """Test that account activities can be imported without GetAccountActivitiesRequest."""
        # This test verifies the fix for the Oct 5 2026 production issue
        # where GetAccountActivitiesRequest was not available in alpaca-py 0.19.1
        
        # The import should not raise ImportError
        try:
            from alpaca.trading import ActivityType
            assert ActivityType is not None
        except ImportError as e:
            pytest.fail(f"Failed to import ActivityType: {e}")
        
        # GetAccountActivitiesRequest should NOT exist in alpaca-py 0.19.1
        try:
            from alpaca.trading.requests import GetAccountActivitiesRequest
            pytest.fail("GetAccountActivitiesRequest should not exist in alpaca-py 0.19.1")
        except ImportError:
            # Expected - this class doesn't exist in 0.19.1
            pass
    
    @patch('src.broker.alpaca.TradingClient')
    def test_get_account_activities_uses_raw_api(self, mock_trading_client):
        """Test that get_account_activities uses raw REST API (client.get)."""
        # Mock the client.get method to return dividend activities
        mock_client_instance = MagicMock()
        mock_client_instance.get.return_value = [
            {
                "activity_type": "DIV",
                "date": "2026-10-01",
                "net_amount": 50.0,
                "symbol": "AAPL",
                "description": "Dividend from AAPL",
                "id": "div_1",
            }
        ]
        mock_trading_client.return_value = mock_client_instance
        
        # Create broker and fetch activities
        broker = AlpacaBroker(api_key="test_key", secret_key="test_secret")
        broker.client = mock_client_instance  # Override with our mock
        
        activities = broker.get_account_activities(
            activity_types=['DIV'],
            date_start=date(2026, 9, 1),
            date_end=date(2026, 10, 31),
        )
        
        # Verify client.get was called with correct path
        assert mock_client_instance.get.called
        call_args = mock_client_instance.get.call_args
        assert "account/activities/DIV" in str(call_args)
        
        # Verify activities were parsed correctly
        assert len(activities) == 1
        assert activities[0]["activity_type"] == "DIV"
        assert activities[0]["net_amount"] == 50.0
        assert activities[0]["symbol"] == "AAPL"
    
    @patch('src.broker.alpaca.TradingClient')
    def test_get_account_activities_handles_multiple_types(self, mock_trading_client):
        """Test fetching multiple activity types."""
        mock_client_instance = MagicMock()
        
        # Mock responses for different activity types
        def mock_get(path, data=None):
            if "DIV" in path and "DIVCGL" not in path:
                return [{"activity_type": "DIV", "net_amount": 50.0, "symbol": "AAPL", "id": "1", "date": "2026-10-01"}]
            elif "DIVCGL" in path:
                return [{"activity_type": "DIVCGL", "net_amount": 5.0, "symbol": "MSFT", "id": "2", "date": "2026-10-02"}]
            return []
        
        mock_client_instance.get.side_effect = mock_get
        mock_trading_client.return_value = mock_client_instance
        
        broker = AlpacaBroker(api_key="test_key", secret_key="test_secret")
        broker.client = mock_client_instance
        
        activities = broker.get_account_activities(
            activity_types=['DIV', 'DIVCGL'],
        )
        
        # Should have both activities
        assert len(activities) == 2
        assert any(a["activity_type"] == "DIV" for a in activities)
        assert any(a["activity_type"] == "DIVCGL" for a in activities)
    
    @patch('src.broker.alpaca.TradingClient')
    def test_get_account_activities_handles_errors_gracefully(self, mock_trading_client):
        """Test that errors are handled gracefully and return empty list."""
        mock_client_instance = MagicMock()
        mock_client_instance.get.side_effect = Exception("API Error")
        mock_trading_client.return_value = mock_client_instance
        
        broker = AlpacaBroker(api_key="test_key", secret_key="test_secret")
        broker.client = mock_client_instance
        
        # Should not raise, should return empty list
        activities = broker.get_account_activities()
        assert activities == []
    
    @patch('src.broker.alpaca.TradingClient')
    def test_get_account_activities_with_date_params(self, mock_trading_client):
        """Test that get_account_activities passes date parameters correctly."""
        mock_client_instance = MagicMock()
        mock_client_instance.get.return_value = [
            {
                "activity_type": "DIV",
                "date": "2026-10-01",
                "net_amount": 50.0,
                "symbol": "AAPL",
                "id": "div_1",
            }
        ]
        mock_trading_client.return_value = mock_client_instance
        
        broker = AlpacaBroker(api_key="test_key", secret_key="test_secret")
        broker.client = mock_client_instance
        
        start = date(2026, 10, 1)
        end = date(2026, 10, 31)
        
        activities = broker.get_account_activities(
            activity_types=['DIV'],
            date_start=start,
            date_end=end,
            page_size=50,
        )
        
        # Verify client.get was called with date params
        assert mock_client_instance.get.called
        call_args = mock_client_instance.get.call_args
        # Check that date params were included
        params = call_args[1].get('data', {}) if len(call_args) > 1 else call_args[0][1] if len(call_args[0]) > 1 else {}
        assert params.get('date') == '2026-10-01'
        assert params.get('until') == '2026-10-31'
        assert params.get('page_size') == 50


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
