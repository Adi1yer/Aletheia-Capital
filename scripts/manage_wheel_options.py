#!/usr/bin/env python3
"""Daily wheel options manager: BTC/roll threatened shorts, then write CCs on lots.

Does not rebalance equities — only options lifecycle for the wheel-hybrid paper book.
Emails only when EMAIL_ON_CHANGES_ONLY is set and actions occurred (or always if unset
and recipient configured without that flag — default for GH: changes only).
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
    from src.options.cc_agent import resolve_ambiguous_cc_actions
    from src.options.covered_calls import (
        CoveredCallManager,
        apply_underhedge_trims,
        tickers_needing_atomic_unwind,
    )
    from src.options.wheel_lifecycle import (
        build_coverage_map,
        build_short_put_map,
        manage_or_roll_short_calls,
        short_option_underlyings,
        sync_wheel_assignment_state,
    )
    from src.portfolio.manager import PortfolioDecision
    from src.trading.execution_status import can_submit_live_orders
    from src.utils.wheel_email import build_wheel_daily_email, manage_results_have_actions

    logger = structlog.get_logger()
    force = bool(os.getenv("FORCE_EXECUTE_AFTER_HOURS"))
    now = datetime.now(ZoneInfo("America/New_York"))
    ok, reason = can_submit_live_orders(now, cutoff_et=os.getenv("EXECUTE_CUTOFF_ET", "15:55"))
    execute = True
    if not ok and not force:
        logger.warning("Outside submit window — dry manage only", reason=reason)
        execute = False

    broker = AlpacaBroker()
    portfolio = broker.sync_portfolio()
    positions = broker.get_positions() or {}
    def _px(value) -> float:
        try:
            v = float(value)
        except (TypeError, ValueError):
            return 0.0
        if v != v or v <= 0 or v == float("inf") or v == float("-inf"):
            return 0.0
        return v

    prices: dict[str, float] = {}
    for t, p in positions.items():
        tu = str(t).upper()
        qty = _px((p or {}).get("qty"))
        mv = _px((p or {}).get("market_value"))
        if qty > 0 and mv:
            prices[tu] = abs(mv) / qty
        else:
            entry = _px((p or {}).get("avg_entry_price"))
            if entry > 0:
                prices[tu] = entry
    for t, pos in (portfolio.positions or {}).items():
        tu = str(t).upper()
        if _px(prices.get(tu)) <= 0:
            basis = _px(getattr(pos, "long_cost_basis", 0))
            if basis > 0:
                prices[tu] = basis
    try:
        from src.options.wheel_lifecycle import short_option_underlyings

        opt_early = broker.get_option_positions() or []
        need_px = [
            u for u in short_option_underlyings(opt_early) if _px(prices.get(u)) <= 0
        ]
        if need_px and hasattr(broker, "get_last_equity_prices"):
            prices.update(broker.get_last_equity_prices(need_px) or {})
    except Exception as e:
        logger.warning("Could not backfill prices for short-option underlyings", error=str(e))

    mgr = CoveredCallManager(
        min_premium_usd=float(os.getenv("CC_MIN_PREMIUM_USD", "15")),
        min_premium_pct=float(os.getenv("CC_MIN_PREMIUM_PCT", "0.004")),
        otm_pct_low=float(os.getenv("CC_OTM_PCT_LOW", "0.03")),
        otm_pct_high=float(os.getenv("CC_OTM_PCT_HIGH", "0.08")),
        target_otm_pct=float(os.getenv("CC_TARGET_OTM_PCT", "0.05")),
        wait_fill=True,
    )

    try:
        manage_results = manage_or_roll_short_calls(
            broker,
            prices,
            mgr,
            manage_dte_threshold=int(os.getenv("MANAGE_DTE_THRESHOLD", "7")),
            manage_itm_pct=float(os.getenv("MANAGE_ITM_PCT", "0.02")),
            profit_take_pct=float(os.getenv("CC_PROFIT_TAKE_PCT", "0.60")),
            prefer_roll=True,
            execute=execute,
            cc_score=int(os.getenv("WHEEL_RULES_SCORE", "55")),
        )
    except Exception as e:
        logger.error("Afternoon manage/roll failed; continuing to CC", error=str(e))
        manage_results = [{"status": "error", "reason": str(e)}]
    amb = [r for r in manage_results if r.get("status") == "ambiguous"]
    if amb:
        cands = {}
        for r in amb:
            reason = str(r.get("reason") or "")
            if any(
                m in reason
                for m in (
                    "profit_take_requires_credit",
                    "roll_debit_exceeds_cap",
                    "roll_debit_too_large",
                    "btc_cost_unknown",
                    "no_share_coverage_for_roll_sto",
                )
            ):
                continue
            und = str(r.get("underlying") or "").upper()
            sym = r.get("new_contract")
            if und and sym:
                cands.setdefault(und, []).append({"symbol": sym})
        manage_results.extend(
            resolve_ambiguous_cc_actions(
                amb,
                candidate_contracts_by_underlying=cands,
                broker=broker if execute else None,
                execute=execute,
            )
        )

    portfolio = broker.sync_portfolio()
    try:
        opt_pos = broker.get_option_positions() or []
    except Exception as e:
        logger.error("Option positions unavailable after manage; continuing fail-closed", error=str(e))
        opt_pos = []
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
        px = _px(prices.get(str(t).upper()) or prices.get(t))
        # Include every ≥100 lot so afternoon can cover an extra lot even if the
        # mark is missing (select_contract will skip if still unpriced).
        if qty >= 100:
            cc_lots.append(str(t).upper())
            if px <= 0:
                logger.warning("Afternoon CC lot has no mark; still attempting write", ticker=t)

    cc_results: list = []
    if cc_lots and execute:
        scores = {t: int(os.getenv("WHEEL_RULES_SCORE", "55")) for t in cc_lots}
        try:
            cc_results = mgr.execute_covered_calls(
                broker=broker,
                portfolio=portfolio,
                cc_lot_tickers=cc_lots,
                cc_scores=scores,
                current_prices=prices,
            )
        except Exception as e:
            logger.error("Afternoon covered-call execute failed", error=str(e))
            cc_results.append({"status": "error", "reason": str(e)})
        try:
            short_now = short_option_underlyings(broker.get_option_positions() or [])
        except Exception as e:
            logger.error("Option positions unavailable; skipping atomic unwind", error=str(e))
            short_now = None
        if short_now is not None:
            try:
                unwind_port = broker.sync_portfolio()
            except Exception:
                unwind_port = portfolio
            unwind = tickers_needing_atomic_unwind(
                cc_results,
                held_lot_tickers=[str(x).upper() for x in cc_lots],
                short_option_underlyings=short_now,
            )
            for t in sorted(unwind):
                qty = (
                    int(unwind_port.long_qty(t) or 0)
                    if hasattr(unwind_port, "long_qty")
                    else int(
                        getattr(
                            (getattr(unwind_port, "positions", None) or {}).get(t)
                            or (getattr(unwind_port, "positions", None) or {}).get(
                                str(t).upper()
                            ),
                            "long",
                            0,
                        )
                        or 0
                    )
                )
                if qty <= 0:
                    continue
                try:
                    order = broker.execute_order(
                        t,
                        PortfolioDecision(
                            action="sell",
                            quantity=qty,
                            confidence=90,
                            reasoning="Atomic CC unwind",
                        ),
                        current_price=_px(prices.get(t) or prices.get(str(t).upper())) or None,
                    )
                    fill = None
                    ok = False
                    if order and hasattr(broker, "wait_for_order_fill"):
                        oid = str(order.get("order_id") or order.get("id") or "")
                        if oid:
                            fill = broker.wait_for_order_fill(
                                oid, timeout_s=60.0, min_filled_qty=qty
                            )
                            ok = bool(fill.get("ok"))
                    cc_results.append(
                        {
                            "underlying": t,
                            "status": "atomic_unwind" if ok else "atomic_unwind_failed",
                            "quantity": qty,
                            "order": order,
                            "fill": fill,
                        }
                    )
                except Exception as ue:
                    cc_results.append(
                        {
                            "underlying": t,
                            "status": "atomic_unwind_failed",
                            "quantity": qty,
                            "reason": str(ue)[:200],
                        }
                    )

        apply_underhedge_trims(broker, prices, cc_results)
    elif execute:
        apply_underhedge_trims(broker, prices, cc_results)

    portfolio = broker.sync_portfolio()
    coverage_unavailable = False
    try:
        opt_pos = broker.get_option_positions() or []
    except Exception as e:
        logger.error("Option positions unavailable for coverage map", error=str(e))
        opt_pos = []
        coverage_unavailable = True
    coverage = [] if coverage_unavailable else build_coverage_map(
        portfolio,
        opt_pos,
        prices,
        max_underlying_price=max_px,
    )
    short_puts = [] if coverage_unavailable else build_short_put_map(
        portfolio, opt_pos, prices
    )
    option_mtm = None
    if not coverage_unavailable:
        opt_mtm = 0.0
        for op in opt_pos or []:
            try:
                opt_mtm += float((op or {}).get("market_value") or 0.0)
            except (TypeError, ValueError):
                pass
        option_mtm = round(opt_mtm, 2)

    btc = sum(1 for r in manage_results if r.get("status") == "btc_executed")
    rolls = sum(1 for r in manage_results if r.get("status") == "roll_executed")
    wrote = sum(1 for r in cc_results if r.get("status") == "executed")
    unwound = sum(1 for r in cc_results if r.get("status") == "atomic_unwind")
    trimmed = sum(1 for r in cc_results if r.get("status") == "underhedge_trim")
    skipped = [r for r in cc_results if r.get("status") == "skipped"]
    logger.info(
        "Daily wheel options manage complete",
        execute=execute,
        reason=reason if not ok else "ok",
        btc=btc,
        rolls=rolls,
        cc_wrote=wrote,
        unwound=unwound,
        trimmed=trimmed,
        cc_skipped=len(skipped),
        lots=cc_lots,
        stages=list((state.get("names") or {}).keys()),
    )
    for r in skipped[:12]:
        logger.info("CC skip", underlying=r.get("underlying"), reason=r.get("reason"))
    print(
        f"manage execute={execute} btc={btc} rolls={rolls} cc_wrote={wrote} "
        f"unwind={unwound} cc_skipped={len(skipped)} lots={cc_lots}"
    )
    try:
        from src.performance.official_track import load_snapshots, save_snapshot
        from datetime import datetime as _dt
        from zoneinfo import ZoneInfo as _ZI

        today = _dt.now(tz=_ZI("America/New_York")).date().isoformat()
        snaps = load_snapshots()
        for s in snaps:
            if s.get("date") == today:
                job = dict(s.get("job") or {})
                job["afternoon"] = "ok" if execute else "skip"
                s["job"] = job
                save_snapshot(s)
                break
    except Exception:
        pass

    # Email on changes only (default for this script when recipient set).
    changes_only = os.getenv("EMAIL_ON_CHANGES_ONLY", "1").strip() not in ("0", "false", "False")
    recipient = (os.getenv("RECIPIENT_EMAIL") or "").strip()
    if recipient and manage_results_have_actions(
        manage_results, cc_results, coverage_unavailable=coverage_unavailable
    ):
        from src.utils.email import get_email_notifier

        equity = float(getattr(portfolio, "cash", 0) or 0)
        for t, pos in (portfolio.positions or {}).items():
            px = _px(prices.get(str(t).upper()) or prices.get(t))
            equity += int(getattr(pos, "long", 0) or 0) * px
        results = {
            "wheel_mode": True,
            "timestamp": datetime.now(ZoneInfo("America/New_York")).isoformat(),
            "portfolio": {
                "cash": float(getattr(portfolio, "cash", 0) or 0),
                "equity": round(equity, 2),
                "positions": {
                    t: {"long": int(getattr(pos, "long", 0) or 0)}
                    for t, pos in (portfolio.positions or {}).items()
                },
            },
            "wheel_manage_results": manage_results,
            "covered_call_results": cc_results,
            "coverage_map": coverage,
            "short_put_map": short_puts,
            "option_mtm_usd": option_mtm,
            "coverage_unavailable": coverage_unavailable,
            "wheel_scorecard": {
                "coverage_map": coverage,
                "short_put_map": short_puts,
                "option_mtm_usd": option_mtm,
                "coverage_unavailable": coverage_unavailable,
            },
            "decisions": {},
            "execution_results": {},
        }
        # Prefer broker equity for email when available.
        try:
            be = float(getattr(portfolio, "_broker_equity", 0) or 0)
            rc = float(getattr(portfolio, "_raw_cash", 0) or 0)
            if be > 0:
                results["portfolio"]["broker_equity"] = round(be, 2)
                results["portfolio"]["equity"] = round(be, 2)
            if rc > 0:
                results["portfolio"]["raw_cash"] = round(rc, 2)
        except Exception:
            pass
        subject, text, html = build_wheel_daily_email(results)
        subject = subject.replace("daily wheel", "afternoon options")
        get_email_notifier().send_email(recipient, subject, text, html)
        logger.info("Afternoon manage email sent", recipient=recipient)
    elif recipient and not changes_only:
        pass  # reserved
    else:
        logger.info(
            "No afternoon email",
            changes=manage_results_have_actions(manage_results, cc_results),
            recipient=bool(recipient),
        )

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        print(f"manage_wheel_options failed: {e}", file=sys.stderr)
        raise
