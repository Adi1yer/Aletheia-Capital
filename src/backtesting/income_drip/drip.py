"""Dividend drip manager.

Tracks dividend cash and manages reinvestment into growth sleeve.
"""

from datetime import datetime
from typing import Dict, List, Optional
import structlog

logger = structlog.get_logger()


class DividendDripManager:
    """Manager for dividend accumulation and drip reinvestment."""
    
    def __init__(self, data_file: Optional[str] = None):
        """
        Initialize dividend drip manager.
        
        Args:
            data_file: Optional path to persist dividend state
        """
        self.data_file = data_file
        self.accumulated_cash: float = 0.0
        self.dividend_history: List[Dict] = []
        
    def record_dividend(
        self,
        ticker: str,
        amount: float,
        ex_date: datetime,
        payment_date: datetime,
    ):
        """
        Record a dividend payment.
        
        Args:
            ticker: Stock ticker
            amount: Dividend amount in USD
            ex_date: Ex-dividend date
            payment_date: Payment date
        """
        self.accumulated_cash += amount
        self.dividend_history.append({
            "ticker": ticker,
            "amount": amount,
            "ex_date": ex_date.isoformat(),
            "payment_date": payment_date.isoformat(),
            "timestamp": datetime.now().isoformat(),
        })
        
        logger.info(
            "Recorded dividend",
            ticker=ticker,
            amount=amount,
            accumulated=self.accumulated_cash,
        )
        
    def get_drip_amount(self) -> float:
        """
        Get accumulated dividend cash available for drip.
        
        Returns:
            Accumulated dividend cash in USD
        """
        return self.accumulated_cash
    
    def execute_drip(self, amount: float) -> float:
        """
        Execute drip reinvestment, reducing accumulated cash.
        
        Args:
            amount: Amount to reinvest (capped at accumulated cash)
            
        Returns:
            Actual amount reinvested
        """
        actual = min(amount, self.accumulated_cash)
        self.accumulated_cash -= actual
        
        logger.info(
            "Executed dividend drip",
            requested=amount,
            actual=actual,
            remaining=self.accumulated_cash,
        )
        
        return actual
    
    def reset(self):
        """Reset dividend state (for testing)."""
        self.accumulated_cash = 0.0
        self.dividend_history.clear()
