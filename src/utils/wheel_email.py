"""Compact daily email digest for wheel-hybrid runs (text + minimal HTML)."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


def _f(x: Any, default: float = 0.0) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(v):
        return default
    return v


def _otm_label(row: dict) -> str:
    if _f(row.get("price")) <= 0:
        return "n/a"
    otm = row.get("otm_pct")
    if otm is None:
        return "n/a"
    v = _f(otm, default=float("nan"))
    if not math.isfinite(v):
        return "n/a"
    return f"{v}%"


def _put_moneyness_label(row: dict) -> str:
    """Puts: positive otm_pct is stock above strike (OTM); negative is ITM."""
    if _f(row.get("price")) <= 0:
        return "n/a"
    otm = row.get("otm_pct")
    if otm is None:
        return "n/a"
    v = _f(otm, default=float("nan"))
    if not math.isfinite(v):
        return "n/a"
    if v >= 0:
        return f"OTM={v}%"
    return f"ITM={abs(v)}%"


def _sleeve_mix(results: dict) -> Dict[str, Any]:
    port = results.get("portfolio") or {}
    prices = {}
    coverage = results.get("coverage_map") or (results.get("wheel_scorecard") or {}).get(
        "coverage_map"
    ) or []
    coverage_prices = {
        str(r.get("ticker") or "").upper(): _f(r.get("price"))
        for r in coverage
        if _f(r.get("price")) > 0
    }
    for t, pos in (port.get("positions") or {}).items():
        # Prefer risk_analysis prices when present; ignore NaN so we fall back.
        ra = (
            (results.get("risk_analysis") or {}).get(t)
            or (results.get("risk_analysis") or {}).get(str(t).upper())
            or {}
        )
        px = _f(ra.get("current_price"))
        if px <= 0:
            px = coverage_prices.get(str(t).upper(), 0.0)
        if px <= 0:
            px = _f(pos.get("market_value")) / max(int(pos.get("long") or 0), 1)
        if px <= 0:
            px = _f(pos.get("long_cost_basis"))
        prices[str(t).upper()] = px

    equity = _f(port.get("equity"))
    if equity <= 0:
        equity = _f(port.get("broker_equity") or results.get("broker_equity"))
    cash = _f(port.get("raw_cash"))
    if cash <= 0:
        cash = _f(port.get("cash"))
    spendable = _f(port.get("cash"))
    wheel_tickers = {str(r.get("ticker") or "").upper() for r in coverage if r.get("ticker")}
    dd = results.get("decision_diagnostics") or {}
    for t in dd.get("wheel_targets") or []:
        wheel_tickers.add(str(t).upper())
    for t in dd.get("cc_lot_tickers") or []:
        wheel_tickers.add(str(t).upper())

    wheel_mv = 0.0
    dir_mv = 0.0
    for t, pos in (port.get("positions") or {}).items():
        qty = int(pos.get("long") or 0)
        px = prices.get(str(t).upper()) or prices.get(t) or 0.0
        mv = qty * px
        if str(t).upper() in wheel_tickers:
            wheel_mv += mv
        else:
            dir_mv += mv

    stock_mv = wheel_mv + dir_mv
    # Premium received is already in cash. Alpaca NAV then subtracts the
    # remaining short-option mark. Cash+stocks is the "keep the premium"
    # book without that mark-to-market drag.
    cash_plus_stocks = cash + stock_mv

    option_mtm = None
    ws = results.get("wheel_scorecard") or {}
    if "option_mtm_usd" in results or "option_mtm_usd" in ws:
        option_mtm = _f(
            results.get("option_mtm_usd")
            if results.get("option_mtm_usd") is not None
            else ws.get("option_mtm_usd")
        )
    else:
        found = False
        total = 0.0
        for pos in results.get("option_positions") or []:
            if isinstance(pos, dict) and "market_value" in pos:
                total += _f(pos.get("market_value"))
                found = True
        if found:
            option_mtm = total

    if equity <= 0:
        if option_mtm is not None:
            equity = cash_plus_stocks + option_mtm
        else:
            equity = cash_plus_stocks
    return {
        "equity": round(equity, 2),
        "cash": round(cash, 2),
        "spendable_cash": round(spendable, 2),
        "cash_pct": round(100.0 * cash / equity, 1) if equity > 0 else 0.0,
        "wheel_mv": round(wheel_mv, 2),
        "wheel_pct": round(100.0 * wheel_mv / equity, 1) if equity > 0 else 0.0,
        "directional_mv": round(dir_mv, 2),
        "directional_pct": round(100.0 * dir_mv / equity, 1) if equity > 0 else 0.0,
        "target_wheel_pct": 70.0,
        "target_directional_pct": 30.0,
        "stock_mv": round(stock_mv, 2),
        "cash_plus_stocks": round(cash_plus_stocks, 2),
        "option_mtm": None if option_mtm is None else round(option_mtm, 2),
        "premium_ledger": round(_f(ws.get("premium_ledger_usd")), 2),
    }


def build_wheel_daily_email(results: dict) -> Tuple[str, str, str]:
    """
    Return (subject, body_text, body_html) for a wheel-mode daily digest.
    """
    ts = str(results.get("timestamp") or "")[:10]
    try:
        day = datetime.fromisoformat(str(results.get("timestamp") or "").replace("Z", "+00:00"))
        day_label = day.strftime("%Y-%m-%d")
    except Exception:
        day_label = ts or "today"

    mix = _sleeve_mix(results)
    ws = results.get("wheel_scorecard") or {}
    spy_ret = ws.get("spy_return_since_start") or ws.get("spy_pct")
    fund_ret = ws.get("fund_return_since_start") or ws.get("fund_pct")
    spy_part = ""
    if spy_ret is not None:
        try:
            spy_part = f" (SPY {_f(spy_ret)*100:+.2f}% since start)"
        except Exception:
            spy_part = ""
    subject = (
        f"Aletheia daily wheel — {day_label} — "
        f"cash+stocks ${mix['cash_plus_stocks']:,.2f} "
        f"(Alpaca ${mix['equity']:,.2f}){spy_part}"
    )

    lines: List[str] = []
    lines.append(f"ALETHEIA DAILY WHEEL — {day_label}")
    lines.append("=" * 72)
    lines.append(
        f"Cash + stocks ${mix['cash_plus_stocks']:,.2f} "
        f"(premium sits in cash; open shorts not subtracted)"
    )
    lines.append(
        f"Alpaca equity ${mix['equity']:,.2f} | Cash ${mix['cash']:,.2f} "
        f"({mix['cash_pct']:.1f}%)"
    )
    if mix.get("option_mtm") is not None:
        lines.append(
            f"Open option marks ${mix['option_mtm']:,.2f} "
            f"(Alpaca subtracts this from NAV)"
        )
    lines.append(
        f"Sleeves actual: wheel ${mix['wheel_mv']:,.2f} ({mix['wheel_pct']:.1f}% / target "
        f"{mix['target_wheel_pct']:.0f}%) | "
        f"directional ${mix['directional_mv']:,.2f} ({mix['directional_pct']:.1f}% / target "
        f"{mix['target_directional_pct']:.0f}%)"
    )
    if fund_ret is not None or spy_ret is not None:
        lines.append(
            f"vs SPY: fund={fund_ret if fund_ret is not None else 'n/a'} | "
            f"spy={spy_ret if spy_ret is not None else 'n/a'} | "
            f"Sharpe fund={ws.get('fund_sharpe')} spy={ws.get('spy_sharpe')} | "
            f"maxDD={ws.get('max_drawdown')}"
        )
    lines.append(
        f"Premium collected (ledger): ${mix['premium_ledger']:,.2f}"
    )
    lines.append("")

    # Actions
    lines.append("ACTIONS TODAY")
    lines.append("-" * 40)
    decisions = results.get("decisions") or {}
    exec_results = results.get("execution_results") or {}
    action_n = 0
    for t, d in decisions.items():
        if not isinstance(d, dict):
            continue
        act = d.get("action")
        if act not in ("buy", "sell", "cover", "short"):
            continue
        qty = d.get("quantity")
        reason = str(d.get("reasoning") or "")[:120]
        st = ""
        er = exec_results.get(t)
        if isinstance(er, dict):
            fill = er.get("fill")
            if isinstance(fill, dict) and "ok" in fill:
                st = " [filled]" if fill.get("ok") else " [fill_failed]"
            else:
                raw = str(er.get("status") or "submitted")
                if raw.startswith("OrderStatus."):
                    raw = raw.split(".", 1)[-1]
                st = f" [{raw.lower()}]"
        elif er:
            st = " [submitted]"
        lines.append(f"  {t}: {act} {qty}{st} — {reason}")
        action_n += 1

    manage = results.get("wheel_manage_results") or []
    for r in manage:
        st = str(r.get("status") or "")
        if st in ("hold", "within_band", ""):
            continue
        if st == "hold" or r.get("reason") == "within_band":
            continue
        und = r.get("underlying") or "?"
        if st in ("btc_executed", "would_btc", "btc_failed"):
            lines.append(
                f"  BTC {und}: {r.get('contract_symbol')} ({r.get('reason')}) [{st}]"
            )
            action_n += 1
        elif st in ("roll_executed", "would_roll", "roll_partial"):
            lines.append(
                f"  ROLL {und}: {r.get('old_contract')} → {r.get('new_contract')} "
                f"strike {r.get('new_strike')} exp {r.get('new_expiry')} "
                f"net~${_f(r.get('est_net_credit')):,.2f} [{st}]"
            )
            action_n += 1
        elif st == "agent_rewrite_executed":
            lines.append(
                f"  AGENT REWRITE {und}: {r.get('agent_contract') or r.get('new_contract')} "
                f"qty={r.get('qty')} [{st}]"
            )
            action_n += 1
        elif st == "agent_rewrite_partial":
            lines.append(
                f"  AGENT REWRITE PARTIAL {und}: qty={r.get('qty')}/{r.get('requested_qty')} [{st}]"
            )
            action_n += 1
        elif st == "agent_rewrite_failed":
            lines.append(
                f"  AGENT REWRITE FAILED {und}: {r.get('reason') or r.get('agent_reason')} [{st}]"
            )
            action_n += 1
        elif st in ("agent_resolved",) and r.get("agent_action") == "hold_assign":
            lines.append(
                f"  HOLD/ASSIGN {und}: {r.get('agent_reason') or r.get('reason')}"
            )
            action_n += 1
        elif st == "ambiguous" or r.get("agent_action"):
            lines.append(
                f"  AMBIGUOUS {und}: {r.get('reason') or r.get('agent_reason')} "
                f"→ {r.get('agent_action') or 'pending'}"
            )
            action_n += 1

    cc_results = results.get("covered_call_results") or []
    for r in cc_results:
        st = str(r.get("status") or "")
        und = r.get("underlying") or "?"
        if st == "executed":
            lines.append(
                f"  CC WRITE {und}: {r.get('contracts')}x {r.get('contract_symbol')} "
                f"strike ${ _f(r.get('strike')):,.2f} exp {r.get('expiry')} "
                f"prem~${_f(r.get('estimated_premium')):,.2f}"
            )
            action_n += 1
        elif st == "atomic_unwind":
            lines.append(f"  UNWIND {und}: sold {r.get('quantity')} (CC write failed)")
            action_n += 1
        elif st == "underhedge_trim":
            lines.append(
                f"  TRIM {und}: sold {r.get('quantity')} uncovered extra "
                f"(kept covered lot after CC miss)"
            )
            action_n += 1
        elif st in (
            "skipped",
            "failed",
            "atomic_unwind_failed",
            "underhedge_trim_failed",
            "partial",
        ):
            lines.append(f"  CC {st.upper()} {und}: {r.get('reason')}")
            action_n += 1

    csp = results.get("csp_results") or []
    for r in csp:
        if r.get("status") == "executed":
            lines.append(
                f"  CSP {r.get('underlying')}: {r.get('contract_symbol')} "
                f"prem~${_f(r.get('estimated_premium')):,.2f}"
            )
            action_n += 1
        elif r.get("status") in ("skipped", "failed", "error"):
            lines.append(
                f"  CSP {str(r.get('status')).upper()} {r.get('underlying') or ''}: "
                f"{r.get('reason')}"
            )
            action_n += 1

    if action_n == 0:
        skip = results.get("execute_skipped_reason") or ""
        if skip:
            lines.append(f"  (no portfolio changes — execute skipped: {skip})")
        else:
            lines.append("  (no portfolio changes this run)")
    lines.append("")

    # Coverage map
    lines.append("COVERAGE MAP (100-share wheel lots)")
    lines.append("-" * 40)
    if results.get("coverage_unavailable") or (ws.get("coverage_unavailable")):
        lines.append("  (coverage unavailable — option positions fetch failed; do not trust empty map)")
    coverage = results.get("coverage_map") or ws.get("coverage_map") or []
    if not coverage and not (
        results.get("coverage_unavailable") or ws.get("coverage_unavailable")
    ):
        lines.append("  (no 100-share wheel lots)")
    for row in coverage:
        t = row.get("ticker")
        cov = str(row.get("coverage") or "")
        if cov in ("UNCOVERED", "UNDERHEDGED", "OVERHEDGED", "NAKED_SHORT"):
            lines.append(
                f"  {t}: {row.get('shares')} sh @ ${_f(row.get('price')):.2f} "
                f"MV ${_f(row.get('market_value')):,.2f} — {cov}"
                + (
                    f" | {row.get('contract')} x{row.get('short_contracts')}"
                    if row.get("contract")
                    else ""
                )
            )
        else:
            ncall = int(row.get("short_contracts") or 1)
            extra = ""
            if ncall > 1:
                extra = f" / {ncall} calls"
            lines.append(
                f"  {t}: {row.get('shares')} sh{extra} | {row.get('contract')} "
                f"strike ${_f(row.get('strike')):.2f} DTE={row.get('dte')} "
                f"OTM={_otm_label(row)}"
            )
            extras = [
                c
                for c in (row.get("contracts") or [])
                if str(c.get("symbol") or "") != str(row.get("contract") or "")
            ]
            if extras:
                bits = []
                for c in extras:
                    try:
                        cq = int(c.get("qty") or 1)
                    except (TypeError, ValueError):
                        cq = 1
                    bit = f"${_f(c.get('strike')):.2f} {str(c.get('expiry') or '')[5:]}"
                    if cq > 1:
                        bit += f" x{cq}"
                    bits.append(bit)
                lines.append(f"      also {', '.join(bits)}")
    lines.append("")

    # Open CSPs — cash is the hedge, not shares.
    lines.append("OPEN SHORT PUTS (cash-secured)")
    lines.append("-" * 40)
    puts = results.get("short_put_map") or ws.get("short_put_map") or []
    if results.get("coverage_unavailable") or ws.get("coverage_unavailable"):
        lines.append("  (option positions unavailable — open puts not listed)")
    elif not puts:
        lines.append("  (none)")
    for row in puts:
        t = row.get("ticker")
        shares = int(row.get("shares") or 0)
        hedge = "cash (no shares)" if shares < 100 else f"{shares} sh also held"
        lines.append(
            f"  {t}: {int(row.get('qty') or 1)}x {row.get('contract')} "
            f"strike ${_f(row.get('strike')):.2f} DTE={row.get('dte')} "
            f"collateral ${_f(row.get('collateral_usd')):,.0f} | {hedge} "
            f"{_put_moneyness_label(row)}"
        )
    lines.append("")

    # Directional compact
    lines.append("DIRECTIONAL SLEEVE")
    lines.append("-" * 40)
    dd = results.get("decision_diagnostics") or {}
    dir_targets = set(str(x).upper() for x in (dd.get("directional_targets") or []))
    port = results.get("portfolio") or {}
    dir_rows = 0
    for t, pos in (port.get("positions") or {}).items():
        qty = int(pos.get("long") or 0)
        if qty <= 0:
            continue
        if coverage and any(str(r.get("ticker") or "").upper() == str(t).upper() for r in coverage):
            continue
        if dir_targets and str(t).upper() not in dir_targets and qty >= 100:
            continue
        ra = (results.get("risk_analysis") or {}).get(t) or {}
        px = _f(ra.get("current_price"))
        if px <= 0:
            px = _f(pos.get("market_value")) / max(qty, 1)
        if px <= 0:
            px = _f(pos.get("long_cost_basis"))
        lines.append(f"  {t}: {qty} sh MV ${_f(qty * px):,.2f}")
        dir_rows += 1
    if dir_rows == 0:
        lines.append("  (none / see coverage map)")
    lines.append("")
    lines.append("This is an automated daily paper-trading digest.")

    text = "\n".join(lines)

    # Minimal HTML
    html_body = "<br>".join(
        f"<b>{line}</b>" if line.startswith("ACTIONS") or line.startswith("COVERAGE") or line.startswith("OPEN SHORT") or line.startswith("DIRECTIONAL") or line.startswith("ALETHEIA") else line
        for line in lines
    )
    html = f"""<!DOCTYPE html>
