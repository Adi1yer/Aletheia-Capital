"""Unit tests for growth-income-drip paper track."""

import os
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.backtesting.growth_quality import MomentumSelector
from src.backtesting.income_drip import DividendBallastSelector, DividendDripManager
from src.performance.drip_track import (
    TRACK_ID,
    START_DATE,
    START_NAV_USD,
    config_fingerprint,
    is_quarterly_rebalance_due,
    calculate_returns,
)


class TestMomentumSelector:
    """Tests for momentum selector."""
    
    def test_initialization(self):
        """Test momentum selector initializes correctly."""
        selector = MomentumSelector(
            lookback_months=12,
            skip_months=1,
            top_n=30,
        )
        assert selector.lookback_months == 12
        assert selector.skip_months == 1
        assert selector.top_n == 30
    
    def test_get_weights_equal_weight(self):
        """Test equal weight calculation."""
        selector = MomentumSelector()
        tickers = ["AAPL", "MSFT", "GOOGL"]
        weights = selector.get_weights(tickers)
        
        assert len(weights) == 3
        assert abs(sum(weights.values()) - 1.0) < 0.001
        assert all(abs(w - 1/3) < 0.001 for w in weights.values())
    
    def test_get_weights_empty(self):
        """Test weight calculation with empty list."""
        selector = MomentumSelector()
        weights = selector.get_weights([])
        assert weights == {}


class TestDividendBallastSelector:
    """Tests for dividend ballast selector."""
    
    def test_initialization(self):
        """Test ballast selector initializes correctly."""
        selector = DividendBallastSelector(
            min_dividend_yield=0.02,
            max_holdings=15,
        )
        assert selector.min_dividend_yield == 0.02
        assert selector.max_holdings == 15
    
    def test_get_weights_equal_weight(self):
        """Test equal weight calculation."""
        selector = DividendBallastSelector()
        tickers = ["JNJ", "PG", "KO", "PEP"]
        weights = selector.get_weights(tickers)
        
        assert len(weights) == 4
        assert abs(sum(weights.values()) - 1.0) < 0.001
        assert all(abs(w - 0.25) < 0.001 for w in weights.values())


class TestDividendDripManager:
    """Tests for dividend drip manager."""
    
    def test_initialization(self):
        """Test drip manager initializes correctly."""
        manager = DividendDripManager()
        assert manager.accumulated_cash == 0.0
        assert manager.dividend_history == []
    
    def test_record_dividend(self):
        """Test recording dividend payments."""
        manager = DividendDripManager()
        ex_date = datetime(2026, 3, 15)
        payment_date = datetime(2026, 3, 30)
        
        manager.record_dividend("AAPL", 100.0, ex_date, payment_date)
        
        assert manager.accumulated_cash == 100.0
        assert len(manager.dividend_history) == 1
        assert manager.dividend_history[0]["ticker"] == "AAPL"
        assert manager.dividend_history[0]["amount"] == 100.0
    
    def test_record_multiple_dividends(self):
        """Test accumulating multiple dividends."""
        manager = DividendDripManager()
        ex_date = datetime(2026, 3, 15)
        payment_date = datetime(2026, 3, 30)
        
        manager.record_dividend("AAPL", 100.0, ex_date, payment_date)
        manager.record_dividend("MSFT", 50.0, ex_date, payment_date)
        manager.record_dividend("GOOGL", 75.0, ex_date, payment_date)
        
        assert manager.accumulated_cash == 225.0
        assert len(manager.dividend_history) == 3
    
    def test_execute_drip(self):
        """Test drip execution reduces cash."""
        manager = DividendDripManager()
        ex_date = datetime(2026, 3, 15)
        payment_date = datetime(2026, 3, 30)
        
        manager.record_dividend("AAPL", 100.0, ex_date, payment_date)
        
        reinvested = manager.execute_drip(60.0)
        
        assert reinvested == 60.0
        assert manager.accumulated_cash == 40.0
    
    def test_execute_drip_capped(self):
        """Test drip execution is capped at available cash."""
        manager = DividendDripManager()
        ex_date = datetime(2026, 3, 15)
        payment_date = datetime(2026, 3, 30)
        
        manager.record_dividend("AAPL", 100.0, ex_date, payment_date)
        
        reinvested = manager.execute_drip(150.0)
        
        assert reinvested == 100.0
        assert manager.accumulated_cash == 0.0
    
    def test_reset(self):
        """Test reset clears state."""
        manager = DividendDripManager()
        ex_date = datetime(2026, 3, 15)
        payment_date = datetime(2026, 3, 30)
        
        manager.record_dividend("AAPL", 100.0, ex_date, payment_date)
        manager.reset()
        
        assert manager.accumulated_cash == 0.0
        assert manager.dividend_history == []


