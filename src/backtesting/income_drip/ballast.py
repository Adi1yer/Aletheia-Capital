"""Dividend ballast selector for income drip strategy.

Selects high-quality dividend paying stocks for portfolio ballast.
"""

from datetime import datetime
from typing import Dict, List, Optional
import yfinance as yf
import structlog

logger = structlog.get_logger()


class DividendBallastSelector:
    """Selector for dividend ballast stocks."""
    
    def __init__(
        self,
        min_dividend_yield: float = 0.02,
        min_market_cap_b: float = 10.0,
        min_adv_usd: float = 20_000_000,
        max_holdings: int = 15,
    ):
        """
        Initialize dividend ballast selector.
        
        Args:
            min_dividend_yield: Minimum dividend yield (default 0.02 = 2%)
            min_market_cap_b: Minimum market cap in billions (default 10.0)
            min_adv_usd: Minimum average daily volume in USD (default 20M)
            max_holdings: Maximum number of holdings (default 15)
        """
        self.min_dividend_yield = min_dividend_yield
        self.min_market_cap_b = min_market_cap_b
        self.min_adv_usd = min_adv_usd
        self.max_holdings = max_holdings
        
    def select(
        self,
        universe: List[str],
        as_of_date: Optional[datetime] = None,
    ) -> List[str]:
        """
        Select dividend ballast stocks from universe.
        
        Args:
            universe: List of tickers to screen
            as_of_date: Selection date (default: today)
            
        Returns:
            List of selected tickers (up to max_holdings)
        """
        if not as_of_date:
            as_of_date = datetime.now()
            
        logger.info(
            "Running dividend ballast selection",
            universe_size=len(universe),
            min_yield=self.min_dividend_yield,
            max_holdings=self.max_holdings,
        )
        
        candidates: Dict[str, float] = {}
        
        for ticker in universe:
            try:
                stock = yf.Ticker(ticker)
                info = stock.info
                
                # Check market cap
                market_cap = info.get("marketCap", 0)
                if market_cap < self.min_market_cap_b * 1e9:
                    continue
                
                # Check dividend yield
                dividend_yield = info.get("dividendYield", 0)
                if dividend_yield < self.min_dividend_yield:
                    continue
                
                # Check liquidity
                avg_volume = info.get("averageVolume", 0)
                current_price = info.get("currentPrice", info.get("regularMarketPrice", 0))
                adv_usd = avg_volume * current_price
                
                if adv_usd < self.min_adv_usd:
                    continue
                
                # Store with yield as score
                candidates[ticker] = dividend_yield
                
            except Exception as e:
                logger.debug(
                    "Failed to evaluate dividend candidate",
                    ticker=ticker,
                    error=str(e),
                )
                continue
        
        # Sort by dividend yield and take top holdings
        sorted_candidates = sorted(
            candidates.items(),
            key=lambda x: x[1],
            reverse=True,
        )[:self.max_holdings]
        
        selected = [t[0] for t in sorted_candidates]
        
        logger.info(
            "Dividend ballast selection complete",
            candidates=len(candidates),
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
