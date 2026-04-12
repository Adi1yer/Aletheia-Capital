"""Email notification system"""

import smtplib
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
        self.smtp_server = smtp_server or getattr(settings, 'smtp_server', None)
        self.smtp_port = smtp_port
        self.sender_email = sender_email or getattr(settings, 'sender_email', None)
        self.sender_password = sender_password or getattr(settings, 'sender_password', None)
        
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
            msg = MIMEMultipart('alternative')
            msg['From'] = self.sender_email
            msg['To'] = recipient
            msg['Subject'] = subject
            
            # Add text and HTML parts
            part1 = MIMEText(body_text, 'plain')
            msg.attach(part1)
            
            if body_html:
                part2 = MIMEText(body_html, 'html')
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
    
    def send_daily_update(
        self,
        recipient: str,
        update_data: dict,
        formatted_report: str,
    ) -> bool:
        """
        Send daily market update email
        
        Args:
            recipient: Recipient email address
            update_data: Update data dictionary
            formatted_report: Formatted text report
        
        Returns:
            True if sent successfully, False otherwise
        """
        subject = f"Daily Market Update - {update_data.get('date', 'N/A')}"
        
        # Create HTML version
        html_body = self._format_daily_update_html(update_data, formatted_report)
        
        return self.send_email(
            recipient=recipient,
            subject=subject,
            body_text=formatted_report,
            body_html=html_body,
        )
    
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
        all_decisions = results.get('decisions', {})
        decision_count = len(all_decisions)
        buy_count = sum(1 for d in all_decisions.values() if d.get("action") in ("buy", "cover"))
        sell_count = sum(1 for d in all_decisions.values() if d.get("action") == "sell")
        executed = results.get('execution_results', {})
        executed_count = sum(1 for r in executed.values() if r) if executed else 0

        ts = results.get("timestamp")
        week_label = "Week"
        if ts:
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                week_start: date = dt.date()
                week_label = f"Week of {week_start.strftime('%B %d, %Y')}"
            except Exception:
                week_label = f"Week of {ts[:10]}"

        subject = f"{week_label} – {buy_count} Buys, {sell_count} Sells, {executed_count} Executed ({decision_count} analyzed)"
        
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
    
    def _format_daily_update_html(self, update_data: dict, text_report: str) -> str:
        """Format daily update as HTML"""
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
                .positive {{ color: green; }}
                .negative {{ color: red; }}
                .section {{ margin: 20px 0; }}
            </style>
        </head>
        <body>
            <h1>Daily Market Update - {update_data.get('date', 'N/A')}</h1>
        """
        
        # Portfolio Status
        if 'portfolio' in update_data and 'error' not in update_data['portfolio']:
            portfolio = update_data['portfolio']
            html += f"""
            <div class="section">
                <h2>Portfolio Status</h2>
                <table>
                    <tr><th>Metric</th><th>Value</th></tr>
                    <tr><td>Cash</td><td>${portfolio.get('cash', 0):,.2f}</td></tr>
                    <tr><td>Equity</td><td>${portfolio.get('equity', 0):,.2f}</td></tr>
                    <tr><td>Portfolio Value</td><td>${portfolio.get('portfolio_value', 0):,.2f}</td></tr>
                    <tr><td>Buying Power</td><td>${portfolio.get('buying_power', 0):,.2f}</td></tr>
                    <tr><td>Positions</td><td>{portfolio.get('position_count', 0)}</td></tr>
                </table>
            </div>
            """
        
        # Market Summary
        if 'market_summary' in update_data:
            html += """
            <div class="section">
                <h2>Market Summary</h2>
                <table>
                    <tr><th>Index</th><th>Ticker</th><th>Price</th><th>Change %</th></tr>
            """
            for name, data in update_data['market_summary'].items():
                if 'error' not in data:
                    change_class = 'positive' if data['change_pct'] >= 0 else 'negative'
                    change_str = f"+{data['change_pct']:.2f}%" if data['change_pct'] >= 0 else f"{data['change_pct']:.2f}%"
                    html += f"""
                    <tr>
                        <td>{name}</td>
                        <td>{data['ticker']}</td>
                        <td>${data['current']:.2f}</td>
                        <td class="{change_class}">{change_str}</td>
                    </tr>
                    """
            html += """
                </table>
            </div>
            """
        
        # Top Holdings
        if 'holdings_data' in update_data and update_data['holdings_data']:
            html += """
            <div class="section">
                <h2>Top Holdings</h2>
                <table>
                    <tr><th>Ticker</th><th>Price</th><th>Change %</th><th>P/E</th></tr>
            """
            sorted_holdings = sorted(
                update_data['holdings_data'].items(),
                key=lambda x: x[1].get('price_change_pct', 0),
                reverse=True
            )
            for ticker, data in sorted_holdings[:10]:
                change_class = 'positive' if data['price_change_pct'] >= 0 else 'negative'
                change_str = f"+{data['price_change_pct']:.2f}%" if data['price_change_pct'] >= 0 else f"{data['price_change_pct']:.2f}%"
                pe = data.get('pe_ratio', 'N/A')
                html += f"""
                <tr>
                    <td>{ticker}</td>
                    <td>${data['current_price']:.2f}</td>
                    <td class="{change_class}">{change_str}</td>
                    <td>{pe if pe else 'N/A'}</td>
                </tr>
                """
            html += """
                </table>
            </div>
            """
        
        html += """
        </body>
        </html>
        """
        return html
    
    def _format_trading_results_text(self, results: dict, past_perf: Optional[dict] = None, outlook: Optional[str] = None) -> str:
        """Format trading results as plain text"""
        text = []
        text.append("=" * 80)
        text.append("WEEKLY TRADING RESULTS")
        text.append("=" * 80)
        text.append("")
        text.append(f"Timestamp: {_format_timestamp(results.get('timestamp', 'N/A'))}")
        text.append(f"Tickers Analyzed: {len(results.get('tickers', []))}")
        text.append(f"Decisions Made: {len(results.get('decisions', {}))}")
        text.append("")

        # Portfolio summary
        if 'portfolio' in results:
            portfolio = results['portfolio']
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
                    key=lambda kv: abs((kv[1] or {}).get("long", 0) or 0) + abs((kv[1] or {}).get("short", 0) or 0),
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
            text.append("RECENT ORDERS")
            text.append("-" * 80)
            for o in recent_orders[:20]:
                sym = o.get("symbol") or o.get("asset_id") or "?"
                side = o.get("side") or "?"
                qty = o.get("qty") or o.get("filled_qty") or 0
                status = o.get("status") or ""
                filled = (o.get("filled_at") or "")[:19]
                text.append(f"{sym}: {side} {qty} - {status} {filled}")
            text.append("")

        # Decisions -- buys and sells first, then top holds
        decisions = results.get('decisions', {})
        if decisions:
            buys = [(t, d) for t, d in decisions.items() if d.get("action") in ("buy", "cover")]
            sells = [(t, d) for t, d in decisions.items() if d.get("action") == "sell"]
            holds = [(t, d) for t, d in decisions.items() if d.get("action") == "hold"]
            buys.sort(key=lambda x: x[1].get("confidence", 0), reverse=True)
            sells.sort(key=lambda x: x[1].get("confidence", 0), reverse=True)
            holds.sort(key=lambda x: x[1].get("confidence", 0), reverse=True)

            text.append(f"DECISIONS SUMMARY: {len(buys)} buys, {len(sells)} sells, {len(holds)} holds")
            text.append("-" * 80)
            text.append("")

            if buys:
                text.append("BUY ORDERS")
                text.append("-" * 40)
                for ticker, d in buys:
                    text.append(f"  {ticker}: buy {d.get('quantity', 0)} shares (Confidence: {d.get('confidence', 0)}%)")
                    reasoning = (d.get("reasoning") or "").strip()
                    if reasoning:
                        text.append(f"    Reason: {reasoning[:200]}")
                text.append("")

            if sells:
                text.append("SELL ORDERS")
                text.append("-" * 40)
                for ticker, d in sells:
                    text.append(f"  {ticker}: sell {d.get('quantity', 0)} shares (Confidence: {d.get('confidence', 0)}%)")
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
                    text.append(f"  {ticker}: hold (Confidence: {d.get('confidence', 0)}%) – {snippet}")
                text.append("")

        # Execution Results
        exec_results = results.get('execution_results') or {}
        if exec_results:
            executed = sum(1 for r in exec_results.values() if r)
            failed_tickers = [t for t, r in exec_results.items() if not r]
            text.append(f"EXECUTION RESULTS: {executed} orders executed")
            if failed_tickers:
                text.append(f"FAILED ORDERS ({len(failed_tickers)}): {', '.join(failed_tickers)}")
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

        # AI-generated weekly outlook
        if outlook:
            text.append("WEEKLY OUTLOOK")
            text.append("-" * 80)
            text.append(outlook.strip())
            text.append("")
        
        text.append("=" * 80)
        return "\n".join(text)
    
    def _format_trading_results_html(self, results: dict, past_perf: Optional[dict] = None, outlook: Optional[str] = None) -> str:
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
        """
        
        # Portfolio
        if 'portfolio' in results:
            portfolio = results['portfolio']
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
                    key=lambda kv: abs((kv[1] or {}).get("long", 0) or 0) + abs((kv[1] or {}).get("short", 0) or 0),
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
        
        # Decisions -- buys and sells first, then top holds
        decisions = results.get('decisions', {})
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

            # Failed orders section
            exec_results = results.get('execution_results') or {}
            if exec_results:
                failed_tickers = [t for t, r in exec_results.items() if not r]
                executed_count = sum(1 for r in exec_results.values() if r)
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

        def compute_equity(portfolio: Optional[Dict[str, Any]], risk: Optional[Dict[str, Any]]) -> Optional[float]:
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
        prev_exec_count = sum(1 for r in prev_exec_res.values() if r) if isinstance(prev_exec_res, dict) else None
        curr_exec_count = sum(1 for r in curr_exec_res.values() if r) if isinstance(curr_exec_res, dict) else None

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
        lines.append("In 2–3 sentences, summarize the portfolio's current stance and one key risk or opportunity for the week ahead.")
        lines.append("Avoid disclaimers and avoid restating the full input. Be direct and concise.")
        lines.append("")
        lines.append("Context:")
        lines.append(f"- Equity: ${eq:,.2f}" if isinstance(eq, (int, float)) else f"- Equity: {eq}")
        lines.append(f"- Cash: ${cash:,.2f}" if isinstance(cash, (int, float)) else f"- Cash: {cash}")
        lines.append(f"- Buys/Longs this run: {', '.join(buys) or 'none'}")
        lines.append(f"- Sells/Shorts this run: {', '.join(sells) or 'none'}")
        lines.append(f"- Holds this run: {', '.join(holds) or 'none'}")

        if past_perf and past_perf.get("prev_equity") is not None and past_perf.get("curr_equity") is not None:
            delta = past_perf["curr_equity"] - past_perf["prev_equity"]
            pct = (delta / past_perf["prev_equity"] * 100) if past_perf["prev_equity"] else 0.0
            lines.append(
                f"- Week-over-week equity change: {delta:+.2f} ({pct:+.2f}%)"
            )

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

