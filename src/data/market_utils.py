"""Shared market math helpers (no agent imports)."""

from typing import Any, List, Optional


def compute_return_vs_index(ticker_prices, index_prices) -> Optional[float]:
    if not ticker_prices or not index_prices or len(ticker_prices) < 2 or len(index_prices) < 2:
        return None
    t_ret = (ticker_prices[-1].close - ticker_prices[0].close) / ticker_prices[0].close * 100
    i_ret = (index_prices[-1].close - index_prices[0].close) / index_prices[0].close * 100
    return round(t_ret - i_ret, 2)
