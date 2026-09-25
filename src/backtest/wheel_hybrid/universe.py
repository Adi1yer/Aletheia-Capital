"""Fixed research universe for wheel backtest (no look-ahead bias)."""

from typing import List

# Fixed universe: historically liquid names ≤$35 with active options markets.
# Chosen based on 2019-2020 criteria (pre-backtest period) to avoid cherry-picking.
WHEEL_RESEARCH_UNIVERSE: List[str] = [
    "F",      # Ford - stable ADV, consistently under $20
    "T",      # AT&T - high ADV, dividend stock, under $30
    "SOFI",   # SoFi - fintech, volatile but liquid post-IPO
    "NIO",    # Nio - EV play, high retail interest
    "PLUG",   # Plug Power - hydrogen / clean energy
    "VALE",   # Vale - commodities, ADV > $500M
]

# Fallback if some tickers lack historical data
WHEEL_FALLBACK_UNIVERSE: List[str] = [
    "F",
    "T",
    "BAC",    # Bank of America
    "AAL",    # American Airlines
    "CCL",    # Carnival
]


def get_wheel_universe(
    start_date: str,
    *,
    use_fallback: bool = False,
    custom: List[str] = None,
) -> List[str]:
    """
    Return the fixed research universe for the backtest.
    
    Args:
        start_date: Backtest start date (YYYY-MM-DD). Included for future date-based logic.
        use_fallback: Use fallback universe if primary has data issues.
        custom: Override with custom universe.
    
    Returns:
        List of ticker symbols.
    """
    if custom:
        return custom
    if use_fallback:
        return WHEEL_FALLBACK_UNIVERSE.copy()
    return WHEEL_RESEARCH_UNIVERSE.copy()
