"""Wheel lifecycle: manage short options (BTC / roll), track CSP↔CC handoff state."""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from src.broker.alpaca import AlpacaBroker
    from src.options.covered_calls import CoveredCallManager
    from src.portfolio.models import Portfolio

logger = structlog.get_logger()

STATE_PATH = Path("data/performance/wheel_state.json")
OCC_RE = re.compile(r"^([A-Z]+)(\d{6})([CP])(\d{8})$")


def parse_occ_symbol(symbol: str) -> Optional[Dict[str, Any]]:
    """Parse OCC option symbol → underlying, expiry, type, strike."""
    sym = (symbol or "").strip().upper()
    m = OCC_RE.match(sym)
    if not m:
        # Alpaca sometimes pads root to 6 chars with spaces — strip internals.
        compact = sym.replace(" ", "")
        m = OCC_RE.match(compact)
    if not m:
        return None
    root, yymmdd, cp, strike_raw = m.groups()
    try:
        exp = datetime.strptime(yymmdd, "%y%m%d").date()
    except ValueError:
        return None
    strike = int(strike_raw) / 1000.0
    return {
        "underlying": root,
        "expiry": exp.isoformat(),
        "option_type": "call" if cp == "C" else "put",
        "strike": strike,
        "symbol": sym,
    }


def load_wheel_state(path: Path = STATE_PATH) -> Dict[str, Any]:
    if not path.is_file():
        return {"names": {}, "updated_at": None}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"names": {}, "updated_at": None}


