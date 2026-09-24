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


def _option_qty(op: Optional[Dict]) -> int:
    """Contract count. Missing qty → 1; explicit 0 stays 0; never negative."""
    if not op:
        return 0
    raw = op.get("qty")
    if raw is None or raw == "":
        return 1
    try:
        return max(0, abs(int(float(raw))))
    except (TypeError, ValueError):
        return 1


def _inferred_short_floors(cc_results: Optional[List[Dict]] = None) -> Dict[str, int]:
    """Min shorts implied by this session's writes: prior + filled (not live + filled)."""
    out: Dict[str, int] = {}
    for r in cc_results or []:
        st = str(r.get("status") or "")
        if st not in ("executed", "partial"):
            continue
        und = str(r.get("underlying") or "").upper()
        try:
            n = int(r.get("contracts") or 0)
            prior = int(r.get("prior_short_calls") or 0)
        except (TypeError, ValueError):
            n, prior = 0, 0
        if und:
            out[und] = max(out.get(und, 0), prior + max(0, n))
    return out


def _working_short_calls(open_orders: Optional[List[Dict]] = None) -> Dict[str, int]:
    """Unfilled sell-to-open calls still working (do not trim under those)."""
    out: Dict[str, int] = {}
    if not open_orders:
        return out
    from src.options.wheel_lifecycle import parse_occ_symbol

    terminal = {
        "filled",
        "canceled",
        "cancelled",
        "expired",
        "rejected",
        "replaced",
        "done_for_day",
    }
    for o in open_orders:
        if str(o.get("side") or "").lower() not in ("sell", "sell_short"):
            continue
        if str(o.get("status") or "").lower() in terminal:
            continue
        parsed = parse_occ_symbol(str(o.get("symbol") or ""))
        if not parsed or parsed.get("option_type") != "call":
            continue
        und = str(parsed.get("underlying") or "").upper()
        q = _option_qty(o)
        if und and q > 0:
            out[und] = out.get(und, 0) + q
    return out


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
        qty = _option_qty(op)
        if und and qty:
            out[und] = out.get(und, 0) + qty
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
            px = _finite_px(
                current_prices.get(ticker)
                or current_prices.get(str(ticker).upper())
            )
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

        flagged = {str(t).upper() for t in cc_lot_tickers if str(t).strip()}
        candidates = []
        seen: Set[str] = set()
        for ticker in list(dict.fromkeys(list(cc_lot_tickers) + list((portfolio.positions or {}).keys()))):
            ticker = str(ticker or "").upper()
            if ticker not in flagged or ticker in seen:
                continue
            seen.add(ticker)
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
            floor = max(0.0, float(strike_floor_otm))
            lo = max(lo, floor)
            # Existing extra-lot shorts often sit near the top of the 3–8% band.
            # Without widening, lo>hi → empty chain → skip → trim the new shares.
            if lo > hi + 1e-12:
                hi = lo + max(0.02, float(self.otm_pct_high) - float(self.otm_pct_low))

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
        try:
            live_port = broker.sync_portfolio()
            if live_port is not None:
                portfolio = live_port
        except Exception:
            pass
        prices = {str(k).upper(): v for k, v in (current_prices or {}).items()}
        scores = {}
        for k, v in (cc_scores or {}).items():
            try:
                scores[str(k).upper()] = int(v or 0)
            except (TypeError, ValueError):
                scores[str(k).upper()] = 0

        existing_options = broker.get_option_positions()

        candidates = self.identify_callable_positions(
            portfolio,
            cc_lot_tickers,
            existing_options,
        )

        flagged = {str(t).upper() for t in cc_lot_tickers if str(t).strip()}
        results: List[Dict] = []
        have_by_und = short_call_qty_by_underlying(existing_options)
        for ticker in flagged:
            if any(str(c["ticker"]).upper() == ticker for c in candidates):
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
            ticker = str(cand["ticker"] or "").upper()
            price = _finite_px(prices.get(ticker))
            score = int(scores.get(ticker, 0) or 0)
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
            have0 = int(cand.get("short_calls_have") or 0)
            shares0 = int(cand.get("current_long") or 0)
            existing_strikes = _short_call_strikes(existing_options, ticker)
            # Cap and write one contract at a time; re-select so extra lots can
            # land at a different strike than the open short.
            filled_total = 0
            last_order = None
            last_contract = None
            last_reason = ""
            for _ in range(max(1, lots)):
                sto_qty = live_coverage_sto_qty(broker, ticker, 1)
                # Local cap: a stale option snapshot must not let us write past
                # the lots we already counted as filled this loop.
                if coverage_sto_qty(shares0, have0 + filled_total, 1) <= 0:
                    break
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
                        "prior_short_calls": have0,
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