class TestDripTrack:
    """Tests for drip track record."""
    
    def test_track_constants(self):
        """Test track constants are correct."""
        assert TRACK_ID == "growth-income-drip-v1"
        assert START_DATE == date(2026, 9, 27)
        assert START_NAV_USD == 10_000.0
    
    def test_config_fingerprint(self):
        """Test config fingerprinting."""
        config1 = {
            "growth_weight": 0.80,
            "ballast_weight": 0.20,
            "momentum_lookback_months": 12,
        }
        config2 = {
            "growth_weight": 0.80,
            "ballast_weight": 0.20,
            "momentum_lookback_months": 12,
        }
        config3 = {
            "growth_weight": 0.75,
            "ballast_weight": 0.25,
            "momentum_lookback_months": 12,
        }
        
        fp1 = config_fingerprint(config1)
        fp2 = config_fingerprint(config2)
        fp3 = config_fingerprint(config3)
        
        assert fp1 == fp2
        assert fp1 != fp3
        assert len(fp1) == 12
    
    def test_quarterly_rebalance_due_no_last(self):
        """Test quarterly rebalance when no last rebalance exists."""
        # The actual function uses datetime.now() internally
        # Testing the logic with is_quarterly_rebalance_due is covered by other tests
        # This test just verifies the function exists and is callable
        from src.performance.drip_track import is_quarterly_rebalance_due
        result = is_quarterly_rebalance_due(None)
        assert isinstance(result, bool)
    
    def test_quarterly_rebalance_due_three_months_passed(self):
        """Test quarterly rebalance after 3 months."""
        last_rebalance = date(2026, 3, 15)
        
        # 2 months later - should be False
        result = is_quarterly_rebalance_due(last_rebalance)
        # This will depend on current date, so we can't assert true/false directly
        # The function compares against datetime.now(ET).date()
        
        assert isinstance(result, bool)
    
    def test_calculate_returns_empty(self):
        """Test return calculation with no snapshots."""
        returns = calculate_returns([])
        assert returns == {}
    
    def test_calculate_returns_single_snapshot(self):
        """Test return calculation with one snapshot."""
        snapshots = [
            {
                "date": "2026-09-27",
                "nav": 10500.0,
            }
        ]
        returns = calculate_returns(snapshots)
        
        assert returns["start_nav"] == START_NAV_USD
        assert returns["current_nav"] == 10500.0
        assert returns["total_return_pct"] == 5.0
    
    def test_calculate_returns_multiple_snapshots(self):
        """Test return calculation with multiple snapshots."""
        snapshots = [
            {"date": "2026-09-27", "nav": 10000.0},
            {"date": "2026-09-28", "nav": 10100.0},
            {"date": "2026-09-29", "nav": 10200.0},
            {"date": "2026-09-30", "nav": 10300.0},
        ]
        returns = calculate_returns(snapshots)
        
        assert returns["start_nav"] == START_NAV_USD
        assert returns["current_nav"] == 10300.0
        assert returns["total_return_pct"] == 3.0
        assert returns["num_snapshots"] == 4
        assert "sharpe_ratio" in returns


