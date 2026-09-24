"""Portfolio data models"""

import math
from typing import Dict, Optional
from pydantic import BaseModel


class Position(BaseModel):
    """Individual position in a stock"""
    long: int = 0
    short: int = 0
    long_cost_basis: float = 0.0
    short_cost_basis: float = 0.0
    short_margin_used: float = 0.0


class Portfolio(BaseModel):
    """Portfolio state"""
    cash: float = 0.0
    margin_requirement: float = 0.5
    margin_used: float = 0.0
    positions: Dict[str, Position] = {}
    realized_gains: Dict[str, Dict[str, float]] = {}
    
    def get_position(self, ticker: str) -> Position:
        """Get position for a ticker, creating if doesn't exist"""
        if ticker not in self.positions:
            self.positions[ticker] = Position()
        return self.positions[ticker]

    def long_qty(self, ticker: str) -> int:
        """Read long shares without creating an empty position."""
        pos = (self.positions or {}).get(ticker)
        key = str(ticker or "").upper()
        if pos is None and key:
            pos = (self.positions or {}).get(key)
        if pos is None and key:
            for k, p in (self.positions or {}).items():
                if str(k).upper() == key:
                    pos = p
                    break
        return int(getattr(pos, "long", 0) or 0) if pos else 0
    
    def get_equity(self, current_prices: Dict[str, float]) -> float:
        """Calculate total equity (cash + market value of positions)"""
        equity = float(self.cash or 0)
        if not math.isfinite(equity):
            equity = 0.0
        prices = {}
        for k, v in (current_prices or {}).items():
            try:
                px = float(v)
            except (TypeError, ValueError):
                continue
            if math.isfinite(px) and px > 0:
                prices[str(k).upper()] = px
        
        for ticker, position in self.positions.items():
            price = prices.get(str(ticker).upper())
            if price is None:
                continue
            equity += position.long * price - position.short * price
        
        return equity if math.isfinite(equity) else 0.0

