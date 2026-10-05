"""Email formatting for growth-income-drip daily snapshots."""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple


def _f(x: Any, default: float = 0.0) -> float:
    """Convert to finite float."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(v):
        return default
    return v


def _pct_label(value: Any, digits: int = 1) -> str:
    """Format percentage with n/a for invalid values."""
    v = _f(value, default=float("nan"))
    if not math.isfinite(v):
        return "n/a"
    return f"{v:.{digits}f}%"


def _signed_pct(value: Optional[float]) -> str:
    """Format signed percentage with +/- prefix."""
    if value is None or not math.isfinite(_f(value, default=float("nan"))):
        return "n/a"
    return f"{float(value):+.2f}%"


def build_drip_daily_email(
    *,
    nav: float,
    cash: float,
    positions: Dict[str, Dict],
    last_rebalance: Optional[str] = None,
    rebalance_due: bool = False,
    growth_nav: Optional[float] = None,
    ballast_nav: Optional[float] = None,
    spy_since_start_pct: Optional[float] = None,
    excess_return_pct: Optional[float] = None,
    track_return_pct: Optional[float] = None,
    track_id: str = "growth-income-drip-v1",
    start_date: str = "2026-09-27",
    start_nav: float = 10000.0,
    dividend_cash: Optional[float] = None,
    drip_buys: Optional[List[Dict]] = None,
    residual_buys: Optional[List[Dict]] = None,
) -> Tuple[str, str]:
    """
    Build enhanced daily snapshot email for drip track.
    
    Args:
        nav: Current NAV (Alpaca equity)
        cash: Current cash balance
        positions: Dictionary of positions with qty and market_value
        last_rebalance: Date of last rebalance
        rebalance_due: Whether quarterly rebalance is due
        growth_nav: Growth sleeve market value
        ballast_nav: Ballast sleeve market value
        spy_since_start_pct: SPY return since track start
        excess_return_pct: Track return minus SPY return
        track_return_pct: Track return since start
        track_id: Track identifier
        start_date: Track start date
        start_nav: Track starting NAV
        dividend_cash: Accumulated dividend cash for drip
        drip_buys: List of dividend drip buy trades executed
        residual_buys: List of residual cash deployment buy trades executed
        
    Returns:
        Tuple of (subject, body_text)
    """
    # Calculate metrics
    cash_pct = (cash / nav * 100.0) if nav > 0 else 0.0
    
    # Calculate invested dollars and percent
    stock_market_value = sum(
        _f(pos.get("market_value", 0))
        for pos in positions.values()
    )
    invested_dollars = stock_market_value
    invested_pct = (invested_dollars / nav * 100.0) if nav > 0 else 0.0
    
    # Growth vs ballast breakdown
    growth_mv = _f(growth_nav, 0.0) if growth_nav is not None else 0.0
    ballast_mv = _f(ballast_nav, 0.0) if ballast_nav is not None else 0.0
    growth_pct = (growth_mv / nav * 100.0) if nav > 0 else 0.0
    ballast_pct = (ballast_mv / nav * 100.0) if nav > 0 else 0.0
    
    # Top holdings (sorted by market value)
    sorted_positions = sorted(
        positions.items(),
        key=lambda x: _f(x[1].get("market_value", 0)),
        reverse=True
    )
    top_holdings = sorted_positions[:10]  # Top 10 holdings
    
    # Build subject line
    if spy_since_start_pct is not None and excess_return_pct is not None:
        subject = (
            f"[{track_id}] Daily Snapshot — "
            f"NAV ${nav:,.2f} "
            f"(SPY {_signed_pct(spy_since_start_pct)} / "
            f"excess {_signed_pct(excess_return_pct)})"
        )
    else:
        subject = f"[{track_id}] Daily Snapshot — NAV ${nav:,.2f}"
    
    # Build email body
    lines = []
    lines.append(f"GROWTH-INCOME-DRIP DAILY SNAPSHOT")
    lines.append("=" * 72)
    lines.append("")
    
    # Track performance summary
    lines.append("TRACK PERFORMANCE")
    lines.append("-" * 40)
    lines.append(f"  Track: {track_id}")
    lines.append(f"  Start: {start_date} at ${start_nav:,.2f}")
    lines.append(f"  Current NAV: ${nav:,.2f}")
    if track_return_pct is not None:
        lines.append(f"  Track return: {_signed_pct(track_return_pct)}")
    if spy_since_start_pct is not None:
        lines.append(f"  SPY since start: {_signed_pct(spy_since_start_pct)}")
    if excess_return_pct is not None:
        lines.append(f"  Excess return: {_signed_pct(excess_return_pct)}")
    lines.append("")
    
    # Portfolio allocation
    lines.append("PORTFOLIO ALLOCATION")
    lines.append("-" * 40)
    lines.append(f"  NAV: ${nav:,.2f}")
    lines.append(f"  Cash: ${cash:,.2f} ({cash_pct:.1f}%)")
    lines.append(f"  Invested: ${invested_dollars:,.2f} ({invested_pct:.1f}%)")
    lines.append("")
    
    # Sleeve breakdown
    lines.append("SLEEVE BREAKDOWN")
    lines.append("-" * 40)
    if growth_mv > 0 or ballast_mv > 0:
        lines.append(f"  Growth sleeve: ${growth_mv:,.2f} ({growth_pct:.1f}% / target 80%)")
        lines.append(f"  Dividend ballast: ${ballast_mv:,.2f} ({ballast_pct:.1f}% / target 20%)")
    else:
        lines.append("  (sleeve breakdown unavailable)")
    lines.append(f"  Total positions: {len(positions)}")
    lines.append("")
    
    # Top holdings
    lines.append("TOP HOLDINGS")
    lines.append("-" * 40)
    if top_holdings:
        for ticker, pos in top_holdings:
            qty = int(pos.get("qty", 0))
            mv = _f(pos.get("market_value", 0))
            pct_of_nav = (mv / nav * 100.0) if nav > 0 else 0.0
            lines.append(f"  {ticker}: {qty} shares, MV ${mv:,.2f} ({pct_of_nav:.1f}%)")
    else:
        lines.append("  (no positions)")
    lines.append("")
    
    # Rebalance status
    lines.append("REBALANCE STATUS")
    lines.append("-" * 40)
    lines.append(f"  Quarterly rebalance due: {'Yes' if rebalance_due else 'No'}")
    lines.append(f"  Last rebalance: {last_rebalance or 'Never'}")
    lines.append("")
    
    # Dividend drip status
    if dividend_cash is not None or (drip_buys and len(drip_buys) > 0):
        lines.append("DIVIDEND DRIP")
        lines.append("-" * 40)
        if dividend_cash is not None:
            lines.append(f"  Accumulated dividend cash: ${dividend_cash:,.2f}")
        if drip_buys and len(drip_buys) > 0:
            lines.append(f"  Drip buys executed: {len(drip_buys)}")
            for buy in drip_buys[:5]:  # Show first 5
                ticker = buy.get("ticker", "?")
                shares = buy.get("shares", 0)
                amount = _f(buy.get("drip_amount", 0))
                lines.append(f"    {ticker}: {shares} shares @ ${amount:,.2f}")
            if len(drip_buys) > 5:
                lines.append(f"    ... and {len(drip_buys) - 5} more")
        else:
            lines.append("  No drip trades executed today")
        lines.append("")
    
    # Residual cash deployment
    if residual_buys and len(residual_buys) > 0:
        lines.append("RESIDUAL CASH DEPLOYMENT")
        lines.append("-" * 40)
        lines.append(f"  Buys executed: {len(residual_buys)}")
        total_deployed = sum(_f(buy.get("allocated_usd", 0)) for buy in residual_buys)
        lines.append(f"  Total deployed: ${total_deployed:,.2f}")
        for buy in residual_buys[:5]:  # Show first 5
            ticker = buy.get("ticker", "?")
            shares = buy.get("shares", 0)
            amount = _f(buy.get("allocated_usd", 0))
            lines.append(f"    {ticker}: {shares} shares @ ${amount:,.2f}")
        if len(residual_buys) > 5:
            lines.append(f"    ... and {len(residual_buys) - 5} more")
        lines.append("")
    
    # Footer
    lines.append("-" * 72)
    total_trades = (len(drip_buys) if drip_buys else 0) + (len(residual_buys) if residual_buys else 0)
    if total_trades > 0:
        trade_types = []
        if drip_buys and len(drip_buys) > 0:
            trade_types.append(f"{len(drip_buys)} dividend drip")
        if residual_buys and len(residual_buys) > 0:
            trade_types.append(f"{len(residual_buys)} residual cash deployment")
        lines.append(f"Trades executed: {', '.join(trade_types)}.")
    else:
        lines.append("This is an automated daily snapshot. No trades executed.")
    lines.append(f"Track: {track_id} | Strategy: 80% growth momentum, 20% dividend ballast")
    
    body = "\n".join(lines)
    return subject, body