<html><body style="font-family:ui-monospace,Menlo,Consolas,monospace;font-size:13px;line-height:1.45;color:#111">
<pre style="white-space:pre-wrap">{text}</pre>
</body></html>"""
    return subject, text, html


def manage_results_have_actions(
    manage_results: List[dict],
    cc_results: Optional[List[dict]] = None,
    *,
    coverage_unavailable: bool = False,
) -> bool:
    """True when afternoon manage should email (portfolio changed or material attempt)."""
    if coverage_unavailable:
        return True
    for r in manage_results or []:
        st = str(r.get("status") or "")
        if st in (
            "btc_executed",
            "roll_executed",
            "roll_partial",
            "ambiguous",
            "atomic_unwind",
            "btc_failed",
            "agent_rewrite_executed",
            "agent_rewrite_partial",
            "agent_rewrite_failed",
            "agent_resolved",
        ):
            return True
        if r.get("agent_action"):
            return True
    for r in cc_results or []:
        # Omit "skipped" — no book change; avoids noisy afternoon "changes only" mail.
        if str(r.get("status") or "") in (
            "executed",
            "partial",
            "atomic_unwind",
            "atomic_unwind_failed",
            "underhedge_trim",
            "underhedge_trim_failed",
            "failed",
        ):
            return True
    return False
