"""Concentrated Beat SPY book: 10–12 liquid names, factor entry, agent veto-only."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from src.alpha.liquidity_gate import passes_buy_liquidity
from src.portfolio.beat_spy_policy import (
    CASH_BUFFER_PCT,
    CASH_FLOOR_PCT,
    MAX_BUY_TICKERS,
    MAX_POSITION_PCT,
    MAX_SECTOR_PCT,
    MIN_ADV_USD,
    MIN_BUY_NOTIONAL_USD,
    MIN_MCAP_USD,
    MIN_PRICE_USD,
)
from src.portfolio.manager import PortfolioDecision
from src.portfolio.models import Portfolio
from src.portfolio.phase13_policy import position_stop_triggered
from src.portfolio.sectors import prefetch_sectors, resolve_sector


def _price_map(tickers: List[str], risk_analysis: Dict[str, Dict]) -> Dict[str, float]:
    return {t: float((risk_analysis.get(t) or {}).get("current_price") or 0.0) for t in tickers}


def allocate_beat_spy_book(
    *,
    tickers: List[str],
    portfolio: Portfolio,
    risk_analysis: Dict[str, Dict],
    ticker_dossiers: Optional[Dict[str, Dict[str, Any]]] = None,
    beat_spy_mu: Optional[Dict[str, float]] = None,
    beat_spy_veto: Optional[Set[str]] = None,
    vol_by_ticker: Optional[Dict[str, float]] = None,
    pending_orders_by_symbol: Optional[Dict[str, Dict[str, int]]] = None,
    max_names: int = MAX_BUY_TICKERS,
    max_position_pct: float = MAX_POSITION_PCT,
    max_sector_pct: float = MAX_SECTOR_PCT,
    cash_buffer_pct: float = CASH_BUFFER_PCT,
    cash_floor_pct: float = CASH_FLOOR_PCT,
    min_trade_notional: float = MIN_BUY_NOTIONAL_USD,
    skip_new_buys: bool = False,
    book_stop_loss_pct: float = 0.08,
    min_mcap_usd: float = MIN_MCAP_USD,
    min_adv_usd: float = MIN_ADV_USD,
    min_price_usd: float = MIN_PRICE_USD,
) -> Tuple[Dict[str, PortfolioDecision], Dict[str, Any]]:
    """
    Target weights = top N by μ̂ that pass liquidity + sector cap.
    Sell holdings not in the set. Agents may only veto (beat_spy_veto).
    """
    ticker_dossiers = ticker_dossiers or {}
    beat_spy_mu = beat_spy_mu or {}
    beat_spy_veto = beat_spy_veto or set()
    vol_by_ticker = vol_by_ticker or {}
    pending_orders_by_symbol = pending_orders_by_symbol or {}

    current_prices = _price_map(tickers, risk_analysis)
    for t, pos in (portfolio.positions or {}).items():
        if t not in current_prices:
            current_prices[t] = float((risk_analysis.get(t) or {}).get("current_price") or 0.0)
    equity = float(portfolio.get_equity({k: v for k, v in current_prices.items() if v > 0}))
    if equity <= 0:
        equity = max(float(portfolio.cash), 1.0)

    universe = list(dict.fromkeys(list(tickers) + list(portfolio.positions or {})))
    sector_by_ticker = prefetch_sectors(universe, dossiers=ticker_dossiers)
    for t in universe:
        if t not in sector_by_ticker:
            sector_by_ticker[t] = resolve_sector(
                t, dossier=ticker_dossiers.get(t), risk=risk_analysis.get(t)
            )

    diagnostics: Dict[str, Any] = {
        "beat_spy_concentrated": True,
        "ticker_count": len(tickers),
        "skip_new_buys": bool(skip_new_buys),
        "liquidity_rejects": [],
        "veto_skips": [],
        "target_names": [],
        "target_weights": {},
        "exited": [],
        "book_stop_sells": 0,
        "sector_skip_ahead": [],
        "cash_buffer_pct": float(cash_buffer_pct),
        "cash_floor_pct": float(cash_floor_pct),
        "buy_candidates_pre_rank": 0,
        "buy_candidates_post_rank": 0,
        "buy_signal_count": 0,
        "sell_signal_on_held_count": 0,
        "cc_scored_count": 0,
        "cc_passed_threshold_count": 0,
        "cc_lot_build_count": 0,
        "cc_held_lot_count": 0,
        "cash_rotation_sell_count": 0,
        "cash_rotation_skipped_edge": 0,
        "cash_rotation_skipped_risk": 0,
        "sector_blocks": 0,
    }

    decisions: Dict[str, PortfolioDecision] = {}

    def _held_qty(t: str) -> int:
        pos = portfolio.get_position(t)
        pending = pending_orders_by_symbol.get(t) or {}
        return max(0, int(pos.long if pos else 0) - int(pending.get("sell_qty", 0) or 0))

    # Book stops still fire on off weeks.
    for t in list(portfolio.positions or {}):
        qty = _held_qty(t)
        px = float(current_prices.get(t) or 0.0)
        pos = portfolio.get_position(t)
        cost = float(getattr(pos, "long_cost_basis", 0.0) or 0.0) if pos else 0.0
        if qty > 0 and px > 0 and position_stop_triggered(
            qty=qty, price=px, cost_basis=cost, stop_pct=book_stop_loss_pct
        ):
            decisions[t] = PortfolioDecision(
                action="sell",
                quantity=qty,
                confidence=80,
                reasoning=f"Book stop: {px:.2f} vs cost {cost:.2f}",
            )
            diagnostics["book_stop_sells"] += 1
            diagnostics["exited"].append(t)

    if skip_new_buys:
        diagnostics["rebalance_mode"] = "risk_only"
        for t in universe:
            if t not in decisions:
                decisions[t] = PortfolioDecision(
                    action="hold",
                    quantity=0,
                    confidence=0,
                    reasoning="Off-week: risk-only (no adds / no rebuild)",
                )
        return decisions, diagnostics

    ranked = sorted(
        universe,
        key=lambda t: (float(beat_spy_mu.get(t, -999.0)), t),
        reverse=True,
    )
    diagnostics["buy_candidates_pre_rank"] = len(ranked)

    cap_dollars = equity * float(max_sector_pct)
    pos_dollars = equity * float(max_position_pct)
    projected: Dict[str, float] = {}
    target: List[str] = []
    for t in ranked:
        if len(target) >= max(1, int(max_names)):
            break
        if t in beat_spy_veto:
            diagnostics["veto_skips"].append(t)
            continue
        px = float(current_prices.get(t) or 0.0)
        if px <= 0:
            continue
        is_held = _held_qty(t) > 0 and t not in {x for x in diagnostics["exited"]}
        ok, reason = passes_buy_liquidity(
            ticker_dossiers.get(t),
            px,
            min_mcap=min_mcap_usd,
            min_adv=min_adv_usd,
            min_price=min_price_usd,
        )
        if not ok and not is_held:
            diagnostics["liquidity_rejects"].append({"ticker": t, "reason": reason})
            continue
        sec = sector_by_ticker.get(t) or "Unknown"
        if sec != "Unknown" and cap_dollars > 0:
            used = float(projected.get(sec, 0.0))
            if used >= cap_dollars:
                diagnostics["sector_skip_ahead"].append(t)
                diagnostics["sector_blocks"] += 1
                continue
            projected[sec] = used + min(pos_dollars, cap_dollars - used)
        target.append(t)

    diagnostics["target_names"] = list(target)
    diagnostics["buy_candidates_post_rank"] = len(target)

    # Size ∝ max(μ - min_μ, ε) / vol so negative-μ names in the set still get weight.
    mus = [float(beat_spy_mu.get(t, 0.0)) for t in target] or [0.0]
    floor_mu = min(mus)
    scores: Dict[str, float] = {}
    for t in target:
        mu = float(beat_spy_mu.get(t, 0.0))
        vol = max(float(vol_by_ticker.get(t) or 0.20), 0.08)
        scores[t] = max(mu - floor_mu, 0.05) / vol
    score_sum = sum(scores.values()) or 1.0
    deploy_pct = max(0.0, 1.0 - max(float(cash_buffer_pct), float(cash_floor_pct)))
    raw_w = {t: (scores[t] / score_sum) * deploy_pct for t in target}

    # Cap per name then renormalize leftover into names with room.
    weights: Dict[str, float] = {t: min(raw_w[t], float(max_position_pct)) for t in target}
    leftover = deploy_pct - sum(weights.values())
    if leftover > 1e-6:
        room = {t: max(0.0, float(max_position_pct) - weights[t]) for t in target}
        room_sum = sum(room.values())
        if room_sum > 0:
            for t in target:
                weights[t] += leftover * (room[t] / room_sum)
    diagnostics["target_weights"] = {t: round(weights[t], 4) for t in target}

    # Exit names not in the target set (the rebuild).
    for t, pos in list((portfolio.positions or {}).items()):
        if t in decisions:
            continue
        qty = _held_qty(t)
        px = float(current_prices.get(t) or 0.0)
        if qty <= 0 or px <= 0:
            continue
        if t not in target:
            decisions[t] = PortfolioDecision(
                action="sell",
                quantity=qty,
                confidence=70,
                reasoning="Rebuild: not in concentrated 10–12 target set",
            )
            diagnostics["exited"].append(t)
            diagnostics["cash_rotation_sell_count"] += 1

    # Buy / trim to target weight.
    for t in target:
        if t in decisions and decisions[t].action == "sell":
            continue
        px = float(current_prices.get(t) or 0.0)
        if px <= 0:
            continue
        held = _held_qty(t)
        target_qty = int((equity * float(weights.get(t, 0.0))) // px)
        pending_buy = int((pending_orders_by_symbol.get(t) or {}).get("buy_qty", 0) or 0)
        delta = target_qty - held - pending_buy
        notional = abs(delta) * px
        if delta >= 1 and notional >= float(min_trade_notional):
            decisions[t] = PortfolioDecision(
                action="buy",
                quantity=int(delta),
                confidence=75,
                reasoning=(
                    f"Concentrated target {weights[t]*100:.1f}% "
                    f"(μ̂={float(beat_spy_mu.get(t, 0.0)):.3f})"
                ),
            )
        elif delta <= -1 and (notional >= float(min_trade_notional) or target_qty == 0):
            decisions[t] = PortfolioDecision(
                action="sell",
                quantity=min(held, int(-delta)),
                confidence=65,
                reasoning=f"Trim to concentrated target {weights[t]*100:.1f}%",
            )
        elif t not in decisions:
            decisions[t] = PortfolioDecision(
                action="hold",
                quantity=0,
                confidence=60,
                reasoning=f"At concentrated target {weights[t]*100:.1f}%",
            )

    for t in universe:
        if t not in decisions:
            decisions[t] = PortfolioDecision(
                action="hold",
                quantity=0,
                confidence=0,
                reasoning="Outside concentrated target set",
            )

    diagnostics["n_target"] = len(target)
    diagnostics["n_exited"] = len(diagnostics["exited"])
    diagnostics["liquidity_reject_count"] = len(diagnostics["liquidity_rejects"])
    return decisions, diagnostics
