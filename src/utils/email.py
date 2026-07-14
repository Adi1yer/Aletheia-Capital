"""Email notification system"""

import smtplib
import json
import os
from datetime import datetime, date
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Optional, Dict, Any
import html

import structlog

from src.config.settings import settings
from src.scan_cache import ScanCache
from src.llm.models import get_llm_for_agent

logger = structlog.get_logger()


def _load_scorecard_leaderboard(limit: int = 12, regime_mode: Optional[str] = None) -> list:
    path = "data/performance/agent_scorecard.json"
    if not os.path.exists(path):
        return []
    try:
        with open(path) as f:
            data = json.load(f)
    except Exception:
        return []
    agents_src = (data.get("agents") or {})
    header_mode = "global"
    if regime_mode:
        by_regime = (data.get("by_regime") or {}).get(regime_mode) or {}
        regime_agents = by_regime.get("agents") or {}
        if regime_agents:
            agents_src = regime_agents
            header_mode = regime_mode
    rows = []
    for ak, row in agents_src.items():
        if not isinstance(row, dict):
            continue
        obs = int(row.get("directional_observations") or 0)
        if obs < 3:
            continue
        rows.append(
            (
                ak,
                float(row.get("directional_accuracy") or 0),
                float(row.get("confidence_weighted_return_pct") or 0),
                obs,
                header_mode,
            )
        )
    rows.sort(key=lambda x: x[1] * 50 + x[3], reverse=True)
    return rows[:limit]


def _portfolio_concentration_lines(portfolio: dict, risk: dict, max_pct: float = 25.0) -> list:
    eq = float(portfolio.get("equity") or 0)
    if eq <= 0:
        return []
    lines = []
    positions = portfolio.get("positions") or {}
    for sym, pos in positions.items():
        long_q = (pos or {}).get("long") or 0
        if not long_q:
            continue
        px = (risk.get(sym) or {}).get("current_price") if isinstance(risk.get(sym), dict) else None
        if px is None:
            px = (pos or {}).get("long_cost_basis") or 0
        mv = float(long_q) * float(px)
        pct = 100.0 * mv / eq
        if pct >= max_pct:
            lines.append(f"{sym}: ~{pct:.1f}% of equity (long {long_q} @ ~${float(px):.2f})")
    return lines


def _format_timestamp(iso_ts: str) -> str:
    """Turn ISO timestamp into human-readable text for emails."""
    if not iso_ts or iso_ts == "N/A":
        return "N/A"
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        return dt.strftime("%B %d, %Y at %I:%M %p UTC")
    except Exception:
        return iso_ts


