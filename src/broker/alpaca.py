"""Alpaca broker integration for paper trading"""

from typing import Dict, List, Optional
from datetime import date, timedelta
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    MarketOrderRequest,
    LimitOrderRequest,
    GetOrdersRequest,
    GetOptionContractsRequest,
)
from alpaca.trading.enums import OrderSide, TimeInForce, OrderType, ContractType
from src.config.settings import settings
from src.portfolio.models import Portfolio, Position
from src.portfolio.manager import PortfolioDecision
import structlog

logger = structlog.get_logger()


class AlpacaBroker:
    """Alpaca broker integration (alpaca-py SDK)"""

    def __init__(self):
        """Initialize Alpaca client for paper trading"""
        paper_base_url = "https://paper-api.alpaca.markets/v2"
        if settings.alpaca_base_url != paper_base_url:
            logger.warning(
                "Alpaca base_url not set to paper trading endpoint, overriding",
                provided_url=settings.alpaca_base_url,
                using_url=paper_base_url,
            )

        self.client = TradingClient(
            api_key=settings.alpaca_api_key,
            secret_key=settings.alpaca_secret_key,
            paper=True,
        )
        logger.info("Initialized Alpaca broker for paper trading", base_url=paper_base_url)

    def get_account(self) -> Dict:
        """Get account information"""
        try:
            account = self.client.get_account()
            return {
                "cash": float(account.cash),
                "buying_power": float(account.buying_power),
                "portfolio_value": float(account.portfolio_value),
                "equity": float(account.equity),
            }
        except Exception as e:
            logger.error("Error fetching account", error=str(e))
            raise

    def get_positions(self) -> Dict[str, Dict]:
        """Get current positions"""
        try:
            positions = self.client.get_all_positions()
            position_dict = {}

            for pos in positions:
                qty = abs(int(float(pos.qty)))
                side = getattr(pos.side, "value", str(pos.side)).lower() if hasattr(pos, "side") else ("long" if int(float(pos.qty)) >= 0 else "short")
                if side not in ("long", "short"):
                    side = "long"
                position_dict[pos.symbol] = {
                    "qty": qty,
                    "avg_entry_price": float(pos.avg_entry_price),
                    "market_value": float(pos.market_value),
                    "side": side,
                }

            return position_dict
        except Exception as e:
            logger.error("Error fetching positions", error=str(e))
            raise

    def get_open_orders(self, limit: int = 50) -> List[Dict]:
        """Get open (pending) orders from Alpaca."""
        try:
            req = GetOrdersRequest(status="open", limit=limit)
            orders = self.client.get_orders(req)
            return [
                {
                    "id": str(o.id),
                    "symbol": o.symbol,
                    "side": getattr(o.side, "value", str(o.side)).lower(),
                    "qty": int(float(o.qty)) if o.qty else 0,
                    "status": getattr(o.status, "value", str(o.status)).lower(),
                    "submitted_at": str(o.submitted_at) if hasattr(o, "submitted_at") and o.submitted_at else None,
                    "type": getattr(o.type, "value", str(o.type)).lower() if hasattr(o, "type") else "market",
                }
                for o in (orders or [])
            ]
        except Exception as e:
            logger.error("Error fetching open orders", error=str(e))
            return []

    def get_recent_orders(self, limit: int = 20) -> List[Dict]:
        """Get recently closed/filled orders from Alpaca."""
        try:
            req = GetOrdersRequest(status="closed", limit=limit)
            orders = self.client.get_orders(req)
            return [
                {
                    "id": str(o.id),
                    "symbol": o.symbol,
                    "side": getattr(o.side, "value", str(o.side)).lower(),
                    "qty": int(float(o.qty)) if o.qty else 0,
                    "status": getattr(o.status, "value", str(o.status)).lower(),
                    "filled_at": str(o.filled_at) if hasattr(o, "filled_at") and o.filled_at else None,
                    "submitted_at": str(o.submitted_at) if hasattr(o, "submitted_at") and o.submitted_at else None,
                }
                for o in (orders or [])
            ]
        except Exception as e:
            logger.error("Error fetching recent orders", error=str(e))
            return []

    def execute_order(
        self,
        ticker: str,
        decision: PortfolioDecision,
    ) -> Optional[Dict]:
        """
        Execute a trading order

        Args:
            ticker: Stock ticker symbol
            decision: Portfolio decision to execute

        Returns:
            Order information if successful, None otherwise
        """
        if decision.action == "hold" or decision.quantity == 0:
            logger.info("Skipping hold order", ticker=ticker)
            return None

        try:
            if decision.action in ["buy", "cover"]:
                side = OrderSide.BUY
            elif decision.action in ["sell", "short"]:
                side = OrderSide.SELL
            else:
                logger.warning("Unknown action", ticker=ticker, action=decision.action)
                return None

            order_data = MarketOrderRequest(
                symbol=ticker,
                qty=decision.quantity,
                side=side,
                time_in_force=TimeInForce.DAY,
            )

            order = self.client.submit_order(order_data=order_data)

            logger.info(
                "Order submitted",
                ticker=ticker,
                action=decision.action,
                quantity=decision.quantity,
                order_id=str(order.id),
            )

            return {
                "order_id": str(order.id),
                "symbol": order.symbol,
                "qty": int(order.qty),
                "side": str(order.side) if hasattr(order.side, "value") else order.side,
                "status": str(order.status) if hasattr(order.status, "value") else order.status,
            }

        except Exception as e:
            logger.error("Order execution failed", ticker=ticker, error=str(e))
            return None
    
    def execute_decisions(
        self,
        decisions: Dict[str, PortfolioDecision],
        rate_limit: int = 200,  # Alpaca limit: 200 requests/minute
    ) -> Dict[str, Optional[Dict]]:
        """
        Execute multiple trading decisions with rate limiting
        
        Args:
            decisions: Dictionary mapping ticker to PortfolioDecision
            rate_limit: Maximum requests per minute (default: 200 for Alpaca)
        
        Returns:
            Dictionary mapping ticker to order result
        """
        import time
        
        logger.info("Executing trading decisions", decision_count=len(decisions))
        
        results = {}
        non_hold_decisions = {t: d for t, d in decisions.items() if d.action != "hold" and d.quantity > 0}
        
        if not non_hold_decisions:
            logger.info("No trades to execute (all holds)")
            return results
        
        # Calculate delay between requests to respect rate limit
        # Add 10% buffer to be safe
        delay_seconds = 60.0 / (rate_limit * 0.9)  # ~0.33 seconds between requests
        
        logger.info(
            "Executing trades with rate limiting",
            trade_count=len(non_hold_decisions),
            delay_seconds=round(delay_seconds, 3),
            estimated_time_minutes=round(len(non_hold_decisions) * delay_seconds / 60, 1)
        )
        
        # Execute sells first to free cash / buying power for subsequent buys.
        priority = {"sell": 0, "short": 0, "cover": 1, "buy": 2}
        ordered = sorted(
            non_hold_decisions.items(),
            key=lambda kv: (priority.get(kv[1].action, 99), kv[0]),
        )

        executed = 0
        for i, (ticker, decision) in enumerate(ordered, 1):
            result = self.execute_order(ticker, decision)
            results[ticker] = result
            
            if result:
                executed += 1
            
            # Rate limiting: wait between requests (except for last one)
            if i < len(ordered):
                time.sleep(delay_seconds)
            
            # Log progress for large batches
            if len(ordered) > 50 and i % 50 == 0:
                logger.info(
                    "Execution progress",
                    completed=i,
                    total=len(ordered),
                    pct=round(i / len(ordered) * 100, 1)
                )
        
        logger.info(
            "Trading execution complete",
            executed_count=executed,
            total_decisions=len(decisions),
            failed_count=len(ordered) - executed
        )
        return results
    
    # ── Options methods ──────────────────────────────────────────────

    def get_option_contracts(
        self,
        underlying: str,
        option_type: str = "call",
        expiry_gte: Optional[date] = None,
        expiry_lte: Optional[date] = None,
        strike_gte: Optional[float] = None,
        strike_lte: Optional[float] = None,
        limit: int = 50,
    ) -> List[Dict]:
        """Discover available option contracts for an underlying symbol."""
        try:
            if expiry_gte is None:
                expiry_gte = date.today() + timedelta(days=7)
            if expiry_lte is None:
                expiry_lte = date.today() + timedelta(days=45)

            ct = ContractType.CALL if option_type == "call" else ContractType.PUT
            req = GetOptionContractsRequest(
                underlying_symbols=[underlying],
                type=ct,
                expiration_date_gte=expiry_gte.isoformat(),
                expiration_date_lte=expiry_lte.isoformat(),
                strike_price_gte=str(strike_gte) if strike_gte else None,
                strike_price_lte=str(strike_lte) if strike_lte else None,
                limit=limit,
            )
            resp = self.client.get_option_contracts(req)
            contracts = resp.option_contracts if hasattr(resp, "option_contracts") else resp
            results = []
            for c in (contracts or []):
                results.append({
                    "symbol": c.symbol,
                    "underlying": c.underlying_symbol,
                    "strike": float(c.strike_price) if c.strike_price else 0.0,
                    "expiry": str(c.expiration_date),
                    "type": str(c.type) if hasattr(c, "type") else option_type,
                    "open_interest": int(c.open_interest) if hasattr(c, "open_interest") and c.open_interest else 0,
                    "close_price": float(c.close_price) if hasattr(c, "close_price") and c.close_price else 0.0,
                    "tradable": getattr(c, "tradable", True),
                })
            logger.info("Option contracts fetched", underlying=underlying, count=len(results))
            return results
        except Exception as e:
            logger.error("Failed to fetch option contracts", underlying=underlying, error=str(e))
            return []

    def submit_option_order(
        self,
        contract_symbol: str,
        qty: int,
        side: str = "sell",
        order_type: str = "market",
        limit_price: Optional[float] = None,
    ) -> Optional[Dict]:
        """Submit an options order (e.g. sell-to-open for covered calls)."""
        try:
            order_side = OrderSide.SELL if side == "sell" else OrderSide.BUY

            if order_type == "limit" and limit_price is not None:
                order_data = LimitOrderRequest(
                    symbol=contract_symbol,
                    qty=qty,
                    side=order_side,
                    type=OrderType.LIMIT,
                    time_in_force=TimeInForce.DAY,
                    limit_price=limit_price,
                )
            else:
                order_data = MarketOrderRequest(
                    symbol=contract_symbol,
                    qty=qty,
                    side=order_side,
                    time_in_force=TimeInForce.DAY,
                )

            order = self.client.submit_order(order_data=order_data)
            logger.info(
                "Option order submitted",
                contract=contract_symbol,
                side=side,
                qty=qty,
                order_id=str(order.id),
            )
            return {
                "order_id": str(order.id),
                "symbol": order.symbol,
                "qty": int(order.qty) if order.qty else qty,
                "side": side,
                "status": str(order.status) if hasattr(order.status, "value") else str(order.status),
            }
        except Exception as e:
            logger.error("Option order failed", contract=contract_symbol, error=str(e))
            return None

    def get_option_positions(self) -> List[Dict]:
        """Return current option positions (contracts whose symbol length > 10)."""
        try:
            positions = self.client.get_all_positions()
            results = []
            for pos in (positions or []):
                sym = pos.symbol or ""
                if len(sym) > 10:
                    results.append({
                        "symbol": sym,
                        "qty": abs(int(float(pos.qty))),
                        "side": "short" if int(float(pos.qty)) < 0 else "long",
                        "avg_entry_price": float(pos.avg_entry_price),
                        "market_value": float(pos.market_value),
                        "underlying": sym[:4].rstrip("0123456789"),
                    })
            return results
        except Exception as e:
            logger.error("Failed to fetch option positions", error=str(e))
            return []

    def sync_portfolio(self) -> Portfolio:
        """
        Sync portfolio state from Alpaca
        
        Returns:
            Portfolio object with current state
        """
        try:
            account = self.get_account()
            positions = self.get_positions()
            
            portfolio = Portfolio(
                cash=account['cash'],
                margin_requirement=0.5,  # Default margin requirement
                margin_used=0.0,  # Calculate if needed
            )
            
            for ticker, pos_data in positions.items():
                if pos_data['side'] == 'long':
                    portfolio.positions[ticker] = Position(
                        long=pos_data['qty'],
                        short=0,
                        long_cost_basis=pos_data['avg_entry_price'],
                        short_cost_basis=0.0,
                        short_margin_used=0.0,
                    )
                elif pos_data['side'] == 'short':
                    portfolio.positions[ticker] = Position(
                        long=0,
                        short=pos_data['qty'],
                        long_cost_basis=0.0,
                        short_cost_basis=pos_data['avg_entry_price'],
                        short_margin_used=pos_data['market_value'] * 0.5,  # Estimate
                    )
            
            logger.info(
                "Portfolio synced from broker",
                cash=round(portfolio.cash, 2),
                position_count=len(portfolio.positions),
                positions={t: {"long": p.long, "short": p.short} for t, p in portfolio.positions.items()},
            )
            return portfolio
        
        except Exception as e:
            logger.error("Portfolio sync failed", error=str(e))
            raise

