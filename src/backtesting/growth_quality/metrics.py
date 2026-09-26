"""Performance metrics calculation for growth/quality backtest."""

from __future__ import annotations

import math
import statistics
from typing import Dict, List, Optional, Tuple


def calculate_metrics(
    equity_curve: List[Tuple[str, float]],
    spy_curve: List[Tuple[str, float]],
    start_nav: float,
    trades: List[Dict],
) -> Dict:
    """
    Calculate comprehensive performance metrics.
    
    Args:
        equity_curve: [(date, nav), ...]
        spy_curve: [(date, spy_level), ...]
        start_nav: Initial NAV
        trades: List of trade dictionaries
    
    Returns:
        Dict of metrics (sharpe, sortino, dd, beta, alpha, etc.)
    """
    if not equity_curve or not spy_curve:
        return {}
    
    navs = [nav for _, nav in equity_curve]
    spy_levels = [level for _, level in spy_curve]
    
    # Absolute returns
    end_nav = navs[-1]
    abs_return = (end_nav / start_nav) - 1.0
    abs_return_usd = end_nav - start_nav
    
    # Annualized return
    days = len(navs)
    years = days / 252.0
    ann_return = ((end_nav / start_nav) ** (1.0 / years) - 1.0) if years > 0 else 0.0
    
    # SPY returns
    spy_start = spy_levels[0]
    spy_end = spy_levels[-1]
    spy_return = (spy_end / spy_start) - 1.0 if spy_start > 0 else 0.0
    spy_ann_return = ((spy_end / spy_start) ** (1.0 / years) - 1.0) if years > 0 and spy_start > 0 else 0.0
    
    # Excess return
    excess_return = abs_return - spy_return
    excess_return_usd = abs_return_usd - (spy_return * start_nav)
    excess_ann_return = ann_return - spy_ann_return
    
    # Daily returns
    fund_returns = []
    for i in range(1, len(navs)):
        if navs[i - 1] > 0:
            fund_returns.append((navs[i] / navs[i - 1]) - 1.0)
    
    spy_returns = []
    for i in range(1, len(spy_levels)):
        if spy_levels[i - 1] > 0:
            spy_returns.append((spy_levels[i] / spy_levels[i - 1]) - 1.0)
    
    # Sharpe (rf=0%)
    sharpe = _sharpe(fund_returns, periods_per_year=252.0)
    
    # Sortino (rf=0%)
    sortino = _sortino(fund_returns, periods_per_year=252.0)
    
    # Max drawdown
    max_dd = _max_drawdown(navs)
    
    # SPY max drawdown
    spy_max_dd = _max_drawdown(spy_levels)
    
    # Current drawdown
    peak = max(navs)
    current_dd = (navs[-1] / peak - 1.0) if peak > 0 else 0.0
    
    # Beta, correlation, alpha
    beta, corr = _beta_corr(fund_returns, spy_returns)
    alpha = _alpha(fund_returns, spy_returns, beta, periods_per_year=252.0)
    
    # Hit rate
    wins = sum(1 for r in fund_returns if r > 0)
    hit_rate = (wins / len(fund_returns)) if fund_returns else 0.0
    
    # Turnover (approximate)
    total_traded = sum(
        abs(t.get("cash_change", 0.0))
        for t in trades
        if t.get("type") in ("buy", "sell")
    )
    avg_nav = sum(navs) / len(navs) if navs else start_nav
    turnover = (total_traded / avg_nav / 2.0) if avg_nav > 0 else 0.0  # Divide by 2 for annual turnover
    
    # Trade counts
    buys = sum(1 for t in trades if t.get("type") == "buy")
    sells = sum(1 for t in trades if t.get("type") == "sell")
    
    return {
        "start_nav": round(start_nav, 2),
        "end_nav": round(end_nav, 2),
        "abs_return_pct": round(abs_return * 100.0, 2),
        "abs_return_usd": round(abs_return_usd, 2),
        "ann_return_pct": round(ann_return * 100.0, 2),
        "spy_return_pct": round(spy_return * 100.0, 2),
        "spy_ann_return_pct": round(spy_ann_return * 100.0, 2),
        "excess_return_pct": round(excess_return * 100.0, 2),
        "excess_return_usd": round(excess_return_usd, 2),
        "excess_ann_return_pct": round(excess_ann_return * 100.0, 2),
        "max_drawdown_pct": round(max_dd * 100.0, 2) if max_dd is not None else None,
        "spy_max_drawdown_pct": round(spy_max_dd * 100.0, 2) if spy_max_dd is not None else None,
        "current_drawdown_pct": round(current_dd * 100.0, 2),
        "sharpe": round(sharpe, 2) if sharpe is not None else None,
        "sortino": round(sortino, 2) if sortino is not None else None,
        "beta": round(beta, 2) if beta is not None else None,
        "correlation": round(corr, 2) if corr is not None else None,
        "alpha_annual_pct": round(alpha * 100.0, 2) if alpha is not None else None,
        "hit_rate_pct": round(hit_rate * 100.0, 1),
        "hit_sessions": wins,
        "total_sessions": len(fund_returns),
        "turnover_annual": round(turnover, 2),
        "trade_counts": {
            "buys": buys,
            "sells": sells,
        },
        "years": round(years, 2),
    }


