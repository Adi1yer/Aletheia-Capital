"""Covered call manager — identifies callable positions, selects strikes, and executes."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

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


def _contract_premium_usd(contract: Dict) -> float:
    """Best available premium estimate (per share × 100)."""
    for key in ("mid_price", "close_price", "ask_price", "bid_price"):
        try:
            px = float(contract.get(key) or 0.0)
        except (TypeError, ValueError):
            px = 0.0
        if px > 0:
            return px * 100.0
    return 0.0


class CoveredCallManager:
    """Identifies callable positions, picks contracts, and sells covered calls."""

    def __init__(
        self,
        min_premium_pct: float = 0.005,
        min_premium_usd: float = 15.0,
        *,
        # Wheel-friendly default: 5–12% OTM (less assignment-chasing than ATM).
        otm_pct_low: float = 0.05,
        otm_pct_high: float = 0.12,
        target_otm_pct: float = 0.08,
    ):
        self.min_premium_pct = min_premium_pct
        self.min_premium_usd = min_premium_usd
        self.otm_pct_low = otm_pct_low
        self.otm_pct_high = otm_pct_high
        self.target_otm_pct = target_otm_pct

    def identify_callable_positions(
        self,
        portfolio: "Portfolio",
        cc_lot_tickers: List[str],
        existing_option_positions: Optional[List[Dict]] = None,
    ) -> List[Dict]:
        """Find positions with >= 100 shares that are flagged as CC candidates."""
        already_written = set()
        for op in existing_option_positions or []:
            if op.get("side") == "short":
                und = str(op.get("underlying") or "")
                if und:
                    already_written.add(und)

        candidates = []
        seen = set()
        for ticker in cc_lot_tickers:
            if ticker in already_written:
                logger.info("Skipping CC — already have open call", ticker=ticker)
                continue
            pos = portfolio.get_position(ticker)
            if pos and pos.long >= CC_LOT_SIZE:
                lots = pos.long // CC_LOT_SIZE
                candidates.append(
                    {
                        "ticker": ticker,
                        "callable_lots": lots,
                        "current_long": pos.long,
                    }
                )
                seen.add(ticker)

        for ticker, pos in portfolio.positions.items():
            if ticker in already_written or ticker in seen:
                continue
            if pos.long >= CC_LOT_SIZE and ticker in cc_lot_tickers:
                lots = pos.long // CC_LOT_SIZE
                candidates.append(
                    {
                        "ticker": ticker,
                        "callable_lots": lots,
                        "current_long": pos.long,
                    }
                )

        logger.info(
            "Callable positions identified",
            count=len(candidates),
            tickers=[c["ticker"] for c in candidates],
        )
        return candidates

    def select_contract(
        self,
        underlying: str,
        current_price: float,
        cc_score: int,
        broker: "AlpacaBroker",
    ) -> Tuple[Optional[Dict], str]:
        """
        Pick a call contract.

        Returns (contract, skip_reason). skip_reason is empty on success.

        Strike band comes from manager OTM settings (wheel defaults to 5–12% OTM).
        Legacy aggressive ATM behavior is available by constructing the manager with
        otm_pct_low=0.0 for high scores.
        """
        if current_price <= 0:
            return None, "invalid_price"

        # Mild score tilt: higher score → slightly closer to ATM within the band.
        if cc_score >= 55:
            lo = max(self.otm_pct_low, self.target_otm_pct - 0.03)
            hi = self.target_otm_pct + 0.02
            target = self.target_otm_pct
        else:
            lo = self.otm_pct_low
            hi = self.otm_pct_high
            target = self.target_otm_pct

        strike_low = current_price * (1.0 + lo)
        strike_high = current_price * (1.0 + hi)

        contracts = broker.get_option_contracts(
            underlying=underlying,
            option_type="call",
            expiry_gte=date.today() + timedelta(days=14),
            expiry_lte=date.today() + timedelta(days=35),
            strike_gte=strike_low,
            strike_lte=strike_high,
            limit=40,
        )

        if not contracts:
            return None, (
                f"no_contracts_in_otm_band_"
                f"{strike_low:.2f}-{strike_high:.2f}"
            )

        tradable = [c for c in contracts if c.get("tradable", True)] or list(contracts)
        target_strike = current_price * (1.0 + target)
        tradable.sort(key=lambda c: (abs(c["strike"] - target_strike), c["expiry"]))

        best = None
        last_reason = "no_contract_met_premium"
        for cand in tradable:
            estimated_premium = _contract_premium_usd(cand)
            position_value = current_price * CC_LOT_SIZE
            if estimated_premium < float(self.min_premium_usd):
                last_reason = (
                    f"premium_below_usd_floor_"
                    f"{estimated_premium:.2f}<{self.min_premium_usd:.2f}"
                )
                continue
            if position_value > 0 and estimated_premium / position_value < self.min_premium_pct:
                last_reason = (
                    f"premium_below_pct_floor_"
                    f"{estimated_premium / position_value * 100:.3f}%"
                )
                continue
            best = dict(cand)
            best["estimated_premium_usd"] = estimated_premium
            break

        if best is None:
            return None, last_reason

        logger.info(
            "Contract selected",
            underlying=underlying,
            contract=best["symbol"],
            strike=best["strike"],
            expiry=best["expiry"],
            est_premium=round(float(best.get("estimated_premium_usd") or 0), 2),
            otm_pct=round((float(best["strike"]) / current_price - 1.0) * 100, 2),
        )
        return best, ""

    def execute_covered_calls(
        self,
        broker: "AlpacaBroker",
        portfolio: "Portfolio",
        cc_lot_tickers: List[str],
        cc_scores: Dict[str, int],
        current_prices: Dict[str, float],
    ) -> List[Dict]:
        """End-to-end: identify positions, select contracts, submit sell-to-open orders."""
        existing_options = broker.get_option_positions()

        candidates = self.identify_callable_positions(
            portfolio,
            cc_lot_tickers,
            existing_options,
        )

        flagged = set(cc_lot_tickers)
        results: List[Dict] = []
        # Explicit skip when flagged but not yet 100 shares (pending equity fill).
        for ticker in flagged:
            if any(c["ticker"] == ticker for c in candidates):
                continue
            pos = portfolio.get_position(ticker)
            qty = int(getattr(pos, "long", 0) or 0) if pos else 0
            if qty < CC_LOT_SIZE:
                results.append(
                    {
                        "underlying": ticker,
                        "status": "skipped",
                        "reason": f"insufficient_shares_for_lot_{qty}<{CC_LOT_SIZE}",
                    }
                )

        for cand in candidates:
            ticker = cand["ticker"]
            price = float(current_prices.get(ticker, 0.0) or 0.0)
            score = int(cc_scores.get(ticker, 0) or 0)
            if price <= 0:
                results.append(
                    {"underlying": ticker, "status": "skipped", "reason": "invalid_price"}
                )
                continue
            if score < 40:
                results.append(
                    {
                        "underlying": ticker,
                        "status": "skipped",
                        "reason": f"cc_score_below_threshold_{score}<40",
                    }
                )
                continue

            contract, reason = self.select_contract(ticker, price, score, broker)
            if contract is None:
                results.append(
                    {
                        "underlying": ticker,
                        "status": "skipped",
                        "reason": reason or "no suitable contract",
                    }
                )
                continue

            lots = cand["callable_lots"]
            order = broker.submit_option_order(
                contract_symbol=contract["symbol"],
                qty=lots,
                side="sell",
                order_type="market",
            )
            prem = float(contract.get("estimated_premium_usd") or _contract_premium_usd(contract))
            if order:
                decision = CoveredCallDecision(
                    underlying=ticker,
                    contract_symbol=contract["symbol"],
                    strike=contract["strike"],
                    expiry=contract["expiry"],
                    contracts=lots,
                    estimated_premium=prem * lots,
                    cc_score=score,
                )
                results.append({**decision.to_dict(), "status": "executed", "order": order})
            else:
                results.append(
                    {
                        "underlying": ticker,
                        "contract_symbol": contract["symbol"],
                        "status": "failed",
                        "reason": "order submission failed",
                    }
                )

        logger.info(
            "Covered call execution complete",
            total=len(results),
            executed=sum(1 for r in results if r.get("status") == "executed"),
            skipped=sum(1 for r in results if r.get("status") == "skipped"),
            failed=sum(1 for r in results if r.get("status") == "failed"),
        )
        return results