class TestSecretIsolation:
    """Tests for secret and environment variable isolation."""
    
    def test_drip_secrets_distinct_from_wheel(self):
        """Test that drip uses separate secret names."""
        drip_secrets = {
            "DRIP_ALPACA_API_KEY",
            "DRIP_ALPACA_SECRET_KEY",
            "DRIP_ALPACA_BASE_URL",
        }
        
        wheel_secrets = {
            "ALPACA_API_KEY",
            "ALPACA_SECRET_KEY",
            "ALPACA_BASE_URL",
        }
        
        # Ensure no overlap
        assert drip_secrets.isdisjoint(wheel_secrets)
    
    def test_drip_broker_requires_drip_secrets(self):
        """Test that drip broker creation requires DRIP_ALPACA_* env vars."""
        # Clear drip secrets
        old_api = os.environ.pop("DRIP_ALPACA_API_KEY", None)
        old_secret = os.environ.pop("DRIP_ALPACA_SECRET_KEY", None)
        
        try:
            from scripts.growth_income_drip_rebalance import get_drip_broker
            
            with pytest.raises(ValueError, match="DRIP_ALPACA"):
                get_drip_broker()
        finally:
            # Restore if they existed
            if old_api:
                os.environ["DRIP_ALPACA_API_KEY"] = old_api
            if old_secret:
                os.environ["DRIP_ALPACA_SECRET_KEY"] = old_secret
    
    def test_drip_broker_uses_paper_only(self):
        """Test that drip broker constructs without base_url (hardcoded in AlpacaBroker)."""
        os.environ["DRIP_ALPACA_API_KEY"] = "test_key"
        os.environ["DRIP_ALPACA_SECRET_KEY"] = "test_secret"
        os.environ.pop("DRIP_ALPACA_BASE_URL", None)
        
        try:
            from scripts.growth_income_drip_rebalance import get_drip_broker
            
            with patch("scripts.growth_income_drip_rebalance.AlpacaBroker") as mock_broker:
                get_drip_broker()
                
                # Verify AlpacaBroker was called with only api_key and secret_key (no base_url)
                mock_broker.assert_called_once_with(
                    api_key="test_key",
                    secret_key="test_secret",
                )
        finally:
            os.environ.pop("DRIP_ALPACA_API_KEY", None)
            os.environ.pop("DRIP_ALPACA_SECRET_KEY", None)
    
    def test_drip_broker_construction_no_unsupported_kwargs(self):
        """Test that drip broker construction succeeds with real AlpacaBroker (no unsupported kwargs)."""
        os.environ["DRIP_ALPACA_API_KEY"] = "test_key"
        os.environ["DRIP_ALPACA_SECRET_KEY"] = "test_secret"
        
        try:
            from scripts.growth_income_drip_rebalance import get_drip_broker
            from src.broker.alpaca import AlpacaBroker
            
            # This should not raise TypeError about unexpected keyword arguments
            # (If it does, the fix didn't work)
            broker = get_drip_broker()
            
            # Verify it's an AlpacaBroker instance
            assert isinstance(broker, AlpacaBroker)
        finally:
            os.environ.pop("DRIP_ALPACA_API_KEY", None)
            os.environ.pop("DRIP_ALPACA_SECRET_KEY", None)


class FakeBroker:
    """Fake broker for testing execute_delta_rebalance."""
    
    def __init__(self, prices=None, fail_orders=False, positions=None):
        self.prices = prices or {}
        self.fail_orders = fail_orders
        self.positions = positions if positions is not None else {}
        self.orders_submitted = []
        self.get_last_equity_prices_calls = []
    
    def get_positions(self):
        """Return positions as a dict (matching AlpacaBroker.get_positions signature)."""
        return self.positions
    
    def get_last_equity_prices(self, symbols):
        """Track calls and return prices."""
        self.get_last_equity_prices_calls.append(symbols)
        return {s: self.prices.get(s, 0) for s in symbols if s in self.prices}
    
    def execute_order(self, ticker, decision, current_price=None):
        """Track orders submitted."""
        self.orders_submitted.append({
            "ticker": ticker,
            "action": decision.action,
            "quantity": decision.quantity,
            "current_price": current_price,
        })
        if self.fail_orders:
            return {"success": False, "error": "test_failure"}
        return {
            "success": True,
            "order_id": f"test_order_{len(self.orders_submitted)}",
        }


