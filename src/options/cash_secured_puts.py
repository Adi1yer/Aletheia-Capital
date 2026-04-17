"""Cash-secured puts — sell OTM puts for income when value-bull / growth-bear regime."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, List, Optional, TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from src.broker.alpaca import AlpacaBroker

logger = structlog.get_logger()


class CashSecuredPutManager:
    """Select short-dated slightly OTM puts and sell to open (cash-secured)."""

    def __init__(self, min_premium_pct: float = 0.003):
        self.min_premium_pct = min_premium_pct

    def select_put_contract(
        self,
        underlying: str,
        current_price: float,
        csp_score: int,
        broker: "AlpacaBroker",
    ) -> Optional[Dict]:
        if current_price <= 0:
            return None

        if csp_score >= 55:
            strike_high = current_price * 0.98
            strike_low = current_price * 0.90
        else:
            strike_high = current_price * 0.95
            strike_low = current_price * 0.85

        contracts = broker.get_option_contracts(
            underlying=underlying,
            option_type="put",
            expiry_gte=date.today() + timedelta(days=14),
            expiry_lte=date.today() + timedelta(days=45),
            strike_gte=strike_low,
            strike_lte=strike_high,
            limit=20,
        )
        if not contracts:
            logger.info("No suitable put contracts", underlying=underlying)
            return None

        tradable = [c for c in contracts if c.get("tradable", True)] or contracts
        target = current_price * (0.94 if csp_score >= 55 else 0.91)
        tradable.sort(key=lambda c: (abs(c["strike"] - target), c["expiry"]))

        best = tradable[0]
        collateral = best["strike"] * 100
        est_prem = best.get("close_price", 0.0) * 100
        if collateral > 0 and est_prem / collateral < self.min_premium_pct:
            logger.info("Put premium too low", underlying=underlying, pct=est_prem / collateral)
            return None
        return best

    def execute_cash_secured_puts(
        self,
        broker: "AlpacaBroker",
        csp_tickers: List[str],
        csp_scores: Dict[str, int],
        current_prices: Dict[str, float],
    ) -> List[Dict]:
        results: List[Dict] = []
        for underlying in csp_tickers:
            price = float(current_prices.get(underlying) or 0.0)
            score = int(csp_scores.get(underlying, 0))
            if price <= 0 or score < 40:
                continue
            contract = self.select_put_contract(underlying, price, score, broker)
            if not contract:
                results.append({"underlying": underlying, "status": "skipped", "reason": "no contract"})
                continue
            order = broker.submit_option_order(
                contract_symbol=contract["symbol"],
                qty=1,
                side="sell",
                order_type="market",
            )
            if order:
                results.append({
                    "underlying": underlying,
                    "status": "executed",
                    "contract_symbol": contract["symbol"],
                    "strike": contract["strike"],
                    "expiry": contract["expiry"],
                    "csp_score": score,
                    "order": order,
                })
            else:
                results.append({"underlying": underlying, "status": "failed", "reason": "order"})
        logger.info(
            "CSP execution complete",
            n=len(results),
            ok=sum(1 for r in results if r.get("status") == "executed"),
        )
        return results
