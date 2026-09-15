"""70% wheel / 30% directional capital allocator for wheel-10k."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Set

import structlog

from src.options.wheel_universe import WheelCandidate
from src.portfolio.manager import PortfolioDecision
from src.portfolio.models import Portfolio

logger = structlog.get_logger()

CC_LOT = 100


def allocate_wheel_hybrid_book(
    *,
    portfolio: Portfolio,
    current_prices: Dict[str, float],
    wheel_candidates: Sequence[WheelCandidate],
    directional_candidates: Sequence[str],
    equity: Optional[float] = None,
    wheel_pct: float = 0.70,
    directional_pct: float = 0.30,
    cash_buffer_pct: float = 0.06,
    max_wheel_names: int = 4,
    max_directional_names: int = 5,
    max_underlying_price: float = 35.0,
    pending_orders_by_symbol: Optional[Dict[str, Dict[str, Any]]] = None,
    short_option_underlyings: Optional[Set[str]] = None,
) -> tuple[Dict[str, PortfolioDecision], Dict[str, Any]]:
    """
    Build equity decisions for the hybrid book.

    - Wheel sleeve: bring/keep 100-share lots on cheap liquid names (CC fuel).
    - Directional sleeve: smaller long-only positions (not forced to 100 shares).
    - CSP entries are selected separately (tickers list); collateral reserved in diagnostics.
    """
    eq = float(equity if equity is not None else 0.0)
    if eq <= 0 and hasattr(portfolio, "get_equity"):
        try:
            eq = float(portfolio.get_equity(current_prices) or 0.0)
        except Exception:
            eq = 0.0
    if eq <= 0:
        eq = float(getattr(portfolio, "cash", 0) or 0)
    cash = float(getattr(portfolio, "cash", 0) or 0)
    pending = pending_orders_by_symbol or {}
    short_und = {str(x).upper() for x in (short_option_underlyings or set())}

    wheel_budget = eq * float(wheel_pct)
    dir_budget = eq * float(directional_pct)
    buffer_cash = eq * float(cash_buffer_pct)

    diagnostics: Dict[str, Any] = {
        "wheel_mode": True,
        "equity": round(eq, 2),
        "wheel_budget": round(wheel_budget, 2),
        "directional_budget": round(dir_budget, 2),
        "cash_buffer": round(buffer_cash, 2),
        "wheel_targets": [],
        "directional_targets": [],
        "csp_candidates": [],
        "cc_lot_tickers": [],
        "skipped": [],
    }

    def held_qty(t: str) -> int:
        pos = portfolio.get_position(t) if hasattr(portfolio, "get_position") else None
        if pos is None:
            pos = (portfolio.positions or {}).get(t)
        if not pos:
            return 0
        return int(getattr(pos, "long", 0) or 0)

    decisions: Dict[str, PortfolioDecision] = {}

    # Existing wheel lots (100+ shares, price still in band) keep priority.
    existing_wheel: List[str] = []
    for t, pos in list((portfolio.positions or {}).items()):
        qty = int(getattr(pos, "long", 0) or 0)
        px = float(current_prices.get(t) or 0.0)
        if qty >= CC_LOT and 0 < px <= float(max_underlying_price):
            existing_wheel.append(t)

    ranked_new = [c.ticker for c in wheel_candidates if c.ticker not in existing_wheel]
    wheel_targets: List[str] = []
    for t in existing_wheel + ranked_new:
        if t in wheel_targets:
            continue
        wheel_targets.append(t)
        if len(wheel_targets) >= int(max_wheel_names):
            break
    diagnostics["wheel_targets"] = list(wheel_targets)

    wheel_spent = 0.0
    for t in existing_wheel:
        px = float(current_prices.get(t) or 0.0)
        qty = held_qty(t)
        wheel_spent += qty * px

    # Top up / open 100-share lots within wheel budget (leave room for CSP collateral).
    csp_reserve_frac = 0.40
    lot_budget = wheel_budget * (1.0 - csp_reserve_frac)
    for t in wheel_targets:
        px = float(current_prices.get(t) or 0.0)
        if px <= 0 or px > float(max_underlying_price):
            diagnostics["skipped"].append({"ticker": t, "reason": "price"})
            continue
        held = held_qty(t)
        pending_buy = int((pending.get(t) or {}).get("buy_qty", 0) or 0)
        need = max(0, CC_LOT - held - pending_buy)
        if need <= 0:
            if held >= CC_LOT:
                diagnostics["cc_lot_tickers"].append(t)
            continue
        cost = need * px
        if wheel_spent + cost > lot_budget:
            # Still a CSP candidate if we cannot afford shares.
            if held < CC_LOT and t not in short_und:
                diagnostics["csp_candidates"].append(t)
            diagnostics["skipped"].append({"ticker": t, "reason": "lot_budget"})
            continue
        if cash - cost < buffer_cash and held < CC_LOT:
            if t not in short_und:
                diagnostics["csp_candidates"].append(t)
            diagnostics["skipped"].append({"ticker": t, "reason": "cash_buffer"})
            continue
        decisions[t] = PortfolioDecision(
            action="buy",
            quantity=int(need),
            confidence=70,
            reasoning=f"Wheel lot build toward {CC_LOT} shares ({wheel_pct:.0%} sleeve)",
        )
        wheel_spent += cost
        cash -= cost
        if held + need >= CC_LOT:
            diagnostics["cc_lot_tickers"].append(t)

    # CSP candidates: ranked wheel names without a full lot and no short option yet.
    for t in wheel_targets:
        if t in diagnostics["cc_lot_tickers"]:
            continue
        if held_qty(t) >= CC_LOT:
            diagnostics["cc_lot_tickers"].append(t)
            continue
        if t in short_und:
            continue
        if t not in diagnostics["csp_candidates"]:
            diagnostics["csp_candidates"].append(t)

    diagnostics["csp_candidates"] = diagnostics["csp_candidates"][: int(max_wheel_names)]
    diagnostics["csp_collateral_reserve"] = round(wheel_budget * csp_reserve_frac, 2)

    # Directional sleeve: equal-weight among top names not in wheel targets.
    wheel_set = set(wheel_targets)
    dir_names = [t for t in directional_candidates if t not in wheel_set][: int(max_directional_names)]
    diagnostics["directional_targets"] = list(dir_names)
    if dir_names and dir_budget > 0:
        per = dir_budget / len(dir_names)
        for t in dir_names:
            px = float(current_prices.get(t) or 0.0)
            if px <= 0:
                continue
            held = held_qty(t)
            pending_buy = int((pending.get(t) or {}).get("buy_qty", 0) or 0)
            target_qty = int(per // px)
            delta = target_qty - held - pending_buy
            if delta >= 1 and delta * px >= 50:
                if t in decisions:
                    continue
                decisions[t] = PortfolioDecision(
                    action="buy",
                    quantity=int(delta),
                    confidence=60,
                    reasoning=f"Directional sleeve target (~{directional_pct:.0%} book)",
                )
            elif delta <= -1 and (abs(delta) * px >= 50 or target_qty == 0):
                decisions[t] = PortfolioDecision(
                    action="sell",
                    quantity=abs(int(delta)),
                    confidence=55,
                    reasoning="Directional sleeve trim",
                )

    # Exit orphan holdings left from prior broken runs / off-mandate names.
    keep = set(wheel_targets) | set(dir_names) | set(diagnostics["cc_lot_tickers"])
    orphans: List[str] = []
    for t, pos in list((portfolio.positions or {}).items()):
        qty = int(getattr(pos, "long", 0) or 0)
        if qty <= 0 or t in keep or t in decisions:
            continue
        px = float(current_prices.get(t) or 0.0)
        if px > 0 and qty * px < 40:
            continue
        decisions[t] = PortfolioDecision(
            action="sell",
            quantity=qty,
            confidence=60,
            reasoning="Orphan exit: not in wheel or directional targets",
        )
        orphans.append(t)
    diagnostics["orphan_exits"] = orphans

    # Hold markers for CC path when already at lot size with no trade.
    for t in diagnostics["cc_lot_tickers"]:
        if t not in decisions:
            decisions[t] = PortfolioDecision(
                action="hold",
                quantity=0,
                confidence=65,
                reasoning="Wheel lot held — covered call eligible",
            )

    # Email / ops diagnostics expected by the weekly digest templates.
    lot_builds = sum(
        1
        for d in decisions.values()
        if getattr(d, "action", "") == "buy"
        and "Wheel lot" in str(getattr(d, "reasoning", ""))
    )
    diagnostics["cc_held_lot_count"] = len(diagnostics["cc_lot_tickers"])
    diagnostics["cc_lot_build_count"] = lot_builds
    diagnostics["cc_scored_count"] = len(diagnostics["cc_lot_tickers"])
    diagnostics["cc_passed_threshold_count"] = len(diagnostics["cc_lot_tickers"])
    diagnostics["buy_candidates_pre_rank"] = len(wheel_candidates) + len(directional_candidates)
    diagnostics["buy_candidates_post_rank"] = len(wheel_targets) + len(dir_names)
    diagnostics["buy_signal_count"] = sum(
        1 for d in decisions.values() if getattr(d, "action", "") == "buy"
    )

    logger.info(
        "Wheel hybrid allocated",
        decisions=len(decisions),
        cc_lots=diagnostics["cc_lot_tickers"],
        csp=diagnostics["csp_candidates"],
        directional=diagnostics["directional_targets"],
        orphans=orphans,
    )
    return decisions, diagnostics
