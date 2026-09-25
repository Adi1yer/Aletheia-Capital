"""Portfolio ledger for wheel hybrid backtest."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional

import structlog

logger = structlog.get_logger()


@dataclass
class EquityLot:
    """100-share lot for covered calls."""
    ticker: str
    shares: int
    cost_basis: float  # per share
    date_acquired: date


@dataclass
class ShortOption:
    """Short call or put position."""
    ticker: str
    option_type: str  # "call" or "put"
    strike: float
    expiry: date
    quantity: int  # number of contracts
    premium_collected: float  # total premium (quantity × 100 × per-share premium)
    date_opened: date
    cost_basis_per_share: float  # for BTC tracking


@dataclass
class DirectionalPosition:
    """Directional sleeve position (can be fractional shares)."""
    ticker: str
    shares: float
    cost_basis: float  # per share
    date_acquired: date


class WheelPortfolio:
    """Tracks cash, equity lots, short options, and directional positions."""
    
    def __init__(self, initial_cash: float):
        self.cash: float = initial_cash
        self.equity_lots: List[EquityLot] = []
        self.short_calls: List[ShortOption] = []
        self.short_puts: List[ShortOption] = []
        self.directional: List[DirectionalPosition] = []
        
        # Ledger
        self.premium_collected_total: float = 0.0
        self.realized_pnl: float = 0.0
        self.trades: List[Dict] = []
        
        # Track reserved cash for CSP collateral (not available for other uses)
        self.reserved_cash: float = 0.0
    
    def add_equity_lot(
        self,
        ticker: str,
        shares: int,
        price: float,
        trade_date: date,
    ):
        """Buy a 100-share lot for covered calls."""
        cost = shares * price
        if cost > self.cash:
            logger.warning("Insufficient cash for lot", ticker=ticker, cost=cost, cash=self.cash)
            return False
        
        self.cash -= cost
        self.equity_lots.append(EquityLot(
            ticker=ticker,
            shares=shares,
            cost_basis=price,
            date_acquired=trade_date,
        ))
        self.trades.append({
            "date": trade_date,
            "type": "buy_lot",
            "ticker": ticker,
            "shares": shares,
            "price": price,
            "cash_change": -cost,
        })
        logger.info("Bought equity lot", ticker=ticker, shares=shares, price=price)
        return True
    
    def sell_equity_lot(
        self,
        ticker: str,
        shares: int,
        price: float,
        trade_date: date,
    ):
        """Sell a 100-share lot (e.g., call assignment)."""
        # Find and remove lot (FIFO)
        for i, lot in enumerate(self.equity_lots):
            if lot.ticker == ticker and lot.shares == shares:
                proceeds = shares * price
                self.cash += proceeds
                realized = proceeds - (lot.shares * lot.cost_basis)
                self.realized_pnl += realized
                
                self.trades.append({
                    "date": trade_date,
                    "type": "sell_lot",
                    "ticker": ticker,
                    "shares": shares,
                    "price": price,
                    "cost_basis": lot.cost_basis,
                    "realized_pnl": realized,
                    "cash_change": proceeds,
                })
                
                del self.equity_lots[i]
                logger.info("Sold equity lot", ticker=ticker, shares=shares, price=price, pnl=realized)
                return True
        
        logger.warning("No lot found to sell", ticker=ticker, shares=shares)
        return False
    
    def write_covered_call(
        self,
        ticker: str,
        strike: float,
        expiry: date,
        premium_per_share: float,
        trade_date: date,
    ):
        """Write one covered call (1 contract = 100 shares)."""
        # Verify we have at least one 100-share lot
        has_lot = any(lot.ticker == ticker and lot.shares >= 100 for lot in self.equity_lots)
        if not has_lot:
            logger.warning("No lot to cover call", ticker=ticker)
            return False
        
        premium_total = premium_per_share * 100
        self.cash += premium_total
        self.premium_collected_total += premium_total
        
        self.short_calls.append(ShortOption(
            ticker=ticker,
            option_type="call",
            strike=strike,
            expiry=expiry,
            quantity=1,
            premium_collected=premium_total,
            date_opened=trade_date,
            cost_basis_per_share=premium_per_share,
        ))
        
        self.trades.append({
            "date": trade_date,
            "type": "write_cc",
            "ticker": ticker,
            "strike": strike,
            "expiry": expiry,
            "premium": premium_total,
            "cash_change": premium_total,
        })
        
        logger.info("Wrote covered call", ticker=ticker, strike=strike, expiry=expiry, premium=premium_total)
        return True
    
    def write_cash_secured_put(
        self,
        ticker: str,
        strike: float,
        expiry: date,
        premium_per_share: float,
        trade_date: date,
    ):
        """Write one cash-secured put (1 contract = 100 shares)."""
        collateral_needed = strike * 100
        
        # Check AVAILABLE cash (total cash - already reserved)
        available_cash = self.cash - self.reserved_cash
        if collateral_needed > available_cash:
            logger.warning(
                "Insufficient available cash for CSP collateral",
                ticker=ticker,
                collateral=collateral_needed,
                available_cash=available_cash,
                total_cash=self.cash,
                reserved=self.reserved_cash
            )
            return False
        
        premium_total = premium_per_share * 100
        self.cash += premium_total
        self.premium_collected_total += premium_total
        
        # ACTUALLY reserve the collateral
        self.reserved_cash += collateral_needed
        
        self.short_puts.append(ShortOption(
            ticker=ticker,
            option_type="put",
            strike=strike,
            expiry=expiry,
            quantity=1,
            premium_collected=premium_total,
            date_opened=trade_date,
            cost_basis_per_share=premium_per_share,
        ))
        
        self.trades.append({
            "date": trade_date,
            "type": "write_csp",
            "ticker": ticker,
            "strike": strike,
            "expiry": expiry,
            "premium": premium_total,
            "collateral": collateral_needed,
            "cash_change": premium_total,
        })
        
        logger.info("Wrote CSP", ticker=ticker, strike=strike, expiry=expiry, premium=premium_total, reserved=collateral_needed)
        return True
    
    def buy_to_close_call(
        self,
        ticker: str,
        strike: float,
        expiry: date,
        close_price_per_share: float,
        trade_date: date,
    ):
        """Buy to close a short call."""
        for i, call in enumerate(self.short_calls):
            if call.ticker == ticker and call.strike == strike and call.expiry == expiry:
                cost = close_price_per_share * 100
                if cost > self.cash:
                    logger.warning("Insufficient cash for BTC", ticker=ticker, cost=cost, cash=self.cash)
                    return False
                
                self.cash -= cost
                realized = call.premium_collected - cost
                self.realized_pnl += realized
                
                self.trades.append({
                    "date": trade_date,
                    "type": "btc_call",
                    "ticker": ticker,
                    "strike": strike,
                    "expiry": expiry,
                    "close_price": close_price_per_share * 100,
                    "premium_collected": call.premium_collected,
                    "realized_pnl": realized,
                    "cash_change": -cost,
                })
                
                del self.short_calls[i]
                logger.info("BTC call", ticker=ticker, strike=strike, pnl=realized)
                return True
        
        logger.warning("No matching call to close", ticker=ticker, strike=strike, expiry=expiry)
        return False
    
    def buy_to_close_put(
        self,
        ticker: str,
        strike: float,
        expiry: date,
        close_price_per_share: float,
        trade_date: date,
    ):
        """Buy to close a short put."""
        for i, put in enumerate(self.short_puts):
            if put.ticker == ticker and put.strike == strike and put.expiry == expiry:
                cost = close_price_per_share * 100
                if cost > self.cash:
                    logger.warning("Insufficient cash for BTC", ticker=ticker, cost=cost, cash=self.cash)
                    return False
                
                # Release reserved collateral
                collateral_released = put.strike * 100 * put.quantity
                self.reserved_cash = max(0.0, self.reserved_cash - collateral_released)
                
                self.cash -= cost
                realized = put.premium_collected - cost
                self.realized_pnl += realized
                
                self.trades.append({
                    "date": trade_date,
                    "type": "btc_put",
                    "ticker": ticker,
                    "strike": strike,
                    "expiry": expiry,
                    "close_price": close_price_per_share * 100,
                    "premium_collected": put.premium_collected,
                    "realized_pnl": realized,
                    "cash_change": -cost,
                })
                
                del self.short_puts[i]
                logger.info("BTC put", ticker=ticker, strike=strike, pnl=realized, collateral_released=collateral_released)
                return True
        
        logger.warning("No matching put to close", ticker=ticker, strike=strike, expiry=expiry)
        return False
    
    def assign_call(
        self,
        ticker: str,
        strike: float,
        expiry: date,
        trade_date: date,
    ):
        """Handle call assignment: sell lot at strike, close call at intrinsic."""
        for i, call in enumerate(self.short_calls):
            if call.ticker == ticker and call.strike == strike and call.expiry == expiry:
                # Sell the lot at strike price
                success = self.sell_equity_lot(ticker, 100, strike, trade_date)
                if success:
                    # Close the call at intrinsic value (already paid via lot sale)
                    del self.short_calls[i]
                    self.trades.append({
                        "date": trade_date,
                        "type": "assign_call",
                        "ticker": ticker,
                        "strike": strike,
                        "expiry": expiry,
                    })
                    logger.info("Call assigned", ticker=ticker, strike=strike)
                return success
        return False
    
    def assign_put(
        self,
        ticker: str,
        strike: float,
        expiry: date,
        trade_date: date,
    ):
        """Handle put assignment: buy 100 shares at strike, close put."""
        for i, put in enumerate(self.short_puts):
            if put.ticker == ticker and put.strike == strike and put.expiry == expiry:
                cost = strike * 100
                
                # Release reserved collateral FIRST (we're about to use it)
                collateral_released = put.strike * 100 * put.quantity
                self.reserved_cash = max(0.0, self.reserved_cash - collateral_released)
                
                if cost > self.cash:
                    logger.error(
                        "Insufficient cash for put assignment - FORCE EXPIRE",
                        ticker=ticker,
                        cost=cost,
                        cash=self.cash,
                        collateral_was=collateral_released
                    )
                    # Force-close the put at intrinsic to prevent orphan
                    intrinsic = max(0.0, strike - 0.01) * 100  # Assume stock near strike
                    realized = put.premium_collected - intrinsic
                    self.realized_pnl += realized
                    del self.short_puts[i]
                    self.trades.append({
                        "date": trade_date,
                        "type": "force_expire_put",
                        "ticker": ticker,
                        "strike": strike,
                        "expiry": expiry,
                        "realized_pnl": realized,
                        "reason": "insufficient_cash_for_assignment",
                    })
                    return False
                
                # Buy 100 shares at strike
                self.cash -= cost
                self.equity_lots.append(EquityLot(
                    ticker=ticker,
                    shares=100,
                    cost_basis=strike,
                    date_acquired=trade_date,
                ))
                
                # Close the put
                del self.short_puts[i]
                
                self.trades.append({
                    "date": trade_date,
                    "type": "assign_put",
                    "ticker": ticker,
                    "strike": strike,
                    "expiry": expiry,
                    "cost": cost,
                    "cash_change": -cost,
                })
                
                logger.info("Put assigned", ticker=ticker, strike=strike, collateral_released=collateral_released)
                return True
        return False
    
    def expire_call(
        self,
        ticker: str,
        strike: float,
        expiry: date,
        trade_date: date,
    ):
        """Expire a call OTM (keep premium, no assignment)."""
        for i, call in enumerate(self.short_calls):
            if call.ticker == ticker and call.strike == strike and call.expiry == expiry:
                realized = call.premium_collected
                self.realized_pnl += realized
                
                self.trades.append({
                    "date": trade_date,
                    "type": "expire_call",
                    "ticker": ticker,
                    "strike": strike,
                    "expiry": expiry,
                    "realized_pnl": realized,
                })
                
                del self.short_calls[i]
                logger.info("Call expired OTM", ticker=ticker, strike=strike)
                return True
        return False
    
    def expire_put(
        self,
        ticker: str,
        strike: float,
        expiry: date,
        trade_date: date,
    ):
        """Expire a put OTM (keep premium, no assignment)."""
        for i, put in enumerate(self.short_puts):
            if put.ticker == ticker and put.strike == strike and put.expiry == expiry:
                # Release reserved collateral
                collateral_released = put.strike * 100 * put.quantity
                self.reserved_cash = max(0.0, self.reserved_cash - collateral_released)
                
                realized = put.premium_collected
                self.realized_pnl += realized
                
                self.trades.append({
                    "date": trade_date,
                    "type": "expire_put",
                    "ticker": ticker,
                    "strike": strike,
                    "expiry": expiry,
                    "realized_pnl": realized,
                })
                
                del self.short_puts[i]
                logger.info("Put expired OTM", ticker=ticker, strike=strike, collateral_released=collateral_released)
                return True
        return False
    
    def add_directional_position(
        self,
        ticker: str,
        shares: float,
        price: float,
        trade_date: date,
    ):
        """Buy directional position (fractional shares allowed)."""
        cost = shares * price
        if cost > self.cash:
            logger.warning("Insufficient cash for directional", ticker=ticker, cost=cost, cash=self.cash)
            return False
        
        self.cash -= cost
        self.directional.append(DirectionalPosition(
            ticker=ticker,
            shares=shares,
            cost_basis=price,
            date_acquired=trade_date,
        ))
        
        self.trades.append({
            "date": trade_date,
            "type": "buy_directional",
            "ticker": ticker,
            "shares": shares,
            "price": price,
            "cash_change": -cost,
        })
        
        logger.info("Bought directional", ticker=ticker, shares=shares, price=price)
        return True
    
    def sell_directional_position(
        self,
        ticker: str,
        shares: float,
        price: float,
        trade_date: date,
    ):
        """Sell directional position."""
        # Find and remove position (FIFO)
        for i, pos in enumerate(self.directional):
            if pos.ticker == ticker and pos.shares >= shares:
                proceeds = shares * price
                cost_basis_portion = shares * pos.cost_basis
                realized = proceeds - cost_basis_portion
                
                self.cash += proceeds
                self.realized_pnl += realized
                
                self.trades.append({
                    "date": trade_date,
                    "type": "sell_directional",
                    "ticker": ticker,
                    "shares": shares,
                    "price": price,
                    "cost_basis": pos.cost_basis,
                    "realized_pnl": realized,
                    "cash_change": proceeds,
                })
                
                # Update or remove position
                pos.shares -= shares
                if pos.shares < 0.01:
                    del self.directional[i]
                
                logger.info("Sold directional", ticker=ticker, shares=shares, price=price, pnl=realized)
                return True
        
        logger.warning("No directional position to sell", ticker=ticker, shares=shares)
        return False
    
    def get_nav(
        self,
        prices: Dict[str, float],
        option_marks: Dict[str, Dict[str, float]],
    ) -> float:
        """
        Calculate net asset value.
        
        Args:
            prices: {ticker: current_price}
            option_marks: {ticker: {"call_strike_expiry": mark, ...}}
        
        Returns:
            Total NAV (cash + equity + options).
        """
        nav = self.cash
        
        # Equity lots
        for lot in self.equity_lots:
            price = prices.get(lot.ticker, lot.cost_basis)
            nav += lot.shares * price
        
        # Directional positions
        for pos in self.directional:
            price = prices.get(pos.ticker, pos.cost_basis)
            nav += pos.shares * price
        
        # Short options (negative value)
        for call in self.short_calls:
            key = f"call_{call.strike}_{call.expiry}"
            mark = option_marks.get(call.ticker, {}).get(key, 0.0)
            nav -= mark * 100 * call.quantity
        
        for put in self.short_puts:
            key = f"put_{put.strike}_{put.expiry}"
            mark = option_marks.get(put.ticker, {}).get(key, 0.0)
            nav -= mark * 100 * put.quantity
        
        return nav
    
    def get_csp_collateral(self) -> float:
        """Calculate total collateral reserved for CSPs."""
        return sum(put.strike * 100 * put.quantity for put in self.short_puts)
    
    def get_wheel_market_value(self, prices: Dict[str, float]) -> float:
        """Market value of wheel equity lots."""
        mv = 0.0
        for lot in self.equity_lots:
            price = prices.get(lot.ticker, lot.cost_basis)
            mv += lot.shares * price
        return mv
    
    def get_directional_market_value(self, prices: Dict[str, float]) -> float:
        """Market value of directional positions."""
        mv = 0.0
        for pos in self.directional:
            price = prices.get(pos.ticker, pos.cost_basis)
            mv += pos.shares * price
        return mv
