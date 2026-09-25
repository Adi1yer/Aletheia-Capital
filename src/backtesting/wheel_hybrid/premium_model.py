"""Synthetic option premium model using Black-Scholes and realized volatility."""

from __future__ import annotations

import math
from datetime import date, timedelta
from typing import List, Optional, Tuple

import structlog

logger = structlog.get_logger()


def _norm_cdf(x: float) -> float:
    """Cumulative distribution function for standard normal (approximation)."""
    # Abramowitz and Stegun approximation
    t = 1.0 / (1.0 + 0.2316419 * abs(x))
    d = 0.3989423 * math.exp(-x * x / 2.0)
    prob = d * t * (0.3193815 + t * (-0.3565638 + t * (1.781478 + t * (-1.821256 + t * 1.330274))))
    return 1.0 - prob if x >= 0 else prob


def black_scholes_call(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
) -> float:
    """
    Black-Scholes European call option price.
    
    Args:
        S: Underlying price
        K: Strike price
        T: Time to expiration (years)
        r: Risk-free rate (annual)
        sigma: Volatility (annual)
    
    Returns:
        Call option price.
    """
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return max(0.0, S - K)
    
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    
    call_price = S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)
    return max(0.0, call_price)


def black_scholes_put(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
) -> float:
    """
    Black-Scholes European put option price.
    
    Args:
        S: Underlying price
        K: Strike price
        T: Time to expiration (years)
        r: Risk-free rate (annual)
        sigma: Volatility (annual)
    
    Returns:
        Put option price.
    """
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return max(0.0, K - S)
    
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    
    put_price = K * math.exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1)
    return max(0.0, put_price)


def realized_volatility(
    prices: List[float],
    window: int = 21,
) -> Optional[float]:
    """
    Calculate annualized realized volatility from daily returns.
    
    Args:
        prices: List of daily closing prices (most recent last).
        window: Lookback window in trading days.
    
    Returns:
        Annualized volatility (sigma) or None if insufficient data.
    """
    if len(prices) < window + 1:
        return None
    
    tail = prices[-window - 1:]
    returns = [math.log(tail[i] / tail[i - 1]) for i in range(1, len(tail)) if tail[i] > 0 and tail[i - 1] > 0]
    
    if len(returns) < 5:
        return None
    
    mean_ret = sum(returns) / len(returns)
    variance = sum((r - mean_ret) ** 2 for r in returns) / max(1, len(returns) - 1)
    daily_vol = math.sqrt(variance)
    
    # Annualize: sqrt(252)
    annual_vol = daily_vol * math.sqrt(252.0)
    
    # Floor at 10%, cap at 200% (reasonable bounds)
    return max(0.10, min(2.0, annual_vol))


def select_call_strike(
    underlying_price: float,
    otm_pct_low: float = 0.03,
    otm_pct_high: float = 0.08,
    target_otm_pct: float = 0.05,
) -> float:
    """
    Select covered call strike based on OTM percentage target.
    
    Args:
        underlying_price: Current stock price.
        otm_pct_low: Minimum OTM percentage (3%).
        otm_pct_high: Maximum OTM percentage (8%).
        target_otm_pct: Target OTM percentage (5%).
    
    Returns:
        Strike price rounded to nearest $0.50 or $1.00 increment.
    """
    target_strike = underlying_price * (1.0 + target_otm_pct)
    
    # Round to standard option strikes ($0.50 increments below $25, $1 above)
    if target_strike < 25:
        strike = round(target_strike * 2) / 2.0
    else:
        strike = round(target_strike)
    
    # Ensure within bounds
    min_strike = underlying_price * (1.0 + otm_pct_low)
    max_strike = underlying_price * (1.0 + otm_pct_high)
    
    return max(min_strike, min(max_strike, strike))