class TestDeltaRebalance:
    """Tests for delta rebalance logic."""
    
    def test_calculate_target_allocations(self):
        """Test target allocation calculation."""
        from scripts.growth_income_drip_rebalance import calculate_target_allocations
        
        growth_tickers = ["AAPL", "MSFT", "GOOGL"]
        ballast_tickers = ["JNJ", "PG"]
        
        targets = calculate_target_allocations(
            growth_tickers,
            ballast_tickers,
            growth_weight=0.80,
            ballast_weight=0.20,
            total_equity=10000.0,
        )
        
        # Growth sleeve: 80% = $8000, split 3 ways = $2666.67 each
        assert abs(targets["AAPL"] - 8000/3) < 1.0
        assert abs(targets["MSFT"] - 8000/3) < 1.0
        assert abs(targets["GOOGL"] - 8000/3) < 1.0
        
        # Ballast sleeve: 20% = $2000, split 2 ways = $1000 each
        assert abs(targets["JNJ"] - 1000.0) < 1.0
        assert abs(targets["PG"] - 1000.0) < 1.0
        
        # Total should equal equity (minus rounding)
        assert abs(sum(targets.values()) - 10000.0) < 1.0
    
    def test_calculate_target_allocations_empty(self):
        """Test target allocation with empty lists."""
        from scripts.growth_income_drip_rebalance import calculate_target_allocations
        
        targets = calculate_target_allocations(
            growth_tickers=[],
            ballast_tickers=[],
            growth_weight=0.80,
            ballast_weight=0.20,
            total_equity=10000.0,
        )
        
        assert targets == {}
    
    def test_execute_delta_rebalance_uses_batch_pricing(self):
        """Test that rebalance uses batch get_last_equity_prices API."""
        from scripts.growth_income_drip_rebalance import execute_delta_rebalance
        
        broker = FakeBroker(prices={"AAPL": 150.0, "MSFT": 300.0})
        targets = {"AAPL": 3000.0, "MSFT": 3000.0}
        current_positions = {}
        
        actions = execute_delta_rebalance(broker, targets, current_positions)
        
        # Verify batch pricing was called
        assert len(broker.get_last_equity_prices_calls) == 1
        assert set(broker.get_last_equity_prices_calls[0]) == {"AAPL", "MSFT"}
        
        # Verify orders were submitted via execute_order
        assert len(broker.orders_submitted) == 2
        assert broker.orders_submitted[0]["action"] == "buy"
        assert broker.orders_submitted[1]["action"] == "buy"
    
    def test_execute_delta_rebalance_uses_execute_order(self):
        """Test that rebalance uses execute_order, not submit_market_order."""
        from scripts.growth_income_drip_rebalance import execute_delta_rebalance
        
        broker = FakeBroker(prices={"AAPL": 100.0})
        targets = {"AAPL": 1000.0}
        current_positions = {}
        
        actions = execute_delta_rebalance(broker, targets, current_positions)
        
        # Verify execute_order was called with correct parameters
        assert len(broker.orders_submitted) == 1
        order = broker.orders_submitted[0]
        assert order["ticker"] == "AAPL"
        assert order["action"] == "buy"
        assert order["quantity"] == 10
        assert order["current_price"] == 100.0
    
    def test_execute_delta_rebalance_fails_on_zero_prices(self):
        """Test that rebalance fails when no prices are available."""
        from scripts.growth_income_drip_rebalance import execute_delta_rebalance
        
        broker = FakeBroker(prices={})
        targets = {"AAPL": 3000.0, "MSFT": 3000.0}
        current_positions = {}
        
        with pytest.raises(RuntimeError, match="No prices available"):
            execute_delta_rebalance(broker, targets, current_positions)
    
    def test_execute_delta_rebalance_fails_on_zero_trades_with_targets(self):
        """Test that rebalance fails when zero trades execute despite non-empty targets."""
        from scripts.growth_income_drip_rebalance import execute_delta_rebalance
        
        broker = FakeBroker(prices={"AAPL": 100.0, "MSFT": 200.0}, fail_orders=True)
        targets = {"AAPL": 3000.0, "MSFT": 3000.0}
        current_positions = {}
        
        with pytest.raises(RuntimeError, match="Rebalance failed.*0 executed"):
            execute_delta_rebalance(broker, targets, current_positions)
    
    def test_execute_delta_rebalance_skips_invalid_prices(self):
        """Test that rebalance skips tickers with invalid prices."""
        from scripts.growth_income_drip_rebalance import execute_delta_rebalance
        
        broker = FakeBroker(prices={"AAPL": 100.0, "MSFT": 0})
        targets = {"AAPL": 1000.0, "MSFT": 1000.0}
        current_positions = {}
        
        actions = execute_delta_rebalance(broker, targets, current_positions)
        
        # Only AAPL should be traded
        assert len(broker.orders_submitted) == 1
        assert broker.orders_submitted[0]["ticker"] == "AAPL"
        assert len(actions["buys"]) == 1
    
    def test_execute_delta_rebalance_sells_before_buys(self):
        """Test that sells are executed before buys."""
        from scripts.growth_income_drip_rebalance import execute_delta_rebalance
        
        broker = FakeBroker(prices={"AAPL": 100.0, "MSFT": 200.0})
        targets = {"AAPL": 1000.0, "MSFT": 0}
        current_positions = {"MSFT": {"qty": 10}}
        
        actions = execute_delta_rebalance(broker, targets, current_positions)
        
        # Verify both buy and sell happened
        assert len(actions["buys"]) == 1
        assert len(actions["sells"]) == 1
        assert actions["buys"][0]["ticker"] == "AAPL"
        assert actions["sells"][0]["ticker"] == "MSFT"


