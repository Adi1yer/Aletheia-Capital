"""70% wheel / 30% directional capital allocator for wheel-10k."""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Set

import structlog

from src.options.wheel_universe import WheelCandidate
from src.portfolio.manager import PortfolioDecision
from src.portfolio.models import Portfolio

logger = structlog.get_logger()

CC_LOT = 100


def _finite_px(value: Any) -> float:
    try:
        px = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(px) or px <= 0:
        return 0.0
    return px


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
    max_lots_per_name: int = 3,
    max_position_pct: float = 0.35,
    add_lot_min_score: float = 0.55,
    pending_orders_by_symbol: Optional[Dict[str, Dict[str, Any]]] = None,
    short_option_underlyings: Optional[Set[str]] = None,
    preflight_ok: Optional[Set[str]] = None,
    uncovered_unwind: Optional[Set[str]] = None,
    csp_reserve_frac: float = 0.20,
) -> tuple[Dict[str, PortfolioDecision], Dict[str, Any]]:
    """
    Build equity decisions for the hybrid book.

    - Wheel sleeve: bring/keep 100-share lots on cheap liquid names (CC fuel).
    - Directional sleeve: smaller long-only positions (not forced to 100 shares).
    - CSP entries are selected separately (tickers list); collateral reserved in diagnostics.
    - ``preflight_ok``: only open *new* lots for tickers that passed option preflight.
    - ``uncovered_unwind``: force-sell 100-share lots that failed CC write (atomic rule).
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

    # Pending equity buys already commit cash/BP — do not double-spend.
    pending_buy_notional = 0.0
    for sym, pend in pending.items():
        bq = int((pend or {}).get("buy_qty", 0) or 0)
        if bq <= 0:
            continue
        px = _finite_px(current_prices.get(str(sym).upper()) or current_prices.get(sym))
        if px > 0:
            pending_buy_notional += bq * px
    cash = max(0.0, cash - pending_buy_notional)

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
        "pending_buy_notional": round(pending_buy_notional, 2),
        "max_lots_per_name": int(max_lots_per_name),
        "add_lot_min_score": float(add_lot_min_score),
    }

    def held_qty(t: str) -> int:
        pos = portfolio.get_position(t) if hasattr(portfolio, "get_position") else None
        if pos is None:
            pos = (portfolio.positions or {}).get(t)
        if not pos:
            return 0
        return int(getattr(pos, "long", 0) or 0)

    decisions: Dict[str, PortfolioDecision] = {}

    preflight = {str(x).upper() for x in (preflight_ok or set())} if preflight_ok is not None else None
    unwind_set = {str(x).upper() for x in (uncovered_unwind or set())}

    # Force-unwind uncovered lots that failed CC (atomic invariant).
    # Credit estimated sell proceeds so replacement buys can use freed cash.
    for t in list(unwind_set):
        qty = held_qty(t)
        if qty <= 0:
            continue
        if t in short_und:
            diagnostics["skipped"].append(
                {"ticker": t, "reason": "unwind_blocked_open_short_option"}
            )
            continue
        px = _finite_px(current_prices.get(t))
        decisions[t] = PortfolioDecision(
            action="sell",
            quantity=qty,
            confidence=90,
            reasoning="Atomic CC rule: unwind lot — covered call write failed/skipped",
        )
        diagnostics["skipped"].append({"ticker": t, "reason": "atomic_unwind"})
        if px > 0:
            cash += qty * px

    # Existing wheel lots (100+ shares). Soft band (≤ max×1.25) keeps recently-appreciated
    # lots in the CC path so a same-session BTC cannot orphan-sell them.
    soft_max = float(max_underlying_price) * 1.25
    existing_wheel: List[str] = []
    graduated_lots: List[str] = []  # ≥100 shares above soft max — still CC-eligible, never orphan
    for t, pos in list((portfolio.positions or {}).items()):
        if t in unwind_set or t in decisions:
            continue
        qty = int(getattr(pos, "long", 0) or 0)
        px = _finite_px(current_prices.get(t))
        if qty >= CC_LOT and px > 0:
            if px <= soft_max:
                existing_wheel.append(t)
            else:
                graduated_lots.append(t)

    score_by_ticker = {str(c.ticker).upper(): float(c.score) for c in wheel_candidates}
    ranked_new = [c.ticker for c in wheel_candidates if c.ticker not in existing_wheel]
    if preflight is not None:
        ranked_new = [t for t in ranked_new if t in preflight]
    # Name count is not a hard stop — fill the 70% sleeve. Prefer existing lots, then score rank.
    wheel_targets: List[str] = []
    for t in existing_wheel + ranked_new:
        if t in wheel_targets or t in unwind_set:
            continue
        wheel_targets.append(t)
    diagnostics["wheel_targets"] = list(wheel_targets)
    diagnostics["max_wheel_names_soft"] = int(max_wheel_names)
    diagnostics["preflight_required"] = preflight is not None
    diagnostics["preflight_ok_count"] = len(preflight) if preflight is not None else None

    wheel_spent = 0.0
    for t in existing_wheel + graduated_lots:
        px = _finite_px(current_prices.get(t))
        qty = held_qty(t)
        wheel_spent += qty * px

    # Top up / open first 100-share lots within wheel budget (leave room for CSP + buffer).
    reserve = float(csp_reserve_frac)
    lot_budget = wheel_budget * (1.0 - reserve)
    csp_cash_floor = wheel_budget * reserve
    min_cash_after_first_lot = buffer_cash + csp_cash_floor
    max_name_dollars = eq * float(max_position_pct) if eq > 0 else 0.0
    max_shares = max(CC_LOT, int(max_lots_per_name) * CC_LOT)

    def _try_first_lot(t: str, *, top_up_only: bool) -> None:
        nonlocal cash, wheel_spent
        if t in decisions:
            return
        px = _finite_px(current_prices.get(t))
        if px <= 0 or px > float(max_underlying_price):
            diagnostics["skipped"].append({"ticker": t, "reason": "price"})
            return
        held = held_qty(t)
        pending_buy = int((pending.get(t) or {}).get("buy_qty", 0) or 0)
        need = max(0, CC_LOT - held - pending_buy)
        if need <= 0:
            if held >= CC_LOT:
                diagnostics["cc_lot_tickers"].append(t)
            return
        if top_up_only and held <= 0:
            return
        if not top_up_only and held > 0:
            return
        # First lot only: do not buy shares into a naked short option (CSP collateral).
        if t in short_und:
            diagnostics["skipped"].append({"ticker": t, "reason": "open_short_option"})
            return
        if held < CC_LOT and preflight is not None and t not in preflight:
            diagnostics["skipped"].append({"ticker": t, "reason": "preflight_failed"})
            if t not in short_und:
                diagnostics["csp_candidates"].append(t)
            return
        cost = need * px
        if wheel_spent + cost > lot_budget:
            if held < CC_LOT and t not in short_und:
                diagnostics["csp_candidates"].append(t)
            diagnostics["skipped"].append({"ticker": t, "reason": "lot_budget"})
            return
        if cash - cost < min_cash_after_first_lot:
            if t not in short_und:
                diagnostics["csp_candidates"].append(t)
            diagnostics["skipped"].append({"ticker": t, "reason": "cash_buffer_or_csp_reserve"})
            return
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

    # 1) Finish incomplete first lots. 2) Extra lots on held names. 3) New first lots.
    for t in wheel_targets:
        _try_first_lot(t, top_up_only=True)

    # Extra 100-share lots on high-conviction names (may already have a short call).
    # Spend down to the cash buffer only — CSP reserve is for names we do not own.
    extra_adds: List[str] = []
    extra_ranked = sorted(
        [t for t in wheel_targets if t not in unwind_set],
        key=lambda x: score_by_ticker.get(str(x).upper(), 0.0),
        reverse=True,
    )
    for t in extra_ranked:
        if t in decisions and getattr(decisions[t], "action", "") != "hold":
            continue
        px = _finite_px(current_prices.get(t))
        if px <= 0 or px > float(max_underlying_price):
            continue
        held = held_qty(t)
        pending_buy = int((pending.get(t) or {}).get("buy_qty", 0) or 0)
        planned = int(getattr(decisions.get(t), "quantity", 0) or 0) if (
            t in decisions and getattr(decisions.get(t), "action", "") == "buy"
        ) else 0
        have = held + pending_buy + planned
        # Add-on only after a lot is already on the book (not the same-session first buy).
        if held < CC_LOT:
            continue
        score = float(score_by_ticker.get(str(t).upper(), 0.0) or 0.0)
        if score + 1e-9 < float(add_lot_min_score):
            diagnostics["skipped"].append(
                {"ticker": t, "reason": f"add_lot_score_{score:.2f}<{float(add_lot_min_score):.2f}"}
            )
            continue
        if have + CC_LOT > max_shares:
            diagnostics["skipped"].append({"ticker": t, "reason": "max_lots_per_name"})
            continue
        cost = CC_LOT * px
        if max_name_dollars > 0 and (have + CC_LOT) * px > max_name_dollars + 1e-6:
            diagnostics["skipped"].append({"ticker": t, "reason": "max_position_pct"})
            continue
        # Extra lots fill the 70% wheel sleeve (not the thinner first-lot/CSP split).
        if wheel_spent + cost > wheel_budget:
            diagnostics["skipped"].append({"ticker": t, "reason": "wheel_budget_extra"})
            continue
        if cash - cost < buffer_cash:
            diagnostics["skipped"].append({"ticker": t, "reason": "cash_buffer_extra"})
            continue
        if preflight is not None and t not in preflight:
            diagnostics["skipped"].append({"ticker": t, "reason": "preflight_failed_extra"})
            continue
        prev = decisions.get(t)
        prev_qty = int(getattr(prev, "quantity", 0) or 0) if prev and getattr(prev, "action", "") == "buy" else 0
        decisions[t] = PortfolioDecision(
            action="buy",
            quantity=prev_qty + CC_LOT,
            confidence=75,
            reasoning=(
                f"Wheel add-on lot (score {score:.2f}, "
                f"{(have + CC_LOT) // CC_LOT} lots, {wheel_pct:.0%} sleeve)"
            ),
        )
        wheel_spent += cost
        cash -= cost
        extra_adds.append(t)
        if t not in diagnostics["cc_lot_tickers"]:
            diagnostics["cc_lot_tickers"].append(t)
    diagnostics["extra_lot_adds"] = extra_adds

    for t in wheel_targets:
        _try_first_lot(t, top_up_only=False)

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

    # Overflow existing 100-lots (beyond max_wheel_names) stay CC-eligible so we never
    # orphan-sell covered/naked wheel inventory without a write attempt.
    for t in existing_wheel:
        if held_qty(t) >= CC_LOT and t not in diagnostics["cc_lot_tickers"]:
            diagnostics["cc_lot_tickers"].append(t)
            diagnostics.setdefault("overflow_cc_lots", []).append(t)
    # Graduated lots (price > soft max) still get CC writes — never orphan-sell a 100-lot.
    for t in graduated_lots:
        if held_qty(t) >= CC_LOT and t not in diagnostics["cc_lot_tickers"]:
            diagnostics["cc_lot_tickers"].append(t)
            diagnostics.setdefault("graduated_cc_lots", []).append(t)

    diagnostics["csp_candidates"] = diagnostics["csp_candidates"][: max(int(max_wheel_names), 8)]
    diagnostics["csp_collateral_reserve"] = round(wheel_budget * reserve, 2)
    diagnostics["csp_reserve_frac"] = reserve

    # Directional sleeve: residual cash only after wheel buys + buffer + CSP reserve.
    wheel_set = set(wheel_targets) | set(diagnostics["cc_lot_tickers"])
    dir_names = [t for t in directional_candidates if t not in wheel_set][: int(max_directional_names)]
    diagnostics["directional_targets"] = list(dir_names)
    csp_cash_reserve = wheel_budget * reserve
    cash_after_wheel = cash
    residual_dir_budget = min(
        dir_budget,
        max(0.0, cash_after_wheel - buffer_cash - csp_cash_reserve),
    )
    diagnostics["directional_residual_budget"] = round(residual_dir_budget, 2)
    diagnostics["csp_cash_reserve"] = round(csp_cash_reserve, 2)
    if dir_names and residual_dir_budget > 0:
        per = residual_dir_budget / len(dir_names)
        for t in dir_names:
            px = _finite_px(current_prices.get(t))
            if px <= 0:
                continue
            held = held_qty(t)
            pending_buy = int((pending.get(t) or {}).get("buy_qty", 0) or 0)
            # Cap at 99 shares so directional never forms an uncovered CC lot.
            max_dir_qty = 99
            target_qty = min(max_dir_qty, int(per // px))
            delta = target_qty - held - pending_buy
            if held + pending_buy > max_dir_qty:
                # Trim excess that would create a naked 100-lot outside the wheel path.
                over = held + pending_buy - max_dir_qty
                if over >= 1:
                    decisions[t] = PortfolioDecision(
                        action="sell",
                        quantity=int(over),
                        confidence=70,
                        reasoning="Directional cap 99 — avoid uncovered 100-share lot",
                    )
                continue
            if delta >= 1 and delta * px >= 50:
                if t in decisions:
                    continue
                if t in short_und:
                    diagnostics["skipped"].append(
                        {"ticker": t, "reason": "directional_blocked_open_short_option"}
                    )
                    continue
                cost = delta * px
                if cash_after_wheel - cost < buffer_cash + csp_cash_reserve:
                    continue
                decisions[t] = PortfolioDecision(
                    action="buy",
                    quantity=int(delta),
                    confidence=60,
                    reasoning=f"Directional sleeve residual (~{directional_pct:.0%} target, wheel-first)",
                )
                cash_after_wheel -= cost
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
        # Never sell shares while a short option is open on this name (BTC first).
        if t in short_und:
            diagnostics["skipped"].append({"ticker": t, "reason": "orphan_blocked_open_short_option"})
            continue
        px = _finite_px(current_prices.get(t))
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
