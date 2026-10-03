"""Dividend drip manager.

Tracks dividend cash and manages reinvestment into growth sleeve.
"""

from datetime import datetime
from typing import Dict, List, Optional, Set
import json
from pathlib import Path
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
        self.processed_activity_ids: Set[str] = set()
        self._load_state()
        
    def _load_state(self):
        """Load state from file if it exists."""
        if not self.data_file:
            return
            
        try:
            path = Path(self.data_file)
            if not path.exists():
                return
                
            with open(path, 'r') as f:
                data = json.load(f)
                
            self.accumulated_cash = float(data.get('accumulated_cash', 0.0))
            self.dividend_history = data.get('dividend_history', [])
            self.processed_activity_ids = set(data.get('processed_activity_ids', []))
            
            logger.info(
                "Loaded drip state from file",
                accumulated_cash=self.accumulated_cash,
                history_count=len(self.dividend_history),
                processed_count=len(self.processed_activity_ids),
            )
        except Exception as e:
            logger.warning("Failed to load drip state", error=str(e))
    
    def _save_state(self):
        """Save state to file."""
        if not self.data_file:
            return
            
        try:
            path = Path(self.data_file)
            path.parent.mkdir(parents=True, exist_ok=True)
            
            data = {
                'accumulated_cash': self.accumulated_cash,
                'dividend_history': self.dividend_history,
                'processed_activity_ids': list(self.processed_activity_ids),
                'last_updated': datetime.now().isoformat(),
            }
            
            with open(path, 'w') as f:
                json.dump(data, f, indent=2)
                
            logger.info("Saved drip state to file", path=str(path))
        except Exception as e:
            logger.warning("Failed to save drip state", error=str(e))
    
    def record_dividend(
        self,
        ticker: str,
        amount: float,
        ex_date: datetime,
        payment_date: datetime,
        activity_id: Optional[str] = None,
    ):
        """
        Record a dividend payment.
        
        Args:
            ticker: Stock ticker
            amount: Dividend amount in USD
            ex_date: Ex-dividend date
            payment_date: Payment date
            activity_id: Optional activity ID to prevent duplicates
        """
        # Skip if we've already processed this activity
        if activity_id and activity_id in self.processed_activity_ids:
            logger.debug("Skipping duplicate dividend", activity_id=activity_id)
            return
        
        self.accumulated_cash += amount
        self.dividend_history.append({
            "ticker": ticker,
            "amount": amount,
            "ex_date": ex_date.isoformat(),
            "payment_date": payment_date.isoformat(),
            "timestamp": datetime.now().isoformat(),
            "activity_id": activity_id,
        })
        
        if activity_id:
            self.processed_activity_ids.add(activity_id)
        
        logger.info(
            "Recorded dividend",
            ticker=ticker,
            amount=amount,
            accumulated=self.accumulated_cash,
        )
        
        self._save_state()
        
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
        
        self._save_state()
        return actual
    
    def reset(self):
        """Reset dividend state (for testing)."""
        self.accumulated_cash = 0.0
        self.dividend_history.clear()
