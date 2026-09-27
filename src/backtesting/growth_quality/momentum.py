"""Arm C style 12-1 momentum selector for growth sleeve.

Ranks liquid US equities by trailing 12-month return excluding most recent month.
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set
import yfinance as yf
import pandas as pd
import structlog

logger = structlog.get_logger()


class MomentumSelector:
    """12-1 momentum selector (Arm C style)."""
    
    def __init__(
        self,
        lookback_months: int = 12,
        skip_months: int = 1,
        top_n: int = 30,
        min_market_cap_b: float = 5.0,
        min_adv_usd: float = 10_000_000,
    ):
        """
        Initialize momentum selector.
        
        Args:
            lookback_months: Total lookback period (default 12)
            skip_months: Recent months to skip (default 1)
            top_n: Number of top momentum stocks to select (default 30)
            min_market_cap_b: Minimum market cap in billions (default 5.0)
            min_adv_usd: Minimum average daily volume in USD (default 10M)
        """
        self.lookback_months = lookback_months
        self.skip_months = skip_months
        self.top_n = top_n
        self.min_market_cap_b = min_market_cap_b
        self.min_adv_usd = min_adv_usd
        
    def select(
        self,
        universe: List[str],
        as_of_date: Optional[datetime] = None,
    ) -> List[str]:
        """
        Select top momentum stocks from universe.
        
        Args:
            universe: List of tickers to screen
            as_of_date: Selection date (default: today)
            
        Returns:
            List of selected tickers (up to top_n)
        """
        if not as_of_date:
            as_of_date = datetime.now()
            
        logger.info(
            "Running momentum selection",
            universe_size=len(universe),
            lookback_months=self.lookback_months,
            skip_months=self.skip_months,
            top_n=self.top_n,
        )
        
        # Calculate date range for momentum
        end_date = as_of_date - timedelta(days=self.skip_months * 30)
        start_date = end_date - timedelta(days=self.lookback_months * 30)
        
        momentum_scores: Dict[str, float] = {}
        valid_tickers: Set[str] = set()
        
        for ticker in universe:
            try:
                stock = yf.Ticker(ticker)
                
                # Get market cap
                info = stock.info
                market_cap = info.get("marketCap", 0)
                if market_cap < self.min_market_cap_b * 1e9:
                    continue
                    
                # Get historical data for momentum calculation
                hist = stock.history(
                    start=start_date.strftime("%Y-%m-%d"),
                    end=end_date.strftime("%Y-%m-%d"),
                )
                
                if hist.empty or len(hist) < 20:
                    continue
                    
                # Calculate momentum (total return over period)
                start_price = hist["Close"].iloc[0]
                end_price = hist["Close"].iloc[-1]
                momentum = (end_price - start_price) / start_price
                
                # Check average daily volume
                avg_volume = hist["Volume"].mean()
                avg_price = hist["Close"].mean()
                adv_usd = avg_volume * avg_price
                
                if adv_usd < self.min_adv_usd:
                    continue
                
                momentum_scores[ticker] = momentum
                valid_tickers.add(ticker)
                
            except Exception as e:
                logger.debug("Failed to calculate momentum", ticker=ticker, error=str(e))
                continue
        
        # Sort by momentum and take top N
        sorted_tickers = sorted(
            momentum_scores.items(),
            key=lambda x: x[1],
            reverse=True,
        )[:self.top_n]
        
        selected = [t[0] for t in sorted_tickers]
        
        logger.info(
            "Momentum selection complete",
            valid_tickers=len(valid_tickers),
            selected=len(selected),
        )
        
        return selected
    
    def get_weights(self, tickers: List[str]) -> Dict[str, float]:
        """
        Calculate equal weights for selected tickers.
        
        Args:
            tickers: List of selected tickers
            
        Returns:
            Dictionary mapping ticker to weight (equal weight)
        """
        if not tickers:
            return {}
        
        weight = 1.0 / len(tickers)
        return {ticker: weight for ticker in tickers}