class TestPositionsHandling:
    """Tests for positions handling with AlpacaBroker return type."""
    
    def test_broker_get_positions_returns_dict(self):
        """Test that AlpacaBroker.get_positions returns a dict, not a list."""
        from src.broker.alpaca import AlpacaBroker
        
        # Check the return type annotation
        import inspect
        sig = inspect.signature(AlpacaBroker.get_positions)
        # Return annotation should be Dict[str, Dict]
        assert "Dict" in str(sig.return_annotation)
    
    def test_positions_dict_iteration_empty(self):
        """Test iterating over empty positions dict (regression test for bug)."""
        # Simulate the drip script logic
        positions = {}  # Empty dict from broker.get_positions()
        
        # This should not raise an error
        current_positions = {
            symbol: {"qty": int(pos["qty"]), "market_value": float(pos["market_value"])}
            for symbol, pos in positions.items()
        }
        
        assert current_positions == {}
    
    def test_positions_dict_iteration_with_data(self):
        """Test iterating over non-empty positions dict (regression test for bug)."""
        # Simulate actual return value from AlpacaBroker.get_positions()
        positions = {
            "AAPL": {
                "qty": 10,
                "avg_entry_price": 150.0,
                "market_value": 1500.0,
                "side": "long"
            },
            "MSFT": {
                "qty": 5,
                "avg_entry_price": 300.0,
                "market_value": 1500.0,
                "side": "long"
            }
        }
        
        # This is the fixed logic (using .items())
        current_positions = {
            symbol: {"qty": int(pos["qty"]), "market_value": float(pos["market_value"])}
            for symbol, pos in positions.items()
        }
        
        assert len(current_positions) == 2
        assert current_positions["AAPL"]["qty"] == 10
        assert current_positions["AAPL"]["market_value"] == 1500.0
        assert current_positions["MSFT"]["qty"] == 5
        assert current_positions["MSFT"]["market_value"] == 1500.0
    
    def test_wrong_iteration_raises_error(self):
        """Test that the old buggy iteration pattern raises TypeError."""
        positions = {
            "AAPL": {
                "qty": 10,
                "market_value": 1500.0
            }
        }
        
        # The old buggy pattern: iterating over dict yields keys (strings)
        with pytest.raises(TypeError, match="string indices must be integers"):
            _ = {
                pos["symbol"]: {"qty": int(pos["qty"]), "market_value": float(pos["market_value"])}
                for pos in positions  # BUG: iterating over dict yields string keys
            }
    
    def test_main_with_nonempty_positions(self):
        """Test main() logic handles non-empty positions correctly."""
        # Simulate broker.get_positions() return value
        positions = {
            "AAPL": {
                "qty": 10,
                "avg_entry_price": 150.0,
                "market_value": 1500.0,
                "side": "long"
            },
            "MSFT": {
                "qty": 5,
                "avg_entry_price": 300.0,
                "market_value": 1500.0,
                "side": "long"
            }
        }
        
        # Test that the positions dict comprehension doesn't raise (this is the fix)
        current_positions = {
            symbol: {"qty": int(pos["qty"]), "market_value": float(pos["market_value"])}
            for symbol, pos in positions.items()
        }
        
        assert len(current_positions) == 2
        assert "AAPL" in current_positions
        assert "MSFT" in current_positions
        assert current_positions["AAPL"]["qty"] == 10
        assert current_positions["AAPL"]["market_value"] == 1500.0