class EmailNotifier:
    """Send email notifications"""

    def __init__(
        self,
        smtp_server: Optional[str] = None,
        smtp_port: int = 587,
        sender_email: Optional[str] = None,
        sender_password: Optional[str] = None,
    ):
        """
        Initialize email notifier

        Args:
            smtp_server: SMTP server (e.g., 'smtp.gmail.com')
            smtp_port: SMTP port (default: 587 for TLS)
            sender_email: Sender email address
            sender_password: Sender email password or app password
        """
        self.smtp_server = smtp_server or getattr(settings, "smtp_server", None)
        self.smtp_port = smtp_port
        self.sender_email = sender_email or getattr(settings, "sender_email", None)
        self.sender_password = sender_password or getattr(settings, "sender_password", None)

        if not all([self.smtp_server, self.sender_email, self.sender_password]):
            logger.warning("Email notifier not fully configured - notifications will be disabled")
            self.enabled = False
        else:
            self.enabled = True
            logger.info("Email notifier initialized", smtp_server=self.smtp_server)

    def send_email(
        self,
        recipient: str,
        subject: str,
        body_text: str,
        body_html: Optional[str] = None,
    ) -> bool:
        """
        Send email notification

        Args:
            recipient: Recipient email address
            subject: Email subject
            body_text: Plain text body
            body_html: HTML body (optional)

        Returns:
            True if sent successfully, False otherwise
        """
        if not self.enabled:
            logger.warning("Email notifier not configured, skipping email")
            return False

        try:
            # Create message
            msg = MIMEMultipart("alternative")
            msg["From"] = self.sender_email
            msg["To"] = recipient
            msg["Subject"] = subject

            # Add text and HTML parts
            part1 = MIMEText(body_text, "plain")
            msg.attach(part1)

            if body_html:
                part2 = MIMEText(body_html, "html")
                msg.attach(part2)

            # Send email
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.sender_email, self.sender_password)
                server.send_message(msg)

            logger.info("Email sent successfully", recipient=recipient, subject=subject)
            return True

        except Exception as e:
            logger.error("Failed to send email", recipient=recipient, error=str(e))
            return False

    def send_trading_results(
        self,
        recipient: str,
        results: dict,
    ) -> bool:
        """
        Send weekly trading results email

        Args:
            recipient: Recipient email address
            results: Trading results dictionary

        Returns:
            True if sent successfully, False otherwise
        """
        all_decisions = results.get("decisions", {})
        decision_count = len(all_decisions)
        buy_count = sum(1 for d in all_decisions.values() if d.get("action") in ("buy", "cover"))
        sell_count = sum(1 for d in all_decisions.values() if d.get("action") == "sell")
        executed = results.get("execution_results", {})
        es = results.get("execution_status") or {}
        if es.get("had_live_execution"):
            from src.trading.execution_status import execution_subject_fragment

            exec_part = execution_subject_fragment(es)
            executed_count = int(es.get("submitted") or 0)
        else:
            exec_part = ""
            executed_count = (
                sum(
                    1
                    for r in executed.values()
                    if r and (not isinstance(r, dict) or r.get("status") != "failed")
                )
                if executed
                else 0
            )

        ts = results.get("timestamp")
        week_label = "Week"
        if ts:
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                week_start: date = dt.date()
                week_label = f"Week of {week_start.strftime('%B %d, %Y')}"
            except Exception:
                week_label = f"Week of {ts[:10]}"

        cc_results = results.get("covered_call_results") or []
        cc_written = sum(1 for r in cc_results if r.get("status") == "executed")
        cc_part = f", {cc_written} Calls Written" if cc_written else ""
        exec_label = exec_part or (f"{executed_count} Executed" if executed_count else "0 Executed")
        subject = f"{week_label} – {buy_count} Buys, {sell_count} Sells, {exec_label}{cc_part} ({decision_count} analyzed)"

        # Build past performance snapshot from scan cache (if available)
        past_perf = self._build_past_performance(results)

        # Optionally generate an AI weekly outlook
        outlook = self._generate_weekly_outlook(results, past_perf)

        # Create text and HTML versions
        text_body = self._format_trading_results_text(results, past_perf, outlook)
        html_body = self._format_trading_results_html(results, past_perf, outlook)

        return self.send_email(
            recipient=recipient,
            subject=subject,
            body_text=text_body,
            body_html=html_body,
        )

    def _execution_status_text_lines(self, results: dict) -> List[str]:
        es = results.get("execution_status") or {}
        if not es.get("had_live_execution"):
            return []
        lines = [
            "ORDER EXECUTION STATUS",
            "-" * 80,
        ]
        if es.get("run_in_rth"):
            lines.append("Market session: US regular hours (9:30 AM–4:00 PM ET)")
        else:
            lines.append("Market session: OUTSIDE US regular hours")
            if es.get("next_open_et"):
                lines.append(f"Next regular open: {es['next_open_et']} ET")
        lines.append(
            "This run: "
            f"{int(es.get('submitted', 0))} submitted to broker, "
            f"{int(es.get('filled', 0))} filled, "
            f"{int(es.get('pending', 0))} pending/open, "
            f"{int(es.get('partial', 0))} partial, "
            f"{int(es.get('failed', 0))} failed"
        )
        if es.get("note"):
            lines.append(str(es["note"]))
        lines.append(
            "Note: “Submitted” means Alpaca accepted the order; fills may arrive at the next market open."
        )
        return lines

    def _execution_status_html_block(self, results: dict) -> str:
        es = results.get("execution_status") or {}
        if not es.get("had_live_execution"):
            return ""
        session = (
            "US regular hours (9:30 AM–4:00 PM ET)"
            if es.get("run_in_rth")
            else "Outside US regular hours"
        )
        next_open = ""
        if not es.get("run_in_rth") and es.get("next_open_et"):
            next_open = f"<br/><strong>Next regular open:</strong> {html_escape(str(es['next_open_et']))} ET"
        note = f"<br/><em>{html_escape(str(es['note']))}</em>" if es.get("note") else ""
        return f"""
        <div class="section" style="background:#fff8e6;border-left:4px solid #e6a700;padding:12px;margin:12px 0;">
            <h2>Order execution status</h2>
            <p>
                <strong>Market session:</strong> {html_escape(session)}{next_open}<br/>
                <strong>This run:</strong>
                {int(es.get('submitted', 0))} submitted,
                {int(es.get('filled', 0))} filled,
                {int(es.get('pending', 0))} pending/open,
                {int(es.get('partial', 0))} partial,
                {int(es.get('failed', 0))} failed<br/>
                <small>Submitted = broker accepted the order. After-hours runs often stay pending until the next open.</small>
                {note}
            </p>
        </div>
        """

    def _format_trading_results_text(
        self, results: dict, past_perf: Optional[dict] = None, outlook: Optional[str] = None
    ) -> str:
        """Format trading results as plain text"""
        text = []
        text.append("=" * 80)
        text.append("WEEKLY TRADING RESULTS")
        text.append("=" * 80)
        text.append("")
        text.append(f"Timestamp: {_format_timestamp(results.get('timestamp', 'N/A'))}")
        text.append(f"Tickers Analyzed: {len(results.get('tickers', []))}")
        text.append(f"Decisions Made: {len(results.get('decisions', {}))}")
        text.extend(self._execution_status_text_lines(results))
        text.append("")
        iw = (results.get("intraweek_stock_summary") or "").strip()
        if iw:
            text.append("INTRA-WEEK MAIN PAPER ACCOUNT (from daily snapshots)")
            text.append("-" * 80)
            text.append(iw)
            text.append("")

        # Portfolio summary
        if "portfolio" in results:
            portfolio = results["portfolio"]
            text.append("PORTFOLIO STATUS")
            text.append("-" * 80)
            text.append(f"Cash: ${portfolio.get('cash', 0):,.2f}")
            text.append(f"Equity: ${portfolio.get('equity', 0):,.2f}")
            buying_power = portfolio.get("buying_power")
            if buying_power is not None:
                text.append(f"Buying Power: ${buying_power:,.2f}")
            text.append("")

            # Positions snapshot (top by absolute size)
            positions: Dict[str, Any] = portfolio.get("positions") or {}
            if positions:
                text.append("Top Positions:")
                sorted_positions = sorted(
                    positions.items(),
                    key=lambda kv: abs((kv[1] or {}).get("long", 0) or 0)
                    + abs((kv[1] or {}).get("short", 0) or 0),
                    reverse=True,
                )
                for sym, pos in sorted_positions[:10]:
                    long_qty = pos.get("long", 0) or 0
                    short_qty = pos.get("short", 0) or 0
                    if long_qty:
                        cb = pos.get("long_cost_basis", 0) or 0
                        text.append(f"  {sym}: long {long_qty} (cost basis ${cb:,.2f})")
                    if short_qty:
                        cb = pos.get("short_cost_basis", 0) or 0
                        text.append(f"  {sym}: short {short_qty} (cost basis ${cb:,.2f})")
            text.append("")

            conc = _portfolio_concentration_lines(portfolio, results.get("risk_analysis") or {})
            if conc:
                text.append("CONCENTRATION ALERTS (informational)")
                text.append("-" * 40)
                for line in conc:
                    text.append(f"  {line}")
                text.append("")

        lb = _load_scorecard_leaderboard(regime_mode=(results.get("regime") or {}).get("mode"))
        if lb:
            mode_label = lb[0][4] if lb else "global"
            text.append(f"AGENT LEADERBOARD ({mode_label})")
            text.append("-" * 40)
            for ak, acc, cw, obs, _mode in lb:
                text.append(f"  {ak}: acc {acc:.0%}, cw-ret {cw:.2f}, n={obs}")
            text.append("")
        learning = results.get("learning_context") or {}
        if learning:
            text.append("LEARNING CONTEXT")
            text.append("-" * 40)
            text.append(
                f"  Feedback refresh: {'ok' if learning.get('feedback_refresh_ok') else 'failed'}"
            )
            text.append(
                f"  Scorecard present: {'yes' if learning.get('scorecard_present') else 'no'}"
            )
            if learning.get("scorecard_present_after") is not None:
                text.append(
                    f"  Scorecard after save: {'yes' if learning.get('scorecard_present_after') else 'no'}"
                )
            before = learning.get("scan_cache_run_count_before")
            after = learning.get("scan_cache_run_count_after")
            if before is not None:
                text.append(f"  Scan cache runs (before run): {int(before or 0)}")
            if after is not None:
                text.append(f"  Scan cache runs (after save): {int(after or 0)}")
            elif learning.get("scan_cache_run_count") is not None:
                text.append(
                    f"  Scan cache runs (loaded): {int(learning.get('scan_cache_run_count', 0))}"
                )
            if learning.get("ledger_run_count") is not None:
                text.append(f"  Ledger runs: {int(learning.get('ledger_run_count', 0))}")
            if learning.get("ledger_run_count_after") is not None:
                text.append(
                    f"  Ledger runs (after save): {int(learning.get('ledger_run_count_after', 0))}"
                )
            text.append(
                f"  Cache restore (perf/scan): "
                f"{'hit' if learning.get('cache_restore_hit_performance') else 'miss'}/"
                f"{'hit' if learning.get('cache_restore_hit_scan') else 'miss'}"
            )
            if learning.get("s3_runs_restored"):
                text.append(f"  S3 runs restored: {int(learning.get('s3_runs_restored', 0))}")
            if learning.get("scorecard_source"):
                text.append(f"  Scorecard source: {learning.get('scorecard_source')}")
            if learning.get("scorecard_agent_count") is not None:
                text.append(f"  Scorecard agents: {int(learning.get('scorecard_agent_count', 0))}")
            if learning.get("scorecard_progress") is not None:
                req = int(learning.get("scorecard_progress_required") or 2)
                prog = int(learning.get("scorecard_progress") or 0)
                text.append(f"  Scorecard progress: {prog}/{req} runs (scan cache or weekly ledger)")
            if learning.get("scorecard_skip_reason"):
                text.append(f"  Scorecard note: {str(learning.get('scorecard_skip_reason'))[:200]}")
                need = max(
                    0,
                    int(learning.get("scorecard_progress_required") or 2)
                    - int(
                        learning.get("scorecard_progress")
                        or learning.get("scan_cache_run_count_before")
                        or learning.get("scan_cache_run_count")
                        or 0
                    ),
                )
                if need > 0 and "need_at_least" in str(learning.get("scorecard_skip_reason")):
                    text.append(
                        f"  Learning activates after {need} more saved weekly run(s)."
                    )
            if learning.get("feedback_refresh_error"):
                text.append(f"  Refresh error: {str(learning.get('feedback_refresh_error'))[:200]}")
            policy = learning.get("policy_calibration") or {}
            if policy:
                text.append(
                    f"  Learned policy: buy_conf={policy.get('min_buy_confidence')}, "
                    f"rotation_edge={policy.get('cash_rotation_min_edge')}, "
                    f"csp_floor=${policy.get('min_csp_premium_usd')}"
                )
                for adj in (policy.get("adjustments") or [])[:3]:
                    text.append(
                        f"    {adj.get('knob')}: {adj.get('delta'):+} ({adj.get('reason', '')[:80]})"
                    )
            weight_changes = learning.get("weight_changes") or []
            weight_skips = learning.get("weight_skips") or []
            if weight_changes or weight_skips:
                text.append("LEARNING CHANGELOG")
                text.append("-" * 40)
                for wc in weight_changes[:5]:
                    text.append(
                        f"  Weight {wc.get('agent')}: {wc.get('old')} -> {wc.get('new')} "
                        f"(n={wc.get('observations')})"
                    )
                for ws in weight_skips[:3]:
                    text.append(
                        f"  Skip {ws.get('agent')}: {ws.get('reason')} "
                        f"(n={ws.get('observations')}/{ws.get('required')})"
                    )
                text.append("")

        attr = (results.get("learning_context") or {}).get("portfolio_attribution")
        if attr:
            text.append("PORTFOLIO ATTRIBUTION (LEARNING)")
            text.append("-" * 40)
            text.append(
                f"  Equity delta: ${attr.get('equity_delta_usd', 0):+.2f} "
                f"({attr.get('equity_delta_pct', 0):+.2f}%)"
            )
            text.append(
                f"  Cash flow from fills (buys negative): ${attr.get('trading_pnl_usd', 0):+.2f}, "
                f"Market move + residual: ${attr.get('carry_pnl_usd', 0):+.2f}, "
                f"Options premium: ${attr.get('options_premium_usd', 0):+.2f}"
            )
            eq_before = float(attr.get("equity_before") or 0)
            trading_pnl = abs(float(attr.get("trading_pnl_usd") or 0))
            if eq_before > 0 and trading_pnl > 0.5 * eq_before:
                text.append(
                    "  Note: Large fill cash flow; net change is Equity delta above."
                )
            for c in (attr.get("top_contributors") or [])[:3]:
                text.append(
                    f"  {c.get('ticker')}: ${c.get('contrib_usd', 0):+.2f} "
                    f"({c.get('price_change_pct', 0):+.1f}%)"
                )
            text.append("")

        try:
            from src.performance.counterfactual_ledger import recent_for_email

            missed = recent_for_email(limit=3)
            if missed:
                text.append("MISSED OPPORTUNITIES (LEARNING)")
                text.append("-" * 40)
                for m in missed:
                    text.append(
                        f"  {m.get('ticker')}: would {m.get('would_be_action')} -> "
                        f"ret {m.get('forward_return_pct')}%"
                    )
                text.append("")
        except Exception:
            pass

        try:
            from src.performance.options_ledger import recent_summary

            opt_sum = recent_summary(weeks=8)
            if opt_sum.get("csp_executed") or opt_sum.get("cc_executed") or opt_sum.get("resolved_count"):
                text.append("OPTIONS OUTCOMES (LEARNING)")
                text.append("-" * 40)
                text.append(
                    f"  Rolling {opt_sum.get('weeks', 8)}w: "
                    f"CSP {opt_sum.get('csp_executed', 0)} fills "
                    f"(avg ${opt_sum.get('csp_avg_premium_usd', 0):.0f}, "
                    f"{opt_sum.get('csp_sub_floor_count', 0)} below ${opt_sum.get('min_csp_premium_floor', 75):.0f}), "
                    f"CC {opt_sum.get('cc_executed', 0)} fills "
                    f"(avg ${opt_sum.get('cc_avg_premium_usd', 0):.0f})"
                )
                if opt_sum.get("outcome_counts"):
                    text.append(f"  Resolved outcomes: {opt_sum.get('outcome_counts')}")
                text.append("")
        except Exception:
            pass

        regime = results.get("regime") or {}
        if regime.get("mode"):
            text.append("MARKET REGIME")
            text.append("-" * 40)
            text.append(
                f"  {regime.get('mode')}: {regime.get('detail', '')} "
                f"(SPY {regime.get('last_close')} vs SMA200 {regime.get('sma_200')})"
            )
            text.append("")

        try:
            from src.analytics.agent_correlation import top_redundant_pairs

            pairs = top_redundant_pairs(results.get("agent_signals") or {})
            if pairs:
                text.append("AGENT REDUNDANCY (high agreement this run)")
                text.append("-" * 40)
                for p in pairs:
                    text.append(
                        f"  {p['agent_a']} & {p['agent_b']}: {p['agreement_pct']}% "
                        f"(n={p['observations']})"
                    )
                text.append("")
        except Exception:
            pass

        try:
            from src.analytics.portfolio_metrics import compute_snapshot_metrics

            pm = compute_snapshot_metrics()
            if pm.get("max_drawdown_4w_pct") is not None:
                text.append("PORTFOLIO RISK SNAPSHOT (daily snapshots)")
                text.append("-" * 40)
                text.append(f"  Max drawdown (4w): {pm['max_drawdown_4w_pct']}%")
                if pm.get("herfindahl") is not None:
                    text.append(f"  Concentration (HHI): {pm['herfindahl']}")
                text.append("")
        except Exception:
            pass

        outcomes = self._build_decision_outcomes(results)
        if outcomes:
            text.append("LAST RUN DECISIONS VS OUTCOME")
            text.append("-" * 80)
            for row in outcomes[:8]:
                text.append(
                    f"  {row['ticker']}: {row['action']} -> ret {row.get('return_pct', 'n/a')}%"
                )
            text.append("")

        active = (results.get("learning_context") or {}).get("active_agents")
        if not active and results.get("run_id"):
            pass
        if results.get("run_id"):
            try:
                import json as _json
                from pathlib import Path

                wpath = Path("config/agent_weights.json")
                if wpath.is_file():
                    text.append("ACTIVE AGENTS THIS RUN")
                    text.append("-" * 40)
                    meta_agents = []
                    if results.get("run_id"):
                        from src.scan_cache import ScanCache

                        try:
                            run = ScanCache().load_run(results["run_id"])
                            meta_agents = (run.get("meta") or {}).get("active_agents") or []
                        except Exception:
                            meta_agents = []
                    if meta_agents:
                        text.append(f"  {len(meta_agents)} agents: " + ", ".join(meta_agents[:12]))
                        if len(meta_agents) > 12:
                            text.append(f"  ... +{len(meta_agents) - 12} more")
                    text.append("")
            except Exception:
                pass

        # Open and recent orders (if any)
        open_orders = results.get("open_orders") or []
        recent_orders = results.get("recent_orders") or []
        if open_orders:
            text.append("OPEN ORDERS")
            text.append("-" * 80)
            for o in open_orders[:10]:
                sym = o.get("symbol") or o.get("asset_id") or "?"
                side = o.get("side") or "?"
                qty = o.get("qty") or o.get("filled_qty") or 0
                status = o.get("status") or "open"
                submitted = (o.get("submitted_at") or "")[:19]
                text.append(f"{sym}: {side} {qty} ({status}, submitted {submitted})")
            text.append("")

        if recent_orders:
            text.append("RECENT ORDERS (incl. partial fills)")
            text.append("-" * 80)
            for o in recent_orders[:20]:
                sym = o.get("symbol") or o.get("asset_id") or "?"
                side = o.get("side") or "?"
                qty = o.get("qty") or 0
                filled_qty = o.get("filled_qty") or 0
                status = o.get("status") or ""
                filled = (o.get("filled_at") or "")[:19]
                partial = ""
                if qty and filled_qty and int(filled_qty) < int(qty):
                    partial = f" partial {filled_qty}/{qty}"
                text.append(f"{sym}: {side} {qty}{partial} - {status} {filled}")
            text.append("")
            exec_res = results.get("execution_results") or {}
            failed = [
                k
                for k, v in exec_res.items()
                if k != "error" and isinstance(v, dict) and v.get("status") == "failed"
            ]
            if failed:
                text.append(f"Execution failures: {', '.join(failed[:10])}")
                text.append("")

        # Decisions -- buys and sells first, then top holds
        decisions = results.get("decisions", {})
        if decisions:
            buys = [(t, d) for t, d in decisions.items() if d.get("action") in ("buy", "cover")]
            sells = [(t, d) for t, d in decisions.items() if d.get("action") == "sell"]
            holds = [(t, d) for t, d in decisions.items() if d.get("action") == "hold"]
            buys.sort(key=lambda x: x[1].get("confidence", 0), reverse=True)
            sells.sort(key=lambda x: x[1].get("confidence", 0), reverse=True)
            holds.sort(key=lambda x: x[1].get("confidence", 0), reverse=True)
            actionable_holds = [
                (t, d)
                for t, d in holds
                if int(d.get("confidence", 0)) >= 55 and "bullish" in (d.get("reasoning") or "").lower()
            ][:5]

            text.append(
                f"DECISIONS SUMMARY: {len(buys)} buys, {len(sells)} sells, {len(holds)} holds"
            )
            text.append("-" * 80)
            text.append("")

            if buys:
                text.append("BUY ORDERS")
                text.append("-" * 40)
                for ticker, d in buys:
                    text.append(
                        f"  {ticker}: buy {d.get('quantity', 0)} shares (Confidence: {d.get('confidence', 0)}%)"
                    )
                    reasoning = (d.get("reasoning") or "").strip()
                    if reasoning:
                        text.append(f"    Reason: {reasoning[:200]}")
                text.append("")

            if sells:
                text.append("SELL ORDERS")
                text.append("-" * 40)
                for ticker, d in sells:
                    text.append(
                        f"  {ticker}: sell {d.get('quantity', 0)} shares (Confidence: {d.get('confidence', 0)}%)"
                    )
                    reasoning = (d.get("reasoning") or "").strip()
                    if reasoning:
                        text.append(f"    Reason: {reasoning[:200]}")
                text.append("")

            if holds:
                text.append(f"TOP HOLDS (showing 10 of {len(holds)})")
                text.append("-" * 40)
                for ticker, d in holds[:10]:
                    reasoning = (d.get("reasoning") or "").strip()
                    snippet = reasoning[:120] if reasoning else ""
                    text.append(
                        f"  {ticker}: hold (Confidence: {d.get('confidence', 0)}%) – {snippet}"
                    )
                text.append("")

        dd = results.get("decision_diagnostics") or {}
        if dd:
            text.append("DECISION DIAGNOSTICS")
            text.append("-" * 80)
            text.append(
                f"Signals: bullish>=buy={int(dd.get('buy_signal_count', 0))}, "
                f"bearish>=sell on held={int(dd.get('sell_signal_on_held_count', 0))}"
            )
            text.append(
                f"Buy candidates: pre-rank={int(dd.get('buy_candidates_pre_rank', 0))}, "
                f"post-rank={int(dd.get('buy_candidates_post_rank', 0))}"
            )
            text.append(
                f"CC candidates: scored={int(dd.get('cc_scored_count', 0))}, "
                f"passed_threshold={int(dd.get('cc_passed_threshold_count', 0))}"
            )
            text.append(
                f"Sizing/risk blocked buys: {int(dd.get('buy_blocked_by_risk_or_sizing_count', 0))}"
            )
            lane_ct = dd.get("lane_contributions") or {}
            if lane_ct:
                text.append(
                    f"Lane contributions: bullish={int(lane_ct.get('bullish', 0))}, "
                    f"bearish={int(lane_ct.get('bearish', 0))}, total={int(lane_ct.get('total', 0))}"
                )
            blockers = dd.get("buy_blockers") or {}
            if isinstance(blockers, dict) and blockers:
                pairs = [f"{k}={int(v)}" for k, v in blockers.items()]
                text.append("Top blockers: " + ", ".join(pairs[:6]))
                cash_blk = int(blockers.get("cash_or_pending", 0) or 0)
                if cash_blk >= int(dd.get("buy_blocked_by_risk_or_sizing_count", 0) or 0) // 2:
                    text.append(
                        "Note: top buys often blocked by insufficient cash for meaningful position size"
                    )
            if dd.get("enable_cash_rotation"):
                text.append(
                    f"Cash rotation sells: {int(dd.get('cash_rotation_sell_count', 0))} "
                    f"(skipped edge={int(dd.get('cash_rotation_skipped_edge', 0))}, "
                    f"skipped risk={int(dd.get('cash_rotation_skipped_risk', 0))})"
                )
                rot_list = dd.get("rotation_sell_tickers") or []
                for row in rot_list[:8]:
                    if isinstance(row, dict):
                        text.append(
                            f"  Rotation sell {row.get('ticker')}: {str(row.get('reason', ''))[:120]}"
                        )
                rot_skip = str(dd.get("cash_rotation_skip_reason") or "").strip()
                if rot_skip and int(dd.get("cash_rotation_sell_count", 0) or 0) == 0:
                    text.append(f"Cash rotation note: {rot_skip}")
            if int(dd.get("cc_held_lot_count", 0) or 0) or int(dd.get("cc_lot_build_count", 0) or 0):
                text.append(
                    f"CC lots: held={int(dd.get('cc_held_lot_count', 0))}, "
                    f"lot_build={int(dd.get('cc_lot_build_count', 0))}"
                )
            llm_budget = results.get("llm_budget") or {}
            if llm_budget:
                text.append(
                    f"LLM budget: used={int(llm_budget.get('used', 0))}, "
                    f"remaining={int(llm_budget.get('remaining', 0))}"
                )
            agent_errors = results.get("agent_errors") or {}
            if agent_errors:
                text.append(f"Agent errors: {len(agent_errors)}")
            text.append("")
        slo = results.get("slo") or {}
        if slo:
            text.append("SLO HEALTH")
            text.append("-" * 80)
            text.append(
                f"Overall: {'ok' if slo.get('ok') else 'breach'}; "
                f"coverage={int(slo.get('coverage', 0))}, "
                f"agent_errors={int(slo.get('agent_error_count', 0))}, "
                f"data_quality={int(slo.get('data_quality_score', 0))}"
            )
            text.append("")

        # Execution Results
        exec_results = results.get("execution_results") or {}
        es = results.get("execution_status") or {}
        by_ticker_status = es.get("by_ticker") or {}
        if exec_results:
            submitted_n = int(es.get("submitted") or 0)
            if submitted_n:
                text.append(
                    f"SUBMITTED TRADES (THIS RUN): {submitted_n} orders "
                    f"({int(es.get('filled', 0))} filled, {int(es.get('pending', 0))} pending)"
                )
            else:
                executed = sum(
                    1
                    for r in exec_results.values()
                    if r and (not isinstance(r, dict) or r.get("status") != "failed")
                )
                text.append(f"EXECUTION RESULTS: {executed} orders submitted")
            decisions_map = results.get("decisions") or {}
            submitted_rows = []
            for ticker, res in exec_results.items():
                if ticker == "error" or not res:
                    continue
                if isinstance(res, dict) and res.get("status") == "failed":
                    continue
                dec = decisions_map.get(ticker) or {}
                action = dec.get("action") or res.get("side") or "?"
                qty = dec.get("quantity") or res.get("qty") or res.get("filled_qty") or "?"
                reason = (dec.get("reasoning") or res.get("reason") or "").strip()
                fill_st = (by_ticker_status.get(ticker) or {}).get("status") or "submitted"
                submitted_rows.append((ticker, action, qty, fill_st, reason))
            if submitted_rows:
                text.append("-" * 40)
                for ticker, action, qty, fill_st, reason in submitted_rows:
                    text.append(f"  {ticker}: {action} {qty} [{fill_st}]")
                    if reason:
                        text.append(f"    Reason: {reason[:200]}")
            failed_tickers = [
                t
                for t, r in exec_results.items()
                if t != "error" and ((not r) or (isinstance(r, dict) and r.get("status") == "failed"))
            ]
            if failed_tickers:
                text.append(f"FAILED ORDERS ({len(failed_tickers)}): {', '.join(failed_tickers)}")
                for t in failed_tickers[:10]:
                    rr = exec_results.get(t) or {}
                    err = rr.get("error") if isinstance(rr, dict) else None
                    if err:
                        text.append(f"  - {t}: {err[:200]}")
            text.append("")

        # Covered Call Results
        cc_diag = results.get("covered_call_diagnostics") or {}
        cc_results = results.get("covered_call_results") or []
        cc_executed = [r for r in cc_results if r.get("status") == "executed"]
        cc_skipped = [r for r in cc_results if r.get("status") == "skipped"]
        cc_failed = [r for r in cc_results if r.get("status") == "failed"]
        text.append("COVERED CALLS")
        text.append("-" * 80)
        enabled = bool(cc_diag.get("enabled", False))
        text.append(f"Enabled: {'yes' if enabled else 'no'}")
        text.append(
            f"Execution mode: {'live' if bool(cc_diag.get('execute_mode', False)) else 'dry'}"
        )
        text.append(f"Candidate tickers: {int(cc_diag.get('cc_lot_ticker_count', 0) or 0)}")
        text.append(
            "Outcome: "
            f"executed={int(cc_diag.get('executed_count', len(cc_executed)) or 0)}, "
            f"skipped={int(cc_diag.get('skipped_count', len(cc_skipped)) or 0)}, "
            f"failed={int(cc_diag.get('failed_count', len(cc_failed)) or 0)}"
        )
        if cc_diag.get("reason_not_run"):
            text.append(f"Step note: {cc_diag.get('reason_not_run')}")
        if cc_executed:
            total_premium = sum(r.get("estimated_premium", 0) for r in cc_executed)
            text.append(f"Calls written: {len(cc_executed)} (est. premium: ${total_premium:,.2f})")
            for r in cc_executed:
                text.append(
                    f"  {r['underlying']}: sold {r['contracts']}x {r['contract_symbol']} "
                    f"strike ${r['strike']:,.2f} exp {r['expiry']} "
                    f"(cc_score={r.get('cc_score', '?')}, premium ~${r.get('estimated_premium', 0):,.2f})"
                )
        if cc_skipped:
            text.append(
                f"Skipped: {len(cc_skipped)} ({', '.join(r.get('underlying', '?') for r in cc_skipped)})"
            )
        if cc_failed:
            text.append(
                f"Failed: {len(cc_failed)} ({', '.join(r.get('underlying', '?') for r in cc_failed)})"
            )
        text.append("")
        # CC lot builds in decisions
        cc_lot_buys = [
            (t, d)
            for t, d in decisions.items()
            if d.get("action") == "buy" and "CC lot build" in (d.get("reasoning") or "")
        ]
        if cc_lot_buys:
            text.append("CC LOT BUILDS (bought 100 shares for covered call writing)")
            text.append("-" * 80)
            for ticker, d in cc_lot_buys:
                text.append(
                    f"  {ticker}: bought {d.get('quantity', 0)} shares ({d.get('reasoning', '')})"
                )
            text.append("")

        csp_results = results.get("csp_results") or []
        if csp_results:
            text.append("CASH-SECURED PUTS")
            text.append("-" * 40)
            for r in csp_results:
                st = r.get("status", "?")
                u = r.get("underlying", "?")
                text.append(f"  {u}: {st} {r.get('contract_symbol', '')}")
            text.append("")

        # Past performance section (week-over-week equity change, if available)
        if past_perf:
            text.append("PAST PERFORMANCE (VS PREVIOUS RUN)")
            text.append("-" * 80)
            prev_eq = past_perf.get("prev_equity")
            curr_eq = past_perf.get("curr_equity")
            if prev_eq is not None and curr_eq is not None:
                delta = curr_eq - prev_eq
                pct = (delta / prev_eq * 100) if prev_eq else 0.0
                sign = "+" if delta >= 0 else ""
                text.append(f"Equity change: {sign}${delta:,.2f} ({pct:+.2f}%)")
            prev_exec = past_perf.get("prev_executed_count")
            curr_exec = past_perf.get("curr_executed_count")
            if prev_exec is not None and curr_exec is not None:
                text.append(f"Executed orders: this run={curr_exec}, previous={prev_exec}")
            text.append("")

        bench = results.get("benchmark") or {}
        if bench:
            text.append("BENCHMARK (ACTIVE RETURN)")
            text.append("-" * 80)
            if bench.get("equity_delta_pct") is not None:
                text.append(f"Book Δ: {float(bench['equity_delta_pct']):+.2f}%")
            if bench.get("spy_return_pct") is not None:
                text.append(f"SPY Δ: {float(bench['spy_return_pct']):+.2f}%")
            if bench.get("do_nothing_return_pct") is not None:
                text.append(f"Do-nothing (prior book) Δ: {float(bench['do_nothing_return_pct']):+.2f}%")
            if bench.get("active_vs_spy_pct") is not None:
                text.append(f"Active vs SPY: {float(bench['active_vs_spy_pct']):+.2f} pp")
            if bench.get("active_vs_do_nothing_pct") is not None:
                text.append(f"Active vs do-nothing: {float(bench['active_vs_do_nothing_pct']):+.2f} pp")
            thr = results.get("auto_throttle") or (results.get("phase13") or {}).get("auto_throttle") or {}
            if thr:
                text.append(
                    f"Auto-throttle: {'ON' if thr.get('throttled') else 'off'} "
                    f"(neg weeks {thr.get('negative_weeks', 0)}/{thr.get('threshold_weeks', 8)})"
                )
            text.append("")

        p13 = results.get("phase13") or {}
        if p13.get("enabled") or p13.get("special_opportunity_tickers"):
            text.append("PHASE 13 CONTROLS")
            text.append("-" * 80)
            specs = p13.get("special_opportunity_tickers") or []
            if specs:
                text.append(f"Special opportunities: {', '.join(str(x) for x in specs)}")
            dd = results.get("decision_diagnostics") or {}
            if dd.get("risk_off_active"):
                text.append("Hard risk-off: active (ordinary buys blocked)")
            if dd.get("book_stop_sells"):
                text.append(f"Book-stop sells: {dd.get('book_stop_sells')}")
            text.append("")

        # AI-generated weekly outlook
        if outlook:
            text.append("WEEKLY OUTLOOK")
            text.append("-" * 80)
            text.append(outlook.strip())
            text.append("")

        text.append("=" * 80)
        return "\n".join(text)

    def _format_trading_results_html(
        self, results: dict, past_perf: Optional[dict] = None, outlook: Optional[str] = None
    ) -> str:
        """Format trading results as HTML"""
        html = f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; }}
                h1 {{ color: #333; }}
                h2 {{ color: #666; border-bottom: 2px solid #ddd; padding-bottom: 5px; }}
                table {{ border-collapse: collapse; width: 100%; margin: 20px 0; }}
                th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
                th {{ background-color: #f2f2f2; }}
                .buy {{ color: green; }}
                .sell {{ color: red; }}
                .short {{ color: red; }}
                .hold {{ color: gray; }}
                .section {{ margin: 20px 0; }}
            </style>
        </head>
        <body>
            <h1>Weekly Trading Results</h1>
            <p><strong>Timestamp:</strong> {_format_timestamp(results.get('timestamp', 'N/A'))}</p>
            <p><strong>Tickers Analyzed:</strong> {len(results.get('tickers', []))}</p>
            <p><strong>Decisions Made:</strong> {len(results.get('decisions', {}))}</p>
            {self._execution_status_html_block(results)}
        """
        iw = (results.get("intraweek_stock_summary") or "").strip()
        if iw:
            html += f"""
            <div class="section">
                <h2>Intra-week main paper account (daily snapshots)</h2>
                <pre style="white-space:pre-wrap;font-size:12px;">{html_escape(iw)}</pre>
            </div>
            """

        # Portfolio
        if "portfolio" in results:
            portfolio = results["portfolio"]
            html += f"""
            <div class="section">
                <h2>Portfolio Status</h2>
                <table>
                    <tr><th>Metric</th><th>Value</th></tr>
                    <tr><td>Cash</td><td>${portfolio.get('cash', 0):,.2f}</td></tr>
                    <tr><td>Equity</td><td>${portfolio.get('equity', 0):,.2f}</td></tr>
        """
            buying_power = portfolio.get("buying_power")
            if buying_power is not None:
                html += f"""
                    <tr><td>Buying Power</td><td>${buying_power:,.2f}</td></tr>
        """
            html += """
                </table>
            </div>
            """

            # Positions table
            positions: Dict[str, Any] = portfolio.get("positions") or {}
            if positions:
                html += """
                <div class="section">
                    <h2>Top Positions</h2>
                    <table>
                        <tr><th>Ticker</th><th>Side</th><th>Quantity</th><th>Cost Basis</th></tr>
                """
                sorted_positions = sorted(
                    positions.items(),
                    key=lambda kv: abs((kv[1] or {}).get("long", 0) or 0)
                    + abs((kv[1] or {}).get("short", 0) or 0),
                    reverse=True,
                )
                for sym, pos in sorted_positions[:10]:
                    long_qty = pos.get("long", 0) or 0
                    short_qty = pos.get("short", 0) or 0
                    if long_qty:
                        cb = pos.get("long_cost_basis", 0) or 0
                        html += f"""
                        <tr>
                            <td>{sym}</td>
                            <td>long</td>
                            <td>{long_qty}</td>
                            <td>${cb:,.2f}</td>
                        </tr>
                        """
                    if short_qty:
                        cb = pos.get("short_cost_basis", 0) or 0
                        html += f"""
                        <tr>
                            <td>{sym}</td>
                            <td>short</td>
                            <td>{short_qty}</td>
                            <td>${cb:,.2f}</td>
                        </tr>
                        """
                html += """
                    </table>
                </div>
                """
            conc = _portfolio_concentration_lines(portfolio, results.get("risk_analysis") or {})
            if conc:
                html += """
                <div class="section">
                    <h2>Concentration alerts</h2>
                    <ul>
                """
                for line in conc:
                    html += f"<li>{html_escape(line)}</li>"
                html += "</ul></div>"

        lb = _load_scorecard_leaderboard(regime_mode=(results.get("regime") or {}).get("mode"))
        if lb:
            mode_label = lb[0][4] if lb else "global"
            html += f"""
            <div class="section">
                <h2>Agent leaderboard ({html_escape(mode_label)})</h2>
                <table>
                    <tr><th>Agent</th><th>Accuracy</th><th>CW return</th><th>N</th></tr>
            """
            for ak, acc, cw, obs, _mode in lb:
                html += f"""
                <tr><td>{html_escape(ak)}</td><td>{acc:.0%}</td><td>{cw:.2f}</td><td>{obs}</td></tr>
                """
            html += "</table></div>"
        learning = results.get("learning_context") or {}
        if learning:
            skip_note = ""
            if learning.get("scorecard_skip_reason"):
                need = max(
                    0,
                    2
                    - int(
                        learning.get("scan_cache_run_count_before")
                        or learning.get("scan_cache_run_count")
                        or 0
                    ),
                )
                if need > 0 and "need_at_least" in str(learning.get("scorecard_skip_reason")):
                    skip_note = f"<br/><strong>Next:</strong> {need} more saved run(s) until scorecard activates."
                skip_note += f"<br/><strong>Scorecard note:</strong> {html_escape(str(learning.get('scorecard_skip_reason'))[:200])}"
            policy = learning.get("policy_calibration") or {}
            policy_html = ""
            if policy:
                policy_html = f"""
                    <strong>Learned policy:</strong>
                    buy_conf={policy.get('min_buy_confidence')},
                    sell_conf={policy.get('min_sell_confidence')},
                    rotation_edge={policy.get('cash_rotation_min_edge')},
                    csp_floor=${policy.get('min_csp_premium_usd')}<br/>
                """
                for adj in (policy.get("adjustments") or [])[:3]:
                    policy_html += (
                        f"&nbsp;&nbsp;{html_escape(str(adj.get('knob')))}: "
                        f"{adj.get('delta'):+} ({html_escape(str(adj.get('reason', ''))[:80])})<br/>"
                    )
            changelog_html = ""
            weight_changes = learning.get("weight_changes") or []
            weight_skips = learning.get("weight_skips") or []
            if weight_changes or weight_skips:
                changelog_html = "<strong>Learning changelog</strong><br/><ul>"
                for wc in weight_changes[:5]:
                    changelog_html += (
                        f"<li>Weight {html_escape(str(wc.get('agent')))}: "
                        f"{wc.get('old')} → {wc.get('new')} (n={wc.get('observations')})</li>"
                    )
                for ws in weight_skips[:3]:
                    changelog_html += (
                        f"<li>Skip {html_escape(str(ws.get('agent')))}: "
                        f"{html_escape(str(ws.get('reason')))} "
                        f"(n={ws.get('observations')}/{ws.get('required')})</li>"
                    )
                changelog_html += "</ul>"
            html += f"""
            <div class="section">
                <h2>Learning context</h2>
                <p>
                    <strong>Feedback refresh:</strong> {"ok" if learning.get("feedback_refresh_ok") else "failed"}<br/>
                    <strong>Scorecard present:</strong> {"yes" if learning.get("scorecard_present") else "no"}<br/>
                    <strong>Scorecard after save:</strong> {"yes" if learning.get("scorecard_present_after") else "no"}<br/>
                    <strong>Scan cache (before / after):</strong> {int(learning.get("scan_cache_run_count_before") or learning.get("scan_cache_run_count") or 0)} / {int(learning.get("scan_cache_run_count_after") or 0)}<br/>
                    <strong>Ledger runs:</strong> {int(learning.get("ledger_run_count") or 0)} / {int(learning.get("ledger_run_count_after") or 0)} after save<br/>
                    <strong>Cache restore (perf/scan):</strong> {"hit" if learning.get("cache_restore_hit_performance") else "miss"} / {"hit" if learning.get("cache_restore_hit_scan") else "miss"}<br/>
                    <strong>Scorecard agents:</strong> {int(learning.get("scorecard_agent_count", 0) or 0)}<br/>
                    {f'<strong>Scorecard source:</strong> {html_escape(str(learning.get("scorecard_source")))}<br/>' if learning.get("scorecard_source") else ""}
                    {policy_html}
                    {skip_note}
                    {f'<strong>Refresh error:</strong> {html_escape(str(learning.get("feedback_refresh_error"))[:200])}' if learning.get("feedback_refresh_error") else ""}
                </p>
                {changelog_html}
            </div>
            """

        try:
            from src.performance.options_ledger import recent_summary

            opt_sum = recent_summary(weeks=8)
            if opt_sum.get("csp_executed") or opt_sum.get("cc_executed"):
                html += f"""
                <div class="section">
                    <h2>Options outcomes (learning)</h2>
                    <p>Rolling {opt_sum.get('weeks', 8)} weeks: CSP {opt_sum.get('csp_executed', 0)} fills
                    (avg ${opt_sum.get('csp_avg_premium_usd', 0):.0f},
                    {opt_sum.get('csp_sub_floor_count', 0)} below ${opt_sum.get('min_csp_premium_floor', 75):.0f}),
                    CC {opt_sum.get('cc_executed', 0)} fills
                    (avg ${opt_sum.get('cc_avg_premium_usd', 0):.0f})</p>
                </div>
                """
        except Exception:
            pass

        outcomes = self._build_decision_outcomes(results)
        if outcomes:
            html += """
            <div class="section">
                <h2>Last run decisions vs outcome</h2>
                <table>
                    <tr><th>Ticker</th><th>Action</th><th>Return %</th></tr>
            """
            for row in outcomes[:8]:
                html += f"""
                <tr>
                    <td>{html_escape(str(row.get('ticker')))}</td>
                    <td>{html_escape(str(row.get('action')))}</td>
                    <td>{row.get('return_pct', 'n/a')}</td>
                </tr>
                """
            html += "</table></div>"

        attr = (results.get("learning_context") or {}).get("portfolio_attribution")
        if attr:
            html += f"""
            <div class="section">
                <h2>Portfolio attribution (learning)</h2>
                <p>Equity delta: ${attr.get('equity_delta_usd', 0):+.2f} ({attr.get('equity_delta_pct', 0):+.2f}%)<br/>
                Cash flow from fills (buys negative): ${attr.get('trading_pnl_usd', 0):+.2f},
                Market move + residual: ${attr.get('carry_pnl_usd', 0):+.2f},
                Options premium: ${attr.get('options_premium_usd', 0):+.2f}</p>
            </div>
            """

        try:
            from src.performance.counterfactual_ledger import recent_for_email

            missed = recent_for_email(limit=3)
            if missed:
                html += """
                <div class="section"><h2>Missed opportunities (learning)</h2><ul>
                """
                for m in missed:
                    html += f"<li>{html_escape(str(m.get('ticker')))}: would {html_escape(str(m.get('would_be_action')))} → {m.get('forward_return_pct')}%</li>"
                html += "</ul></div>"
        except Exception:
            pass

        # Decisions -- buys and sells first, then top holds
        decisions = results.get("decisions", {})
        if decisions:
            buys = [(t, d) for t, d in decisions.items() if d.get("action") in ("buy", "cover")]
            sells = [(t, d) for t, d in decisions.items() if d.get("action") == "sell"]
            holds = [(t, d) for t, d in decisions.items() if d.get("action") == "hold"]
            buys.sort(key=lambda x: x[1].get("confidence", 0), reverse=True)
            sells.sort(key=lambda x: x[1].get("confidence", 0), reverse=True)
            holds.sort(key=lambda x: x[1].get("confidence", 0), reverse=True)

            html += f"""
            <div class="section">
                <h2>Decisions Summary</h2>
                <p><strong>{len(buys)}</strong> buys, <strong>{len(sells)}</strong> sells, <strong>{len(holds)}</strong> holds</p>
            </div>
            """

            if buys:
                html += """
                <div class="section">
                    <h2>Buy Orders</h2>
                    <table>
                        <tr><th>Ticker</th><th>Quantity</th><th>Confidence</th><th>Reasoning</th></tr>
                """
                for ticker, d in buys:
                    reasoning = html_escape((d.get("reasoning") or "")[:200])
                    html += f"""
                    <tr>
                        <td>{ticker}</td>
                        <td class="buy">{d.get('quantity', 0)}</td>
                        <td>{d.get('confidence', 0)}%</td>
                        <td>{reasoning}</td>
                    </tr>
                    """
                html += """
                    </table>
                </div>
                """

            if sells:
                html += """
                <div class="section">
                    <h2>Sell Orders</h2>
                    <table>
                        <tr><th>Ticker</th><th>Quantity</th><th>Confidence</th><th>Reasoning</th></tr>
                """
                for ticker, d in sells:
                    reasoning = html_escape((d.get("reasoning") or "")[:200])
                    html += f"""
                    <tr>
                        <td>{ticker}</td>
                        <td class="sell">{d.get('quantity', 0)}</td>
                        <td>{d.get('confidence', 0)}%</td>
                        <td>{reasoning}</td>
                    </tr>
                    """
                html += """
                    </table>
                </div>
                """

            if holds:
                html += f"""
                <div class="section">
                    <h2>Top Holds (showing 10 of {len(holds)})</h2>
                    <table>
                        <tr><th>Ticker</th><th>Confidence</th><th>Reasoning</th></tr>
                """
                for ticker, d in holds[:10]:
                    reasoning = html_escape((d.get("reasoning") or "")[:160])
                    html += f"""
                    <tr>
                        <td>{ticker}</td>
                        <td>{d.get('confidence', 0)}%</td>
                        <td>{reasoning}</td>
                    </tr>
                    """
                html += """
                    </table>
                </div>
                """
            dd = results.get("decision_diagnostics") or {}
            if dd:
                blockers = dd.get("buy_blockers") or {}
                blocker_text = ""
                if isinstance(blockers, dict) and blockers:
                    pairs = [f"{k}={int(v)}" for k, v in blockers.items()]
                    blocker_text = ", ".join(pairs[:6])
                html += f"""
                <div class="section">
                    <h2>Decision Diagnostics</h2>
                    <table>
                        <tr><th>Metric</th><th>Value</th></tr>
                        <tr><td>Signals (bullish &gt;= buy)</td><td>{int(dd.get("buy_signal_count", 0))}</td></tr>
                        <tr><td>Signals (bearish &gt;= sell on held)</td><td>{int(dd.get("sell_signal_on_held_count", 0))}</td></tr>
                        <tr><td>Buy candidates pre/post rank</td><td>{int(dd.get("buy_candidates_pre_rank", 0))} / {int(dd.get("buy_candidates_post_rank", 0))}</td></tr>
                        <tr><td>CC scored / passed</td><td>{int(dd.get("cc_scored_count", 0))} / {int(dd.get("cc_passed_threshold_count", 0))}</td></tr>
                        <tr><td>Blocked by risk/sizing</td><td>{int(dd.get("buy_blocked_by_risk_or_sizing_count", 0))}</td></tr>
                        <tr><td>Top blockers</td><td>{html_escape(blocker_text) if blocker_text else "-"}</td></tr>
                        <tr><td>Cash rotation sells</td><td>{int(dd.get("cash_rotation_sell_count", 0))}</td></tr>
                        <tr><td>Cash rotation skipped (edge / risk)</td><td>{int(dd.get("cash_rotation_skipped_edge", 0))} / {int(dd.get("cash_rotation_skipped_risk", 0))}</td></tr>
                        <tr><td>Cash rotation note</td><td>{html_escape(str(dd.get("cash_rotation_skip_reason") or "-"))}</td></tr>
                        <tr><td>Rotation sell tickers</td><td>{html_escape(", ".join(str(r.get("ticker", "?")) for r in (dd.get("rotation_sell_tickers") or [])[:8]) or "-")}</td></tr>
                        <tr><td>CC lots (held / build)</td><td>{int(dd.get("cc_held_lot_count", 0))} / {int(dd.get("cc_lot_build_count", 0))}</td></tr>
                    </table>
                </div>
                """
                slo = results.get("slo") or {}
                if slo:
                    html += f"""
                    <div class="section">
                        <h2>SLO Health</h2>
                        <table>
                            <tr><th>Metric</th><th>Value</th></tr>
                            <tr><td>Overall</td><td>{'ok' if slo.get("ok") else 'breach'}</td></tr>
                            <tr><td>Decision coverage</td><td>{int(slo.get("coverage", 0))}</td></tr>
                            <tr><td>Agent errors</td><td>{int(slo.get("agent_error_count", 0))}</td></tr>
                            <tr><td>Data quality score</td><td>{int(slo.get("data_quality_score", 0))}</td></tr>
                        </table>
                    </div>
                    """
                lane_ct = dd.get("lane_contributions") or {}
                llm_budget = results.get("llm_budget") or {}
                agent_errors = results.get("agent_errors") or {}
                html += f"""
                <div class="section">
                    <h2>Run Observability</h2>
                    <table>
                        <tr><th>Metric</th><th>Value</th></tr>
                        <tr><td>Lane contributions (bull / bear / total)</td><td>{int(lane_ct.get("bullish", 0))} / {int(lane_ct.get("bearish", 0))} / {int(lane_ct.get("total", 0))}</td></tr>
                        <tr><td>LLM budget (used / remaining)</td><td>{int(llm_budget.get("used", 0))} / {int(llm_budget.get("remaining", 0))}</td></tr>
                        <tr><td>Agent errors</td><td>{len(agent_errors)}</td></tr>
                    </table>
                </div>
                """

            # Submitted / filled orders this run
            exec_results = results.get("execution_results") or {}
            es = results.get("execution_status") or {}
            by_ticker_status = es.get("by_ticker") or {}
            if exec_results:
                failed_tickers = [
                    t
                    for t, r in exec_results.items()
                    if t != "error"
                    and ((not r) or (isinstance(r, dict) and r.get("status") == "failed"))
                ]
                decisions_map = results.get("decisions") or {}
                submitted_rows = []
                for ticker, res in exec_results.items():
                    if ticker == "error" or not res:
                        continue
                    if isinstance(res, dict) and res.get("status") == "failed":
                        continue
                    dec = decisions_map.get(ticker) or {}
                    action = dec.get("action") or res.get("side") or "?"
                    qty = dec.get("quantity") or res.get("qty") or res.get("filled_qty") or "?"
                    reason = html_escape((dec.get("reasoning") or res.get("reason") or "")[:200])
                    fill_st = html_escape(
                        str((by_ticker_status.get(ticker) or {}).get("status") or "submitted")
                    )
                    submitted_rows.append((ticker, action, qty, fill_st, reason))
                if submitted_rows:
                    html += """
                    <div class="section">
                        <h2>Submitted trades (this run)</h2>
                        <table>
                            <tr><th>Ticker</th><th>Action</th><th>Qty</th><th>Fill status</th><th>Reasoning</th></tr>
                    """
                    for ticker, action, qty, fill_st, reason in submitted_rows:
                        html += f"""
                            <tr>
                                <td>{html_escape(str(ticker))}</td>
                                <td>{html_escape(str(action))}</td>
                                <td>{html_escape(str(qty))}</td>
                                <td>{fill_st}</td>
                                <td>{reason}</td>
                            </tr>
                        """
                    html += """
                        </table>
                    </div>
                    """
                if failed_tickers:
                    html += f"""
                    <div class="section">
                        <h2>Failed Orders ({len(failed_tickers)})</h2>
                        <p>These orders were attempted but failed. Check logs for details.</p>
                        <table>
                            <tr><th>Ticker</th></tr>
                    """
                    for t in failed_tickers:
                        html += f"""
                            <tr><td class="sell">{t}</td></tr>
                        """
                    html += """
                        </table>
                    </div>
                    """

        # Covered call results
        cc_diag = results.get("covered_call_diagnostics") or {}
        cc_results = results.get("covered_call_results") or []
        cc_executed = [r for r in cc_results if r.get("status") == "executed"]
        cc_skipped = [r for r in cc_results if r.get("status") == "skipped"]
        cc_failed = [r for r in cc_results if r.get("status") == "failed"]
        total_premium = sum(r.get("estimated_premium", 0) for r in cc_executed)
        html += f"""
        <div class="section">
            <h2>Covered Calls</h2>
            <p>
                <strong>Enabled:</strong> {"yes" if bool(cc_diag.get("enabled", False)) else "no"}<br/>
                <strong>Execution mode:</strong> {"live" if bool(cc_diag.get("execute_mode", False)) else "dry"}<br/>
                <strong>Candidate tickers:</strong> {int(cc_diag.get("cc_lot_ticker_count", 0) or 0)}<br/>
                <strong>Outcome:</strong>
                executed={int(cc_diag.get("executed_count", len(cc_executed)) or 0)},
                skipped={int(cc_diag.get("skipped_count", len(cc_skipped)) or 0)},
                failed={int(cc_diag.get("failed_count", len(cc_failed)) or 0)}
                {f'<br/><strong>Step note:</strong> {html_escape(str(cc_diag.get("reason_not_run")))}' if cc_diag.get("reason_not_run") else ""}
                {f'<br/><strong>Est. premium:</strong> ${total_premium:,.2f}' if total_premium else ""}
            </p>
        """
        if cc_executed:
            html += """
            <table>
                <tr><th>Underlying</th><th>Contract</th><th>Strike</th><th>Expiry</th><th>Contracts</th><th>CC Score</th><th>Est. Premium</th></tr>
            """
            for r in cc_executed:
                html += f"""
                <tr>
                    <td>{r.get('underlying', '?')}</td>
                    <td>{r.get('contract_symbol', '?')}</td>
                    <td>${r.get('strike', 0):,.2f}</td>
                    <td>{r.get('expiry', '?')}</td>
                    <td>{r.get('contracts', 0)}</td>
                    <td>{r.get('cc_score', '?')}</td>
                    <td>${r.get('estimated_premium', 0):,.2f}</td>
                </tr>
                """
            html += "</table>"
        html += "</div>"

        # CC lot builds
        cc_lot_buys = [
            (t, d)
            for t, d in decisions.items()
            if d.get("action") == "buy" and "CC lot build" in (d.get("reasoning") or "")
        ]
        if cc_lot_buys:
            html += """
            <div class="section">
                <h2>CC Lot Builds</h2>
                <p>Shares purchased to reach 100-share lots for covered call writing.</p>
                <table>
                    <tr><th>Ticker</th><th>Quantity</th><th>Reasoning</th></tr>
            """
            for ticker, d in cc_lot_buys:
                html += f"""
                    <tr>
                        <td>{ticker}</td>
                        <td class="buy">{d.get('quantity', 0)}</td>
                        <td>{html_escape((d.get('reasoning') or '')[:200])}</td>
                    </tr>
                """
            html += """
                </table>
            </div>
            """

        # Open and recent orders
        open_orders = results.get("open_orders") or []
        if open_orders:
            html += """
            <div class="section">
                <h2>Open Orders</h2>
                <table>
                    <tr><th>Symbol</th><th>Side</th><th>Qty</th><th>Status</th><th>Submitted At</th></tr>
            """
            for o in open_orders[:10]:
                sym = o.get("symbol") or o.get("asset_id") or "?"
                side = o.get("side", "?")
                qty = o.get("qty") or o.get("filled_qty") or 0
                status = o.get("status", "open")
                submitted = (o.get("submitted_at") or "")[:19]
                html += f"""
                    <tr>
                        <td>{sym}</td>
                        <td>{side}</td>
                        <td>{qty}</td>
                        <td>{status}</td>
                        <td>{submitted}</td>
                    </tr>
                """
            html += """
                </table>
            </div>
            """

        recent_orders = results.get("recent_orders") or []
        if recent_orders:
            html += """
            <div class="section">
                <h2>Recent Orders</h2>
                <table>
                    <tr><th>Symbol</th><th>Side</th><th>Qty</th><th>Status</th><th>Filled At</th></tr>
            """
            for o in recent_orders[:20]:
                sym = o.get("symbol") or o.get("asset_id") or "?"
                side = o.get("side", "?")
                qty = o.get("qty") or o.get("filled_qty") or 0
                status = o.get("status", "")
                filled = (o.get("filled_at") or "")[:19]
                html += f"""
                    <tr>
                        <td>{sym}</td>
                        <td>{side}</td>
                        <td>{qty}</td>
                        <td>{status}</td>
                        <td>{filled}</td>
                    </tr>
                """
            html += """
                </table>
            </div>
            """

        # Past performance section
        if past_perf:
            html += """
            <div class="section">
                <h2>Past Performance (vs Previous Run)</h2>
                <table>
                    <tr><th>Metric</th><th>Value</th></tr>
            """
            prev_eq = past_perf.get("prev_equity")
            curr_eq = past_perf.get("curr_equity")
            if prev_eq is not None and curr_eq is not None:
                delta = curr_eq - prev_eq
                pct = (delta / prev_eq * 100) if prev_eq else 0.0
                sign = "+" if delta >= 0 else ""
                html += f"""
                    <tr><td>Equity change</td><td>{sign}${delta:,.2f} ({pct:+.2f}%)</td></tr>
                """
            prev_exec = past_perf.get("prev_executed_count")
            curr_exec = past_perf.get("curr_executed_count")
            if prev_exec is not None and curr_exec is not None:
                html += f"""
                    <tr><td>Executed orders (this vs previous)</td><td>{curr_exec} vs {prev_exec}</td></tr>
                """
            html += """
                </table>
            </div>
            """

        bench = results.get("benchmark") or {}
        if bench:
            html += """
            <div class="section">
                <h2>Benchmark (active return)</h2>
                <table>
                    <tr><th>Metric</th><th>Value</th></tr>
            """
            if bench.get("equity_delta_pct") is not None:
                html += f"<tr><td>Book Δ</td><td>{float(bench['equity_delta_pct']):+.2f}%</td></tr>"
            if bench.get("spy_return_pct") is not None:
                html += f"<tr><td>SPY Δ</td><td>{float(bench['spy_return_pct']):+.2f}%</td></tr>"
            if bench.get("do_nothing_return_pct") is not None:
                html += (
                    f"<tr><td>Do-nothing (prior book) Δ</td>"
                    f"<td>{float(bench['do_nothing_return_pct']):+.2f}%</td></tr>"
                )
            if bench.get("active_vs_spy_pct") is not None:
                html += f"<tr><td>Active vs SPY</td><td>{float(bench['active_vs_spy_pct']):+.2f} pp</td></tr>"
            if bench.get("active_vs_do_nothing_pct") is not None:
                html += (
                    f"<tr><td>Active vs do-nothing</td>"
                    f"<td>{float(bench['active_vs_do_nothing_pct']):+.2f} pp</td></tr>"
                )
            thr = results.get("auto_throttle") or (results.get("phase13") or {}).get("auto_throttle") or {}
            if thr:
                html += (
                    f"<tr><td>Auto-throttle</td><td>"
                    f"{'ON' if thr.get('throttled') else 'off'} "
                    f"(neg weeks {thr.get('negative_weeks', 0)}/{thr.get('threshold_weeks', 8)})"
                    f"</td></tr>"
                )
            html += "</table></div>"

        p13 = results.get("phase13") or {}
        dd = results.get("decision_diagnostics") or {}
        if p13.get("enabled") or dd.get("risk_off_active") or p13.get("special_opportunity_tickers"):
            specs = ", ".join(str(x) for x in (p13.get("special_opportunity_tickers") or [])) or "none"
            html += f"""
            <div class="section">
                <h2>Phase 13 controls</h2>
                <p>
                    <strong>Risk-off:</strong> {"active" if dd.get("risk_off_active") else "inactive"}<br/>
                    <strong>Special opportunities:</strong> {html_escape(specs)}<br/>
                    <strong>Book-stop sells:</strong> {int(dd.get("book_stop_sells") or 0)}<br/>
                    <strong>Dead-money sells:</strong> {int(dd.get("dead_money_sells") or 0)}
                </p>
            </div>
            """

        # AI-generated weekly outlook
        if outlook:
            html += f"""
            <div class="section">
                <h2>Weekly Outlook</h2>
                <p>{html_escape(outlook.strip())}</p>
            </div>
            """

        html += """
        </body>
        </html>
        """
        return html

    # ---------- Helpers for past performance & AI outlook ----------

    def _build_decision_outcomes(self, results: dict) -> list:
        """Resolved decision attribution rows (ledger first, scan_cache fallback)."""
        try:
            from src.performance.decision_ledger import outcome_rows_for_email

            rows = outcome_rows_for_email(limit=8)
            if rows:
                return rows
        except Exception:
            pass
        run_id = results.get("run_id")
        if not run_id:
            return []
        cache = ScanCache()
        runs = cache.list_runs(limit=5)
        prev_meta = None
        for idx, meta in enumerate(runs):
            if meta.get("run_id") == run_id and idx + 1 < len(runs):
                prev_meta = runs[idx + 1]
                break
        if not prev_meta:
            return []
        prev = cache.load_run(prev_meta["run_id"])
        prev_dec = prev.get("decisions") or {}
        curr_risk = results.get("risk_analysis") or {}
        prev_risk = prev.get("risk") or {}
        rows = []
        for ticker, dec in prev_dec.items():
            action = dec.get("action") if isinstance(dec, dict) else getattr(dec, "action", "")
            if action not in ("buy", "sell"):
                continue
            p0 = (prev_risk.get(ticker) or {}).get("current_price")
            p1 = (curr_risk.get(ticker) or {}).get("current_price")
            if not p0 or not p1:
                continue
            ret = (float(p1) - float(p0)) / float(p0) * 100.0
            rows.append({"ticker": ticker, "action": action, "return_pct": round(ret, 2)})
        rows.sort(key=lambda r: abs(r["return_pct"]), reverse=True)
        return rows[:5]

    def _build_past_performance(self, results: dict) -> Optional[dict]:
        """Compare this run against the previous cached run, if available."""
        run_id = results.get("run_id")
        if not run_id:
            return None

        cache = ScanCache()
        runs = cache.list_runs(limit=10, since_date=None)
        if not runs:
            return None

        # Find this run, then take the next one as "previous"
        prev_meta = None
        for idx, meta in enumerate(runs):
            if meta.get("run_id") == run_id and idx + 1 < len(runs):
                prev_meta = runs[idx + 1]
                break
        if not prev_meta:
            return None

        prev = cache.load_run(prev_meta["run_id"])

        def compute_equity(
            portfolio: Optional[Dict[str, Any]], risk: Optional[Dict[str, Any]]
        ) -> Optional[float]:
            if not portfolio:
                return None
            equity_val = float(portfolio.get("cash", 0.0))
            positions = portfolio.get("positions") or {}
            risk_data = risk or {}
            for sym, pos in positions.items():
                price = (risk_data.get(sym) or {}).get("current_price")
                if price is None:
                    price = pos.get("long_cost_basis") or pos.get("short_cost_basis") or 0.0
                price = float(price)
                equity_val += (pos.get("long", 0) or 0) * price
                equity_val -= (pos.get("short", 0) or 0) * price
            return round(equity_val, 2)

        curr_port = results.get("portfolio") or {}
        curr_eq = curr_port.get("equity")
        if curr_eq is None:
            curr_eq = compute_equity(curr_port, results.get("risk_analysis"))

        prev_port = prev.get("portfolio_after") or prev.get("portfolio_before")
        prev_eq = compute_equity(prev_port, prev.get("risk"))

        prev_exec_res = prev.get("execution_results") or {}
        curr_exec_res = results.get("execution_results") or {}
        prev_exec_count = (
            sum(1 for r in prev_exec_res.values() if r) if isinstance(prev_exec_res, dict) else None
        )
        curr_exec_count = (
            sum(1 for r in curr_exec_res.values() if r) if isinstance(curr_exec_res, dict) else None
        )

        return {
            "prev_run_id": prev_meta["run_id"],
            "prev_equity": prev_eq,
            "curr_equity": curr_eq,
            "prev_executed_count": prev_exec_count,
            "curr_executed_count": curr_exec_count,
        }

    def _generate_weekly_outlook(self, results: dict, past_perf: Optional[dict]) -> Optional[str]:
        """Use an LLM to generate a short 2–3 sentence outlook."""
        try:
            llm = get_llm_for_agent("deepseek-v3", "deepseek")
        except Exception:
            return None

        decisions = results.get("decisions") or {}
        portfolio = results.get("portfolio") or {}
        eq = portfolio.get("equity")
        cash = portfolio.get("cash")

        buys = [t for t, d in decisions.items() if d.get("action") in ("buy", "long")]
        sells = [t for t, d in decisions.items() if d.get("action") in ("sell", "short")]
        holds = [t for t, d in decisions.items() if d.get("action") == "hold"]

        lines = []
        lines.append("You are an investment strategist summarizing this week's trading cycle.")
        lines.append(
            "In 2–3 sentences, summarize the portfolio's current stance and one key risk or opportunity for the week ahead."
        )
        lines.append("Avoid disclaimers and avoid restating the full input. Be direct and concise.")
        lines.append("")
        lines.append("Context:")
        lines.append(f"- Equity: ${eq:,.2f}" if isinstance(eq, (int, float)) else f"- Equity: {eq}")
        lines.append(
            f"- Cash: ${cash:,.2f}" if isinstance(cash, (int, float)) else f"- Cash: {cash}"
        )
        lines.append(f"- Buys/Longs this run: {', '.join(buys) or 'none'}")
        lines.append(f"- Sells/Shorts this run: {', '.join(sells) or 'none'}")
        lines.append(f"- Holds this run: {', '.join(holds) or 'none'}")

        if (
            past_perf
            and past_perf.get("prev_equity") is not None
            and past_perf.get("curr_equity") is not None
        ):
            delta = past_perf["curr_equity"] - past_perf["prev_equity"]
            pct = (delta / past_perf["prev_equity"] * 100) if past_perf["prev_equity"] else 0.0
            lines.append(f"- Week-over-week equity change: {delta:+.2f} ({pct:+.2f}%)")

        bench = results.get("benchmark") or {}
        if bench.get("active_vs_spy_pct") is not None:
            lines.append(f"- Active return vs SPY: {float(bench['active_vs_spy_pct']):+.2f} pp")
        if bench.get("do_nothing_return_pct") is not None:
            lines.append(f"- Do-nothing prior book: {float(bench['do_nothing_return_pct']):+.2f}%")

        prompt = "\n".join(lines)

        try:
            from langchain_core.messages import HumanMessage
        except Exception:
            return None

        try:
            resp = llm.invoke([HumanMessage(content=prompt)])
            text = getattr(resp, "content", "") or str(resp)
            if not isinstance(text, str):
                text = str(text)
            return text.strip()
        except Exception:
            return None


# Utility to escape HTML snippets safely
def html_escape(text: str) -> str:
    return html.escape(text, quote=True)


# Global email notifier instance
_email_notifier: Optional[EmailNotifier] = None


def get_email_notifier() -> EmailNotifier:
    """Get global email notifier instance"""
    global _email_notifier
    if _email_notifier is None:
        _email_notifier = EmailNotifier()
    return _email_notifier
