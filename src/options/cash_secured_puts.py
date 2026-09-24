"""Cash-secured puts — sell OTM puts for income when value-bull / growth-bear regime."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, List, Optional, TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from src.broker.alpaca import AlpacaBroker

logger = structlog.get_logger()


def outstanding_short_put_collateral_usd(
    option_positions: Optional[List[Dict]] = None,
) -> float:
    """Strike × 100 × qty for open short puts (cash already reserved at broker)."""
    from src.options.wheel_lifecycle import parse_occ_symbol

    total = 0.0
    for pos in option_positions or []:
        if str(pos.get("side") or "").lower() != "short":
            continue
        parsed = parse_occ_symbol(str(pos.get("symbol") or ""))
        if not parsed or parsed.get("option_type") != "put":
            continue
        strike = float(parsed.get("strike") or 0.0)
        try:
            qty = int(pos.get("qty") or 0)
        except (TypeError, ValueError):
            qty = 0
        if strike > 0 and qty > 0:
            total += strike * 100.0 * qty
    return total


class CashSecuredPutManager:
    """Select short-dated slightly OTM puts and sell to open (cash-secured)."""

    def __init__(
        self,
        min_premium_pct: float = 0.003,
        min_premium_usd: float = 75.0,
        min_annualized_yield_pct: float = 3.0,
    ):
        self.min_premium_pct = min_premium_pct
        self.min_premium_usd = min_premium_usd
        self.min_annualized_yield_pct = min_annualized_yield_pct

    def select_put_contract(
        self,
        underlying: str,
        current_price: float,
        csp_score: int,
        broker: "AlpacaBroker",
    ) -> Optional[Dict]:
        try:
            current_price = float(current_price)
        except (TypeError, ValueError):
            return None
        if current_price != current_price or current_price <= 0 or current_price == float("inf"):
            return None

        if csp_score >= 55:
            strike_high = current_price * 0.98
            strike_low = current_price * 0.90
        else:
            strike_high = current_price * 0.95
            strike_low = current_price * 0.85

        try:
            contracts = broker.get_option_contracts(
                underlying=underlying,
                option_type="put",
                expiry_gte=date.today() + timedelta(days=14),
                expiry_lte=date.today() + timedelta(days=45),
                strike_gte=strike_low,
                strike_lte=strike_high,
                limit=20,
            )
        except Exception as e:
            logger.error("Put chain unavailable", underlying=underlying, error=str(e))
            return None
        if not contracts:
            logger.info("No suitable put contracts", underlying=underlying)
            return None

        tradable = [c for c in contracts if c.get("tradable", True)] or contracts
        if hasattr(broker, "enrich_option_quotes"):
            try:
                broker.enrich_option_quotes(tradable)
            except Exception:
                pass
        from src.options.covered_calls import _contract_premium_usd

        if tradable and all(_contract_premium_usd(c) <= 0 for c in tradable):
            logger.info("Put quotes unavailable", underlying=underlying)
            return None
        target = current_price * (0.94 if csp_score >= 55 else 0.91)
        tradable.sort(key=lambda c: (abs(float(c.get("strike") or 0) - target), str(c.get("expiry") or "")))

        today = date.today()
        for best in tradable:
            collateral = float(best.get("strike") or 0) * 100
            est_prem = _contract_premium_usd(best)
            if est_prem < self.min_premium_usd:
                continue
            try:
                exp = date.fromisoformat(str(best["expiry"])[:10])
                days = max(1, (exp - today).days)
            except Exception:
                days = 30
            annualized = (est_prem / collateral) * (365.0 / days) * 100.0 if collateral > 0 else 0
            if annualized < self.min_annualized_yield_pct:
                continue
            if collateral > 0 and est_prem / collateral < self.min_premium_pct:
                continue
            return best

        logger.info(
            "No put met premium/yield floors",
            underlying=underlying,
            min_premium_usd=self.min_premium_usd,
        )
        return None

    def execute_cash_secured_puts(
        self,
        broker: "AlpacaBroker",
        csp_tickers: List[str],
        csp_scores: Dict[str, int],
        current_prices: Dict[str, float],
        *,
        max_collateral_usd: Optional[float] = None,
        wait_fill: bool = True,
        collateral_already_used_usd: float = 0.0,
        option_positions: Optional[List[Dict]] = None,
    ) -> List[Dict]:
        results: List[Dict] = []
        try:
            seeded = float(collateral_already_used_usd or 0.0)
        except (TypeError, ValueError):
            seeded = 0.0
        if seeded != seeded or seeded < 0 or seeded == float("inf"):
            seeded = 0.0
        if option_positions is not None and seeded <= 0:
            seeded = outstanding_short_put_collateral_usd(option_positions)
        collateral_used = seeded
        for underlying in csp_tickers:
            und = str(underlying or "").upper()
            try:
                price = float(current_prices.get(und) or current_prices.get(underlying) or 0.0)
            except (TypeError, ValueError):
                price = 0.0
            if price != price or price <= 0 or price == float("inf"):
                price = 0.0
            try:
                score = int(csp_scores.get(und, csp_scores.get(underlying, 0)) or 0)
            except (TypeError, ValueError):
                score = 0
            if price <= 0 or score < 40:
                continue
            contract = self.select_put_contract(und, price, score, broker)
            if not contract:
                results.append({"underlying": und, "status": "skipped", "reason": "no contract"})
                continue
            needed = float(contract["strike"]) * 100.0
            if max_collateral_usd is not None and collateral_used + needed > float(max_collateral_usd):
                results.append(
                    {
                        "underlying": und,
                        "status": "skipped",
                        "reason": f"csp_collateral_cap_{collateral_used + needed:.0f}>{max_collateral_usd:.0f}",
                    }
                )
                continue
            order = broker.submit_option_order(
                contract_symbol=contract["symbol"],
                qty=1,
                side="sell",
                order_type="market",
                wait_fill=wait_fill,
                fill_timeout_s=45.0,
            )
            ok = bool(order) and order.get("fill_ok") is True
            if ok:
                collateral_used += needed
                from src.options.covered_calls import _contract_premium_usd

                est_prem = _contract_premium_usd(contract)
                try:
                    fill = (order or {}).get("fill") or {}
                    avg = float(fill.get("filled_avg_price") or order.get("filled_avg_price") or 0.0)
                    if avg > 0:
                        est_prem = abs(avg) * 100.0
                except (TypeError, ValueError):
                    pass
                results.append({
                    "underlying": und,
                    "status": "executed",
                    "contract_symbol": contract["symbol"],
                    "strike": contract["strike"],
                    "expiry": contract["expiry"],
                    "csp_score": score,
                    "collateral_usd": needed,
                    "estimated_premium": round(est_prem, 2),
                    "order": order,
                })
            else:
                results.append(
                    {
                        "underlying": und,
                        "status": "failed",
                        "reason": "order_or_fill",
                        "order": order,
                    }
                )
        logger.info(
            "CSP execution complete",
            n=len(results),
            ok=sum(1 for r in results if r.get("status") == "executed"),
            collateral_used=round(collateral_used, 2),
            collateral_seeded=round(seeded, 2),
        )
        return results