def select_put_strike(
    underlying_price: float,
    csp_score: int = 50,
    otm_pct_range: Tuple[float, float] = (0.02, 0.10),
) -> float:
    """
    Select cash-secured put strike based on score and OTM range.
    
    Args:
        underlying_price: Current stock price.
        csp_score: Strategy score (0-100); higher = more bullish → closer to ATM.
        otm_pct_range: (min_otm, max_otm) as fractions.
    
    Returns:
        Strike price rounded to standard increments.
    """
    min_otm, max_otm = otm_pct_range
    
    # Higher score → lower OTM (closer to ATM, more premium)
    # Score 55+ → 2-5% OTM; Score <55 → 5-10% OTM
    if csp_score >= 55:
        otm_pct = 0.02 + (0.03 * (1.0 - min(100, csp_score) / 100.0))
    else:
        otm_pct = 0.05 + (0.05 * (1.0 - csp_score / 55.0))
    
    otm_pct = max(min_otm, min(max_otm, otm_pct))
    
    target_strike = underlying_price * (1.0 - otm_pct)
    
    # Round to standard strikes
    if target_strike < 25:
        strike = round(target_strike * 2) / 2.0
    else:
        strike = round(target_strike)
    
    return strike


def estimate_call_premium(
    underlying_price: float,
    strike: float,
    dte: int,
    realized_vol: float,
    rf_rate: float = 0.0,
) -> float:
    """
    Estimate covered call premium using Black-Scholes.
    
    Args:
        underlying_price: Current stock price.
        strike: Call strike.
        dte: Days to expiration.
        realized_vol: Annualized realized volatility.
        rf_rate: Risk-free rate (annual).
    
    Returns:
        Estimated premium per share (multiply by 100 for contract value).
    """
    T = dte / 365.0
    premium = black_scholes_call(underlying_price, strike, T, rf_rate, realized_vol)
    return premium


def estimate_put_premium(
    underlying_price: float,
    strike: float,
    dte: int,
    realized_vol: float,
    rf_rate: float = 0.0,
) -> float:
    """
    Estimate cash-secured put premium using Black-Scholes.
    
    Args:
        underlying_price: Current stock price.
        strike: Put strike.
        dte: Days to expiration.
        realized_vol: Annualized realized volatility.
        rf_rate: Risk-free rate (annual).
    
    Returns:
        Estimated premium per share (multiply by 100 for contract value).
    """
    T = dte / 365.0
    premium = black_scholes_put(underlying_price, strike, T, rf_rate, realized_vol)
    return premium


def check_assignment_call(
    underlying_price: float,
    strike: float,
) -> bool:
    """
    Determine if a short call would be assigned at expiration.
    
    Simple heuristic: assigned if underlying closes above strike.
    
    Args:
        underlying_price: Stock price at expiration.
        strike: Call strike.
    
    Returns:
        True if assigned, False if expires OTM.
    """
    return underlying_price > strike


def check_assignment_put(
    underlying_price: float,
    strike: float,
) -> bool:
    """
    Determine if a short put would be assigned at expiration.
    
    Simple heuristic: assigned if underlying closes below strike.
    
    Args:
        underlying_price: Stock price at expiration.
        strike: Put strike.
    
    Returns:
        True if assigned, False if expires OTM.
    """
    return underlying_price < strike


def estimate_option_mark(
    option_type: str,
    underlying_price: float,
    strike: float,
    dte: int,
    realized_vol: float,
    rf_rate: float = 0.0,
) -> float:
    """
    Estimate current mark-to-market value of an option position.
    
    Args:
        option_type: "call" or "put".
        underlying_price: Current stock price.
        strike: Option strike.
        dte: Days to expiration.
        realized_vol: Current realized volatility estimate.
        rf_rate: Risk-free rate.
    
    Returns:
        Estimated option value per share.
    """
    if dte <= 0:
        if option_type == "call":
            return max(0.0, underlying_price - strike)
        else:
            return max(0.0, strike - underlying_price)
    
    if option_type == "call":
        return estimate_call_premium(underlying_price, strike, dte, realized_vol, rf_rate)
    else:
        return estimate_put_premium(underlying_price, strike, dte, realized_vol, rf_rate)
