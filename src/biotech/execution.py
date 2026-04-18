"""Optional paper execution: synthetic long straddle (buy ATM call + buy ATM put), defined loss = premiums."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional

import structlog

from src.biotech.models import BiotechSnapshot
from src.biotech.risk_biotech import BiotechRiskBudget, equity_from_alpaca_account
from src.broker.alpaca import AlpacaBroker

logger = structlog.get_logger()


def propose_straddle_legs(
    broker: AlpacaBroker,
    ticker: str,
    underlying_price: float,
) -> tuple[Optional[Dict], Optional[Dict]]:
    """Pick nearest weekly-ish expiry, ATM-ish call and put."""
    if underlying_price <= 0:
        return None, None

    expiry_lo = date.today() + timedelta(days=7)
    expiry_hi = date.today() + timedelta(days=45)
    contracts = broker.get_option_contracts(
        underlying=ticker,
        option_type="call",
        expiry_gte=expiry_lo,
        expiry_lte=expiry_hi,
        strike_gte=underlying_price * 0.98,
        strike_lte=underlying_price * 1.02,
        limit=10,
    )
    puts = broker.get_option_contracts(
        underlying=ticker,
        option_type="put",
        expiry_gte=expiry_lo,
        expiry_lte=expiry_hi,
        strike_gte=underlying_price * 0.98,
        strike_lte=underlying_price * 1.02,
        limit=10,
    )
    if not contracts or not puts:
        return None, None

    def pick(cs: List[Dict]) -> Optional[Dict]:
        trad = [c for c in cs if c.get("tradable", True)] or cs
        trad.sort(key=lambda c: (abs(c["strike"] - underlying_price), c.get("expiry", "")))
        return trad[0] if trad else None

    return pick(contracts), pick(puts)


def execute_straddle_paper(
    broker: AlpacaBroker,
    snapshot: BiotechSnapshot,
    budget: BiotechRiskBudget,
) -> Dict[str, Any]:
    acct = broker.get_account()
    eq = equity_from_alpaca_account(acct)
    max_prem = budget.max_premium_dollars(eq)
    price = float(snapshot.last_price or 0.0)
    if price <= 0:
        return {"status": "skipped", "reason": "no underlying price"}

    c, p = propose_straddle_legs(broker, snapshot.ticker, price)
    if not c or not p:
        return {"status": "skipped", "reason": "no suitable option contracts"}

    est = (c.get("close_price", 0) or 0) * 100 + (p.get("close_price", 0) or 0) * 100
    if est > max_prem:
        return {
            "status": "skipped",
            "reason": f"estimated premium {est:.2f} exceeds cap {max_prem:.2f} ({budget.max_premium_pct_equity:.1%} of equity)",
            "equity": eq,
        }

    out: Dict[str, Any] = {"status": "submitted", "equity": eq, "max_premium": max_prem, "orders": []}
    for leg, side in ((c, "buy"), (p, "buy")):
        o = broker.submit_option_order(
            contract_symbol=leg["symbol"],
            qty=min(1, budget.max_contracts_per_leg),
            side=side,
            order_type="market",
        )
        out["orders"].append({"contract": leg.get("symbol"), "order": o})
    return out
