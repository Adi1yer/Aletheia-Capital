"""Universe definitions for growth/quality strategy arms."""

from typing import List, Optional
from datetime import datetime


# QQQ proxy: simplified liquid Nasdaq-100 constituents
# Note: This is a representative set of liquid Nasdaq-100 names with long histories.
# For a true QQQ backtest, Arm A simply holds the QQQ ETF itself.
QQQ_PROXY_CONSTITUENTS: List[str] = [
    # Mag 7 / Tech giants
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA",
    # Other liquid Nasdaq-100 names
    "INTC", "CSCO", "ORCL", "QCOM", "TXN", "AMAT", "MU", "ADI",
    "NFLX", "ADBE", "CRM", "AVGO", "AMD",
    "AMGN", "GILD", "ISRG", "VRTX",
    "COST", "SBUX", "PEP", "MDLZ",
]


# Large-cap liquid universe for quality screening
# S&P 500 blue-chips with long histories and high liquidity
LIQUID_LARGE_CAP_UNIVERSE: List[str] = [
    # Mag 7
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA",
    # Tech
    "INTC", "CSCO", "ORCL", "QCOM", "TXN", "AMAT", "MU", "ADI", "IBM",
    "NFLX", "ADBE", "CRM", "AVGO", "AMD", "PYPL",
    # Healthcare
    "JNJ", "PFE", "MRK", "ABT", "TMO", "LLY", "AMGN", "GILD", "BMY",
    # Finance
    "JPM", "BAC", "WFC", "C", "GS", "MS", "BLK", "AXP", "USB",
    # Consumer
    "WMT", "HD", "MCD", "NKE", "COST", "SBUX", "TGT", "LOW",
    # Industrial
    "BA", "CAT", "GE", "MMM", "HON", "UPS", "LMT", "RTX",
    # Energy
    "XOM", "CVX", "COP", "SLB",
    # Telecom
    "T", "VZ",
    # Pharma
    "UNH", "CVS", "CI",
]


# Equal-weight quality mega-cap names (simplified Arm B)
# Top liquid mega/quality names that are Alpaca-tradable
EQUAL_WEIGHT_QUALITY_NAMES: List[str] = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "JNJ",
    "JPM", "V", "MA", "WMT", "PG",
    "NVDA", "HD", "UNH", "CVX", "COST",
]


def get_qqq_constituents() -> List[str]:
    """
    Return QQQ (Nasdaq-100) proxy constituents.
    
    For Arm A, the backtest will actually hold QQQ ETF itself,
    not these constituents. This list is provided for reference.
    
    Returns:
        List of representative Nasdaq-100 ticker symbols.
    """
    return QQQ_PROXY_CONSTITUENTS.copy()


def get_equal_weight_quality_names(top_n: int = 15) -> List[str]:
    """
    Return equal-weight quality mega-cap names (Arm B).
    
    This is a simplified equal-weight basket of the top liquid
    quality/growth names. Universe is fixed (no look-ahead).
    
    Args:
        top_n: Number of names to return (default 15).
    
    Returns:
        List of ticker symbols.
    """
    return EQUAL_WEIGHT_QUALITY_NAMES[:top_n]


def get_quality_screened_universe(
    start_date: Optional[str] = None,
    top_n: int = 30,
) -> List[str]:
    """
    Return quality-screened large-cap universe (Arm C).
    
    This is a simplified quality screen on liquid large-caps.
    In production, this would filter by fundamentals (ROE, profitability,
    leverage). For this MVP with free data, we return a fixed list
    of known high-quality names with long histories.
    
    TODO: Add dynamic quality screening using free fundamentals
    (e.g., Yahoo Finance info, SEC EDGAR, or FMP free tier).
    
    Args:
        start_date: Backtest start date (for IPO filtering, optional).
        top_n: Number of names to return (default 30).
    
    Returns:
        List of ticker symbols.
    """
    # Simplified: return a subset of liquid large-caps
    # that are generally considered "quality" (profitable, low leverage)
    quality_subset = [
        "AAPL", "MSFT", "GOOGL", "AMZN", "JNJ", "JPM", "V", "MA",
        "WMT", "PG", "NVDA", "HD", "UNH", "CVX", "COST", "ABT",
        "TMO", "LLY", "ORCL", "CSCO", "AVGO", "TXN", "BLK",
        "AMGN", "HON", "LOW", "MCD", "NKE", "QCOM", "SBUX",
    ]
    
    return quality_subset[:top_n]


def get_universe_for_arm(arm: str) -> List[str]:
    """
    Get universe for a specific strategy arm.
    
    Args:
        arm: Strategy arm identifier ("qqq", "equal_weight", "quality_screen").
    
    Returns:
        List of ticker symbols for that arm.
    """
    if arm == "qqq":
        # For QQQ arm, we'll actually hold the QQQ ETF
        return ["QQQ"]
    elif arm == "equal_weight":
        return get_equal_weight_quality_names(top_n=15)
    elif arm == "quality_screen":
        return get_quality_screened_universe(top_n=30)
    else:
        raise ValueError(f"Unknown arm: {arm}. Use 'qqq', 'equal_weight', or 'quality_screen'.")
