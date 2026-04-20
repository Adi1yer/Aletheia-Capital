#!/usr/bin/env python3
"""Daily Alpaca snapshot: one JSON per account per day for intraweek → weekly context."""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Tuple

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

import structlog

from src.broker.alpaca import AlpacaBroker
from src.config.settings import settings
from src.ops.daily_snapshots import save_snapshot

logger = structlog.get_logger()

_OCC_RE = re.compile(r"^([A-Z]{1,6})(\d{6})([CP])(\d{8})$")


def _parse_occ_symbol(symbol: str) -> Dict[str, Any]:
    m = _OCC_RE.match(symbol or "")
    if not m:
        return {}
    under, yymmdd, cp, strike_raw = m.groups()
    yy = int(yymmdd[:2]) + 2000
    mm = int(yymmdd[2:4])
    dd = int(yymmdd[4:6])
    return {
        "underlying": under.strip(),
        "expiry": f"{yy:04d}-{mm:02d}-{dd:02d}",
        "type": "call" if cp == "C" else "put",
        "strike": int(strike_raw) / 1000.0,
    }


def _collect_payload(
    broker: AlpacaBroker,
    account: str,
    max_position_pct: float,
) -> Tuple[Dict[str, Any], List[str], int]:
    acct = broker.get_account()
    positions = broker.get_positions()
    equity = float(acct.get("equity") or acct.get("portfolio_value") or 0)
    cash = float(acct.get("cash", 0))

    alerts: List[str] = []
    top_rows: List[Dict[str, Any]] = []
    option_rows: List[Dict[str, Any]] = []

    for sym, pos in sorted(positions.items(), key=lambda x: -abs(x[1].get("market_value", 0))):
        mv = float(pos.get("market_value", 0))
        qty = int(pos.get("qty", 0))
        avg = float(pos.get("avg_entry_price", 0))
        side = pos.get("side", "long")
        pct_eq = (100.0 * mv / equity) if equity > 0 and side == "long" and mv > 0 else 0.0
        if equity > 0 and side == "long" and mv > 0 and pct_eq > max_position_pct:
            alerts.append(f"{sym}: {pct_eq:.1f}% of equity (>{max_position_pct}%)")
        pnl_pct = 0.0
        if qty and avg:
            last = mv / qty if qty else 0
            pnl_pct = ((last - avg) / avg * 100) if avg > 0 else 0.0
        top_rows.append(
            {
                "symbol": sym,
                "side": side,
                "qty": qty,
                "market_value": round(mv, 2),
                "pct_equity": round(pct_eq, 2),
                "unrealized_pnl_pct": round(pnl_pct, 2),
            }
        )
        occ = _parse_occ_symbol(sym)
        if occ:
            option_rows.append(
                {
                    "symbol": sym,
                    "qty": qty,
                    "side": side,
                    "avg_entry_price": round(avg, 4),
                    "market_value": round(mv, 2),
                    **occ,
                }
            )

    top_rows = sorted(top_rows, key=lambda x: -abs(x.get("market_value", 0)))[:15]

    payload: Dict[str, Any] = {
        "date": date.today().isoformat(),
        "account": account,
        "equity": round(equity, 2),
        "cash": round(cash, 2),
        "buying_power": round(float(acct.get("buying_power", 0) or 0), 2),
        "position_count": len(positions),
        "alerts": alerts,
        "top_positions": top_rows,
        "option_positions": option_rows,
    }
    exit_code = 2 if alerts else 0
    return payload, alerts, exit_code


def main() -> int:
    p = argparse.ArgumentParser(description="Daily Alpaca snapshot (main and/or biotech paper)")
    p.add_argument(
        "--account",
        choices=("stock", "biotech", "both"),
        default="stock",
        help="stock=main ALPACA_* paper; biotech=BIOTECH_ALPACA_*; both=run twice",
    )
    p.add_argument(
        "--max-position-pct",
        type=float,
        default=25.0,
        help="Recorded in alerts if a single long exceeds this %% of equity",
    )
    args = p.parse_args()

    accounts: List[str]
    if args.account == "both":
        accounts = ["stock", "biotech"]
    else:
        accounts = [args.account]

    worst = 0
    for acct in accounts:
        if acct == "stock":
            if not settings.alpaca_api_key or not settings.alpaca_secret_key:
                logger.error("Main Alpaca keys not configured (ALPACA_API_KEY / ALPACA_SECRET_KEY)")
                return 1
            broker = AlpacaBroker()
            payload, alerts, xc = _collect_payload(broker, "stock", args.max_position_pct)
            path = save_snapshot("stock", payload)
            logger.info("Saved stock daily snapshot", path=str(path), alerts=len(alerts))
            worst = max(worst, xc)
        else:
            bk = (settings.biotech_alpaca_api_key or "").strip()
            bs = (settings.biotech_alpaca_secret_key or "").strip()
            if not bk or not bs:
                logger.warning("Biotech Alpaca keys not set; skipping biotech daily snapshot")
                continue
            broker = AlpacaBroker(api_key=bk, secret_key=bs)
            payload, alerts, xc = _collect_payload(broker, "biotech", args.max_position_pct)
            path = save_snapshot("biotech", payload)
            logger.info("Saved biotech daily snapshot", path=str(path), alerts=len(alerts))
            worst = max(worst, xc)

    return worst


if __name__ == "__main__":
    sys.exit(main())