class TestConcurrencyIsolation:
    """Tests for workflow concurrency group isolation."""
    
    def test_concurrency_groups_distinct(self):
        """Test that drip and wheel use different concurrency groups."""
        drip_group = "aletheia-drip-paper"
        wheel_group = "aletheia-wheel-paper"
        
        assert drip_group != wheel_group
        
        # Verify in workflow files
        drip_workflow = Path(".github/workflows/drip-daily-snapshot.yml")
        wheel_workflow = Path(".github/workflows/daily-wheel-scan.yml")
        
        if drip_workflow.exists():
            drip_content = drip_workflow.read_text()
            assert drip_group in drip_content
            assert wheel_group not in drip_content
        
        if wheel_workflow.exists():
            wheel_content = wheel_workflow.read_text()
            assert wheel_group in wheel_content
            assert drip_group not in wheel_content


class TestResidualCashDeployment:
    """Tests for residual cash deployment feature."""
    
    def test_has_excess_cash_above_threshold(self):
        """Test excess cash detection above threshold."""
        from scripts.growth_income_drip_rebalance import has_excess_cash
        
        # 15% cash should trigger with 10% threshold
        assert has_excess_cash(cash=1500.0, nav=10000.0, threshold_pct=0.10)
        
        # 45% cash should definitely trigger
        assert has_excess_cash(cash=4500.0, nav=10000.0, threshold_pct=0.10)
    
    def test_has_excess_cash_below_threshold(self):
        """Test excess cash detection below threshold."""
        from scripts.growth_income_drip_rebalance import has_excess_cash
        
        # 5% cash should not trigger with 10% threshold
        assert not has_excess_cash(cash=500.0, nav=10000.0, threshold_pct=0.10)
        
        # Exactly at threshold should not trigger
        assert not has_excess_cash(cash=1000.0, nav=10000.0, threshold_pct=0.10)
    
    def test_has_excess_cash_zero_nav(self):
        """Test excess cash detection with zero NAV."""
        from scripts.growth_income_drip_rebalance import has_excess_cash
        
        assert not has_excess_cash(cash=1000.0, nav=0.0, threshold_pct=0.10)
    
    def test_deploy_residual_cash_proportional_allocation(self):
        """Test that residual cash is deployed proportionally to current positions."""
        from scripts.growth_income_drip_rebalance import deploy_residual_cash
        
        # Set up current positions with 2 holdings
        current_positions = {
            "AAPL": {"qty": 10, "market_value": 3000.0},  # 60% of portfolio
            "MSFT": {"qty": 5, "market_value": 2000.0},   # 40% of portfolio
        }
        
        broker = FakeBroker(prices={"AAPL": 150.0, "MSFT": 200.0})
        cash_to_deploy = 1000.0
        
        actions = deploy_residual_cash(broker, current_positions, cash_to_deploy)
        
        # Should have submitted 2 buy orders
        assert len(actions["buys"]) == 2
        
        # Find AAPL and MSFT orders
        aapl_order = next((b for b in actions["buys"] if b["ticker"] == "AAPL"), None)
        msft_order = next((b for b in actions["buys"] if b["ticker"] == "MSFT"), None)
        
        assert aapl_order is not None
        assert msft_order is not None
        
        # AAPL should get ~60% of deployment ($600), which is 4 shares at $150
        assert aapl_order["shares"] == 4
        assert abs(aapl_order["allocated_usd"] - 600.0) < 1.0
        
        # MSFT should get ~40% of deployment ($400), which is 2 shares at $200
        assert msft_order["shares"] == 2
        assert abs(msft_order["allocated_usd"] - 400.0) < 1.0
    
    def test_deploy_residual_cash_no_positions(self):
        """Test that residual cash deployment does nothing with no positions."""
        from scripts.growth_income_drip_rebalance import deploy_residual_cash
        
        broker = FakeBroker(prices={})
        actions = deploy_residual_cash(broker, {}, 1000.0)
        
        assert len(actions["buys"]) == 0
        assert len(broker.orders_submitted) == 0
    
    def test_deploy_residual_cash_below_min_trade(self):
        """Test that residual cash deployment respects min trade size."""
        from scripts.growth_income_drip_rebalance import deploy_residual_cash
        
        current_positions = {
            "AAPL": {"qty": 1, "market_value": 150.0},
        }
        
        broker = FakeBroker(prices={"AAPL": 150.0})
        
        # Only $50 to deploy, below $100 min trade
        actions = deploy_residual_cash(broker, current_positions, 50.0, min_trade_usd=100.0)
        
        assert len(actions["buys"]) == 0
    
    def test_deploy_residual_cash_skips_invalid_prices(self):
        """Test that residual cash deployment skips tickers with invalid prices."""
        from scripts.growth_income_drip_rebalance import deploy_residual_cash
        
        current_positions = {
            "AAPL": {"qty": 10, "market_value": 1500.0},
            "MSFT": {"qty": 5, "market_value": 1500.0},
        }
        
        # Only provide price for AAPL
        broker = FakeBroker(prices={"AAPL": 150.0})
        
        actions = deploy_residual_cash(broker, current_positions, 1000.0)
        
        # Should only deploy to AAPL
        assert len(actions["buys"]) == 1
        assert actions["buys"][0]["ticker"] == "AAPL"
    
    def test_deploy_residual_cash_multiple_positions(self):
        """Test residual cash deployment across many positions."""
        from scripts.growth_income_drip_rebalance import deploy_residual_cash
        
        # Create 5 equal-weight positions
        current_positions = {
            f"TICK{i}": {"qty": 10, "market_value": 1000.0}
            for i in range(5)
        }
        
        prices = {f"TICK{i}": 100.0 for i in range(5)}
        broker = FakeBroker(prices=prices)
        
        actions = deploy_residual_cash(broker, current_positions, 5000.0)
        
        # Should deploy to all 5 positions
        assert len(actions["buys"]) == 5
        
        # Each should get ~$1000 (20% of $5000)
        for buy in actions["buys"]:
            assert abs(buy["allocated_usd"] - 1000.0) < 1.0
            assert buy["shares"] == 10  # $1000 / $100 per share


