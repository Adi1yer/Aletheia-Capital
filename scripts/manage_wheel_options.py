#!/usr/bin/env python3
"""Daily wheel options manager: BTC near-ITM/short-DTE shorts, then write CCs on lots.

Does not rebalance equities — only options lifecycle for the wheel-hybrid paper book.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def main() -> int:
    import structlog

    from src.broker.alpaca import AlpacaBroker
    from src.options.covered_calls import CoveredCallManager
    from src.options.wheel_lifecycle import manage_short_options, sync_wheel_assignment_state
    from src.trading.execution_status import can_submit_live_orders

    logger = structlog.get_logger()
    force = bool(os.getenv("FORCE_EXECUTE_AFTER_HOURS"))
    now = datetime.now(ZoneInfo("America/New_York"))
    ok, reason = can_submit_live_orders(now, cutoff_et=os.getenv("EXECUTE_CUTOFF_ET", "15:30"))
    execute = True
    if not ok and not force:
        logger.warning("Outside submit window — dry manage only", reason=reason)
        execute = False

    broker = AlpacaBroker()
    portfolio = broker.sync_portfolio()
    positions = broker.get_positions() or {}
    prices: dict[str, float] = {}
    for t, p in positions.items():
        qty = float((p or {}).get("qty") or 0)
        mv = float((p or {}).get("market_value") or 0)
        if qty > 0 and mv:
            prices[t] = abs(mv) / qty
        else:
            prices[t] = float((p or {}).get("avg_entry_price") or 0)
    for t, pos in (portfolio.positions or {}).items():
        if prices.get(t, 0) <= 0:
            prices[t] = float(getattr(pos, "long_cost_basis", 0) or 0)

    manage_results = manage_short_options(
        broker,
        prices,
        manage_dte_threshold=int(os.getenv("MANAGE_DTE_THRESHOLD", "7")),
        manage_itm_pct=float(os.getenv("MANAGE_ITM_PCT", "0.02")),
        execute=execute,
    )

    portfolio = broker.sync_portfolio()
    opt_pos = broker.get_option_positions() or []
    state = sync_wheel_assignment_state(
        portfolio,
        opt_pos,
        max_underlying_price=float(os.getenv("MAX_UNDERLYING_PRICE", "35")),
        current_prices=prices,
    )

    max_px = float(os.getenv("MAX_UNDERLYING_PRICE", "35"))
    cc_lots = []
    for t, pos in (portfolio.positions or {}).items():
        qty = int(getattr(pos, "long", 0) or 0)
        px = float(prices.get(t) or 0)
        if qty >= 100 and 0 < px <= max_px:
            cc_lots.append(t)

    cc_results = []
    if cc_lots and execute:
        mgr = CoveredCallManager(
            min_premium_usd=float(os.getenv("CC_MIN_PREMIUM_USD", "15")),
            min_premium_pct=float(os.getenv("CC_MIN_PREMIUM_PCT", "0.004")),
            otm_pct_low=float(os.getenv("CC_OTM_PCT_LOW", "0.05")),
            otm_pct_high=float(os.getenv("CC_OTM_PCT_HIGH", "0.12")),
            target_otm_pct=float(os.getenv("CC_TARGET_OTM_PCT", "0.08")),
        )
        scores = {t: int(os.getenv("WHEEL_RULES_SCORE", "55")) for t in cc_lots}
        cc_results = mgr.execute_covered_calls(
            broker=broker,
            portfolio=portfolio,
            cc_lot_tickers=cc_lots,
            cc_scores=scores,
            current_prices=prices,
        )

    btc = sum(1 for r in manage_results if r.get("status") == "btc_executed")
    wrote = sum(1 for r in cc_results if r.get("status") == "executed")
    skipped = [r for r in cc_results if r.get("status") == "skipped"]
    logger.info(
        "Daily wheel options manage complete",
        execute=execute,
        reason=reason if not ok else "ok",
        btc=btc,
        cc_wrote=wrote,
        cc_skipped=len(skipped),
        lots=cc_lots,
        stages=list((state.get("names") or {}).keys()),
    )
    for r in skipped[:12]:
        logger.info("CC skip", underlying=r.get("underlying"), reason=r.get("reason"))
    print(
        f"manage execute={execute} btc={btc} cc_wrote={wrote} "
        f"cc_skipped={len(skipped)} lots={cc_lots}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        print(f"manage_wheel_options failed: {e}", file=sys.stderr)
        raise
