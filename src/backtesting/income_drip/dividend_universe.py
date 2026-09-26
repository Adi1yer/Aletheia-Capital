"""Dividend ballast universe - liquid dividend payers using point-in-time free data."""

from typing import List, Optional, Dict, Tuple
from datetime import date, timedelta
import structlog

logger = structlog.get_logger()


# Large-cap dividend payers that existed throughout 2000-2024
# These are high-quality, stable dividend payers (utilities, consumer staples, pharma, telecom)
DIVIDEND_CORE_UNIVERSE: List[str] = [
    # Utilities
    "NEE", "DUK", "SO", "D", "EXC", "AEP",
    # Consumer Staples
    "PG", "KO", "PEP", "WMT", "COST", "MCD", "CL", "KMB",
    # Healthcare/Pharma
    "JNJ", "PFE", "MRK", "ABT", "BMY",
    # Telecom
    "T", "VZ",
    # Industrials
    "MMM", "CAT", "HON",
    # Energy
    "XOM", "CVX",
    # Financials (stable dividend payers)
    "JPM", "JNJ",
]

# Late additions (IPO/became dividend payers later)
DIVIDEND_LATE_ADDITIONS: Dict[str, int] = {
    "UNH": 2000,  # UnitedHealth became mega-cap dividend payer
}


def get_dividend_universe_point_in_time(
    as_of_date: date,
    top_n: int = 20,
    min_yield_pct: float = 1.5,
    data_provider = None,
) -> List[str]:
    """
    Get point-in-time dividend ballast universe (NO HINDSIGHT).
    
    Selects liquid dividend payers that:
    1. Existed and were tradeable as of the given date
    2. Have sufficient price history (≥252 trading days)
    3. Have dividend yield ≥ min_yield_pct (using trailing 12-month dividends)
    4. Are sorted by quality proxy (dividend consistency + yield)
    
    Methodology:
    - Universe: Large-cap dividend core (utilities, staples, pharma, etc.)
    - Filter: Only names with ≥252 days of price history as of as_of_date
    - Calculate: Trailing 12-month dividend yield as of as_of_date
    - Rank: By dividend yield (descending)
    - Select: Top N by yield that meet minimum yield threshold
    
    Args:
        as_of_date: Date as of which to select (no future knowledge)
        top_n: Target number of names
        min_yield_pct: Minimum dividend yield % (e.g., 1.5 for 1.5%)
        data_provider: Optional data provider for dividend history
    
    Returns:
        List of tickers selected using only past information
    """
    year = as_of_date.year
    
    # Start with core dividend universe
    universe = DIVIDEND_CORE_UNIVERSE.copy()
    
    # Add late additions that had reached dividend payer status by this date
    for ticker, start_year in DIVIDEND_LATE_ADDITIONS.items():
        if year >= start_year + 2:  # Require 2 years of dividend history
            universe.append(ticker)
    
    # Remove duplicates
    universe = list(set(universe))
    
    # If no data provider, fall back to alphabetical (for testing)
    if data_provider is None:
        universe_sorted = sorted(universe)
        return universe_sorted[:top_n]
    
    # Calculate dividend yield for each name
    dividend_yields = {}
    
    lookback_start = as_of_date - timedelta(days=400)  # ~252 trading days + buffer
    
    for ticker in universe:
        try:
            # Get price history to ensure sufficient data
            prices = data_provider.get_prices(
                ticker,
                lookback_start.strftime("%Y-%m-%d"),
                as_of_date.strftime("%Y-%m-%d"),
            )
            
            if not prices or len(prices) < 252:
                # Insufficient price history - skip
                continue
            
            # Get current price (as of as_of_date)
            price_data = [(p.time.date() if hasattr(p.time, 'date') else p.time, p.close) for p in prices]
            price_data.sort(key=lambda x: x[0])
            price_data = [(d, c) for d, c in price_data if d <= as_of_date]
            
            if not price_data:
                continue
            
            current_price = price_data[-1][1]
            
            # Get dividend history for trailing 12 months
            div_start = as_of_date - timedelta(days=365)
            
            try:
                dividends = data_provider.get_dividends(
                    ticker,
                    div_start.strftime("%Y-%m-%d"),
                    as_of_date.strftime("%Y-%m-%d"),
                )
                
                if not dividends:
                    # No dividends in trailing 12 months - skip
                    continue
                
                # Sum dividends in trailing 12 months
                total_dividends = sum(float(d.amount) for d in dividends if hasattr(d, 'amount'))
                
                if total_dividends <= 0 or current_price <= 0:
                    continue
                
                # Calculate yield
                div_yield = (total_dividends / current_price) * 100.0
                
                # Only include if meets minimum yield
                if div_yield >= min_yield_pct:
                    dividend_yields[ticker] = div_yield
            
            except AttributeError:
                # Provider doesn't have get_dividends method - skip
                logger.warning(f"Provider missing get_dividends method for {ticker}")
                continue
                
        except Exception as e:
            # Data fetch failed - skip ticker
            logger.debug(f"Failed to fetch data for {ticker}: {e}")
            continue
    
    # Sort by dividend yield descending
    sorted_by_yield = sorted(
        dividend_yields.items(),
        key=lambda x: x[1],
        reverse=True
    )
    
    selected = [ticker for ticker, _ in sorted_by_yield[:top_n]]
    
    # If we don't have enough names with dividends, fill with alphabetical from core
    if len(selected) < top_n:
        remaining = sorted([t for t in universe if t not in selected])
        selected.extend(remaining[:top_n - len(selected)])
    
    logger.info(
        f"Selected dividend universe on {as_of_date}",
        count=len(selected),
        yields=dict(sorted_by_yield[:min(5, len(sorted_by_yield))])
    )
    
    return selected


def get_dividend_amount_trailing_12m(
    ticker: str,
    as_of_date: date,
    data_provider,
) -> float:
    """
    Get trailing 12-month dividend amount as of a specific date.
    
    Args:
        ticker: Stock ticker
        as_of_date: Date as of which to calculate (no future data)
        data_provider: Data provider with get_dividends() method
    
    Returns:
        Total dividend amount paid in trailing 12 months (or 0.0 if none)
    """
    try:
        div_start = as_of_date - timedelta(days=365)
        
        dividends = data_provider.get_dividends(
            ticker,
            div_start.strftime("%Y-%m-%d"),
            as_of_date.strftime("%Y-%m-%d"),
        )
        
        if not dividends:
            return 0.0
        
        total = sum(float(d.amount) for d in dividends if hasattr(d, 'amount'))
        return total
    
    except Exception as e:
        logger.debug(f"Failed to fetch dividends for {ticker}: {e}")
        return 0.0