def _sharpe(returns: List[float], periods_per_year: float = 252.0, rf: float = 0.0) -> Optional[float]:
    """Calculate annualized Sharpe ratio."""
    if len(returns) < 4:
        return None
    
    mean_ret = sum(returns) / len(returns)
    
    if len(returns) < 2:
        return None
    
    std_ret = statistics.stdev(returns)
    
    if std_ret <= 1e-12:
        return None
    
    sharpe = ((mean_ret - rf) / std_ret) * math.sqrt(periods_per_year)
    return sharpe


def _sortino(returns: List[float], periods_per_year: float = 252.0, rf: float = 0.0) -> Optional[float]:
    """Calculate annualized Sortino ratio (downside deviation)."""
    if len(returns) < 4:
        return None
    
    mean_ret = sum(returns) / len(returns)
    downside = [min(0.0, r - rf) for r in returns]
    
    if not downside:
        return None
    
    downside_var = sum(d * d for d in downside) / len(downside)
    downside_std = math.sqrt(downside_var)
    
    if downside_std <= 1e-12:
        return None
    
    sortino = ((mean_ret - rf) / downside_std) * math.sqrt(periods_per_year)
    return sortino


def _max_drawdown(navs: List[float]) -> Optional[float]:
    """Calculate maximum drawdown."""
    if len(navs) < 2:
        return None
    
    peak = navs[0]
    max_dd = 0.0
    
    for nav in navs:
        peak = max(peak, nav)
        if peak > 0:
            dd = (nav / peak) - 1.0
            max_dd = min(max_dd, dd)
    
    return max_dd


def _beta_corr(
    fund_returns: List[float],
    spy_returns: List[float],
) -> Tuple[Optional[float], Optional[float]]:
    """Calculate beta and correlation vs SPY."""
    n = min(len(fund_returns), len(spy_returns))
    
    if n < 4:
        return None, None
    
    fund = fund_returns[:n]
    spy = spy_returns[:n]
    
    mean_fund = sum(fund) / n
    mean_spy = sum(spy) / n
    
    cov = sum((f - mean_fund) * (s - mean_spy) for f, s in zip(fund, spy)) / max(1, n - 1)
    var_spy = sum((s - mean_spy) ** 2 for s in spy) / max(1, n - 1)
    var_fund = sum((f - mean_fund) ** 2 for f in fund) / max(1, n - 1)
    
    beta = (cov / var_spy) if var_spy > 1e-16 else None
    
    denom = math.sqrt(var_fund * var_spy) if var_fund > 0 and var_spy > 0 else 0.0
    corr = (cov / denom) if denom > 1e-16 else None
    
    return beta, corr


def _alpha(
    fund_returns: List[float],
    spy_returns: List[float],
    beta: Optional[float],
    periods_per_year: float = 252.0,
    rf: float = 0.0,
) -> Optional[float]:
    """Calculate annualized alpha (CAPM)."""
    if beta is None or len(fund_returns) < 4 or len(spy_returns) < 4:
        return None
    
    n = min(len(fund_returns), len(spy_returns))
    mean_fund = sum(fund_returns[:n]) / n
    mean_spy = sum(spy_returns[:n]) / n
    
    alpha_daily = mean_fund - rf - beta * (mean_spy - rf)
    alpha_annual = alpha_daily * periods_per_year
    
    return alpha_annual
