"""Portfolio ledger for growth/quality backtest - long-only equity."""

from dataclasses import dataclass
from datetime import date
from typing import Dict, List

import structlog

logger = structlog.get_logger()


@dataclass
class Position:
    """Long equity position (can be fractional shares)."""
    ticker: str
    shares: float
    cost_basis: float  # per share
    date_acquired: date


class GrowthQualityPortfolio:
    """Tracks cash and long equity positions (no options)."""
    
    def __init__(self, initial_cash: float):
        self.cash: float = initial_cash
        self.positions: List[Position] = []
        self.realized_pnl: float = 0.0
        self.trades: List[Dict] = []
    
    def add_position(
        self,
        ticker: str,
        shares: float,
        price: float,
        trade_date: date,
    ) -> bool:
        """Buy shares (fractional allowed)."""
        cost = shares * price
        if cost > self.cash:
            logger.warning("Insufficient cash", ticker=ticker, cost=cost, cash=self.cash)
            return False
        
        self.cash -= cost
        self.positions.append(Position(
            ticker=ticker,
            shares=shares,
            cost_basis=price,
            date_acquired=trade_date,
        ))
        self.trades.append({
            "date": trade_date,
            "type": "buy",
            "ticker": ticker,
            "shares": shares,
            "price": price,
            "cash_change": -cost,
        })
        logger.info("Bought position", ticker=ticker, shares=shares, price=price)
        return True
    
    def sell_position(
        self,
        ticker: str,
        shares: float,
        price: float,
        trade_date: date,
    ) -> bool:
        """Sell shares (FIFO)."""
        remaining = shares
        
        for i, pos in enumerate(self.positions):
            if pos.ticker != ticker:
                continue
            
            if remaining <= 0:
                break
            
            to_sell = min(pos.shares, remaining)
            proceeds = to_sell * price
            cost_basis_portion = to_sell * pos.cost_basis
            realized = proceeds - cost_basis_portion
            
            self.cash += proceeds
            self.realized_pnl += realized
            
            self.trades.append({
                "date": trade_date,
                "type": "sell",
                "ticker": ticker,
                "shares": to_sell,
                "price": price,
                "cost_basis": pos.cost_basis,
                "realized_pnl": realized,
                "cash_change": proceeds,
            })
            
            pos.shares -= to_sell
            remaining -= to_sell
            
            if pos.shares < 0.001:
                del self.positions[i]
            
            logger.info("Sold position", ticker=ticker, shares=to_sell, price=price, pnl=realized)
        
        if remaining > 0.001:
            logger.warning("Insufficient shares to sell", ticker=ticker, requested=shares, remaining=remaining)
            return False
        
        return True
    
    def get_holdings(self) -> Dict[str, float]:
        """Get current holdings as {ticker: total_shares}."""
        holdings = {}
        for pos in self.positions:
            holdings[pos.ticker] = holdings.get(pos.ticker, 0.0) + pos.shares
        return holdings
    
    def get_position_value(self, ticker: str, price: float) -> float:
        """Get market value of a ticker position."""
        total_shares = sum(pos.shares for pos in self.positions if pos.ticker == ticker)
        return total_shares * price
    
    def get_nav(self, prices: Dict[str, float]) -> float:
        """Calculate net asset value."""
        nav = self.cash
        
        for pos in self.positions:
            price = prices.get(pos.ticker, pos.cost_basis)
            nav += pos.shares * price
        
        return nav
    
    def rebalance_to_target_weights(
        self,
        target_weights: Dict[str, float],
        prices: Dict[str, float],
        trade_date: date,
        trading_cost_pct: float = 0.0005,  # 5 bps round-trip
    ):
        """
        Rebalance portfolio to target weights.
        
        Args:
            target_weights: {ticker: weight} where weights sum to ~1.0
            prices: {ticker: price}
            trade_date: Date of rebalance
            trading_cost_pct: Round-trip trading cost (default 0.05%)
        """
        current_nav = self.get_nav(prices)
        
        if current_nav <= 0:
            return
        
        # Calculate current holdings
        current_holdings = self.get_holdings()
        
        # Calculate target shares
        target_shares = {}
        for ticker, weight in target_weights.items():
            price = prices.get(ticker)
            if price is None or price <= 0:
                continue
            target_value = current_nav * weight
            target_shares[ticker] = target_value / price
        
        # Sell positions no longer in target
        for ticker in list(current_holdings.keys()):
            if ticker not in target_shares:
                price = prices.get(ticker)
                if price is not None and price > 0:
                    shares = current_holdings[ticker]
                    # Apply trading cost
                    net_price = price * (1.0 - trading_cost_pct)
                    self.sell_position(ticker, shares, net_price, trade_date)
        
        # Adjust positions to target
        for ticker, target in target_shares.items():
            price = prices.get(ticker)
            if price is None or price <= 0:
                continue
            
            current = current_holdings.get(ticker, 0.0)
            delta = target - current
            
            if abs(delta) < 0.001:
                continue
            
            if delta > 0:
                # Buy more
                net_price = price * (1.0 + trading_cost_pct)
                self.add_position(ticker, delta, net_price, trade_date)
            else:
                # Sell some
                net_price = price * (1.0 - trading_cost_pct)
                self.sell_position(ticker, abs(delta), net_price, trade_date)
