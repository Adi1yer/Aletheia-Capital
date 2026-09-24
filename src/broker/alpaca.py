"""Alpaca broker integration for paper trading"""

from typing import Any, Callable, Dict, List, Optional, TypeVar
from datetime import date, timedelta
import time
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    MarketOrderRequest,
    LimitOrderRequest,
    GetOrdersRequest,
    GetOptionContractsRequest,
    StopLossRequest,
)
from alpaca.trading.enums import OrderSide, TimeInForce, OrderType, ContractType, OrderClass
from src.config.settings import settings
from src.portfolio.models import Portfolio, Position
from src.portfolio.manager import PortfolioDecision
import structlog

logger = structlog.get_logger()


class BrokerDataError(RuntimeError):
    """Broker account/position data unavailable — callers must not treat as empty book."""


T = TypeVar("T")


def _is_transient_alpaca_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    needles = (
        "timed out",
        "timeout",
        "50410000",
        "503",
        "502",
        "connection reset",
        "temporarily unavailable",
        "gateway",
        "429",
        "too many requests",
    )
    return any(n in text for n in needles)


def alpaca_call_with_retry(
    fn: Callable[[], T],
    *,
    op: str = "alpaca_call",
    attempts: int = 4,
    base_delay_sec: float = 3.0,
) -> T:
    """Retry transient Alpaca/network failures (timeouts, 5xx, rate limits)."""
    last: Optional[BaseException] = None
    for i in range(max(1, int(attempts))):
        try:
            return fn()
        except Exception as e:
            last = e
            if i >= attempts - 1 or not _is_transient_alpaca_error(e):
                raise
            delay = base_delay_sec * (2**i)
            logger.warning(
                "Transient Alpaca error; retrying",
                op=op,
                attempt=i + 1,
                attempts=attempts,
                delay_sec=delay,
                error=str(e),
            )
            time.sleep(delay)
    assert last is not None
    raise last


