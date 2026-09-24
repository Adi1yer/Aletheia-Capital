"""Covered call manager — identifies callable positions, selects strikes, and executes."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, List, Optional, Sequence, Set, Tuple, TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from src.broker.alpaca import AlpacaBroker
    from src.portfolio.models import Portfolio

logger = structlog.get_logger()

CC_LOT_SIZE = 100


def _long_qty(portfolio: "Portfolio", ticker: str) -> int:
    if hasattr(portfolio, "long_qty"):
        return int(portfolio.long_qty(ticker) or 0)
    pos = (getattr(portfolio, "positions", None) or {}).get(ticker)
    if pos is None:
        pos = (getattr(portfolio, "positions", None) or {}).get(str(ticker).upper())
    return int(getattr(pos, "long", 0) or 0) if pos else 0


def _finite_px(value) -> float:
    try:
        px = float(value)
    except (TypeError, ValueError):
        return 0.0
    if px != px or px <= 0:  # NaN != NaN
        return 0.0
    return px


def _short_call_strikes(option_positions: Optional[List[Dict]], underlying: str) -> List[float]:
    und = str(underlying or "").upper()
    out: List[float] = []
    from src.options.wheel_lifecycle import parse_occ_symbol

    for op in option_positions or []:
        if str(op.get("side") or "").lower() != "short":
            continue
        parsed = parse_occ_symbol(str(op.get("symbol") or ""))
        if not parsed or parsed.get("option_type") != "call":
            continue
        if str(parsed.get("underlying") or "").upper() != und:
            continue
        strike = _finite_px(parsed.get("strike"))
        if strike > 0:
            out.append(strike)
    return out


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


def short_call_qty_by_underlying(option_positions: Optional[List[Dict]] = None) -> Dict[str, int]:
    """Map underlying → total short call contracts."""
    out: Dict[str, int] = {}
    for op in option_positions or []:
        if str(op.get("side") or "").lower() != "short":
            continue
        sym = str(op.get("symbol") or "")
        otype = str(op.get("option_type") or "").lower()
        if not otype:
            try:
                from src.options.wheel_lifecycle import parse_occ_symbol

                parsed = parse_occ_symbol(sym)
                otype = str((parsed or {}).get("option_type") or "").lower()
            except Exception:
                otype = ""
        if otype != "call":
            compact = sym.replace(" ", "")
            if len(compact) >= 15 and compact[-9] == "C":
                otype = "call"
            else:
                continue
        und = str(op.get("underlying") or "").upper()
        if not und:
            try:
                from src.options.wheel_lifecycle import parse_occ_symbol

                und = str((parse_occ_symbol(sym) or {}).get("underlying") or "").upper()
            except Exception:
                und = ""
        if und:
            out[und] = out.get(und, 0) + int(op.get("qty") or 1)
    return out


def short_call_underlyings(option_positions: Optional[List[Dict]] = None) -> Set[str]:
    """Underlyings with an open short **call** (not puts)."""
    return set(short_call_qty_by_underlying(option_positions).keys())


def coverage_sto_qty(
    shares: int,
    short_call_qty: int,
    requested: int,
) -> int:
    """Max new short calls that stay covered: floor(shares/100) − existing shorts."""
    req = max(0, int(requested or 0))
    if req <= 0:
        return 0
    slots = max(0, int(shares or 0) // 100)
    need = max(0, slots - max(0, int(short_call_qty or 0)))
    return min(req, need)


def live_coverage_sto_qty(broker: "AlpacaBroker", underlying: str, requested: int) -> int:
    """Coverage-capped STO qty from live broker portfolio + short calls.

    Fail closed: if option positions cannot be fetched, return 0 (never assume
    short_q=0 and open a naked / overhedged short).
    """
    und = str(underlying or "").upper()
    req = max(0, int(requested or 0))
    if req <= 0 or not und:
        return 0
    try:
        portfolio = broker.sync_portfolio()
        shares = _long_qty(portfolio, und)
    except Exception:
        return 0
    try:
        opts = broker.get_option_positions()
    except Exception:
        return 0
    short_q = int(short_call_qty_by_underlying(opts or []).get(und) or 0)
    return coverage_sto_qty(shares, short_q, req)


class CoveredCallManager:
    """Identifies callable positions, picks contracts, and sells covered calls."""

    def __init__(
        self,
        min_premium_pct: float = 0.005,
        min_premium_usd: float = 15.0,
        *,
        otm_pct_low: float = 0.03,
        otm_pct_high: float = 0.08,
        target_otm_pct: float = 0.05,
        wait_fill: bool = True,
        fill_timeout_s: float = 45.0,
    ):
        self.min_premium_pct = min_premium_pct
        self.min_premium_usd = min_premium_usd
        self.otm_pct_low = otm_pct_low
        self.otm_pct_high = otm_pct_high
        self.target_otm_pct = target_otm_pct
        self.wait_fill = wait_fill
        self.fill_timeout_s = fill_timeout_s

    def preflight_underlying(
        self,
        underlying: str,
        current_price: float,
        broker: "AlpacaBroker",
        *,
        cc_score: int = 55,
    ) -> Tuple[bool, str]:
        contract, reason = self.select_contract(underlying, current_price, cc_score, broker)
        if contract is None:
            return False, reason or "preflight_failed"
        return True, ""

    def preflight_tickers(
        self,
        tickers: Sequence[str],
        current_prices: Dict[str, float],
        broker: "AlpacaBroker",
        *,
        cc_score: int = 55,
    ) -> Tuple[Set[str], Dict[str, str]]:
        ok: Set[str] = set()
        fails: Dict[str, str] = {}
        for t in tickers:
            ticker = str(t).upper().strip()
            if not ticker:
                continue
            px = float(current_prices.get(ticker) or 0.0)
            if px <= 0:
                fails[ticker] = "invalid_price"
                continue
            passed, reason = self.preflight_underlying(ticker, px, broker, cc_score=cc_score)
            if passed:
                ok.add(ticker)
            else:
                fails[ticker] = reason
        return ok, fails

    def identify_callable_positions(
        self,
        portfolio: "Portfolio",
        cc_lot_tickers: List[str],
        existing_option_positions: Optional[List[Dict]] = None,
    ) -> List[Dict]:
        """Find positions needing short calls (including underhedged top-ups)."""
        have_by_und = short_call_qty_by_underlying(existing_option_positions)

        candidates = []
        seen = set()
        for ticker in list(dict.fromkeys(list(cc_lot_tickers) + list((portfolio.positions or {}).keys()))):
            if ticker not in cc_lot_tickers:
                continue
            shares = _long_qty(portfolio, ticker)
            if shares < CC_LOT_SIZE:
                continue
            need_lots = int(shares) // CC_LOT_SIZE
            have = int(have_by_und.get(ticker, 0) or 0)
            extra = need_lots - have
            if extra <= 0:
                if have > 0:
                    logger.info("Skipping CC — fully covered", ticker=ticker, have=have)
                continue
            candidates.append(
                {
                    "ticker": ticker,
                    "callable_lots": extra,
                    "current_long": shares,
                    "short_calls_have": have,
                }
            )
            seen.add(ticker)

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
        *,
        expiry_gte_days: int = 14,
        expiry_lte_days: int = 45,
        strike_floor_otm: Optional[float] = None,
    ) -> Tuple[Optional[Dict], str]:
        if current_price <= 0:
            return None, "invalid_price"

        if cc_score >= 55:
            lo = max(self.otm_pct_low, self.target_otm_pct - 0.02)
            hi = min(self.otm_pct_high, self.target_otm_pct + 0.03)
            target = self.target_otm_pct
        else:
            lo = self.otm_pct_low
            hi = self.otm_pct_high
            target = self.target_otm_pct

        if strike_floor_otm is not None:
            lo = max(lo, float(strike_floor_otm))

        strike_low = current_price * (1.0 + lo)
        strike_high = current_price * (1.0 + hi)

        contracts = broker.get_option_contracts(
            underlying=underlying,
            option_type="call",
            expiry_gte=date.today() + timedelta(days=int(expiry_gte_days)),
            expiry_lte=date.today() + timedelta(days=int(expiry_lte_days)),
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
        min_strike = current_price * (1.0 + self.otm_pct_low)
        tradable = [c for c in tradable if float(c.get("strike") or 0) >= min_strike - 1e-6]
        if not tradable:
            return None, f"no_contracts_above_min_otm_{min_strike:.2f}"

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
        have_by_und = short_call_qty_by_underlying(existing_options)
        for ticker in flagged:
            if any(c["ticker"] == ticker for c in candidates):
                continue
            qty = _long_qty(portfolio, ticker)
            if qty < CC_LOT_SIZE:
                results.append(
                    {
                        "underlying": ticker,
                        "status": "skipped",
                        "reason": f"insufficient_shares_for_lot_{qty}<{CC_LOT_SIZE}",
                    }
                )
                continue
            need = qty // CC_LOT_SIZE
            have = int(have_by_und.get(ticker, 0) or 0)
            if have >= need:
                results.append(
                    {
                        "underlying": ticker,
                        "status": "skipped",
                        "reason": "already_has_short_call",
                    }
                )

        for cand in candidates:
            ticker = cand["ticker"]
            price = _finite_px(current_prices.get(ticker))
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

            lots = int(cand["callable_lots"])
            existing_strikes = _short_call_strikes(existing_options, ticker)
            # Cap and write one contract at a time; re-select so extra lots can
            # land at a different strike than the open short.
            filled_total = 0
            last_order = None
            last_contract = None
            last_reason = ""
            for _ in range(max(1, lots)):
                sto_qty = live_coverage_sto_qty(broker, ticker, 1)
                if sto_qty <= 0:
                    break
                floor = None
                if existing_strikes:
                    mx = max(existing_strikes)
                    floor = max(0.0, (mx / price) - 1.0 + 0.005)
                contract, reason = self.select_contract(
                    ticker, price, score, broker, strike_floor_otm=floor
                )
                last_reason = reason or last_reason
                if contract is None:
                    break
                last_contract = contract
                order = broker.submit_option_order(
                    contract_symbol=contract["symbol"],
                    qty=1,
                    side="sell",
                    order_type="market",
                    wait_fill=self.wait_fill,
                    fill_timeout_s=self.fill_timeout_s,
                )
                last_order = order
                if order and (not self.wait_fill or order.get("fill_ok") is True):
                    filled_total += 1
                    existing_strikes.append(_finite_px(contract.get("strike")))
                else:
                    break

            if filled_total > 0 and last_contract:
                prem = float(
                    last_contract.get("estimated_premium_usd")
                    or _contract_premium_usd(last_contract)
                )
                decision = CoveredCallDecision(
                    underlying=ticker,
                    contract_symbol=last_contract["symbol"],
                    strike=last_contract["strike"],
                    expiry=last_contract["expiry"],
                    contracts=filled_total,
                    estimated_premium=prem * filled_total,
                    cc_score=score,
                )
                status = "executed" if filled_total >= lots else "partial"
                results.append(
                    {
                        **decision.to_dict(),
                        "status": status,
                        "requested_contracts": lots,
                        "order": last_order,
                    }
                )
            elif last_order:
                results.append(
                    {
                        "underlying": ticker,
                        "contract_symbol": (last_contract or {}).get("symbol"),
                        "status": "failed",
                        "reason": f"sto_not_filled_{last_order.get('status') or (last_order.get('fill') or {}).get('status')}",
                        "order": last_order,
                    }
                )
            else:
                results.append(
                    {
                        "underlying": ticker,
                        "contract_symbol": (last_contract or {}).get("symbol"),
                        "status": "skipped" if last_reason else "failed",
                        "reason": last_reason or "order submission failed or no coverage slots",
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


def tickers_needing_atomic_unwind(
    cc_results: List[Dict],
    *,
    held_lot_tickers: Sequence[str],
    short_call_underlyings: Optional[Set[str]] = None,
    short_option_underlyings: Optional[Set[str]] = None,
) -> Set[str]:
    """
    Lots that still have ≥100 shares after a failed/skipped CC write.

    Insufficient-shares skips are excluded (equity fill pending — caller should wait).
    already_has_short_call skips are excluded.
    Never unwind while *any* short option (call or put) is open on the name.
    """
    short = {str(x).upper() for x in (short_option_underlyings or set())}
    if not short:
        short = {str(x).upper() for x in (short_call_underlyings or set())}
    held = {str(x).upper() for x in held_lot_tickers}
    out: Set[str] = set()
    for r in cc_results or []:
        status = str(r.get("status") or "")
        if status not in ("skipped", "failed", "error"):
            continue
        und = str(r.get("underlying") or "").upper()
        if not und or und not in held:
            continue
        if und in short:
            continue
        reason = str(r.get("reason") or "")
        if reason.startswith("insufficient_shares_for_lot"):
            continue
        if reason == "already_has_short_call":
            continue
        # Transient data / premium miss — leave lot for afternoon or next session.
        if reason in ("invalid_price", "no suitable contract", "no_contract_met_premium"):
            continue
        if reason.startswith("cc_score_below_threshold"):
            continue
        if reason.startswith("no_contracts_"):
            continue
        if reason.startswith("premium_below_"):
            continue
        out.add(und)
    return out
