"""Optional paper execution: synthetic long straddle (buy ATM call + buy ATM put), defined loss = premiums."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

import structlog

from src.biotech.fill_reconcile import reconcile_straddle_orders
from src.biotech.models import BiotechSnapshot
from src.biotech.risk_biotech import BiotechRiskBudget, equity_from_alpaca_account
from src.broker.alpaca import AlpacaBroker

logger = structlog.get_logger()


def propose_straddle_legs(
    broker: AlpacaBroker,
    ticker: str,
    underlying_price: float,
) -> Optional[Dict[str, Any]]:
    """
    Pick one expiry (nearest in 7–45d), then ATM call + put on same strike/expiry.
    Falls back to strangle if no paired straddle exists.
    """
    if underlying_price <= 0:
        return None

    expiry_lo = date.today() + timedelta(days=7)
    expiry_hi = date.today() + timedelta(days=45)
    calls = broker.get_option_contracts(
        underlying=ticker,
        option_type="call",
        expiry_gte=expiry_lo,
        expiry_lte=expiry_hi,
        strike_gte=underlying_price * 0.95,
        strike_lte=underlying_price * 1.05,
        limit=40,
    )
    puts = broker.get_option_contracts(
        underlying=ticker,
        option_type="put",
        expiry_gte=expiry_lo,
        expiry_lte=expiry_hi,
        strike_gte=underlying_price * 0.95,
        strike_lte=underlying_price * 1.05,
        limit=40,
    )
    if not calls or not puts:
        return None

    def _tradable(cs: List[Dict]) -> List[Dict]:
        return [c for c in cs if c.get("tradable", True)] or list(cs)

    calls = _tradable(calls)
    puts = _tradable(puts)

    expiries = sorted(
        {str(c.get("expiry") or "") for c in calls if c.get("expiry")}
        & {str(p.get("expiry") or "") for p in puts if p.get("expiry")}
    )
    if not expiries:
        return None

    def _nearest_expiry(exps: List[str]) -> str:
        today = date.today()

        def _dist(e: str) -> int:
            try:
                d = date.fromisoformat(e[:10])
                return abs((d - today).days)
            except ValueError:
                return 99999

        return min(exps, key=_dist)

    expiry = _nearest_expiry(expiries)
    calls_e = [c for c in calls if str(c.get("expiry") or "")[:10] == expiry[:10]]
    puts_e = [p for p in puts if str(p.get("expiry") or "")[:10] == expiry[:10]]
    if not calls_e or not puts_e:
        return None

    put_strikes = {round(float(p.get("strike") or 0), 4) for p in puts_e if float(p.get("strike") or 0) > 0}
    call_strikes = {round(float(c.get("strike") or 0), 4) for c in calls_e if float(c.get("strike") or 0) > 0}
    common = sorted(call_strikes & put_strikes)
    if common:
        target_k = min(common, key=lambda k: abs(k - underlying_price))
        call_pick = min(
            [c for c in calls_e if round(float(c.get("strike") or 0), 4) == target_k],
            key=lambda c: abs(float(c.get("strike") or 0) - underlying_price),
        )
        put_pick = min(
            [p for p in puts_e if round(float(p.get("strike") or 0), 4) == target_k],
            key=lambda p: abs(float(p.get("strike") or 0) - underlying_price),
        )
        return {
            "call": call_pick,
            "put": put_pick,
            "strategy_type": "long_straddle",
            "expiry": expiry,
            "strike": target_k,
        }

    # Strangle fallback
    call_pick = min(calls_e, key=lambda c: abs(float(c.get("strike") or 0) - underlying_price))
    put_pick = min(puts_e, key=lambda p: abs(float(p.get("strike") or 0) - underlying_price))
    return {
        "call": call_pick,
        "put": put_pick,
        "strategy_type": "long_strangle",
        "expiry": expiry,
        "strike": float(call_pick.get("strike") or 0),
        "put_strike": float(put_pick.get("strike") or 0),
    }


def _strategy_dict(
    c: Dict,
    p: Dict,
    *,
    strategy_type: str,
    expiry: str,
    strike: float,
    call_px: float,
    put_px: float,
    put_strike: Optional[float] = None,
) -> Dict[str, Any]:
    call_k = float(c.get("strike", 0) or 0)
    put_k = float(put_strike if put_strike is not None else p.get("strike", 0) or 0)
    est = call_px * 100 + put_px * 100
    return {
        "type": strategy_type,
        "call_contract": c.get("symbol"),
        "put_contract": p.get("symbol"),
        "call_strike": call_k,
        "put_strike": put_k,
        "expiry": expiry,
        "estimated_premium_total": est,
        "estimated_premium_per_share": call_px + put_px,
        "break_even_low_est": (put_k - (call_px + put_px)) if put_k > 0 else None,
        "break_even_high_est": (call_k + (call_px + put_px)) if call_k > 0 else None,
    }


def _premium_efficiency_ok(
    est_premium: float,
    underlying_price: float,
    policy: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, str]:
    """Skip if premium is large vs historical avg 5d move notional."""
    policy = policy or {}
    max_ratio = float(policy.get("max_premium_to_expected_move_ratio", 8.0))
    from src.biotech.policy_learning import historical_avg_5d_move_pct

    avg_move_pct = historical_avg_5d_move_pct()
    if underlying_price <= 0 or est_premium <= 0 or avg_move_pct <= 0:
        return True, ""
    expected_payoff = underlying_price * 100.0 * (avg_move_pct / 100.0)
    if expected_payoff <= 0:
        return True, ""
    ratio = est_premium / expected_payoff
    if ratio > max_ratio:
        return False, (
            f"premium efficiency: est ${est_premium:.0f} vs expected move notional "
            f"${expected_payoff:.0f} (ratio {ratio:.1f} > {max_ratio:.1f})"
        )
    return True, ""


def execute_straddle_paper(
    broker: AlpacaBroker,
    snapshot: BiotechSnapshot,
    budget: BiotechRiskBudget,
    *,
    arm: str = "mechanical",
    policy: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    acct = broker.get_account()
    eq = equity_from_alpaca_account(acct)
    max_prem = budget.max_premium_dollars(eq)
    price = float(snapshot.last_price or 0.0)
    if price <= 0:
        return {"status": "skipped", "reason": "no underlying price", "arm": arm}

    legs = propose_straddle_legs(broker, snapshot.ticker, price)
    if not legs:
        return {"status": "skipped", "reason": "no suitable option contracts", "arm": arm}

    c = legs["call"]
    p = legs["put"]
    strategy_type = str(legs.get("strategy_type") or "long_straddle")
    expiry = str(legs.get("expiry") or c.get("expiry") or p.get("expiry") or "")
    strike = float(legs.get("strike") or c.get("strike") or 0)
    put_strike = legs.get("put_strike")

    call_px = float(c.get("close_price", 0) or 0)
    put_px = float(p.get("close_price", 0) or 0)
    est = call_px * 100 + put_px * 100
    strat = _strategy_dict(
        c,
        p,
        strategy_type=strategy_type,
        expiry=expiry,
        strike=strike,
        call_px=call_px,
        put_px=put_px,
        put_strike=float(put_strike) if put_strike is not None else None,
    )

    eff_ok, eff_reason = _premium_efficiency_ok(est, price, policy)
    if not eff_ok:
        return {
            "status": "skipped",
            "reason": eff_reason,
            "arm": arm,
            "strategy": strat,
            "premium_est_usd": est,
        }

    if est > max_prem:
        return {
            "status": "skipped",
            "reason": f"estimated premium {est:.2f} exceeds cap {max_prem:.2f} ({budget.max_premium_pct_equity:.1%} of equity)",
            "equity": eq,
            "arm": arm,
            "strategy": strat,
            "premium_est_usd": est,
        }

    out: Dict[str, Any] = {
        "status": "submitted",
        "equity": eq,
        "max_premium": max_prem,
        "arm": arm,
        "orders": [],
        "strategy": strat,
        "premium_est_usd": est,
    }
    for leg, side in ((c, "buy"), (p, "buy")):
        o = broker.submit_option_order(
            contract_symbol=leg["symbol"],
            qty=min(1, budget.max_contracts_per_leg),
            side=side,
            order_type="market",
        )
        out["orders"].append({"contract": leg.get("symbol"), "order": o})

    recon = reconcile_straddle_orders(broker, out["orders"])
    out["fill_reconcile"] = recon
    out["premium_filled_usd"] = float(recon.get("total_premium_filled") or 0)
    norm = str(recon.get("status") or "submitted")
    if norm == "filled":
        out["status"] = "filled"
    elif norm == "partial":
        out["status"] = "partial"
    else:
        out["status"] = "submitted"
    out["total_premium_filled"] = out["premium_filled_usd"]
    return out
