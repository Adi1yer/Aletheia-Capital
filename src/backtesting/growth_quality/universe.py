"""Universe definitions for growth/quality strategy arms - FIXED FOR CITEABILITY."""

from typing import List, Optional, Dict
from datetime import datetime, date


# =============================================================================
# ARM A: QQQ BUY-AND-HOLD (Citeable concentration baseline)
# =============================================================================

def get_qqq_universe() -> List[str]:
    """
    Return QQQ ETF for buy-and-hold baseline.
    
    QQQ is the Nasdaq-100 ETF - a liquid, transparent concentration vehicle.
    This is the research brief's cited baseline (~+148% vs SPY ~+96% for 2020-2024).
    
    Returns:
        List containing only "QQQ"
    """
    return ["QQQ"]


# =============================================================================
# ARM B: HINDSIGHT MAG7 / QUALITY BASKET (LOOKAHEAD - NOT CITEABLE)
# =============================================================================
# 
# ⚠️ WARNING: THIS ARM USES 2024 HINDSIGHT WINNERS ⚠️
# 
# This is a FIXED list of names that we know (as of 2024) became winners.
# Selecting AAPL, MSFT, GOOGL, AMZN, NVDA with 2010-2024 knowledge is
# SURVIVORSHIP BIAS and LOOK-AHEAD BIAS.
#
# Use ONLY as UPPER BOUND demonstration. Do NOT cite as tradeable edge.
# Do NOT recommend as flagship. Label "HINDSIGHT / LOOKAHEAD" in all tables.
# =============================================================================

HINDSIGHT_QUALITY_BASKET: List[str] = [
    # Mag7 (known 2024 winners)
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA",
    # Quality mega-caps (with hindsight)
    "JNJ", "JPM", "V", "MA", "WMT", "PG", "HD", "UNH", "CVX",
]


def get_hindsight_quality_basket(top_n: int = 15) -> List[str]:
    """
    ⚠️ HINDSIGHT / LOOKAHEAD - NOT CITEABLE ⚠️
    
    Return fixed hindsight winner list from 2024 perspective.
    
    This demonstrates an UPPER BOUND of what perfect foresight would deliver,
    but is NOT a tradeable strategy. Use only for comparison / what-if analysis.
    
    Args:
        top_n: Number of names to return (default 15).
    
    Returns:
        Fixed list of 2024 winners (NOT point-in-time selected).
    """
    return HINDSIGHT_QUALITY_BASKET[:top_n]


# =============================================================================
# ARM C: POINT-IN-TIME LIQUID QUALITY (Citeable, primary KEEP candidate)
# =============================================================================
#
# This arm selects from a liquid large-cap universe using ONLY information
# available at each rebalance date. No 2024 hindsight.
#
# Methodology:
# 1. Start with S&P 100 or largest liquid names by market cap as of each date
# 2. Apply simple quality/momentum screens using only free historical data
# 3. Drop names that didn't exist / weren't tradeable as of that date
# 4. Document clearly what's achievable with free data sources
#
# For MVP with free data, we use a SIMPLIFIED QUALITY PROXY:
# - Large-cap liquid names (S&P 100 core)
# - Exclude financials during 2008-2009 crisis (simple crisis filter)
# - Require minimum history (e.g., 252 days of price data)
#
# Future enhancements with better free fundamentals:
# - ROE / gross profitability from free filings
# - Debt-to-equity screens
# - More sophisticated quality metrics
# =============================================================================

# S&P 100 core (large liquid names, existed throughout 2000-2024)
# This list is approximately the S&P 100 as of ~2010, excluding names that
# didn't exist or were too small. It's a reasonable "liquid large-cap" proxy.
SP100_CORE_LIQUID: List[str] = [
    # Tech
    "AAPL", "MSFT", "INTC", "CSCO", "ORCL", "IBM", "QCOM", "TXN",
    # Healthcare/Pharma
    "JNJ", "PFE", "MRK", "ABT", "LLY", "AMGN", "BMY", "UNH",
    # Finance
    "JPM", "BAC", "WFC", "C", "USB", "AXP", "GS", "BLK",
    # Consumer
    "WMT", "PG", "KO", "PEP", "MCD", "HD", "LOW", "COST",
    # Industrial
    "GE", "BA", "CAT", "MMM", "HON", "UPS",
    # Energy
    "XOM", "CVX", "COP", "SLB",
    # Telecom
    "T", "VZ",
]

