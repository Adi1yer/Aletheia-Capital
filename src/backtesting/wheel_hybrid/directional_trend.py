"""
Trend/momentum overlay for directional sleeve.

Implements free trend-following and dual-momentum strategies to improve
directional sleeve performance. No paid IV data required.

References:
- 200-day SMA trend filter (classic trend-following)
- Dual momentum (Antonacci-style): absolute + relative strength
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional, Tuple

import structlog

logger = structlog.get_logger()


@dataclass
class TrendConfig:
    """Configuration for trend/momentum overlay."""
    
    # SMA trend filter
    enabled: bool = True
    sma_window: int = 200  # 200-day SMA for trend filter
    
    # Dual momentum
    use_dual_momentum: bool = True
    momentum_lookback: int = 126  # ~6 months (21 days * 6)
    relative_strength_universe: List[str] = None  # For relative momentum
    
    # Cash/defensive position when trend is bearish
    cash_when_bearish: bool = True  # Go to cash when below SMA200
    
    def __post_init__(self):
        if self.relative_strength_universe is None:
            # Default universe for relative strength comparison
            self.relative_strength_universe = ["SPY", "QQQ", "IWM", "EFA", "TLT"]


class DirectionalTrendOverlay:
    """
    Trend/momentum overlay for directional sleeve.
    
    Applies classic trend-following (SMA200) and/or dual momentum to
    the directional sleeve only. Wheel sleeve remains always-on.
    """
    
    def __init__(self, config: TrendConfig):
        self.config = config
        
        # Stats tracking
        self.days_risk_on = 0
        self.days_risk_off = 0
        self.trend_signals: List[Dict] = []
    
    def should_hold_directional(
        self,
        ticker: str,
        current_price: float,
        price_history: List[float],
        trade_date: date,
    ) -> Tuple[bool, str]:
        """
        Determine if directional position should be held.
        
        Args:
            ticker: The ticker symbol
            current_price: Current price
            price_history: List of historical prices (most recent last)
            trade_date: Current date
        
        Returns:
            (should_hold, reason) tuple
        """
        if not self.config.enabled:
            return True, "trend_overlay_disabled"
        
        # Check SMA200 trend filter
        if len(price_history) >= self.config.sma_window:
            sma200 = sum(price_history[-self.config.sma_window:]) / self.config.sma_window
            
            if current_price < sma200:
                # Bearish: price below SMA200
                if self.config.cash_when_bearish:
                    self.trend_signals.append({
                        "date": trade_date,
                        "ticker": ticker,
                        "signal": "sell",
                        "reason": "below_sma200",
                        "price": current_price,
                        "sma200": sma200,
                    })
                    return False, "below_sma200"
            else:
                # Bullish: price above SMA200
                self.trend_signals.append({
                    "date": trade_date,
                    "ticker": ticker,
                    "signal": "hold",
                    "reason": "above_sma200",
                    "price": current_price,
                    "sma200": sma200,
                })
                return True, "above_sma200"
        
        # Not enough history for trend filter - hold by default
        return True, "insufficient_history"
    
    def rank_directional_candidates(
        self,
        candidates: List[str],
        prices: Dict[str, float],
        price_histories: Dict[str, List[float]],
        trade_date: date,
    ) -> List[Tuple[str, float, str]]:
        """
        Rank directional candidates by trend/momentum.
        
        Args:
            candidates: List of candidate tickers
            prices: Current prices {ticker: price}
            price_histories: Historical prices {ticker: [prices]}
            trade_date: Current date
        
        Returns:
            List of (ticker, score, reason) sorted by score descending
        """
        if not self.config.enabled:
            # No overlay - return all with neutral score
            return [(t, 0.0, "no_filter") for t in candidates]
        
        scored = []
        
        for ticker in candidates:
            price = prices.get(ticker)
            history = price_histories.get(ticker, [])
            
            if price is None or not history:
                continue
            
            score = 0.0
            reasons = []
            
            # 1. SMA200 trend filter
            if len(history) >= self.config.sma_window:
                sma200 = sum(history[-self.config.sma_window:]) / self.config.sma_window
                
                if price > sma200:
                    # Bullish trend
                    trend_strength = (price - sma200) / sma200
                    score += trend_strength * 100  # Scale to percentage
                    reasons.append(f"above_sma200_{trend_strength*100:.1f}%")
                else:
                    # Bearish trend - negative score
                    trend_strength = (price - sma200) / sma200
                    score += trend_strength * 100
                    reasons.append(f"below_sma200_{abs(trend_strength)*100:.1f}%")
            
            # 2. Momentum (absolute)
            if self.config.use_dual_momentum and len(history) >= self.config.momentum_lookback:
                # Calculate momentum as return over lookback period
                old_price = history[-self.config.momentum_lookback]
                momentum_return = (price - old_price) / old_price
                score += momentum_return * 100  # Scale to percentage
                reasons.append(f"momentum_{momentum_return*100:.1f}%")
            
            reason_str = "|".join(reasons) if reasons else "no_signals"
            scored.append((ticker, score, reason_str))
        
        # Sort by score descending (best momentum/trend first)
        scored.sort(key=lambda x: x[1], reverse=True)
        
        return scored
    
    def filter_directional_universe(
        self,
        universe: List[str],
        prices: Dict[str, float],
        price_histories: Dict[str, List[float]],
        trade_date: date,
    ) -> List[str]:
        """
        Filter universe to only include tickers in bullish trend.
        
        Args:
            universe: Full universe
            prices: Current prices
            price_histories: Historical prices
            trade_date: Current date
        
        Returns:
            Filtered list of tickers in bullish trend
        """
        if not self.config.enabled:
            return universe
        
        filtered = []
        
        for ticker in universe:
            price = prices.get(ticker)
            history = price_histories.get(ticker, [])
            
            if price is None or not history:
                continue
            
            should_hold, reason = self.should_hold_directional(
                ticker, price, history, trade_date
            )
            
            if should_hold:
                filtered.append(ticker)
        
        return filtered
    
    def get_stats(self) -> Dict:
        """Get statistics for the trend overlay."""
        total_days = self.days_risk_on + self.days_risk_off
        
        return {
            "days_risk_on": self.days_risk_on,
            "days_risk_off": self.days_risk_off,
            "total_days": total_days,
            "risk_on_pct": (self.days_risk_on / total_days * 100) if total_days > 0 else 0,
            "signal_count": len(self.trend_signals),
            "config": {
                "enabled": self.config.enabled,
                "sma_window": self.config.sma_window,
                "use_dual_momentum": self.config.use_dual_momentum,
                "momentum_lookback": self.config.momentum_lookback,
                "cash_when_bearish": self.config.cash_when_bearish,
            },
        }
    
    def update_regime(self, is_risk_on: bool):
        """Update daily regime tracking."""
        if is_risk_on:
            self.days_risk_on += 1
        else:
            self.days_risk_off += 1


def calculate_relative_strength(
    ticker: str,
    price_history: List[float],
    benchmark_histories: Dict[str, List[float]],
    lookback: int,
) -> float:
    """
    Calculate relative strength vs benchmark universe (Antonacci-style).
    
    Args:
        ticker: Ticker to evaluate
        price_history: Price history for ticker
        benchmark_histories: Price histories for benchmark universe
        lookback: Lookback period in days
    
    Returns:
        Relative strength score (positive = outperforming)
    """
    if len(price_history) < lookback:
        return 0.0
    
    # Calculate ticker momentum
    ticker_return = (price_history[-1] - price_history[-lookback]) / price_history[-lookback]
    
    # Calculate average benchmark momentum
    benchmark_returns = []
    for bench_history in benchmark_histories.values():
        if len(bench_history) >= lookback:
            bench_return = (bench_history[-1] - bench_history[-lookback]) / bench_history[-lookback]
            benchmark_returns.append(bench_return)
    
    if not benchmark_returns:
        return 0.0
    
    avg_benchmark_return = sum(benchmark_returns) / len(benchmark_returns)
    
    # Relative strength = ticker return - avg benchmark return
    return ticker_return - avg_benchmark_return