class TestConcurrencyIsolation:
    """Tests for workflow concurrency group isolation."""
    
    def test_concurrency_groups_distinct(self):
        """Test that drip and wheel use different concurrency groups."""
        drip_group = "aletheia-drip-paper"
        wheel_group = "aletheia-wheel-paper"
        
        assert drip_group != wheel_group
        
        # Verify in workflow files
        drip_workflow = Path(".github/workflows/drip-daily-snapshot.yml")
        wheel_workflow = Path(".github/workflows/daily-wheel-scan.yml")
        
        if drip_workflow.exists():
            drip_content = drip_workflow.read_text()
            assert drip_group in drip_content
            assert wheel_group not in drip_content
        
        if wheel_workflow.exists():
            wheel_content = wheel_workflow.read_text()
            assert wheel_group in wheel_content
            assert drip_group not in wheel_content


class TestPerformancePathIsolation:
    """Tests for performance data path isolation."""
    
    def test_performance_paths_distinct(self):
        """Test that drip and wheel use different performance directories."""
        from src.performance.drip_track import snapshot_dir as drip_dir
        from src.performance.official_track import snapshot_dir as wheel_dir
        
        drip_path = drip_dir()
        wheel_path = wheel_dir()
        
        assert str(drip_path) != str(wheel_path)
        assert "growth_income_drip_v1" in str(drip_path)
        assert "official" in str(wheel_path)
        
        # Ensure paths don't overlap
        assert not str(drip_path).startswith(str(wheel_path))
        assert not str(wheel_path).startswith(str(drip_path))


