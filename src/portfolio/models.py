"""Portfolio data models"""

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
        if pos is None and ticker:
            pos = (self.positions or {}).get(str(ticker).upper())
        return int(getattr(pos, "long", 0) or 0) if pos else 0
    
    def get_equity(self, current_prices: Dict[str, float]) -> float:
        """Calculate total equity (cash + market value of positions)"""
        equity = self.cash
        
        for ticker, position in self.positions.items():
            if ticker in current_prices:
                price = current_prices[ticker]
                long_value = position.long * price
                short_value = position.short * price
                equity += long_value - short_value
        
        return equity