class AlpacaBroker:
    """Alpaca broker integration (alpaca-py SDK)"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        secret_key: Optional[str] = None,
    ):
        """Initialize Alpaca client for paper trading.

        Optional api_key/secret_key override settings (e.g. isolated biotech paper account).
        """
        paper_base_url = "https://paper-api.alpaca.markets/v2"
        if settings.alpaca_base_url != paper_base_url:
            logger.warning(
                "Alpaca base_url not set to paper trading endpoint, overriding",
                provided_url=settings.alpaca_base_url,
                using_url=paper_base_url,
            )

        key = api_key if api_key is not None else settings.alpaca_api_key
        sec = secret_key if secret_key is not None else settings.alpaca_secret_key

        self.client = TradingClient(
            api_key=key,
            secret_key=sec,
            paper=True,
        )
        logger.info(
            "Initialized Alpaca broker for paper trading",
            base_url=paper_base_url,
            isolated=bool(api_key is not None or secret_key is not None),
        )

    def get_account(self) -> Dict:
        """Get account information (retries on transient Alpaca timeouts)."""
        try:
            account = alpaca_call_with_retry(
                lambda: self.client.get_account(),
                op="get_account",
            )
            return {
                "cash": float(account.cash),
                "buying_power": float(account.buying_power),
                "portfolio_value": float(account.portfolio_value),
                "equity": float(account.equity),
            }
        except Exception as e:
            logger.error("Error fetching account", error=str(e))
            raise

    def get_positions(self) -> Dict[str, Dict]:
        """Get current positions (retries on transient Alpaca timeouts)."""
        try:
            positions = alpaca_call_with_retry(
                lambda: self.client.get_all_positions(),
                op="get_positions",
            )
            position_dict = {}

            for pos in positions:
                sym = str(pos.symbol or "")
                # Options OCC symbols are longer than equity tickers — keep equity-only here.
                if len(sym) > 10:
                    continue
                qty = abs(int(float(pos.qty)))
                side = (
                    getattr(pos.side, "value", str(pos.side)).lower()
                    if hasattr(pos, "side")
                    else ("long" if int(float(pos.qty)) >= 0 else "short")
                )
                if side not in ("long", "short"):
                    side = "long"
                position_dict[sym] = {
                    "qty": qty,
                    "avg_entry_price": float(pos.avg_entry_price),
                    "market_value": float(pos.market_value),
                    "side": side,
                }

            return position_dict
        except Exception as e:
            logger.error("Error fetching positions", error=str(e))
            raise

    def get_last_equity_prices(self, symbols: List[str]) -> Dict[str, float]:
        """Latest bid/ask for underlyings we may not hold (CSP near-ITM checks)."""
        out: Dict[str, float] = {}
        syms = [str(s).upper().strip() for s in symbols if str(s or "").strip()]
        if not syms:
            return out
        try:
            from alpaca.data.historical import StockHistoricalDataClient
            from alpaca.data.requests import StockLatestQuoteRequest

            key = settings.alpaca_api_key
            sec = settings.alpaca_secret_key
            if not key or not sec:
                return out
            client = StockHistoricalDataClient(key, sec)
            quotes = alpaca_call_with_retry(
                lambda: client.get_stock_latest_quote(
                    StockLatestQuoteRequest(symbol_or_symbols=syms)
                ),
                op="get_stock_latest_quote",
                attempts=2,
                base_delay_sec=1.0,
            )
            qmap = quotes if isinstance(quotes, dict) else getattr(quotes, "data", None) or {}
            for s in syms:
                q = qmap.get(s)
                if q is None:
                    continue
                for val in (
                    getattr(q, "ask_price", None),
                    getattr(q, "bid_price", None),
                ):
                    try:
                        px = float(val)
                    except (TypeError, ValueError):
                        continue
                    if px == px and px > 0:
                        out[s] = px
                        break
        except Exception as e:
            logger.warning("Equity quote backfill failed", error=str(e))
        return out

    def get_open_orders(self, limit: int = 50) -> List[Dict]:
        """Get open (pending) orders from Alpaca."""
        try:
            req = GetOrdersRequest(status="open", limit=limit)
            orders = self.client.get_orders(req)
            return [
                {
                    "id": str(o.id),
                    "symbol": o.symbol,
                    "side": getattr(o.side, "value", str(o.side)).lower(),
                    "qty": int(float(o.qty)) if o.qty else 0,
                    "filled_qty": int(float(o.filled_qty))
                    if getattr(o, "filled_qty", None) is not None
                    else 0,
                    "status": getattr(o.status, "value", str(o.status)).lower(),
                    "submitted_at": str(o.submitted_at)
                    if hasattr(o, "submitted_at") and o.submitted_at
                    else None,
                    "type": getattr(o.type, "value", str(o.type)).lower()
                    if hasattr(o, "type")
                    else "market",
                }
                for o in (orders or [])
            ]
        except Exception as e:
            logger.error("Error fetching open orders", error=str(e))
            return []

    def cancel_order(self, order_id: str) -> bool:
        """Cancel a single order by id. Returns True on success."""
        try:
            self.client.cancel_order_by_id(str(order_id))
            logger.info("Cancelled order", order_id=str(order_id))
            return True
        except Exception as e:
            logger.warning("Cancel order failed", order_id=str(order_id), error=str(e))
            return False

    def cancel_stale_orders(self, *, max_age_hours: float = 48.0, limit: int = 50) -> Dict[str, Any]:
        """Cancel open orders older than max_age_hours (pending hygiene)."""
        from datetime import datetime, timezone

        open_orders = self.get_open_orders(limit=limit)
        cancelled = []
        skipped = []
        now = datetime.now(timezone.utc)
        for o in open_orders:
            submitted = o.get("submitted_at")
            age_h = None
            if submitted:
                try:
                    raw = str(submitted).replace("Z", "+00:00")
                    dt = datetime.fromisoformat(raw)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    age_h = (now - dt).total_seconds() / 3600.0
                except Exception:
                    age_h = None
            if float(max_age_hours) > 0 and (age_h is None or age_h < float(max_age_hours)):
                skipped.append({"id": o.get("id"), "symbol": o.get("symbol"), "age_h": age_h})
                continue
            if self.cancel_order(str(o.get("id"))):
                cancelled.append({"id": o.get("id"), "symbol": o.get("symbol"), "age_h": age_h})
        return {"cancelled": cancelled, "skipped": skipped, "max_age_hours": max_age_hours}

    def get_recent_orders(self, limit: int = 20) -> List[Dict]:
        """Get recently closed/filled orders from Alpaca."""
        try:
            req = GetOrdersRequest(status="closed", limit=limit)
            orders = self.client.get_orders(req)
            return [
                {
                    "id": str(o.id),
                    "symbol": o.symbol,
                    "side": getattr(o.side, "value", str(o.side)).lower(),
                    "qty": int(float(o.qty)) if o.qty else 0,
                    "filled_qty": int(float(o.filled_qty)) if getattr(o, "filled_qty", None) else int(float(o.qty)) if o.qty else 0,
                    "filled_avg_price": float(o.filled_avg_price)
                    if getattr(o, "filled_avg_price", None) is not None
                    else None,
                    "status": getattr(o.status, "value", str(o.status)).lower(),
                    "filled_at": str(o.filled_at)
                    if hasattr(o, "filled_at") and o.filled_at
                    else None,
                    "submitted_at": str(o.submitted_at)
                    if hasattr(o, "submitted_at") and o.submitted_at
                    else None,
                }
                for o in (orders or [])
            ]
        except Exception as e:
            logger.error("Error fetching recent orders", error=str(e))
            return []

    def execute_order(
        self,
        ticker: str,
        decision: PortfolioDecision,
        current_price: Optional[float] = None,
        stop_loss_pct: Optional[float] = None,
        use_limit_order: bool = False,
        limit_slippage_pct: float = 0.002,
        execution_tactic: Optional[Dict] = None,
    ) -> Optional[Dict]:
        """
        Execute a trading order

        Args:
            ticker: Stock ticker symbol
            decision: Portfolio decision to execute

        Returns:
            Order information if successful, None otherwise
        """
        if decision.action == "hold" or decision.quantity == 0:
            logger.info("Skipping hold order", ticker=ticker)
            return None

        tactic = execution_tactic or {}
        if tactic:
            use_limit_order = bool(tactic.get("use_limit_order", use_limit_order))
            limit_slippage_pct = float(tactic.get("limit_slippage_pct", limit_slippage_pct))

        try:
            if decision.action in ["buy", "cover"]:
                side = OrderSide.BUY
            elif decision.action in ["sell", "short"]:
                side = OrderSide.SELL
            else:
                logger.warning("Unknown action", ticker=ticker, action=decision.action)
                return None

            if (
                side == OrderSide.BUY
                and use_limit_order
                and current_price
                and float(current_price) > 0
            ):
                limit_px = round(float(current_price) * (1.0 + float(limit_slippage_pct)), 2)
                order_data = LimitOrderRequest(
                    symbol=ticker,
                    qty=decision.quantity,
                    side=side,
                    type=OrderType.LIMIT,
                    time_in_force=TimeInForce.DAY,
                    limit_price=limit_px,
                )
            elif (
                side == OrderSide.BUY
                and stop_loss_pct
                and float(stop_loss_pct) > 0
                and current_price
                and float(current_price) > 0
                and not (bool(execution_tactic) and not bool(execution_tactic.get("use_limit_order")))
            ):
                stop_px = round(float(current_price) * (1.0 - float(stop_loss_pct)), 2)
                order_data = MarketOrderRequest(
                    symbol=ticker,
                    qty=decision.quantity,
                    side=side,
                    time_in_force=TimeInForce.DAY,
                    order_class=OrderClass.BRACKET,
                    stop_loss=StopLossRequest(stop_price=stop_px),
                )
            else:
                order_data = MarketOrderRequest(
                    symbol=ticker,
                    qty=decision.quantity,
                    side=side,
                    time_in_force=TimeInForce.DAY,
                )

            try:
                order = self.client.submit_order(order_data=order_data)
            except Exception as e:
                # Some Alpaca paper-account contexts reject bracket orders intermittently.
                # Fallback once to a plain market buy so the run can still execute.
                if side == OrderSide.BUY and stop_loss_pct and float(stop_loss_pct) > 0:
                    logger.warning(
                        "Bracket buy rejected; retrying as plain market buy",
                        ticker=ticker,
                        error=str(e),
                    )
                    fallback = MarketOrderRequest(
                        symbol=ticker,
                        qty=decision.quantity,
                        side=side,
                        time_in_force=TimeInForce.DAY,
                    )
                    order = self.client.submit_order(order_data=fallback)
                else:
                    raise

            logger.info(
                "Order submitted",
                ticker=ticker,
                action=decision.action,
                quantity=decision.quantity,
                order_id=str(order.id),
            )

            return {
                "order_id": str(order.id),
                "symbol": order.symbol,
                "qty": int(order.qty),
                "side": str(order.side) if hasattr(order.side, "value") else order.side,
                "status": str(order.status) if hasattr(order.status, "value") else order.status,
                "success": True,
                "execution_tactic": (execution_tactic or {}).get("tactic"),
            }

        except Exception as e:
            logger.error("Order execution failed", ticker=ticker, error=str(e))
            return {
                "symbol": ticker,
                "status": "failed",
                "error": str(e),
                "success": False,
            }

    def execute_decisions(
        self,
        decisions: Dict[str, PortfolioDecision],
        rate_limit: int = 200,  # Alpaca limit: 200 requests/minute
        current_prices: Optional[Dict[str, float]] = None,
        stop_loss_pct: Optional[float] = None,
        use_limit_orders: bool = False,
        limit_slippage_pct: float = 0.002,
        run_config: Optional[Dict] = None,
    ) -> Dict[str, Optional[Dict]]:
        """
        Execute multiple trading decisions with rate limiting

        Args:
            decisions: Dictionary mapping ticker to PortfolioDecision
            rate_limit: Maximum requests per minute (default: 200 for Alpaca)

        Returns:
            Dictionary mapping ticker to order result
        """
        import time

        logger.info("Executing trading decisions", decision_count=len(decisions))

        results = {}
        non_hold_decisions = {
            t: d for t, d in decisions.items() if d.action != "hold" and d.quantity > 0
        }

        if not non_hold_decisions:
            logger.info("No trades to execute (all holds)")
            return results

        # Calculate delay between requests to respect rate limit
        # Add 10% buffer to be safe
        delay_seconds = 60.0 / (rate_limit * 0.9)  # ~0.33 seconds between requests

        logger.info(
            "Executing trades with rate limiting",
            trade_count=len(non_hold_decisions),
            delay_seconds=round(delay_seconds, 3),
            estimated_time_minutes=round(len(non_hold_decisions) * delay_seconds / 60, 1),
        )

        # Execute sells first to free cash / buying power for subsequent buys.
        priority = {"sell": 0, "short": 0, "cover": 1, "buy": 2}
        ordered = sorted(
            non_hold_decisions.items(),
            key=lambda kv: (priority.get(kv[1].action, 99), kv[0]),
        )

        prices = current_prices or {}
        executed = 0
        cfg = run_config or {}
        wheel_fill_wait = bool(cfg.get("wheel_mode")) and hasattr(self, "wait_for_order_fill")
        sell_phase_done = False
        for i, (ticker, decision) in enumerate(ordered, 1):
            # After all sells/shorts submitted, wait for fills before buys (free BP).
            if (
                wheel_fill_wait
                and not sell_phase_done
                and decision.action == "buy"
            ):
                sell_failed = False
                for st_ticker, st_res in list(results.items()):
                    st_dec = non_hold_decisions.get(st_ticker)
                    if not st_dec or st_dec.action not in ("sell", "short", "cover"):
                        continue
                    # Tiny leftover / directional sells must not block 100-share lot buys.
                    try:
                        sell_qty = int(getattr(st_dec, "quantity", 0) or 0)
                    except (TypeError, ValueError):
                        sell_qty = 0
                    sell_reason = str(getattr(st_dec, "reasoning", "") or "")
                    material_sell = sell_qty >= 100 or "Atomic" in sell_reason
                    if not isinstance(st_res, dict) or not st_res.get("success", True):
                        logger.warning(
                            "Wheel sell submit failed; blocking subsequent buys"
                            if material_sell
                            else "Wheel leftover sell submit failed; buys still allowed",
                            ticker=st_ticker,
                            result=st_res,
                        )
                        if material_sell:
                            sell_failed = True
                        continue
                    oid = str(st_res.get("order_id") or st_res.get("id") or "")
                    if not oid:
                        logger.warning(
                            "Wheel sell missing order_id; blocking subsequent buys"
                            if material_sell
                            else "Wheel leftover sell missing order_id; buys still allowed",
                            ticker=st_ticker,
                        )
                        if material_sell:
                            sell_failed = True
                        continue
                    if not st_res.get("fill"):
                        fill = self.wait_for_order_fill(
                            oid,
                            timeout_s=float(cfg.get("lot_fill_timeout_s", 60)),
                            min_filled_qty=int(getattr(st_dec, "quantity", 0) or 0) or None,
                        )
                        st_res["fill"] = fill
                    fill = st_res.get("fill") or {}
                    if not fill.get("ok"):
                        logger.warning(
                            "Wheel sell not filled; blocking subsequent buys"
                            if material_sell
                            else "Wheel leftover sell not filled; buys still allowed",
                            ticker=st_ticker,
                            fill=fill,
                        )
                        if material_sell:
                            sell_failed = True
                sell_phase_done = True
                if sell_failed:
                    # Skip remaining buys — do not spend BP that never freed.
                    for rest_ticker, rest_dec in ordered[i - 1 :]:
                        if rest_dec.action == "buy" and rest_ticker not in results:
                            results[rest_ticker] = {
                                "success": False,
                                "error": "blocked_after_sell_fill_failure",
                            }
                    break

            px = prices.get(ticker)
            if px is None:
                px = prices.get(str(ticker).upper())
            px_f = None
            try:
                if px is not None:
                    cand = float(px)
                    if cand == cand and cand > 0:
                        px_f = cand
            except (TypeError, ValueError):
                px_f = None
            tactic = None
            try:
                from src.trading.execution_tactics import select_execution_tactic

                tactic = select_execution_tactic(
                    ticker=ticker,
                    action=decision.action,
                    current_price=px_f,
                    run_config=run_config or {"use_limit_orders": use_limit_orders, "limit_slippage_pct": limit_slippage_pct},
                )
            except Exception:
                tactic = None
            reason_txt = str(getattr(decision, "reasoning", "") or "")
            try:
                dec_qty = int(decision.quantity)
            except (TypeError, ValueError):
                dec_qty = 0
            clip_lots = (
                wheel_fill_wait
                and decision.action == "buy"
                and dec_qty >= 200
                and dec_qty % 100 == 0
                and ("Wheel lot" in reason_txt or "Wheel add-on" in reason_txt)
            )
            if clip_lots:
                filled_total = 0
                last_result: Optional[Dict] = None
                from src.portfolio.manager import PortfolioDecision as _PD

                n_clips = dec_qty // 100
                for clip_i in range(n_clips):
                    clip_dec = _PD(
                        action="buy",
                        quantity=100,
                        confidence=decision.confidence,
                        reasoning=decision.reasoning,
                    )
                    last_result = self.execute_order(
                        ticker,
                        clip_dec,
                        current_price=px_f,
                        stop_loss_pct=stop_loss_pct,
                        use_limit_order=use_limit_orders,
                        limit_slippage_pct=limit_slippage_pct,
                        execution_tactic=tactic,
                    )
                    if not last_result or last_result.get("success") is False:
                        break
                    oid = str(last_result.get("order_id") or last_result.get("id") or "")
                    clip_fill: Dict[str, Any] = {"ok": False}
                    if oid:
                        clip_fill = self.wait_for_order_fill(
                            oid,
                            timeout_s=float(cfg.get("lot_fill_timeout_s", 60)),
                            min_filled_qty=100,
                        )
                    last_result["fill"] = clip_fill
                    if not clip_fill.get("ok"):
                        break
                    try:
                        filled_total += int(clip_fill.get("filled_qty") or 100)
                    except (TypeError, ValueError):
                        filled_total += 100
                    if clip_i + 1 < n_clips:
                        time.sleep(delay_seconds)
                result = last_result or {"success": False, "error": "clip_submit_failed"}
                result["filled_qty"] = filled_total
                result["requested_qty"] = dec_qty
                result["fill"] = {
                    "ok": filled_total >= dec_qty,
                    "filled_qty": filled_total,
                    "qty": dec_qty,
                }
                if filled_total <= 0:
                    result["success"] = False
            else:
                result = self.execute_order(
                    ticker,
                    decision,
                    current_price=px_f,
                    stop_loss_pct=stop_loss_pct,
                    use_limit_order=use_limit_orders,
                    limit_slippage_pct=limit_slippage_pct,
                    execution_tactic=tactic,
                )
            results[ticker] = result

            if result and result.get("success", True):
                executed += 1

            # Rate limiting: wait between requests (except for last one)
            if i < len(ordered):
                time.sleep(delay_seconds)

            # Log progress for large batches
            if len(ordered) > 50 and i % 50 == 0:
                logger.info(
                    "Execution progress",
                    completed=i,
                    total=len(ordered),
                    pct=round(i / len(ordered) * 100, 1),
                )

        logger.info(
            "Trading execution complete",
            executed_count=executed,
            total_decisions=len(decisions),
            failed_count=len(ordered) - executed,
        )
        return results

    # ── Options methods ──────────────────────────────────────────────

    def get_option_contracts(
        self,
        underlying: str,
        option_type: str = "call",
        expiry_gte: Optional[date] = None,
        expiry_lte: Optional[date] = None,
        strike_gte: Optional[float] = None,
        strike_lte: Optional[float] = None,
        limit: int = 50,
    ) -> List[Dict]:
        """Discover available option contracts for an underlying symbol.

        Raises BrokerDataError after retries so callers can tell a fetch
        failure from a truly empty strike/expiry band.
        """
        if expiry_gte is None:
            expiry_gte = date.today() + timedelta(days=7)
        if expiry_lte is None:
            expiry_lte = date.today() + timedelta(days=45)

        ct = ContractType.CALL if option_type == "call" else ContractType.PUT
        req = GetOptionContractsRequest(
            underlying_symbols=[underlying],
            type=ct,
            expiration_date_gte=expiry_gte.isoformat(),
            expiration_date_lte=expiry_lte.isoformat(),
            strike_price_gte=str(strike_gte) if strike_gte else None,
            strike_price_lte=str(strike_lte) if strike_lte else None,
            limit=limit,
        )
        try:
            resp = alpaca_call_with_retry(
                lambda: self.client.get_option_contracts(req),
                op="get_option_contracts",
            )
        except Exception as e:
            logger.error("Failed to fetch option contracts", underlying=underlying, error=str(e))
            raise BrokerDataError(f"option chain unavailable for {underlying}: {e}") from e

        contracts = resp.option_contracts if hasattr(resp, "option_contracts") else resp
        results = []
        for c in contracts or []:
            close_px = 0.0
            for attr in ("close_price", "last_price", "last_trade_price"):
                raw = getattr(c, attr, None)
                try:
                    px = float(raw) if raw is not None else 0.0
                except (TypeError, ValueError):
                    px = 0.0
                if px > 0:
                    close_px = px
                    break
            results.append(
                {
                    "symbol": c.symbol,
                    "underlying": getattr(c, "underlying_symbol", None) or underlying,
                    "strike": float(c.strike_price) if getattr(c, "strike_price", None) else 0.0,
                    "expiry": str(c.expiration_date),
                    "type": str(c.type) if hasattr(c, "type") else option_type,
                    "open_interest": int(c.open_interest)
                    if hasattr(c, "open_interest") and c.open_interest
                    else 0,
                    "close_price": close_px,
                    "tradable": getattr(c, "tradable", True),
                }
            )
        logger.info("Option contracts fetched", underlying=underlying, count=len(results))
        return results

    def enrich_option_quotes(self, contracts: List[Dict]) -> List[Dict]:
        """Fill bid/ask/mid on contract dicts from latest option quotes (best-effort)."""
        symbols = [str(c.get("symbol") or "") for c in contracts or [] if c.get("symbol")]
        symbols = [s for s in symbols if s]
        if not symbols:
            return contracts
        try:
            from alpaca.data.historical.option import OptionHistoricalDataClient
            from alpaca.data.requests import OptionLatestQuoteRequest

            key = settings.alpaca_api_key
            sec = settings.alpaca_secret_key
            if not key or not sec:
                return contracts
            client = OptionHistoricalDataClient(key, sec)
            quotes = alpaca_call_with_retry(
                lambda: client.get_option_latest_quote(
                    OptionLatestQuoteRequest(symbol_or_symbols=symbols[:40])
                ),
                op="get_option_latest_quote",
                attempts=2,
                base_delay_sec=1.0,
            )
            qmap = quotes if isinstance(quotes, dict) else getattr(quotes, "data", None) or {}
            for c in contracts:
                q = qmap.get(str(c.get("symbol") or ""))
                if q is None:
                    continue
                try:
                    bid = float(getattr(q, "bid_price", 0) or 0)
                except (TypeError, ValueError):
                    bid = 0.0
                try:
                    ask = float(getattr(q, "ask_price", 0) or 0)
                except (TypeError, ValueError):
                    ask = 0.0
                mid = (bid + ask) / 2.0 if bid > 0 and ask > 0 else (ask if ask > 0 else bid)
                if bid > 0:
                    c["bid_price"] = bid
                if ask > 0:
                    c["ask_price"] = ask
                if mid > 0:
                    c["mid_price"] = mid
        except Exception as e:
            logger.warning("Option quote enrich failed", error=str(e))
        return contracts

    def get_order(self, order_id: str) -> Optional[Dict]:
        """Fetch a single order by id."""
        try:
            o = self.client.get_order_by_id(str(order_id))
            if o is None:
                return None
            return {
                "id": str(o.id),
                "order_id": str(o.id),
                "symbol": o.symbol,
                "side": getattr(o.side, "value", str(o.side)).lower(),
                "qty": int(float(o.qty)) if o.qty else 0,
                "filled_qty": int(float(o.filled_qty))
                if getattr(o, "filled_qty", None) is not None
                else 0,
                "filled_avg_price": float(o.filled_avg_price)
                if getattr(o, "filled_avg_price", None) is not None
                else None,
                "status": getattr(o.status, "value", str(o.status)).lower(),
            }
        except Exception as e:
            logger.warning("get_order failed", order_id=str(order_id), error=str(e))
            return None

    def wait_for_order_fill(
        self,
        order_id: str,
        *,
        timeout_s: float = 45.0,
        poll_s: float = 1.0,
        cancel_on_timeout: bool = True,
        min_filled_qty: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Poll until the order is fully filled, terminal-failed, or timeout.

        Returns dict with keys: ok, status, filled_qty, qty, order_id, timed_out.
        """
        oid = str(order_id or "")
        if not oid:
            return {
                "ok": False,
                "status": "missing_order_id",
                "filled_qty": 0,
                "qty": 0,
                "order_id": oid,
                "timed_out": False,
            }
        deadline = time.time() + max(1.0, float(timeout_s))
        last: Dict[str, Any] = {}
        terminal_bad = {
            "canceled",
            "cancelled",
            "expired",
            "rejected",
            "replaced",
            "done_for_day",
        }
        while time.time() < deadline:
            last = self.get_order(oid) or {}
            status = str(last.get("status") or "").lower()
            qty = int(last.get("qty") or 0)
            filled = int(last.get("filled_qty") or 0)
            need = int(min_filled_qty) if min_filled_qty is not None else qty
            if status == "filled" or (need > 0 and filled >= need):
                return {
                    "ok": True,
                    "status": status or "filled",
                    "filled_qty": filled,
                    "qty": qty,
                    "order_id": oid,
                    "timed_out": False,
                    "filled_avg_price": last.get("filled_avg_price"),
                }
            if status in terminal_bad:
                return {
                    "ok": False,
                    "status": status,
                    "filled_qty": filled,
                    "qty": qty,
                    "order_id": oid,
                    "timed_out": False,
                }
            time.sleep(max(0.2, float(poll_s)))

        if cancel_on_timeout:
            self.cancel_order(oid)
            last = self.get_order(oid) or last
        filled = int(last.get("filled_qty") or 0)
        qty = int(last.get("qty") or 0)
        need = int(min_filled_qty) if min_filled_qty is not None else qty
        ok = need > 0 and filled >= need
        return {
            "ok": ok,
            "status": str(last.get("status") or "timeout"),
            "filled_qty": filled,
            "qty": qty,
            "order_id": oid,
            "timed_out": True,
            "filled_avg_price": last.get("filled_avg_price"),
        }

    def submit_option_order(
        self,
        contract_symbol: str,
        qty: int,
        side: str = "sell",
        order_type: str = "market",
        limit_price: Optional[float] = None,
        *,
        wait_fill: bool = False,
        fill_timeout_s: float = 45.0,
    ) -> Optional[Dict]:
        """Submit an options order (e.g. sell-to-open for covered calls)."""
        try:
            qty = int(qty)
        except (TypeError, ValueError):
            qty = 0
        if qty <= 0:
            logger.warning("Refusing option order with non-positive qty", contract=contract_symbol, qty=qty)
            return None
        try:
            order_side = OrderSide.SELL if side == "sell" else OrderSide.BUY

            if order_type == "limit" and limit_price is not None:
                order_data = LimitOrderRequest(
                    symbol=contract_symbol,
                    qty=qty,
                    side=order_side,
                    type=OrderType.LIMIT,
                    time_in_force=TimeInForce.DAY,
                    limit_price=limit_price,
                )
            else:
                order_data = MarketOrderRequest(
                    symbol=contract_symbol,
                    qty=qty,
                    side=order_side,
                    time_in_force=TimeInForce.DAY,
                )

            order = self.client.submit_order(order_data=order_data)
            logger.info(
                "Option order submitted",
                contract=contract_symbol,
                side=side,
                qty=qty,
                order_id=str(order.id),
            )
            result = {
                "order_id": str(order.id),
                "id": str(order.id),
                "symbol": order.symbol,
                "qty": int(order.qty) if order.qty else qty,
                "side": side,
                "status": str(order.status)
                if hasattr(order.status, "value")
                else str(order.status),
            }
            if wait_fill:
                fill = self.wait_for_order_fill(
                    str(order.id),
                    timeout_s=fill_timeout_s,
                    min_filled_qty=int(qty),
                )
                result["fill"] = fill
                result["status"] = fill.get("status") or result["status"]
                if not fill.get("ok"):
                    result["fill_ok"] = False
                    return result
                result["fill_ok"] = True
                result["filled_qty"] = fill.get("filled_qty")
            return result
        except Exception as e:
            logger.error("Option order failed", contract=contract_symbol, error=str(e))
            return None

    def get_option_positions(self) -> List[Dict]:
        """Return current option positions (contracts whose symbol length > 10).

        Retries transient Alpaca failures; raises BrokerDataError only after retries
        so callers never treat an outage as an empty book.
        """
        last_err: Optional[BaseException] = None
        for attempt in range(1, 4):
            try:
                positions = alpaca_call_with_retry(
                    lambda: self.client.get_all_positions(),
                    op="get_option_positions",
                )
                results = []
                for pos in positions or []:
                    sym = pos.symbol or ""
                    if len(sym) > 10:
                        und = ""
                        try:
                            from src.options.wheel_lifecycle import parse_occ_symbol

                            parsed = parse_occ_symbol(sym)
                            und = (parsed or {}).get("underlying") or ""
                        except Exception:
                            und = ""
                        if not und:
                            und = (
                                sym[:6].strip().rstrip("0123456789")
                                or sym[:4].rstrip("0123456789")
                            )
                        qty_signed = int(float(pos.qty))
                        qty_abs = abs(qty_signed)
                        mv = float(pos.market_value) if pos.market_value is not None else 0.0
                        mark = (
                            abs(mv) / (qty_abs * 100.0)
                            if qty_abs > 0 and abs(mv) > 0
                            else 0.0
                        )
                        if mark <= 0:
                            try:
                                mark = (
                                    float(pos.current_price)
                                    if getattr(pos, "current_price", None)
                                    else 0.0
                                )
                            except (TypeError, ValueError):
                                mark = 0.0
                        results.append(
                            {
                                "symbol": sym,
                                "qty": qty_abs,
                                "side": "short" if qty_signed < 0 else "long",
                                "avg_entry_price": float(pos.avg_entry_price),
                                "market_value": mv,
                                "current_price": mark,
                                "mark_price": mark,
                                "underlying": und,
                            }
                        )
                return results
            except Exception as e:
                last_err = e
                logger.warning(
                    "Option positions fetch attempt failed",
                    attempt=attempt,
                    error=str(e),
                )
                if attempt < 3:
                    time.sleep(0.5 * attempt)
        logger.error("Failed to fetch option positions after retries", error=str(last_err))
        raise BrokerDataError(f"option positions unavailable: {last_err}") from last_err

    def sync_portfolio(self) -> Portfolio:
        """
        Sync portfolio state from Alpaca

        Returns:
            Portfolio object with current state
        """
        try:
            account = self.get_account()
            positions = self.get_positions()

            # Spendable cash for new equity: Alpaca keeps cash high while CSP
            # collateral reduces buying_power — never plan buys above BP.
            raw_cash = float(account["cash"])
            bp = float(account.get("buying_power") or raw_cash)
            spendable = min(raw_cash, bp) if bp > 0 else raw_cash

            portfolio = Portfolio(
                cash=spendable,
                margin_requirement=0.5,  # Default margin requirement
                margin_used=0.0,  # Calculate if needed
            )
            # Broker equity for sleeve sizing (not haircut by BP).
            try:
                portfolio._broker_equity = float(  # type: ignore[attr-defined]
                    account.get("equity") or account.get("portfolio_value") or 0.0
                )
                portfolio._buying_power = bp  # type: ignore[attr-defined]
                portfolio._raw_cash = raw_cash  # type: ignore[attr-defined]
            except Exception:
                pass

            for ticker, pos_data in positions.items():
                if pos_data["side"] == "long":
                    portfolio.positions[ticker] = Position(
                        long=pos_data["qty"],
                        short=0,
                        long_cost_basis=pos_data["avg_entry_price"],
                        short_cost_basis=0.0,
                        short_margin_used=0.0,
                    )
                elif pos_data["side"] == "short":
                    portfolio.positions[ticker] = Position(
                        long=0,
                        short=pos_data["qty"],
                        long_cost_basis=0.0,
                        short_cost_basis=pos_data["avg_entry_price"],
                        short_margin_used=pos_data["market_value"] * 0.5,  # Estimate
                    )

            logger.info(
                "Portfolio synced from broker",
                cash=round(portfolio.cash, 2),
                position_count=len(portfolio.positions),
                positions={
                    t: {"long": p.long, "short": p.short} for t, p in portfolio.positions.items()
                },
            )
            return portfolio

        except Exception as e:
            logger.error("Portfolio sync failed", error=str(e))
            raise