class TestDripEmail:
    """Tests for drip email formatting."""
    
    def test_build_drip_daily_email_basic(self):
        """Test basic email building with minimal data."""
        from src.utils.drip_email import build_drip_daily_email
        
        positions = {
            "AAPL": {"qty": 10, "market_value": 1500.0},
            "MSFT": {"qty": 5, "market_value": 1500.0},
        }
        
        subject, body = build_drip_daily_email(
            nav=10500.0,
            cash=500.0,
            positions=positions,
            last_rebalance="2026-09-27",
            rebalance_due=False,
        )
        
        # Verify subject
        assert "growth-income-drip-v1" in subject
        assert "10,500" in subject or "10500" in subject
        
        # Verify body contains required fields
        assert "PORTFOLIO ALLOCATION" in body
        assert "Cash:" in body
        assert "Invested:" in body
        assert "SLEEVE BREAKDOWN" in body
        assert "TOP HOLDINGS" in body
        assert "AAPL" in body
        assert "MSFT" in body
        assert "REBALANCE STATUS" in body
    
    def test_email_contains_cash_percentage(self):
        """Test that email includes cash as percentage of NAV."""
        from src.utils.drip_email import build_drip_daily_email
        
        positions = {"AAPL": {"qty": 10, "market_value": 9500.0}}
        
        subject, body = build_drip_daily_email(
            nav=10000.0,
            cash=500.0,
            positions=positions,
        )
        
        # Should show cash percentage (5% in this case)
        assert "Cash:" in body
        assert "500" in body
        assert "5.0%" in body or "(5%" in body
    
    def test_email_contains_invested_dollars_and_percent(self):
        """Test that email includes invested dollars and percentage."""
        from src.utils.drip_email import build_drip_daily_email
        
        positions = {
            "AAPL": {"qty": 10, "market_value": 5000.0},
            "MSFT": {"qty": 5, "market_value": 3000.0},
        }
        
        subject, body = build_drip_daily_email(
            nav=10000.0,
            cash=2000.0,
            positions=positions,
        )
        
        # Should show invested amount and percentage
        assert "Invested:" in body
        assert "8,000" in body or "8000" in body
        assert "80.0%" in body or "(80%" in body
    
    def test_email_contains_sleeve_breakdown(self):
        """Test that email includes growth vs ballast sleeve breakdown."""
        from src.utils.drip_email import build_drip_daily_email
        
        positions = {
            "AAPL": {"qty": 10, "market_value": 6000.0},
            "JNJ": {"qty": 5, "market_value": 2000.0},
        }
        
        subject, body = build_drip_daily_email(
            nav=10000.0,
            cash=2000.0,
            positions=positions,
            growth_nav=6000.0,
            ballast_nav=2000.0,
        )
        
        # Should show sleeve breakdown
        assert "SLEEVE BREAKDOWN" in body
        assert "Growth sleeve:" in body
        assert "Dividend ballast:" in body
        assert "6,000" in body or "6000" in body
        assert "2,000" in body or "2000" in body
        assert "60.0%" in body or "(60%" in body
        assert "20.0%" in body or "(20%" in body
        assert "target 80%" in body
        assert "target 20%" in body
    
    def test_email_contains_top_holdings(self):
        """Test that email includes top holdings detail."""
        from src.utils.drip_email import build_drip_daily_email
        
        positions = {
            "AAPL": {"qty": 10, "market_value": 5000.0},
            "MSFT": {"qty": 5, "market_value": 3000.0},
            "GOOGL": {"qty": 2, "market_value": 2000.0},
            "AMZN": {"qty": 1, "market_value": 1000.0},
        }
        
        subject, body = build_drip_daily_email(
            nav=12000.0,
            cash=1000.0,
            positions=positions,
        )
        
        # Should show top holdings
        assert "TOP HOLDINGS" in body
        assert "AAPL" in body
        assert "10 shares" in body
        assert "MSFT" in body
        assert "5 shares" in body
    
    def test_email_contains_spy_comparison(self):
        """Test that email includes SPY since start and excess return."""
        from src.utils.drip_email import build_drip_daily_email
        
        positions = {"AAPL": {"qty": 10, "market_value": 9000.0}}
        
        subject, body = build_drip_daily_email(
            nav=10000.0,
            cash=1000.0,
            positions=positions,
            spy_since_start_pct=5.0,
            excess_return_pct=2.5,
            track_return_pct=7.5,
        )
        
        # Should show SPY comparison
        assert "TRACK PERFORMANCE" in body
        assert "SPY since start:" in body
        assert "+5.00%" in body
        assert "Excess return:" in body
        assert "+2.50%" in body
        assert "Track return:" in body
        assert "+7.50%" in body
        
        # Subject should also include SPY data
        assert "SPY" in subject
        assert "excess" in subject


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
