"""Fixed research universe for wheel backtest (no look-ahead bias)."""

from datetime import datetime
from typing import List

# LONG-HISTORY UNIVERSE: Blue-chip / liquid names with options history back to ~2000s.
# Excludes names that IPO'd after 2015 or have extreme beta/concentration risk.
# All historically priced ≤$50 at some point, allowing affordable 100-share lots.
WHEEL_LONG_HISTORY_UNIVERSE: List[str] = [
    "F",      # Ford - liquid since 1900s, options since 1970s
    "T",      # AT&T - stable dividend, liquid options
    "BAC",    # Bank of America - major bank, liquid
    "INTC",   # Intel - tech blue-chip, historically ≤$50 in bear markets
    "PFE",    # Pfizer - pharma blue-chip
    "GE",     # General Electric - industrial (note: was split in 2021; data available pre-split)
]

# MODERN RETAIL UNIVERSE (post-2018): Liquid, volatile, ≤$35 recent names.
# Includes IPOs like SOFI (2021), NIO (2020), PLUG (regained liquidity ~2019).
# NOT suitable for long backtests due to limited history.
WHEEL_MODERN_RETAIL_UNIVERSE: List[str] = [
    "F",
    "T",
    "SOFI",   # SoFi - IPO 2021
    "NIO",    # Nio - IPO 2020 (NYSE)
    "PLUG",   # Plug Power - regained liquidity post-2019
    "VALE",   # Vale - commodities
]

# FALLBACK: Minimal set guaranteed liquid across most eras
WHEEL_FALLBACK_UNIVERSE: List[str] = [
    "F",
    "T",
    "BAC",
]


def get_wheel_universe(
    start_date: str,
    *,
    use_fallback: bool = False,
    custom: List[str] = None,
) -> List[str]:
    """
    Return the appropriate fixed research universe for the backtest.
    
    Universe selection logic:
    - Long backtests (start ≤ 2015): LONG_HISTORY (blue chips, no pre-IPO names)
    - Modern backtests (start > 2015): MODERN_RETAIL (includes SOFI/NIO/PLUG when valid)
    - Fallback: Minimal guaranteed-liquid set
    
    Args:
        start_date: Backtest start date (YYYY-MM-DD).
        use_fallback: Use fallback universe if primary has data issues.
        custom: Override with custom universe.
    
    Returns:
        List of ticker symbols.
    """
    if custom:
        return custom
    if use_fallback:
        return WHEEL_FALLBACK_UNIVERSE.copy()
    
    # Parse start date
    try:
        start_year = datetime.fromisoformat(start_date).year
    except (ValueError, AttributeError):
        # Default to long history if parse fails
        start_year = 2000
    
    # Long history for pre-2016 starts
    if start_year <= 2015:
        return WHEEL_LONG_HISTORY_UNIVERSE.copy()
    
    # Modern retail for 2016+ starts
    # But filter out stocks that didn't exist yet
    universe = WHEEL_MODERN_RETAIL_UNIVERSE.copy()
    
    # Remove SOFI if start before 2021
    if start_year < 2021 and "SOFI" in universe:
        universe.remove("SOFI")
    
    # Remove NIO if start before 2020
    if start_year < 2020 and "NIO" in universe:
        universe.remove("NIO")
    
    return universe
