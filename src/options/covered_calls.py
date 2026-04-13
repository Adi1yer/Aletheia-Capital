"""Covered call manager — identifies callable positions, selects strikes, and executes."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, List, Optional, TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from src.broker.alpaca import AlpacaBroker
    from src.portfolio.models import Portfolio

logger = structlog.get_logger()

CC_LOT_SIZE = 100


class CoveredCallDecision:
    """One covered-call write decision."""

    def __init__(
        self,
        underlying: str,
        contract_symbol: str,
        strike: float,
        expiry: str,
        contracts: int,
        estimated_premium: float,
        cc_score: int,
    ):
        self.underlying = underlying
        self.contract_symbol = contract_symbol
        self.strike = strike
        self.expiry = expiry
        self.contracts = contracts
        self.estimated_premium = estimated_premium
        self.cc_score = cc_score

    def to_dict(self) -> Dict:
        return {
            "underlying": self.underlying,
            "contract_symbol": self.contract_symbol,
            "strike": self.strike,
            "expiry": self.expiry,
            "contracts": self.contracts,
            "estimated_premium": round(self.estimated_premium, 2),
            "cc_score": self.cc_score,
        }


class CoveredCallManager:
    """Identifies callable positions, picks contracts, and sells covered calls."""

    def __init__(self, min_premium_pct: float = 0.005):
        self.min_premium_pct = min_premium_pct

    def identify_callable_positions(
        self,
        portfolio: "Portfolio",
        cc_lot_tickers: List[str],
        existing_option_positions: Optional[List[Dict]] = None,
    ) -> List[Dict]:
        """Find positions with >= 100 shares that are flagged as CC candidates.

        Returns a list of dicts: {ticker, callable_lots, current_long}.
        Excludes underlyings that already have an open short call position.
        """
        already_written = set()
        for op in (existing_option_positions or []):
            if op.get("side") == "short":
                already_written.add(op.get("underlying", ""))

        candidates = []
        for ticker in cc_lot_tickers:
            if ticker in already_written:
                logger.info("Skipping CC — already have open call", ticker=ticker)
                continue
            pos = portfolio.get_position(ticker)
            if pos and pos.long >= CC_LOT_SIZE:
                lots = pos.long // CC_LOT_SIZE
                candidates.append({
                    "ticker": ticker,
                    "callable_lots": lots,
                    "current_long": pos.long,
                })

        # Also check for pre-existing large positions not in cc_lot_tickers
        for ticker, pos in portfolio.positions.items():
            if ticker in already_written:
                continue
            if ticker in {c["ticker"] for c in candidates}:
                continue
            if pos.long >= CC_LOT_SIZE and ticker in cc_lot_tickers:
                lots = pos.long // CC_LOT_SIZE
                candidates.append({
                    "ticker": ticker,
                    "callable_lots": lots,
                    "current_long": pos.long,
                })

        logger.info("Callable positions identified", count=len(candidates), tickers=[c["ticker"] for c in candidates])
        return candidates

    def select_contract(
        self,
        underlying: str,
        current_price: float,
        cc_score: int,
        broker: "AlpacaBroker",
    ) -> Optional[Dict]:
        """Pick the best call contract given the CC score and current price.

        Strike selection:
          cc_score 55+  → ATM or 2-5% OTM (aggressive premium)
          cc_score 40-55 → 5-10% OTM (balanced)

        Returns a contract dict from broker or None if nothing suitable.
        """
        if current_price <= 0:
            return None

        if cc_score >= 55:
            strike_low = current_price * 1.00
            strike_high = current_price * 1.05
        else:
            strike_low = current_price * 1.05
            strike_high = current_price * 1.10

        contracts = broker.get_option_contracts(
            underlying=underlying,
            option_type="call",
            expiry_gte=date.today() + timedelta(days=14),
            expiry_lte=date.today() + timedelta(days=35),
            strike_gte=strike_low,
            strike_lte=strike_high,
            limit=20,
        )

        if not contracts:
            logger.info("No suitable contracts found", underlying=underlying, strike_range=(round(strike_low, 2), round(strike_high, 2)))
            return None

        tradable = [c for c in contracts if c.get("tradable", True)]
        if not tradable:
            tradable = contracts

        # Prefer the contract closest to our target strike with the nearest expiry
        target_strike = current_price * (1.03 if cc_score >= 55 else 1.07)
        tradable.sort(key=lambda c: (abs(c["strike"] - target_strike), c["expiry"]))

        best = tradable[0]

        estimated_premium = best.get("close_price", 0.0) * 100
        position_value = current_price * CC_LOT_SIZE
        if position_value > 0 and estimated_premium / position_value < self.min_premium_pct:
            logger.info(
                "Contract premium too low, skipping",
                underlying=underlying,
                premium=estimated_premium,
                position_value=position_value,
                pct=round(estimated_premium / position_value * 100, 3),
            )
            return None

        logger.info(
            "Contract selected",
            underlying=underlying,
            contract=best["symbol"],
            strike=best["strike"],
            expiry=best["expiry"],
            est_premium=round(estimated_premium, 2),
        )
        return best

    def execute_covered_calls(
        self,
        broker: "AlpacaBroker",
        portfolio: "Portfolio",
        cc_lot_tickers: List[str],
        cc_scores: Dict[str, int],
        current_prices: Dict[str, float],
    ) -> List[Dict]:
        """End-to-end: identify positions, select contracts, submit sell-to-open orders.

        Returns a list of execution result dicts.
        """
        existing_options = broker.get_option_positions()

        candidates = self.identify_callable_positions(
            portfolio, cc_lot_tickers, existing_options,
        )

        results: List[Dict] = []
        for cand in candidates:
            ticker = cand["ticker"]
            price = current_prices.get(ticker, 0.0)
            score = cc_scores.get(ticker, 0)
            if price <= 0 or score < 40:
                continue

            contract = self.select_contract(ticker, price, score, broker)
            if contract is None:
                results.append({
                    "underlying": ticker,
                    "status": "skipped",
                    "reason": "no suitable contract",
                })
                continue

            lots = cand["callable_lots"]
            order = broker.submit_option_order(
                contract_symbol=contract["symbol"],
                qty=lots,
                side="sell",
                order_type="market",
            )

            if order:
                decision = CoveredCallDecision(
                    underlying=ticker,
                    contract_symbol=contract["symbol"],
                    strike=contract["strike"],
                    expiry=contract["expiry"],
                    contracts=lots,
                    estimated_premium=contract.get("close_price", 0.0) * 100 * lots,
                    cc_score=score,
                )
                results.append({
                    **decision.to_dict(),
                    "status": "executed",
                    "order": order,
                })
            else:
                results.append({
                    "underlying": ticker,
                    "contract_symbol": contract["symbol"],
                    "status": "failed",
                    "reason": "order submission failed",
                })

        logger.info(
            "Covered call execution complete",
            total=len(results),
            executed=sum(1 for r in results if r.get("status") == "executed"),
            skipped=sum(1 for r in results if r.get("status") == "skipped"),
            failed=sum(1 for r in results if r.get("status") == "failed"),
        )
        return results
