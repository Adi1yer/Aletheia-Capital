"""IBKR sleeve helpers: momentum signals and ledger."""

from __future__ import annotations

from typing import Dict, List

import yfinance as yf


def momentum_pct(symbol: str, yahoo_ticker: str, months: int = 3) -> float:
    hist = yf.Ticker(yahoo_ticker).history(period=f"{months}mo")
    if hist is None or len(hist) < 5:
        return 0.0
    return float((hist["Close"].iloc[-1] - hist["Close"].iloc[0]) / hist["Close"].iloc[0] * 100)


def rank_by_momentum(pairs: List[tuple], months: int = 3) -> List[Dict]:
    out = []
    for sym, yahoo in pairs:
        out.append({"symbol": sym, "yahoo": yahoo, "mom_pct": momentum_pct(sym, yahoo, months)})
    return sorted(out, key=lambda x: x["mom_pct"], reverse=True)