def uncovered_excess_shares(shares: int, short_call_qty: int) -> int:
    """Shares to sell so an already-short name is not left with a full uncovered lot.

    Only trims when at least one short call is open (the covered lot stays).
    200 sh / 1 call → 100; 250 sh / 1 call → 150; 100 sh / 1 call → 0.
    """
    sh = int(shares or 0)
    sc = int(short_call_qty or 0)
    if sc < 1 or sh <= sc * CC_LOT_SIZE:
        return 0
    return sh - sc * CC_LOT_SIZE


def underhedge_trim_orders(
    portfolio: "Portfolio",
    option_positions: Optional[List[Dict]],
    extra_short_calls: Optional[Dict[str, int]] = None,
    working_short_calls: Optional[Dict[str, int]] = None,
) -> List[Tuple[str, int]]:
    have = short_call_qty_by_underlying(option_positions)
    for k, v in (extra_short_calls or {}).items():
        und = str(k).upper()
        try:
            floor = int(v or 0)
        except (TypeError, ValueError):
            floor = 0
        if und and floor:
            have[und] = max(int(have.get(und, 0) or 0), floor)
    for k, v in (working_short_calls or {}).items():
        und = str(k).upper()
        try:
            add = int(v or 0)
        except (TypeError, ValueError):
            add = 0
        if und and add:
            have[und] = int(have.get(und, 0) or 0) + add
    out: List[Tuple[str, int]] = []
    for t in (getattr(portfolio, "positions", None) or {}):
        qty = _long_qty(portfolio, t)
        extra = uncovered_excess_shares(qty, int(have.get(str(t).upper(), 0) or 0))
        if extra > 0:
            out.append((str(t).upper(), extra))
    return out


def apply_underhedge_trims(
    broker: "AlpacaBroker",
    current_prices: Optional[Dict[str, float]],
    results: List[Dict],
) -> List[Dict]:
    """Sell uncovered extra lots after a CC miss; keep the already-covered lot."""
    try:
        port = broker.sync_portfolio()
        opts = broker.get_option_positions() or []
    except Exception as e:
        logger.error("Underhedge trim skipped — option/portfolio sync failed", error=str(e))
        results.append({"status": "skipped", "reason": "underhedge_trim_positions_unavailable"})
        return results

    open_orders: List[Dict] = []
    if hasattr(broker, "get_open_orders"):
        try:
            open_orders = broker.get_open_orders(limit=100) or []
        except Exception as e:
            logger.warning("Open orders unavailable for underhedge credit", error=str(e))

    inferred = _inferred_short_floors(results)
    working = _working_short_calls(open_orders)
    from src.portfolio.manager import PortfolioDecision

    prices = {str(k).upper(): v for k, v in (current_prices or {}).items()}
    for ticker, qty in underhedge_trim_orders(
        port, opts, extra_short_calls=inferred, working_short_calls=working
    ):
        try:
            order = broker.execute_order(
                ticker,
                PortfolioDecision(
                    action="sell",
                    quantity=qty,
                    confidence=90,
                    reasoning="Trim uncovered extra lot — CC write missed",
                ),
                current_price=_finite_px(prices.get(ticker)) or None,
            )
            fill = None
            ok = False
            if isinstance(order, dict) and order.get("success") is False:
                oid = ""
            elif order and hasattr(broker, "wait_for_order_fill"):
                oid = str(order.get("order_id") or order.get("id") or "")
                if oid:
                    fill = broker.wait_for_order_fill(
                        oid, timeout_s=60.0, min_filled_qty=qty
                    )
                    ok = bool(fill.get("ok"))
            results.append(
                {
                    "underlying": ticker,
                    "status": "underhedge_trim" if ok else "underhedge_trim_failed",
                    "quantity": qty,
                    "order": order,
                    "fill": fill,
                    "reason": "uncovered_extra_lot_after_cc",
                }
            )
        except Exception as e:
            results.append(
                {
                    "underlying": ticker,
                    "status": "underhedge_trim_failed",
                    "quantity": qty,
                    "reason": str(e)[:200],
                }
            )
    return results
