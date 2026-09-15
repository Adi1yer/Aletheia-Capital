"""Wheel lifecycle: manage short options (BTC), track CSP↔CC handoff state."""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from src.broker.alpaca import AlpacaBroker
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


def should_manage_short(
    *,
    option_type: str,
    strike: float,
    underlying_price: float,
    dte: int,
    manage_dte_threshold: int = 7,
    manage_itm_pct: float = 0.02,
) -> tuple[bool, str]:
    """Return (manage?, reason) for buy-to-close."""
    if dte <= int(manage_dte_threshold):
        return True, f"dte<={manage_dte_threshold}"
    if underlying_price <= 0 or strike <= 0:
        return False, ""
    if option_type == "call" and underlying_price >= strike * (1.0 - float(manage_itm_pct)):
        return True, "call_near_itm"
    if option_type == "put" and underlying_price <= strike * (1.0 + float(manage_itm_pct)):
        return True, "put_near_itm"
    return False, ""


def manage_short_options(
    broker: "AlpacaBroker",
    current_prices: Dict[str, float],
    *,
    manage_dte_threshold: int = 7,
    manage_itm_pct: float = 0.02,
    execute: bool = True,
) -> List[Dict[str, Any]]:
    """Buy-to-close short options that are near expiry or near ITM (roll = close + reopen later)."""
    results: List[Dict[str, Any]] = []
    positions = broker.get_option_positions() if broker else []
    for pos in positions or []:
        if str(pos.get("side") or "").lower() != "short":
            continue
        symbol = str(pos.get("symbol") or "")
        parsed = parse_occ_symbol(symbol)
        if not parsed:
            # Fallback: broker may already set underlying.
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
        px = float(current_prices.get(und) or 0.0)
        dte = dte_from_expiry(parsed["expiry"])
        manage, reason = should_manage_short(
            option_type=parsed["option_type"],
            strike=float(parsed["strike"]),
            underlying_price=px,
            dte=dte,
            manage_dte_threshold=manage_dte_threshold,
            manage_itm_pct=manage_itm_pct,
        )
        if not manage:
            results.append(
                {
                    "contract_symbol": symbol,
                    "underlying": und,
                    "status": "hold",
                    "dte": dte,
                    "reason": "within_band",
                }
            )
            continue
        qty = int(pos.get("qty") or 1)
        if not execute:
            results.append(
                {
                    "contract_symbol": symbol,
                    "underlying": und,
                    "status": "would_btc",
                    "reason": reason,
                    "dte": dte,
                    "qty": qty,
                }
            )
            continue
        order = broker.submit_option_order(
            contract_symbol=symbol,
            qty=qty,
            side="buy",
            order_type="market",
        )
        results.append(
            {
                "contract_symbol": symbol,
                "underlying": und,
                "status": "btc_executed" if order else "btc_failed",
                "reason": reason,
                "dte": dte,
                "qty": qty,
                "order": order,
                "action": "buy_to_close",
            }
        )
    logger.info(
        "Wheel option manage complete",
        n=len(results),
        btc=sum(1 for r in results if r.get("status") == "btc_executed"),
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
    for t, pos in list((getattr(portfolio, "positions", None) or {}).items()):
        qty = int(getattr(pos, "long", 0) or 0)
        px = float(prices.get(t) or getattr(pos, "cost_basis", 0) or 0)
        if qty < 100:
            continue
        if px > 0 and px > float(max_underlying_price) * 1.25:
            # Likely directional mega-cap lot — skip wheel tagging.
            continue
        prev = dict(names.get(t) or {})
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
        pos = (getattr(portfolio, "positions", None) or {}).get(t)
        qty = int(getattr(pos, "long", 0) or 0) if pos else 0
        if row.get("stage") in ("short_call", "long_shares") and qty < 100 and t not in short_by_und:
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
            out.add(und)
    return out