def save_wheel_state(state: Dict[str, Any], path: Path = STATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    state = dict(state)
    state["updated_at"] = datetime.utcnow().isoformat() + "Z"
    path.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")


def dte_from_expiry(expiry: str, today: Optional[date] = None) -> int:
    today = today or date.today()
    try:
        exp = date.fromisoformat(str(expiry)[:10])
    except ValueError:
        return 999
    return (exp - today).days


def short_option_profit_pct(pos: Dict[str, Any]) -> Optional[float]:
    """Fraction of max credit captured (0–1) for a short option, if prices known."""
    try:
        entry = float(pos.get("avg_entry_price") or pos.get("avg_entry") or 0.0)
        cur = float(
            pos.get("current_price")
            or pos.get("mark_price")
            or 0.0
        )
    except (TypeError, ValueError):
        return None
    if entry != entry or entry <= 0 or entry == float("inf"):
        return None
    # Require a real mark — zero/missing must not look like 100% profit.
    if cur != cur or cur <= 0 or cur == float("inf"):
        return None
    # Marks from AlpacaBroker.get_option_positions are already per-share.
    # Do NOT ÷100 here: that turns a losing ITM short (mark ≫ entry) into a
    # fake ~95% profit_take and blocks near-ITM debit rolls.
    return max(0.0, min(1.0, (entry - abs(cur)) / entry))


def _order_fill_confirmed(order: Optional[Dict[str, Any]], broker: Any = None) -> bool:
    """True only when fill is explicitly confirmed (never assume missing == ok)."""
    if not order:
        return False
    if order.get("submitted") is False:
        return False
    if order.get("fill_ok") is True:
        return True
    fill = order.get("fill")
    if isinstance(fill, dict) and fill.get("ok") is True:
        return True
    if "fill_ok" in order or isinstance(fill, dict):
        return False
    oid = str(order.get("order_id") or order.get("id") or "")
    if broker is not None and oid and hasattr(broker, "wait_for_order_fill"):
        fill2 = broker.wait_for_order_fill(oid, timeout_s=45.0)
        order["fill"] = fill2
        order["fill_ok"] = bool(fill2.get("ok"))
        return bool(fill2.get("ok"))
    return False


def should_manage_short(
    *,
    option_type: str,
    strike: float,
    underlying_price: float,
    dte: int,
    manage_dte_threshold: int = 7,
    manage_itm_pct: float = 0.02,
    profit_pct: Optional[float] = None,
    profit_take_pct: float = 0.60,
) -> tuple[bool, str]:
    """Return (manage?, reason) for buy-to-close / roll.

    Near-ITM / short-DTE take priority over profit-take so debit-roll policy
    applies when assignment risk is real (even if marks also show profit).
    """
    if dte <= int(manage_dte_threshold):
        return True, f"dte<={manage_dte_threshold}"
    if underlying_price > 0 and strike > 0:
        if option_type == "call" and underlying_price >= strike * (1.0 - float(manage_itm_pct)):
            return True, "call_near_itm"
        if option_type == "put" and underlying_price <= strike * (1.0 + float(manage_itm_pct)):
            return True, "put_near_itm"
    if profit_pct is not None and profit_pct >= float(profit_take_pct):
        return True, f"profit_take>={profit_take_pct:.0%}"
    return False, ""


def manage_short_options(
    broker: "AlpacaBroker",
    current_prices: Dict[str, float],
    *,
    manage_dte_threshold: int = 7,
    manage_itm_pct: float = 0.02,
    profit_take_pct: float = 0.60,
    execute: bool = True,
) -> List[Dict[str, Any]]:
    """Buy-to-close short options that are near expiry, near ITM, or profit-taken."""
    results: List[Dict[str, Any]] = []
    try:
        positions = broker.get_option_positions() if broker else []
    except Exception as e:
        logger.error("Option positions unavailable; skip manage/BTC", error=str(e))
        return [{"status": "error", "reason": "option_positions_unavailable"}]
    from src.options.covered_calls import _finite_px

    for pos in positions or []:
        if str(pos.get("side") or "").lower() != "short":
            continue
        symbol = str(pos.get("symbol") or "")
        parsed = parse_occ_symbol(symbol)
        if not parsed:
            und = str(pos.get("underlying") or "").upper()
            results.append(
                {
                    "contract_symbol": symbol,
                    "status": "skipped",
                    "reason": "unparsed_symbol",
                    "underlying": und,
                }
            )
            continue
        und = parsed["underlying"]
        px = _finite_px(current_prices.get(und) or current_prices.get(str(und).upper()))
        dte = dte_from_expiry(parsed["expiry"])
        profit_pct = short_option_profit_pct(pos)
        manage, reason = should_manage_short(
            option_type=parsed["option_type"],
            strike=float(parsed["strike"]),
            underlying_price=px,
            dte=dte,
            manage_dte_threshold=manage_dte_threshold,
            manage_itm_pct=manage_itm_pct,
            profit_pct=profit_pct,
            profit_take_pct=profit_take_pct,
        )
        if not manage:
            results.append(
                {
                    "contract_symbol": symbol,
                    "underlying": und,
                    "status": "hold",
                    "dte": dte,
                    "reason": "within_band",
                    "option_type": parsed["option_type"],
                }
            )
            continue
        try:
            qty = int(pos.get("qty") or 0)
        except (TypeError, ValueError):
            qty = 0
        if qty <= 0:
            continue
        # Capture mark before close for roll net-credit checks (per-share × 100).
        mark = 0.0
        try:
            entry = float(pos.get("avg_entry_price") or pos.get("avg_entry") or 0.0)
            cur = float(pos.get("current_price") or pos.get("mark_price") or 0.0)
            # Per-share marks only — never ÷100 (see short_option_profit_pct).
            mark = abs(cur) if cur else entry
        except (TypeError, ValueError):
            mark = 0.0
        btc_cost_usd = mark * 100.0 * max(qty, 1)

        if not execute:
            results.append(
                {
                    "contract_symbol": symbol,
                    "underlying": und,
                    "status": "would_btc",
                    "reason": reason,
                    "dte": dte,
                    "qty": qty,
                    "option_type": parsed["option_type"],
                    "btc_cost_usd": round(btc_cost_usd, 2),
                    "strike": float(parsed["strike"]),
                }
            )
            continue
        order = broker.submit_option_order(
            contract_symbol=symbol,
            qty=qty,
            side="buy",
            order_type="market",
            wait_fill=True,
            fill_timeout_s=45.0,
        )
        filled_ok = _order_fill_confirmed(order, broker)
        # Prefer actual fill price for roll debit math when marks were missing/stale.
        if filled_ok and order:
            try:
                fill = order.get("fill") or {}
                avg = float(
                    fill.get("filled_avg_price")
                    or order.get("filled_avg_price")
                    or 0.0
                )
                if avg > 0:
                    btc_cost_usd = abs(avg) * 100.0 * max(qty, 1)
            except (TypeError, ValueError):
                pass
        results.append(
            {
                "contract_symbol": symbol,
                "underlying": und,
                "status": "btc_executed" if filled_ok else "btc_failed",
                "reason": reason,
                "dte": dte,
                "qty": qty,
                "order": order,
                "action": "buy_to_close",
                "option_type": parsed["option_type"],
                "btc_cost_usd": round(btc_cost_usd, 2),
                "strike": float(parsed["strike"]),
            }
        )
    logger.info(
        "Wheel option manage complete",
        n=len(results),
        btc=sum(1 for r in results if r.get("status") == "btc_executed"),
    )
    return results


def manage_or_roll_short_calls(
    broker: "AlpacaBroker",
    current_prices: Dict[str, float],
    cc_manager: "CoveredCallManager",
    *,
    manage_dte_threshold: int = 7,
    manage_itm_pct: float = 0.02,
    profit_take_pct: float = 0.60,
    prefer_roll: bool = True,
    execute: bool = True,
    cc_score: int = 55,
    max_roll_debit_usd: float = 25.0,
    max_roll_debit_pct_of_premium: float = 0.25,
) -> List[Dict[str, Any]]:
    """
    BTC threatened short calls, then attempt same-session roll (STO).

    Debit policy B:
    - near-ITM / short DTE: allow debit ≤ max($25, 25% of new premium)
    - profit-take: credit-only
    Puts are BTC-only.
    """
    from src.options.covered_calls import _contract_premium_usd, _finite_px

    base = manage_short_options(
        broker,
        current_prices,
        manage_dte_threshold=manage_dte_threshold,
        manage_itm_pct=manage_itm_pct,
        profit_take_pct=profit_take_pct,
        execute=execute,
    )
    results: List[Dict[str, Any]] = []
    for row in base:
        results.append(row)
        if not prefer_roll:
            continue
        if row.get("status") not in ("btc_executed", "would_btc"):
            continue
        if str(row.get("option_type") or "") != "call":
            continue

        reason = str(row.get("reason") or "")
        und = str(row.get("underlying") or "").upper()
        if not und:
            continue
        is_call_threat = reason in ("call_near_itm",) or reason.startswith("dte<=")
        is_profit_take = "profit_take" in reason
        if not is_call_threat and not is_profit_take:
            continue

        px = _finite_px(current_prices.get(und) or current_prices.get(str(und).upper()))
        try:
            qty = int(row.get("qty") or 0)
        except (TypeError, ValueError):
            qty = 0
        if qty <= 0:
            continue
        if px <= 0:
            results.append(
                {
                    "underlying": und,
                    "status": "ambiguous",
                    "action": "roll",
                    "reason": "missing_underlying_price",
                    "old_contract": row.get("contract_symbol"),
                    "option_type": "call",
                    "qty": qty,
                }
            )
            continue

        new_contract, skip = cc_manager.select_contract(
            und,
            px,
            cc_score,
            broker,
            expiry_gte_days=21,
            expiry_lte_days=45,
            strike_floor_otm=cc_manager.otm_pct_low,
        )
        if new_contract is None:
            results.append(
                {
                    "underlying": und,
                    "status": "ambiguous",
                    "action": "roll",
                    "reason": skip or "no_roll_candidate",
                    "old_contract": row.get("contract_symbol"),
                    "option_type": "call",
                    "qty": qty,
                }
            )
            continue

        new_prem_one = float(
            new_contract.get("estimated_premium_usd") or _contract_premium_usd(new_contract)
        )
        btc_cost_full = float(row.get("btc_cost_usd") or 0.0)
        if btc_cost_full <= 1e-6:
            results.append(
                {
                    "underlying": und,
                    "status": "ambiguous",
                    "action": "roll",
                    "reason": "btc_cost_unknown",
                    "old_contract": row.get("contract_symbol"),
                    "new_contract": new_contract.get("symbol"),
                    "option_type": "call",
                    "qty": qty,
                }
            )
            continue

        from src.options.covered_calls import coverage_sto_qty, live_coverage_sto_qty

        # After BTC, only rewrite covered slots. Excess BTC was flatten cost, not roll debit.
        if row.get("status") == "would_btc":
            # Dry-run: assume BTC clears this short; cap by share slots only.
            try:
                port = broker.sync_portfolio()
                if hasattr(port, "long_qty"):
                    shares = int(port.long_qty(und) or 0)
                else:
                    pos = (getattr(port, "positions", None) or {}).get(und)
                    shares = int(getattr(pos, "long", 0) or 0) if pos else 0
                sto_qty = coverage_sto_qty(shares, 0, qty)
            except Exception:
                sto_qty = 0
        else:
            sto_qty = live_coverage_sto_qty(broker, und, qty)
        if sto_qty <= 0:
            results.append(
                {
                    "underlying": und,
                    "status": "ambiguous" if execute else "would_roll_blocked",
                    "action": "roll",
                    "reason": "no_share_coverage_for_roll_sto",
                    "old_contract": row.get("contract_symbol"),
                    "new_contract": new_contract.get("symbol"),
                    "option_type": "call",
                    "qty": 0,
                    "requested_qty": qty,
                }
            )
            continue

        new_prem = new_prem_one * sto_qty
        btc_cost = btc_cost_full * (sto_qty / float(max(qty, 1)))
        net_credit = new_prem - btc_cost
        debit_cap = max(
            float(max_roll_debit_usd) * sto_qty,
            float(max_roll_debit_pct_of_premium) * max(new_prem, 0.0),
        )

        if is_profit_take and net_credit < -1e-6:
            results.append(
                {
                    "underlying": und,
                    "status": "ambiguous",
                    "action": "roll",
                    "reason": f"profit_take_requires_credit_{net_credit:.2f}",
                    "old_contract": row.get("contract_symbol"),
                    "new_contract": new_contract.get("symbol"),
                    "est_new_premium": new_prem,
                    "est_net_credit": net_credit,
                    "option_type": "call",
                    "qty": sto_qty,
                }
            )
            continue
        if is_call_threat and net_credit < 0 and abs(net_credit) > debit_cap + 1e-6:
            results.append(
                {
                    "underlying": und,
                    "status": "ambiguous",
                    "action": "roll",
                    "reason": f"roll_debit_exceeds_cap_{net_credit:.2f}",
                    "old_contract": row.get("contract_symbol"),
                    "new_contract": new_contract.get("symbol"),
                    "est_new_premium": new_prem,
                    "est_net_credit": net_credit,
                    "option_type": "call",
                    "qty": sto_qty,
                }
            )
            continue

        if not execute or row.get("status") == "would_btc":
            results.append(
                {
                    "underlying": und,
                    "status": "would_roll",
                    "action": "roll",
                    "old_contract": row.get("contract_symbol"),
                    "new_contract": new_contract.get("symbol"),
                    "new_strike": new_contract.get("strike"),
                    "new_expiry": new_contract.get("expiry"),
                    "est_new_premium": new_prem,
                    "est_net_credit": net_credit,
                    "reason": reason,
                    "option_type": "call",
                    "qty": sto_qty,
                }
            )
            continue

        qty = sto_qty
        # Write one contract at a time so partial fills cannot leave a multi-lot
        # roll half-done with the agent retrying the full original qty.
        filled_total = 0
        last_order = None
        for _ in range(max(1, qty)):
            slot = live_coverage_sto_qty(broker, und, 1)
            if slot <= 0:
                break
            order = broker.submit_option_order(
                contract_symbol=str(new_contract["symbol"]),
                qty=1,
                side="sell",
                order_type="market",
                wait_fill=True,
                fill_timeout_s=45.0,
            )
            last_order = order
            if _order_fill_confirmed(order, broker):
                filled_total += 1
            else:
                break

        if filled_total >= qty:
            results.append(
                {
                    "underlying": und,
                    "status": "roll_executed",
                    "action": "roll",
                    "old_contract": row.get("contract_symbol"),
                    "new_contract": new_contract.get("symbol"),
                    "new_strike": new_contract.get("strike"),
                    "new_expiry": new_contract.get("expiry"),
                    "est_new_premium": new_prem_one * filled_total,
                    "est_net_credit": (new_prem_one * filled_total)
                    - (btc_cost_full * (filled_total / float(max(int(row.get("qty") or qty), 1)))),
                    "reason": reason,
                    "order": last_order,
                    "option_type": "call",
                    "qty": filled_total,
                }
            )
        elif filled_total > 0:
            results.append(
                {
                    "underlying": und,
                    "status": "roll_partial",
                    "action": "roll",
                    "reason": "roll_sto_partial_fill",
                    "old_contract": row.get("contract_symbol"),
                    "new_contract": new_contract.get("symbol"),
                    "new_strike": new_contract.get("strike"),
                    "new_expiry": new_contract.get("expiry"),
                    "option_type": "call",
                    "qty": filled_total,
                    "requested_qty": qty,
                    "order": last_order,
                }
            )
            # Remainder for agent top-up (coverage-capped).
            remaining = max(0, qty - filled_total)
            if remaining > 0:
                results.append(
                    {
                        "underlying": und,
                        "status": "ambiguous",
                        "action": "roll",
                        "reason": "roll_sto_not_filled",
                        "old_contract": row.get("contract_symbol"),
                        "new_contract": new_contract.get("symbol"),
                        "option_type": "call",
                        "qty": remaining,
                        "requested_qty": qty,
                        "partial_filled_qty": filled_total,
                        "order": last_order,
                    }
                )
        else:
            results.append(
                {
                    "underlying": und,
                    "status": "ambiguous",
                    "action": "roll",
                    "reason": "roll_sto_not_filled",
                    "old_contract": row.get("contract_symbol"),
                    "new_contract": new_contract.get("symbol"),
                    "option_type": "call",
                    "qty": qty,
                    "requested_qty": qty,
                    "partial_filled_qty": 0,
                    "order": last_order,
                }
            )

    logger.info(
        "Wheel manage_or_roll complete",
        n=len(results),
        rolls=sum(1 for r in results if r.get("status") == "roll_executed"),
        ambiguous=sum(1 for r in results if r.get("status") == "ambiguous"),
    )
    return results


def sync_wheel_assignment_state(
    portfolio: "Portfolio",
    option_positions: List[Dict[str, Any]],
    *,
    path: Path = STATE_PATH,
    max_underlying_price: float = 35.0,
    current_prices: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """
    Update per-name wheel stage from broker reality.

    Stages: cash | short_put | long_shares | short_call
    """
    state = load_wheel_state(path)
    names: Dict[str, Any] = dict(state.get("names") or {})
    prices = current_prices or {}

    short_by_und: Dict[str, str] = {}
    for pos in option_positions or []:
        if str(pos.get("side") or "").lower() != "short":
            continue
        parsed = parse_occ_symbol(str(pos.get("symbol") or ""))
        und = (parsed or {}).get("underlying") or str(pos.get("underlying") or "").upper()
        otype = (parsed or {}).get("option_type") or ""
        if und:
            short_by_und[und] = otype or short_by_und.get(und, "")

    # Scan equity positions for wheel lots.
    for raw_t, pos in list((getattr(portfolio, "positions", None) or {}).items()):
        t = str(raw_t).upper()
        qty = int(getattr(pos, "long", 0) or 0)
        if qty < 100:
            continue
        # Keep tagging graduated (≥ soft-max) lots — they remain wheel CC inventory.
        prev = dict(names.get(t) or names.get(raw_t) or {})
        otype = short_by_und.get(t, "")
        if otype == "call":
            stage = "short_call"
        elif otype == "put":
            stage = "short_put"
        else:
            stage = "long_shares"
            if prev.get("stage") == "short_put":
                prev["event"] = "csp_assigned"
        prev.update({"stage": stage, "shares": qty, "ticker": t})
        names[t] = prev

    # Short puts without shares yet.
    for und, otype in short_by_und.items():
        if otype != "put":
            continue
        row = dict(names.get(und) or {})
        shares = int(row.get("shares") or 0)
        if shares < 100:
            row.update({"stage": "short_put", "ticker": und, "shares": shares})
            names[und] = row

    # Called away: had short_call / long_shares, now no shares and no short call.
    for t, row in list(names.items()):
        tu = str(t).upper()
        if hasattr(portfolio, "long_qty"):
            qty = int(portfolio.long_qty(tu) or 0)
        else:
            pos = (getattr(portfolio, "positions", None) or {}).get(tu) or (
                getattr(portfolio, "positions", None) or {}
            ).get(t)
            qty = int(getattr(pos, "long", 0) or 0) if pos else 0
        if row.get("stage") in ("short_call", "long_shares") and qty < 100 and tu not in short_by_und:
            names[t] = {
                **row,
                "stage": "cash",
                "shares": qty,
                "event": "cc_assigned_or_sold",
            }

    state["names"] = names
    save_wheel_state(state, path)
    return state


def short_option_underlyings(option_positions: List[Dict[str, Any]]) -> set:
    out = set()
    for pos in option_positions or []:
        if str(pos.get("side") or "").lower() != "short":
            continue
        parsed = parse_occ_symbol(str(pos.get("symbol") or ""))
        und = (parsed or {}).get("underlying") or str(pos.get("underlying") or "").upper()
        if und:
            out.add(str(und).upper())
    return out


def short_put_underlyings(option_positions: List[Dict[str, Any]]) -> set:
    """Underlyings with an open short put (CSP) — do not add extra stock into those."""
    out = set()
    for pos in option_positions or []:
        if str(pos.get("side") or "").lower() != "short":
            continue
        parsed = parse_occ_symbol(str(pos.get("symbol") or ""))
        otype = str((parsed or {}).get("option_type") or pos.get("option_type") or "").lower()
        if otype != "put":
            continue
        und = (parsed or {}).get("underlying") or str(pos.get("underlying") or "").upper()
        if und:
            out.add(str(und).upper())
    return out


def build_coverage_map(
    portfolio: "Portfolio",
    option_positions: List[Dict[str, Any]],
    current_prices: Dict[str, float],
    *,
    max_underlying_price: float = 35.0,
) -> List[Dict[str, Any]]:
    """Pair each ≥100-share wheel lot with its short call (or UNCOVERED)."""
    short_calls: Dict[str, Dict[str, Any]] = {}
    for pos in option_positions or []:
        if str(pos.get("side") or "").lower() != "short":
            continue
        parsed = parse_occ_symbol(str(pos.get("symbol") or ""))
        if not parsed or parsed.get("option_type") != "call":
            continue
        und = parsed["underlying"]
        try:
            q = abs(int(float(pos.get("qty")))) if pos.get("qty") is not None else 0
        except (TypeError, ValueError):
            q = 0
        if q <= 0:
            continue
        if und in short_calls:
            short_calls[und]["qty"] = int(short_calls[und].get("qty") or 0) + q
            short_calls[und].setdefault("contracts", []).append(
                {
                    "symbol": parsed.get("symbol"),
                    "strike": parsed.get("strike"),
                    "expiry": parsed.get("expiry"),
                    "qty": q,
                }
            )
            # Keep nearest-term / lowest strike metadata for display.
            try:
                old_exp = str(short_calls[und].get("expiry") or "")
                new_exp = str(parsed.get("expiry") or "")
                if new_exp and (not old_exp or new_exp < old_exp):
                    short_calls[und].update(
                        {
                            "symbol": parsed.get("symbol"),
                            "strike": parsed.get("strike"),
                            "expiry": parsed.get("expiry"),
                        }
                    )
            except Exception:
                pass
        else:
            short_calls[und] = {
                **parsed,
                "qty": q,
                "avg_entry_price": pos.get("avg_entry_price") or pos.get("avg_entry"),
                "current_price": pos.get("current_price") or pos.get("mark_price"),
                "contracts": [
                    {
                        "symbol": parsed.get("symbol"),
                        "strike": parsed.get("strike"),
                        "expiry": parsed.get("expiry"),
                        "qty": q,
                    }
                ],
            }

    rows: List[Dict[str, Any]] = []
    seen_und: set = set()
    for raw_t, pos in list((getattr(portfolio, "positions", None) or {}).items()):
        t = str(raw_t).upper()
        qty = int(getattr(pos, "long", 0) or 0)
        if qty < 100:
            continue
        try:
            px = float(
                current_prices.get(t)
                or current_prices.get(raw_t)
                or 0.0
            )
        except (TypeError, ValueError):
            px = 0.0
        if px != px or px < 0:  # NaN
            px = 0.0
        # Always surface ≥100-share lots (including graduated prices) for coverage alerts.
        seen_und.add(t)
        cc = short_calls.get(t)
        if not cc:
            rows.append(
                {
                    "ticker": t,
                    "shares": qty,
                    "price": px,
                    "market_value": round(qty * px, 2),
                    "coverage": "UNCOVERED",
                }
            )
            continue
        strike = float(cc.get("strike") or 0)
        dte = dte_from_expiry(str(cc.get("expiry") or ""))
        otm = ((strike / px) - 1.0) * 100.0 if px > 0 and strike > 0 else None
        try:
            short_qty = int(cc.get("qty") or 0)
        except (TypeError, ValueError):
            short_qty = 0
        covered_shares = short_qty * 100
        if covered_shares < qty:
            coverage = "UNDERHEDGED"
        elif covered_shares > qty:
            coverage = "OVERHEDGED"
        else:
            coverage = "covered"
        rows.append(
            {
                "ticker": t,
                "shares": qty,
                "price": px,
                "market_value": round(qty * px, 2),
                "coverage": coverage,
                "contract": cc.get("symbol"),
                "strike": strike,
                "expiry": cc.get("expiry"),
                "dte": dte,
                "otm_pct": round(otm, 2) if otm is not None else None,
                "short_contracts": short_qty,
                "contracts": list(cc.get("contracts") or []),
            }
        )

    # Short calls with <100 shares (or zero) are naked / under-covered — must surface.
    for und, cc in short_calls.items():
        if und in seen_und:
            continue
        try:
            px = float(current_prices.get(und) or 0.0)
        except (TypeError, ValueError):
            px = 0.0
        if px != px or px < 0:
            px = 0.0
        if hasattr(portfolio, "long_qty"):
            qty = int(portfolio.long_qty(und) or 0)
        else:
            pos = (getattr(portfolio, "positions", None) or {}).get(und)
            qty = int(getattr(pos, "long", 0) or 0) if pos else 0
        try:
            short_qty = abs(int(float(cc.get("qty")))) if cc.get("qty") is not None else 0
        except (TypeError, ValueError):
            short_qty = 0
        covered_shares = short_qty * 100
        if covered_shares <= qty:
            continue  # fully covered but below 100-share wheel lot threshold — skip
        strike = float(cc.get("strike") or 0)
        dte = dte_from_expiry(str(cc.get("expiry") or ""))
        otm = ((strike / px) - 1.0) * 100.0 if px > 0 and strike > 0 else None
        coverage = "OVERHEDGED" if qty > 0 else "NAKED_SHORT"
        rows.append(
            {
                "ticker": und,
                "shares": qty,
                "price": px,
                "market_value": round(qty * px, 2),
                "coverage": coverage,
                "contract": cc.get("symbol"),
                "strike": strike,
                "expiry": cc.get("expiry"),
                "dte": dte,
                "otm_pct": round(otm, 2) if otm is not None else None,
                "short_contracts": short_qty,
                "contracts": list(cc.get("contracts") or []),
            }
        )
    return rows
