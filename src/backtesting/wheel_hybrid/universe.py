"""Fixed research universe for wheel backtest (no look-ahead bias)."""

from datetime import datetime
from typing import List, Optional

# BLUECHIP UNIVERSE: Controlled 6-name set for apples-to-apples comparison.
# Used for 2000-2024 baseline; liquid/optionable back to ~2000s.
BLUECHIP_UNIVERSE: List[str] = [
    "F",      # Ford - liquid since 1900s, options since 1970s
    "T",      # AT&T - stable dividend, liquid options
    "BAC",    # Bank of America - major bank, liquid
    "INTC",   # Intel - tech blue-chip, historically ≤$50 in bear markets
    "PFE",    # Pfizer - pharma blue-chip
    "GE",     # General Electric - industrial (note: was split in 2021; data available pre-split)
]

# EXPANDED LIQUID UNIVERSE: Large opportunity set (~45 names) for broader CC selection.
# Criteria: Liquid (ADV > $50M historically), optionable, IPO ≤ 2015 for long history,
# historically priced allowing 100-share lots with $10k NAV (≤~$80-100 for diversification).
# Date-filtered in get_wheel_universe() to avoid pre-IPO look-ahead.
# Sectors: Finance, Tech, Healthcare, Consumer, Industrial, Energy, Telecom.
LIQUID_EXPANDED_UNIVERSE: List[str] = [
    # Finance (9)
    "BAC", "C", "WFC", "JPM", "GS", "MS", "USB", "PNC", "AXP",
    # Tech (12)
    "INTC", "CSCO", "ORCL", "IBM", "HPQ", "QCOM", "TXN", "AMAT", "MU", "ADI", "XLNX", "NVDA",
    # Healthcare / Pharma (8)
    "PFE", "MRK", "JNJ", "ABT", "BMY", "LLY", "AMGN", "GILD",
    # Consumer / Retail (6)
    "F", "GM", "KO", "PEP", "MCD", "WMT",
    # Industrial / Aero (4)
    "GE", "BA", "CAT", "MMM",
    # Energy (3)
    "XOM", "CVX", "COP",
    # Telecom (3)
    "T", "VZ", "TMUS",
]

# IPO dates for expanded universe filtering (for names that may not have full 2000+ history)
EXPANDED_IPO_DATES = {
    "TMUS": 2013,  # T-Mobile post-merger listing
    "NVDA": 1999,  # NVIDIA (liquid options post-2000)
    "GILD": 1992,  # Gilead (but liquid options post-2000)
    # Most others IPO'd before 1995; all should have 2000+ data
}

def get_wheel_universe(
    start_date: str,
    *,
    universe_type: str = "auto",
    custom: Optional[List[str]] = None,
) -> List[str]:
    """
    Return the appropriate fixed research universe for the backtest.
    
    Universe selection logic:
    - "bluechip": Fixed 6-name blue-chip set (F, T, BAC, INTC, PFE, GE)
    - "expanded": Large liquid universe (~45 names, date-filtered for IPOs)
    - "auto": Auto-select based on start date (≤2015 → bluechip; >2015 → expanded)
    - custom list: Override with user-provided tickers
    
    Args:
        start_date: Backtest start date (YYYY-MM-DD).
        universe_type: "bluechip", "expanded", or "auto".
        custom: Override with custom universe.
    
    Returns:
        List of ticker symbols, date-filtered to avoid pre-IPO look-ahead.
    """
    if custom:
        return custom
    
    # Parse start date
    try:
        start_year = datetime.fromisoformat(start_date).year
    except (ValueError, AttributeError):
        start_year = 2000
    
    # Explicit universe selection
    if universe_type == "bluechip":
        return BLUECHIP_UNIVERSE.copy()
    
    elif universe_type == "expanded":
        # Filter expanded universe by IPO date
        universe = LIQUID_EXPANDED_UNIVERSE.copy()
        for ticker, ipo_year in EXPANDED_IPO_DATES.items():
            if start_year < ipo_year and ticker in universe:
                universe.remove(ticker)
        return universe
    
    # Auto mode: bluechip for long history, expanded for recent
    elif universe_type == "auto":
        if start_year <= 2015:
            return BLUECHIP_UNIVERSE.copy()
        else:
            # Expanded for 2016+, date-filtered
            universe = LIQUID_EXPANDED_UNIVERSE.copy()
            for ticker, ipo_year in EXPANDED_IPO_DATES.items():
                if start_year < ipo_year and ticker in universe:
                    universe.remove(ticker)
            return universe
    
    else:
        raise ValueError(f"Unknown universe_type: {universe_type}. Use 'bluechip', 'expanded', or 'auto'.")