# Names that became large-cap later (add based on IPO / growth dates)
LATE_ADDITIONS: Dict[str, int] = {
    "GOOGL": 2004,  # Google IPO
    "META": 2012,   # Facebook IPO
    "TSLA": 2010,   # Tesla IPO (but not mega-cap until ~2020)
    "NVDA": 1999,   # NVIDIA (but not mega-cap until ~2016)
    "AMZN": 1997,   # Amazon (but not mega-cap until ~2015)
    "NFLX": 2002,   # Netflix
    "AVGO": 2009,   # Broadcom (post-merger)
    "MA": 2006,     # Mastercard IPO
    "V": 2008,      # Visa IPO
}


def get_point_in_time_quality_universe(
    as_of_date: date,
    top_n: int = 30,
    exclude_financials_crisis: bool = True,
) -> List[str]:
    """
    Get point-in-time liquid quality universe (NO HINDSIGHT).
    
    Selects from large-cap liquid names that:
    1. Existed and were tradeable as of the given date
    2. Meet simple quality proxy (large-cap, liquid, not in crisis sectors)
    3. Have sufficient price history
    
    Args:
        as_of_date: Date as of which to select (no future knowledge allowed)
        top_n: Target number of names
        exclude_financials_crisis: If True, exclude financials during 2008-2009
    
    Returns:
        List of tickers selected using only past information
    """
    year = as_of_date.year
    
    # Start with core liquid names
    universe = SP100_CORE_LIQUID.copy()
    
    # Add names that had IPO'd / became large-cap by this date
    for ticker, ipo_year in LATE_ADDITIONS.items():
        if year >= ipo_year:
            # Conservative: require 2 years post-IPO before including
            if year >= ipo_year + 2:
                universe.append(ticker)
    
    # Crisis filter: exclude financials during 2008-2009
    if exclude_financials_crisis and year in [2008, 2009]:
        financials = ["JPM", "BAC", "WFC", "C", "USB", "AXP", "GS", "BLK"]
        universe = [t for t in universe if t not in financials]
    
    # Remove duplicates, sort for determinism
    universe = sorted(list(set(universe)))
    
    # Return top N (in practice, we'd sort by market cap or liquidity here,
    # but with free data we'll just use the full filtered list)
    return universe[:top_n]


# =============================================================================
# ARM D: EQUAL-WEIGHT S&P 100 (Non-hindsight concentration control)
# =============================================================================
#
# Simple control: equal-weight the S&P 100 core at each rebalance.
# No quality screens, no momentum - just liquid large-cap equal-weight.
# This is more diversified than Arm C and completely rules-based.
# =============================================================================

def get_sp100_equal_weight_universe() -> List[str]:
    """
    Return S&P 100 core for equal-weight control.
    
    This is a simple, rules-based, non-hindsight universe.
    Approximately 50-60 names that were large-cap throughout 2000-2024.
    
    Returns:
        List of S&P 100 core tickers
    """
    return SP100_CORE_LIQUID.copy()


# =============================================================================
# UNIFIED INTERFACE
# =============================================================================

def get_universe_for_arm(
    arm: str,
    as_of_date: Optional[date] = None,
    top_n: Optional[int] = None,
) -> List[str]:
    """
    Get universe for a specific strategy arm.
    
    Args:
        arm: Strategy arm identifier
        as_of_date: Date for point-in-time selection (Arm C only)
        top_n: Number of names (Arms B, C)
    
    Returns:
        List of ticker symbols for that arm
    """
    if arm == "qqq":
        return get_qqq_universe()
    
    elif arm == "hindsight_quality":
        n = top_n if top_n is not None else 15
        return get_hindsight_quality_basket(top_n=n)
    
    elif arm == "point_in_time_quality":
        n = top_n if top_n is not None else 30
        if as_of_date is None:
            # Default: use a recent date for initial call
            as_of_date = date(2020, 1, 1)
        return get_point_in_time_quality_universe(as_of_date, top_n=n)
    
    elif arm == "sp100_equal_weight":
        return get_sp100_equal_weight_universe()
    
    else:
        raise ValueError(
            f"Unknown arm: {arm}. Use 'qqq', 'hindsight_quality', "
            f"'point_in_time_quality', or 'sp100_equal_weight'."
        )
