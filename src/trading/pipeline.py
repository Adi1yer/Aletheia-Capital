"""Weekly trading pipeline"""

import os
from typing import List, Dict, Optional, Any
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from dateutil.relativedelta import relativedelta
import structlog
import time
import uuid
from src.agents.registry import get_registry
from src.agents.base import AgentSignal
from src.agents.tiers import resolve_active_agent_keys, skipped_agent_keys
from src.config.settings import settings
from src.risk.manager import RiskManager
from src.portfolio.manager import PortfolioManager
from src.portfolio.models import Portfolio
from src.performance.tracker import PerformanceTracker
from src.performance.cycle_tracker import CyclePerformanceTracker


# Lazy import for Alpaca broker (only needed when executing trades)
def get_alpaca_broker():
    """Lazy import of Alpaca broker. Returns None if Alpaca not installed or keys not configured."""
    try:
        from src.config.settings import settings

        if not settings.alpaca_api_key or not settings.alpaca_secret_key:
            logger.info(
                "Alpaca keys not configured - set ALPACA_API_KEY and ALPACA_SECRET_KEY in .env for --execute"
            )
            return None
        from src.broker.alpaca import AlpacaBroker

        return AlpacaBroker
    except ImportError as e:
        logger.warning("Alpaca broker not available", error=str(e))
        return None


logger = structlog.get_logger()


def _get_pipeline_data_provider():
    from src.data.providers.aggregator import get_data_provider

    return get_data_provider()


class TradingPipeline:
    """Main trading pipeline for weekly execution"""

    def __init__(
        self, parallel_agents: bool = True, max_workers: Optional[int] = None, broker=None
    ):
        """
        Initialize trading pipeline

        Args:
            parallel_agents: If True, run agents in parallel (default: True)
            max_workers: Maximum number of worker threads for parallel execution (default: None = auto)
            broker: Optional pre-created AlpacaBroker instance to reuse (avoids creating a second connection)
        """
        self.registry = get_registry()
        self.risk_manager = RiskManager()
        self.portfolio_manager = PortfolioManager()
        self._broker_class = get_alpaca_broker()
        self.broker = broker
        self._data_provider = None
        self.performance_tracker = PerformanceTracker()
        self.cycle_tracker = CyclePerformanceTracker()
        self.parallel_agents = parallel_agents
        self.max_workers = max_workers
        logger.info(
            "Initialized trading pipeline",
            parallel_agents=parallel_agents,
            max_workers=max_workers,
        )

    @property
    def data_provider(self):
        if self._data_provider is None:
            self._data_provider = _get_pipeline_data_provider()
        return self._data_provider

    @data_provider.setter
    def data_provider(self, value):
        self._data_provider = value

    def run_weekly_trading(
        self,
        tickers: List[str],
        execute: bool = False,
        scan_cache: Optional[Any] = None,
        run_config: Optional[Dict[str, Any]] = None,
    ) -> Dict:
        """
        Run weekly trading cycle

        Args:
            tickers: List of ticker symbols to trade
            execute: If True, execute trades. If False, only generate decisions.
            scan_cache: If provided (ScanCache instance), persist full run to local storage.
            run_config: Optional dict (e.g. universe, max_stocks, execute) to store with the run.

        Returns:
            Dictionary with trading results
        """
        run_config = run_config or {}
        run_config.setdefault("execute", execute)
        run_start = time.time()
        logger.info("Starting weekly trading cycle", ticker_count=len(tickers), execute=execute)

        # 1. Sync portfolio from broker when available (execute or dry run); else use empty portfolio
        open_orders: List[Dict] = []
        recent_orders: List[Dict] = []
        if self._broker_class:
            if self.broker is None:
                self.broker = self._broker_class()
            logger.info(
                "Syncing portfolio from broker (decisions will use live cash and positions)"
            )
            try:
                portfolio = self.broker.sync_portfolio()
            except Exception as e:
                logger.error(
                    "Portfolio sync failed; aborting run to avoid decisions on bogus data",
                    error=str(e),
                )
                raise SystemExit(1)
            try:
                open_orders = self.broker.get_open_orders(limit=50)
                recent_orders = self.broker.get_recent_orders(limit=20)
            except Exception as e:
                logger.warning("Could not fetch orders from broker", error=str(e))
        else:
            portfolio = Portfolio(cash=0.0, positions={})
            open_orders = []
            recent_orders = []

        # Build pending order quantities per symbol (for portfolio manager)
        pending_orders_by_symbol: Dict[str, Dict[str, int]] = {}
        for o in open_orders:
            sym = (o.get("symbol") or "").strip()
            side = (o.get("side") or "").lower()
            qty = int(o.get("qty") or 0)
            if not sym or qty <= 0:
                continue
            if sym not in pending_orders_by_symbol:
                pending_orders_by_symbol[sym] = {"buy_qty": 0, "sell_qty": 0}
            if side == "buy":
                pending_orders_by_symbol[sym]["buy_qty"] += qty
            elif side == "sell":
                pending_orders_by_symbol[sym]["sell_qty"] += qty
        if pending_orders_by_symbol:
            logger.info(
                "Pending orders by symbol (will cap decisions)", pending=pending_orders_by_symbol
            )

        broker_required = run_config.get("broker_required", True)
        if not self._broker_class and broker_required:
            logger.error(
                "Alpaca keys required but not configured. Set ALPACA_API_KEY and ALPACA_SECRET_KEY in .env. No fallback."
            )
            raise SystemExit(1)

        # 2. Calculate date range (last 3 months for analysis)
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - relativedelta(months=3)).strftime("%Y-%m-%d")

        # 3. Refresh data (right before trading)
        financial_limit = int(run_config.get("financial_limit", 1))
        logger.info(
            "Refreshing market data",
            start_date=start_date,
            end_date=end_date,
            financial_limit=financial_limit,
        )
        self._refresh_data(
            tickers, start_date, end_date, financial_limit=financial_limit
        )
        from src.data.ticker_dossier import build_dossiers_for_tickers, refresh_benchmarks

        refresh_benchmarks(self.data_provider, start_date, end_date)
        dossier_limit = int(run_config.get("dossier_financial_limit", 5))
        self._ticker_dossiers = build_dossiers_for_tickers(
            self.data_provider,
            tickers,
            start_date,
            end_date,
            financial_limit=dossier_limit,
        )
        run_config["llm_cache"] = run_config.get("llm_cache", True)

        next_earnings_by_ticker: Dict[str, Optional[str]] = {}
        blackout = int(run_config.get("earnings_blackout_days", 0) or 0)
        if blackout > 0 and tickers:
            logger.info("Fetching earnings dates for blackout filter", ticker_sample=len(tickers))

            def _earn(sym: str) -> tuple:
                try:
                    return sym, self.data_provider.get_next_earnings_date(sym)
                except Exception:
                    return sym, None

            with ThreadPoolExecutor(max_workers=min(32, len(tickers))) as ex:
                futures = [ex.submit(_earn, t) for t in tickers]
                for fut in as_completed(futures):
                    sym, d = fut.result()
                    next_earnings_by_ticker[sym] = d

        learning_context: Dict[str, Any] = {
            "feedback_refresh_ok": False,
            "feedback_refresh_error": "",
            "scorecard_present": False,
            "scan_cache_run_count": 0,
            "scan_cache_run_count_before": 0,
            "scan_cache_run_count_after": 0,
            "ledger_run_count": 0,
            "ledger_run_count_after": 0,
            "scorecard_agent_count": 0,
            "scorecard_pairs_used": 0,
            "scorecard_skip_reason": "",
            "wrote_scorecard_file": False,
            "wrote_agent_feedback": False,
            "scorecard_present_after": False,
            "scorecard_source": "",
            "cache_restore_hit_performance": os.getenv("CACHE_HIT_PERFORMANCE") == "true",
            "cache_restore_hit_scan": os.getenv("CACHE_HIT_SCAN") == "true",
            "s3_runs_restored": 0,
            "existing_feedback_on_disk": False,
        }
        try:
            from src.backtesting.feedback import existing_feedback_loaded
            from src.scan_cache.remote_store import is_configured, restore_recent_runs

            learning_context["existing_feedback_on_disk"] = existing_feedback_loaded()
            if is_configured():
                learning_context["s3_runs_restored"] = restore_recent_runs(
                    n=int(run_config.get("s3_restore_run_limit", 26))
                )
                if run_config.get("require_s3_restore", False) and int(learning_context["s3_runs_restored"]) <= 0:
                    raise RuntimeError("S3 restore required but no runs were restored")
        except Exception as e:
            logger.warning("Pre-run learning restore failed", error=str(e))

        if scan_cache is not None and run_config.get("refresh_agent_feedback", True):
            learning_context = self._merge_feedback_refresh(
                learning_context, scan_cache, run_config, phase="before"
            )

        # Intra-week main paper account context (daily snapshots → agent prompts via contextvar)
        intraweek_token = None
        try:
            from src.agents.prompt_helpers import (
                reset_intraweek_stock_context,
                set_intraweek_stock_context,
            )
            from src.ops.daily_snapshots import format_snapshots_markdown

            iw = format_snapshots_markdown("stock", days=7).strip()
            if iw:
                intraweek_token = set_intraweek_stock_context(iw)
                run_config["intraweek_stock_summary"] = iw
        except Exception as e:
            logger.warning("Could not load intra-week stock snapshots", error=str(e))

        from src.portfolio.regime import apply_regime_to_run_config, detect_regime

        regime_start = (datetime.now() - relativedelta(months=14)).strftime("%Y-%m-%d")
        regime = detect_regime(self.data_provider, regime_start, end_date)
        run_config = apply_regime_to_run_config(run_config, regime)

        registered_keys = self.registry.get_agent_keys()
        tier_mode = str(run_config.get("agent_tier_mode", "full"))
        override_agents = run_config.get("active_agent_keys")
        if isinstance(override_agents, str):
            override_agents = [a.strip() for a in override_agents.split(",") if a.strip()]
        active_agent_keys = resolve_active_agent_keys(
            tier_mode=tier_mode,
            config_path=run_config.get("agents_tiers_path"),
            override=override_agents,
            core_only=bool(run_config.get("agent_tier_core_only", False)),
            registered_keys=registered_keys,
        )
        skipped = skipped_agent_keys(registered_keys, active_agent_keys)
        min_w = float(run_config.get("min_agent_weight_to_run", 0.15))
        weights = self.registry.get_weights()
        if min_w > 0:
            active_agent_keys = [
                k for k in active_agent_keys if float(weights.get(k, 1.0)) >= min_w
            ]
            skipped = skipped_agent_keys(registered_keys, active_agent_keys)
        run_config["active_agents"] = active_agent_keys
        run_config["skipped_agents"] = skipped
        logger.info(
            "Resolved active agents",
            tier_mode=tier_mode,
            active_count=len(active_agent_keys),
            skipped_count=len(skipped),
        )

        # 4. Run active agents
        logger.info("Running agent analysis")
        max_llm_calls = int(run_config.get("max_llm_calls", 0) or 0)
        self._llm_budget = {"remaining": max_llm_calls} if max_llm_calls > 0 else {"remaining": 10**9}
        if max_llm_calls > 0:
            per_lane: Dict[str, int] = {}
            for ak in active_agent_keys:
                lane = getattr(self.registry.get(ak), "hybrid_lane", "") or "other"
                per_lane[lane] = per_lane.get(lane, 0) + 1
            floors: Dict[str, int] = {}
            for lane, count in per_lane.items():
                floors[lane] = max(1, int(max_llm_calls * 0.1 * (count / max(1, len(active_agent_keys)))))
            self._llm_budget["per_lane"] = dict(floors)
            self._llm_budget["used"] = 0
        try:
            agent_signals = self._run_agents(
                tickers, start_date, end_date, active_agent_keys=active_agent_keys
            )
        finally:
            if intraweek_token is not None:
                try:
                    reset_intraweek_stock_context(intraweek_token)
                except Exception:
                    pass
        self._llm_budget_summary = {
            "remaining": int(self._llm_budget.get("remaining", 0)),
            "used": int(self._llm_budget.get("used", 0)),
            "per_lane_remaining": dict(self._llm_budget.get("per_lane") or {}),
        }

        # Optional second-pass fundamentals on focused names (held + top conviction).
        focused_limit = int(run_config.get("focused_financial_limit", 5) or 5)
        if focused_limit > financial_limit:
            from src.portfolio.sectors import get_sector
            regime_mode = (run_config.get("regime") or {}).get("mode")
            all_weights = self.registry.get_weights(regime_mode=regime_mode)
            agent_weights = {k: all_weights[k] for k in active_agent_keys if k in all_weights}
            held = [t for t, p in (portfolio.positions or {}).items() if int(getattr(p, "long", 0) or 0) > 0]
            focus_scores: List[tuple[str, int]] = []
            for t in tickers:
                agg = self.portfolio_manager._aggregate_signals(t, agent_signals, agent_weights)
                if agg.get("signal") == "bullish":
                    focus_scores.append((t, int(agg.get("confidence") or 0)))
            focus_scores.sort(key=lambda x: x[1], reverse=True)
            sector_cap = int(run_config.get("focused_sector_cap", 6) or 6)
            picked_by_sector: Dict[str, int] = {}
            ranked = []
            for t, _ in focus_scores:
                sec = str(get_sector(t) or "Unknown")
                if picked_by_sector.get(sec, 0) >= sector_cap:
                    continue
                picked_by_sector[sec] = picked_by_sector.get(sec, 0) + 1
                ranked.append(t)
                if len(ranked) >= 50:
                    break
            focused_tickers = list(dict.fromkeys(held + ranked))
            if focused_tickers:
                self._refresh_data(
                    focused_tickers,
                    start_date,
                    end_date,
                    financial_limit=focused_limit,
                )

        # 5. Calculate risk limits
        logger.info("Calculating risk limits")
        risk_analysis = self.risk_manager.calculate_position_limits(
            tickers, portfolio, start_date, end_date
        )

        current_prices = {
            t: float(risk_analysis[t]["current_price"])
            for t in risk_analysis
            if isinstance(risk_analysis.get(t), dict)
            and risk_analysis[t].get("current_price") is not None
        }
        try:
            from src.performance.decision_ledger import resolve_pending_outcomes

            resolved = resolve_pending_outcomes(current_prices, end_date)
            learning_context["decision_outcomes_resolved"] = resolved
        except Exception as e:
            logger.warning("Decision outcome resolution failed", error=str(e))

        try:
            from src.performance.options_ledger import resolve_option_outcomes

            closed_opts: List[str] = []
            try:
                from datetime import date as date_cls
                from src.ops.daily_snapshots import load_snapshots_for_days

                snaps = load_snapshots_for_days("stock", days=2)
                if snaps:
                    lc = snaps[0].get("position_lifecycle_vs_prior_day") or {}
                    closed_opts = list(lc.get("closed_option_symbols") or [])
            except Exception:
                pass
            opt_resolved = resolve_option_outcomes(
                end_date, current_prices=current_prices, closed_option_symbols=closed_opts
            )
            learning_context["options_outcomes_resolved"] = opt_resolved
        except Exception as e:
            logger.warning("Options outcome resolution failed", error=str(e))

        try:
            from src.performance.counterfactual_ledger import resolve_pending_outcomes as resolve_cf

            learning_context["counterfactual_resolved"] = resolve_cf(current_prices, end_date)
        except Exception as e:
            logger.warning("Counterfactual resolution failed", error=str(e))

        try:
            from src.performance.policy_calibration import apply_learned_policy

            policy = apply_learned_policy(run_config, save=False)
            learning_context["policy_calibration"] = policy
        except Exception as e:
            logger.warning("Learned policy apply failed", error=str(e))

        # 6. Get agent weights (active agents only for aggregation)
        regime_mode = (run_config.get("regime") or {}).get("mode")
        all_weights = self.registry.get_weights(regime_mode=regime_mode)
        agent_weights = {k: all_weights[k] for k in active_agent_keys if k in all_weights}

        # 7. Generate portfolio decisions
        enable_cc = bool(run_config.get("enable_covered_calls", False))
        min_cc_score = int(run_config.get("min_cc_score", 40))
        enable_csp = bool(run_config.get("enable_cash_secured_puts", False))
        logger.info(
            "Generating portfolio decisions",
            rebalance=bool(run_config.get("rebalance")),
            covered_calls=enable_cc,
            csp=enable_csp,
        )
        if run_config.get("rebalance") is True:
            decisions = self.portfolio_manager.generate_rebalance_decisions(
                tickers=tickers,
                agent_signals=agent_signals,
                risk_analysis=risk_analysis,
                portfolio=portfolio,
                agent_weights=agent_weights,
                pending_orders_by_symbol=pending_orders_by_symbol,
                min_buy_confidence=int(run_config.get("min_buy_confidence", 60)),
                min_sell_confidence=int(run_config.get("min_sell_confidence", 60)),
                cash_buffer_pct=float(run_config.get("cash_buffer_pct", 0.05)),
                max_buy_tickers=int(run_config.get("max_buy_tickers", 20)),
                enable_covered_calls=enable_cc,
                min_cc_score=min_cc_score,
                next_earnings_by_ticker=next_earnings_by_ticker,
                earnings_blackout_days=blackout,
                enable_cash_secured_puts=enable_csp,
                min_csp_score=int(run_config.get("min_csp_score", 40)),
                enable_conviction_rebalance=bool(
                    run_config.get("enable_conviction_rebalance", False)
                ),
                conviction_score_gap=int(run_config.get("conviction_score_gap", 25)),
                min_hold_confidence_for_rotation=int(
                    run_config.get("min_hold_confidence_for_rotation", 45)
                ),
                enable_cash_rotation=bool(run_config.get("enable_cash_rotation", False)),
                cash_rotation_min_edge=int(run_config.get("cash_rotation_min_edge", 5)),
                cash_rotation_min_buy_notional_usd=float(
                    run_config.get("cash_rotation_min_buy_notional_usd", 1500.0)
                ),
                cash_rotation_min_buy_notional_pct_equity=float(
                    run_config.get("cash_rotation_min_buy_notional_pct_equity", 0.02)
                ),
                max_position_pct=float(run_config.get("max_position_pct", 0.20)),
                max_sector_pct=float(run_config.get("max_sector_pct", 0.35)),
                max_csp_tickers=int(run_config.get("max_csp_tickers", 2)),
                max_csp_collateral_pct=float(run_config.get("max_csp_collateral_pct", 0.10)),
                wash_sale_days=int(run_config.get("wash_sale_days", 0)),
                buy_disagreement_penalty=int(run_config.get("buy_disagreement_penalty", 5)),
                max_cash_rotation_sells=int(run_config.get("max_cash_rotation_sells", 3)),
                min_hold_weeks_before_rotation=int(
                    run_config.get("min_hold_weeks_before_rotation", 2)
                ),
                min_csp_premium_usd=float(run_config.get("min_csp_premium_usd", 75.0)),
                min_csp_annualized_yield_pct=float(
                    run_config.get("min_csp_annualized_yield_pct", 3.0)
                ),
                enable_short_selling=bool(
                    run_config.get("enable_short_selling", settings.enable_short_selling)
                ),
                max_short_position_pct=float(
                    run_config.get("max_short_position_pct", settings.max_short_position_pct)
                ),
                max_short_tickers=int(run_config.get("max_short_tickers", 5)),
                use_portfolio_optimizer=bool(run_config.get("use_portfolio_optimizer", False)),
            )
        else:
            decisions = self.portfolio_manager.generate_decisions(
                tickers=tickers,
                agent_signals=agent_signals,
                risk_analysis=risk_analysis,
                portfolio=portfolio,
                agent_weights=agent_weights,
                pending_orders_by_symbol=pending_orders_by_symbol,
            )
        pretrade = {}
        try:
            from src.risk.pretrade import simulate_pretrade

            pretrade = simulate_pretrade(
                decisions,
                risk_analysis,
                max_sector_pct=float(run_config.get("max_sector_pct", 0.35)),
            )
            if bool(pretrade.get("hard_block")) and execute:
                logger.warning("Pre-trade simulation blocked execution", reason=pretrade.get("block_reason"))
                execute = False
        except Exception as e:
            logger.warning("Pre-trade simulation failed", error=str(e))

        cc_lot_tickers = getattr(self.portfolio_manager, "_last_cc_lot_tickers", [])
        decision_diagnostics = (
            getattr(self.portfolio_manager, "_last_rebalance_diagnostics", {}) or {}
        )
        if int(decision_diagnostics.get("cash_rotation_sell_count", 0) or 0) > 0:
            try:
                from src.utils.alerts import send_alert

                send_alert(
                    "Cash rotation sells",
                    f"{decision_diagnostics.get('cash_rotation_sell_count')} rotation sells this run",
                    decision_diagnostics,
                )
            except Exception:
                pass

        # 8. Execute trades (if enabled)
        execution_results = None
        if execute:
            if self._broker_class is None:
                logger.error("Cannot execute trades - Alpaca broker not available")
                execution_results = {"error": "Alpaca broker not available"}
            else:
                if self.broker is None:
                    self.broker = self._broker_class()
                logger.info("Executing trades")
                px_map = {
                    t: float(risk_analysis[t]["current_price"])
                    for t in risk_analysis
                    if isinstance(risk_analysis.get(t), dict)
                    and risk_analysis[t].get("current_price") is not None
                }
                sl_pct = run_config.get("stop_loss_pct")
                execution_results = self.broker.execute_decisions(
                    decisions,
                    current_prices=px_map,
                    stop_loss_pct=float(sl_pct) if sl_pct is not None else None,
                    use_limit_orders=bool(run_config.get("use_limit_orders", False)),
                    limit_slippage_pct=float(run_config.get("limit_slippage_pct", 0.002)),
                    run_config=run_config,
                )
        else:
            logger.info("Dry run mode - trades not executed")

        if execute and self.broker:
            try:
                open_orders = self.broker.get_open_orders(limit=50)
                recent_orders = self.broker.get_recent_orders(limit=50)
            except Exception as e:
                logger.warning("Could not refresh orders after execute", error=str(e))
        reconciliation = {}
        if execute and self.broker and open_orders:
            try:
                from src.trading.reconciler import reconcile_orders

                reconciliation = reconcile_orders(broker=self.broker, max_polls=int(run_config.get("reconcile_polls", 3)))
            except Exception as e:
                logger.warning("Execution reconciliation failed", error=str(e))

        latest_price_map = {
            t: float(risk_analysis[t]["current_price"])
            for t in risk_analysis
            if isinstance(risk_analysis.get(t), dict)
            and risk_analysis[t].get("current_price") is not None
        }
        try:
            for t in latest_price_map.keys():
                px = self.data_provider.get_prices(
                    t,
                    (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d"),
                    datetime.now().strftime("%Y-%m-%d"),
                )
                if px:
                    latest_price_map[t] = float(px[-1].close)
        except Exception:
            pass

        # 8b. Covered call execution (after equity trades settle)
        cc_results: List[Dict] = []
        cc_diagnostics: Dict[str, Any] = {
            "enabled": bool(enable_cc),
            "execute_mode": bool(execute),
            "cc_lot_tickers": list(cc_lot_tickers),
            "cc_lot_ticker_count": len(cc_lot_tickers),
            "step_ran": False,
            "reason_not_run": "",
            "order_state": {},
        }
        csp_results: List[Dict] = []
        if enable_cc and execute and self.broker and cc_lot_tickers:
            cc_diagnostics["step_ran"] = True
            try:
                from src.options.covered_calls import CoveredCallManager

                logger.info("Running covered call step", cc_lot_tickers=cc_lot_tickers)
                cc_portfolio = self.broker.sync_portfolio()
                cc_manager = CoveredCallManager()
                cc_scores = {
                    t: self.portfolio_manager._score_covered_call(t, agent_signals, agent_weights)
                    for t in cc_lot_tickers
                }
                open_syms = {str(o.get("symbol") or ""): str(o.get("status") or "") for o in (open_orders or [])}
                recent_syms = {str(o.get("symbol") or ""): str(o.get("status") or "") for o in (recent_orders or [])}
                recon = {"open": 0, "partial": 0, "filled": 0}
                for sym in cc_lot_tickers:
                    st = (open_syms.get(sym) or recent_syms.get(sym) or "").lower()
                    if "partial" in st:
                        recon["partial"] += 1
                    elif st in ("filled",):
                        recon["filled"] += 1
                    elif st:
                        recon["open"] += 1
                cc_diagnostics["order_state"] = recon
                cc_results = cc_manager.execute_covered_calls(
                    broker=self.broker,
                    portfolio=cc_portfolio,
                    cc_lot_tickers=cc_lot_tickers,
                    cc_scores=cc_scores,
                    current_prices=latest_price_map,
                )
            except Exception as e:
                logger.error("Covered call step failed (non-fatal)", error=str(e))
                cc_results = [{"status": "error", "reason": str(e)}]
        else:
            if not enable_cc:
                cc_diagnostics["reason_not_run"] = "covered calls disabled by run config"
            elif not execute:
                cc_diagnostics["reason_not_run"] = "dry run mode (no execution)"
            elif not self.broker:
                cc_diagnostics["reason_not_run"] = "broker unavailable"
            elif not cc_lot_tickers:
                cc_diagnostics[
                    "reason_not_run"
                ] = "no covered-call lot candidates from decision engine"

        cc_diagnostics["result_count"] = len(cc_results)
        cc_diagnostics["executed_count"] = sum(
            1 for r in cc_results if r.get("status") == "executed"
        )
        cc_diagnostics["skipped_count"] = sum(1 for r in cc_results if r.get("status") == "skipped")
        cc_diagnostics["failed_count"] = sum(
            1 for r in cc_results if r.get("status") in ("failed", "error")
        )

        csp_lot_tickers = getattr(self.portfolio_manager, "_last_csp_tickers", [])
        csp_scores_map = getattr(self.portfolio_manager, "_last_csp_scores", {})
        if enable_csp and execute and self.broker and csp_lot_tickers:
            try:
                from src.options.cash_secured_puts import CashSecuredPutManager

                logger.info("Running cash-secured put step", csp_tickers=csp_lot_tickers)
                csp_mgr = CashSecuredPutManager(
                    min_premium_usd=float(run_config.get("min_csp_premium_usd", 75.0)),
                    min_annualized_yield_pct=float(
                        run_config.get("min_csp_annualized_yield_pct", 3.0)
                    ),
                )
                csp_results = csp_mgr.execute_cash_secured_puts(
                    broker=self.broker,
                    csp_tickers=csp_lot_tickers,
                    csp_scores=csp_scores_map,
                    current_prices=latest_price_map,
                )
            except Exception as e:
                logger.error("CSP step failed (non-fatal)", error=str(e))
                csp_results = [{"status": "error", "reason": str(e)}]

        # 9. Track performance from previous cycle
        self.cycle_tracker.record_cycle(
            agent_signals=agent_signals,
            decisions=decisions,
            current_prices=current_prices,
            date=end_date,
        )

        # 10. Portfolio after execution (for cache / ledgers)
        portfolio_after = portfolio.model_dump()
        if execute and self.broker:
            try:
                portfolio_after = self.broker.sync_portfolio().model_dump()
            except Exception as e:
                logger.warning("Could not sync portfolio after execution for cache", error=str(e))

        # 11. Persist run + learning artifacts (ledgers decoupled from cache save success)
        run_id = None
        should_persist = bool(
            run_config.get("save_to_cache")
            or (execute and run_config.get("run_profile") == "ci-full")
        )
        if should_persist:
            run_id = f"{end_date}_{uuid.uuid4().hex[:8]}"

        if scan_cache is not None and run_config.get("save_to_cache") is True:
            duration_seconds = time.time() - run_start
            if not run_id:
                run_id = f"{end_date}_{uuid.uuid4().hex[:8]}"
            try:
                data_snapshot = self._build_data_snapshot(tickers, start_date, end_date)
                scan_cache.save_run(
                    run_id=run_id,
                    run_date=end_date,
                    config=run_config,
                    tickers=tickers,
                    start_date=start_date,
                    end_date=end_date,
                    data_snapshot=data_snapshot,
                    agent_signals={
                        agent_key: {t: s.model_dump() for t, s in ticker_signals.items()}
                        for agent_key, ticker_signals in agent_signals.items()
                    },
                    risk_analysis=risk_analysis,
                    decisions={t: d.model_dump() for t, d in decisions.items()},
                    portfolio_before=portfolio.model_dump(),
                    portfolio_after=portfolio_after,
                    execution_results=execution_results,
                    duration_seconds=duration_seconds,
                    diagnostics_artifacts={
                        "pretrade_simulation": pretrade,
                        "reconciliation": reconciliation,
                    },
                )
            except Exception as e:
                logger.error("Scan cache save failed", error=str(e))
                learning_context["scan_cache_save_error"] = str(e)

        if should_persist and run_id:
            learning_context = self._persist_learning_artifacts(
                run_id=run_id,
                run_date=end_date,
                run_config=run_config,
                portfolio=portfolio,
                portfolio_after=portfolio_after,
                agent_signals=agent_signals,
                risk_analysis=risk_analysis,
                decisions=decisions,
                execution_results=execution_results,
                cc_results=cc_results,
                csp_results=csp_results,
                scan_cache=scan_cache,
                learning_context=learning_context,
                recent_orders=recent_orders,
                agent_weights=agent_weights,
            )

            if scan_cache is not None and run_config.get("refresh_agent_feedback", True):
                learning_context = self._merge_feedback_refresh(
                    learning_context, scan_cache, run_config, phase="after"
                )

            weight_meta = self._update_agent_weights(
                scan_cache=scan_cache,
                run_config=run_config,
                learning_context=learning_context,
                run_id=run_id,
            )
            learning_context["weight_changes"] = (weight_meta or {}).get("weight_changes", [])
            learning_context["weight_skips"] = (weight_meta or {}).get("weight_skips", [])
            learning_context["promotion"] = (weight_meta or {}).get("promotion", {})

            try:
                from pathlib import Path
                import json
                from src.performance.policy_calibration import apply_learned_policy, save_policy, compute_policy, load_policy
                from src.performance.canary_autopromoter import append_canary_result, evaluate_canary

                proposed = compute_policy(run_config, saved_policy=load_policy())
                promo = (weight_meta or {}).get("promotion") or {}
                exp = run_config.get("experiment") or {}
                if str(exp.get("variant") or "").lower() == "canary":
                    candidate_id = str(exp.get("name") or "unknown")
                    append_canary_result(
                        candidate_id,
                        {"delta_accuracy_pp": float((learning_context.get("promotion") or {}).get("delta_acc_pp") or 0.0)},
                    )
                    verdict = evaluate_canary(candidate_id, min_consecutive=int(run_config.get("canary_min_consecutive", 3)))
                    promo["promote"] = bool(verdict.get("promote"))
                    promo["reason"] = str(verdict.get("reason") or "canary_evaluated")
                policy_dir = Path("data/performance")
                policy_dir.mkdir(parents=True, exist_ok=True)
                candidate_path = policy_dir / "policy_calibration.candidate.json"
                with open(candidate_path, "w", encoding="utf-8") as f:
                    json.dump(proposed, f, indent=2)
                learning_context["policy_candidate_path"] = str(candidate_path)
                if promo.get("promote", True):
                    prev = load_policy() or {}
                    backup_path = policy_dir / f"policy_calibration.prev.{run_id}.json"
                    with open(backup_path, "w", encoding="utf-8") as f:
                        json.dump(prev, f, indent=2)
                    save_policy(proposed)
                    apply_learned_policy(run_config, recompute=False, save=False)
                    learning_context["policy_calibration"] = proposed
                    learning_context["policy_backup_path"] = str(backup_path)
                else:
                    learning_context["policy_promotion_skipped"] = promo.get("reason")
            except Exception as e:
                logger.warning("Policy promotion apply failed", error=str(e))

            try:
                from src.trading.run_manifest import build_deployment_attestation

                promo = (weight_meta or {}).get("promotion") or {}
                learning_context["deployment_attestation"] = build_deployment_attestation(
                    run_id=run_id,
                    promoted=bool(promo.get("promote", False)),
                    promotion_reason=str(promo.get("reason") or ""),
                    rollback_trigger="slo_breach_or_pretrade_block",
                    manifest_sha256=str(learning_context.get("manifest_sha256") or ""),
                )
            except Exception:
                pass

            try:
                from src.backtesting.agent_evaluator import load_scorecard
                from src.performance.learning_changelog import append_changelog_entry

                sc = learning_context.get("scorecard_source") or ""
                regime_mode = (run_config.get("regime") or {}).get("mode") or ""
                by_regime = (load_scorecard() or {}).get("by_regime") or {}
                regime_counts = {
                    k: len((v or {}).get("agents") or {}) for k, v in by_regime.items()
                }
                append_changelog_entry(
                    run_id=run_id,
                    run_date=end_date,
                    weight_changes=learning_context.get("weight_changes"),
                    weight_skips=learning_context.get("weight_skips"),
                    policy_adjustments=(learning_context.get("policy_calibration") or {}).get(
                        "adjustments"
                    ),
                    scorecard_source=sc,
                    regime_mode=regime_mode,
                    regime_bucket_counts=regime_counts,
                    promoted=(weight_meta or {}).get("promotion", {}).get("promote"),
                    promotion_reason=(weight_meta or {}).get("promotion", {}).get("reason"),
                )
            except Exception as e:
                logger.warning("Learning changelog append failed", error=str(e))

        # 12. Return results (use post-execution portfolio when available)
        broker_used = self.broker is not None
        port_dict = (
            portfolio_after
            if (execute and self.broker and portfolio_after is not None)
            else portfolio.model_dump()
        )
        # Ensure email/reports get equity (cash + market value of positions)
        equity = float(port_dict.get("cash", 0))
        for ticker, pos in (port_dict.get("positions") or {}).items():
            price = risk_analysis.get(ticker, {}).get("current_price")
            if price is None:
                price = pos.get("long_cost_basis") or pos.get("short_cost_basis") or 0
            price = float(price)
            equity += (pos.get("long", 0) * price) - (pos.get("short", 0) * price)
        port_dict["equity"] = round(equity, 2)

        def _safe_dump(obj: Any) -> Any:
            if obj is None:
                return None
            if hasattr(obj, "model_dump"):
                return obj.model_dump()
            if isinstance(obj, dict):
                return obj
            return str(obj)

        ts_iso = datetime.now().isoformat()
        execution_status: Dict[str, Any] = {}
        if execute and execution_results:
            try:
                from src.trading.execution_status import build_execution_status

                execution_status = build_execution_status(
                    execution_results,
                    open_orders,
                    recent_orders,
                    run_timestamp=ts_iso,
                )
            except Exception as e:
                logger.warning("Execution status summary failed", error=str(e))

        results = {
            "run_id": run_id,
            "timestamp": ts_iso,
            "tickers": tickers,
            "intraweek_stock_summary": run_config.get("intraweek_stock_summary") or "",
            "portfolio": port_dict,
            "open_orders": open_orders,
            "recent_orders": recent_orders,
            "broker_used": broker_used,
            "agent_signals": {
                agent_key: {
                    ticker: _safe_dump(signal) for ticker, signal in ticker_signals.items()
                }
                for agent_key, ticker_signals in agent_signals.items()
            },
            "risk_analysis": risk_analysis,
            "decisions": {ticker: _safe_dump(decision) for ticker, decision in decisions.items()},
            "execution_results": execution_results,
            "execution_status": execution_status,
            "covered_call_results": cc_results,
            "covered_call_diagnostics": cc_diagnostics,
            "decision_diagnostics": decision_diagnostics,
            "pretrade_simulation": pretrade,
            "agent_errors": getattr(self, "_agent_errors", {}),
            "llm_budget": getattr(self, "_llm_budget_summary", {}),
            "learning_context": learning_context,
            "csp_results": csp_results,
            "regime": run_config.get("regime") or {},
            "reconciliation": reconciliation,
        }
        try:
            from src.trading.provenance import build_provenance

            agg = {t: self.portfolio_manager._aggregate_signals(t, agent_signals, agent_weights) for t in tickers}
            prov = {}
            for t in tickers:
                prov[t] = build_provenance(
                    ticker=t,
                    aggregated_signal=agg.get(t) or {},
                    decision=results.get("decisions", {}).get(t) or {},
                    risk=(risk_analysis or {}).get(t) or {},
                )
            results["decision_provenance"] = prov
        except Exception:
            pass
        try:
            if hasattr(self.data_provider, "data_quality_score"):
                results["data_quality"] = self.data_provider.data_quality_score()
                if float(results["data_quality"].get("score") or 100.0) < 80.0:
                    results["degrade_mode_label"] = "provider_degraded_fallback"
        except Exception:
            pass
        try:
            from src.performance.cost_optimizer import compute_lane_utility, tune_lane_budget

            lane_utility = compute_lane_utility(results)
            results["lane_utility"] = lane_utility
            cur = dict((run_config.get("lane_llm_budget") or {}))
            if cur:
                results["lane_budget_recommendation"] = tune_lane_budget(cur, lane_utility)
        except Exception:
            pass
        try:
            from src.trading.replay import decision_diff

            shadows = []
            baseline_decisions = results.get("decisions") or {}
            for variant in (run_config.get("shadow_variants") or []):
                ov = dict(variant.get("overrides") or {})
                shadow_cfg = dict(run_config)
                shadow_cfg.update(ov)
                shadow_cfg["save_to_cache"] = False
                shadow_cfg["shadow_variants"] = []
                shadow_res = self.run_weekly_trading(
                    tickers=tickers,
                    start_date=start_date,
                    end_date=end_date,
                    execute=False,
                    scan_cache=None,
                    run_config=shadow_cfg,
                )
                d = decision_diff({"decisions": baseline_decisions}, {"decisions": shadow_res.get("decisions") or {}})
                shadows.append(
                    {
                        "name": str(variant.get("name") or "candidate"),
                        "config_overrides": ov,
                        "decision_diff": d,
                        "summary": {
                            "changed": len(d.get("changed") or []),
                            "missing": len(d.get("missing") or []),
                            "new": len(d.get("new") or []),
                        },
                    }
                )
            if shadows:
                results["shadow_validation"] = {"variants": shadows}
        except Exception as e:
            results["shadow_validation"] = {"variants": [], "error": str(e)}
        try:
            if scan_cache is not None:
                from src.data.providers.trust_plane import detect_provider_drift

                runs = scan_cache.list_runs(limit=2)
                if len(runs) >= 2:
                    left = scan_cache.load_run(runs[1]["run_id"]).get("risk") or {}
                    right = scan_cache.load_run(runs[0]["run_id"]).get("risk") or {}
                    results["provider_drift_alarms"] = detect_provider_drift(left, right)
        except Exception:
            pass
        try:
            from src.ops.slo import evaluate_slos
            from src.utils.alerts import send_alert
            from src.ops.go_no_go import build_go_no_go_report

            results["slo"] = evaluate_slos(results)
            results["go_no_go"] = build_go_no_go_report(results)
            if not results["slo"].get("ok"):
                send_alert("Weekly SLO breach", "One or more SLO checks failed", results["slo"])
        except Exception:
            pass
        try:
            from src.performance.alpha_lifecycle import evaluate_lane_retirement
            from src.agents.champion_challenger import lane_summary

            results["alpha_lifecycle"] = {
                "lane_retirement": [evaluate_lane_retirement(lane) for lane in ("fundamentals", "technicals", "sentiment")],
                "champion_challenger": lane_summary(),
            }
        except Exception:
            pass

        logger.info("Weekly trading cycle complete", decision_count=len(decisions))
        return results

    def _build_data_snapshot(
        self,
        tickers: List[str],
        start_date: str,
        end_date: str,
    ) -> Dict[str, Dict[str, Any]]:
        """
        Build a compact per-ticker snapshot of the data used in this run.
        Uses cached data (cache is warm after _refresh_data).
        """
        snapshot = {}
        for ticker in tickers:
            try:
                prices = self.data_provider.get_prices(ticker, start_date, end_date)
                metrics_list = self.data_provider.get_financial_metrics(ticker, end_date, limit=1)
                line_items_list = self.data_provider.get_line_items(
                    ticker,
                    [
                        "revenue",
                        "net_income",
                        "free_cash_flow",
                        "total_debt",
                        "shareholders_equity",
                    ],
                    end_date,
                    limit=1,
                )
                news = self.data_provider.get_company_news(ticker, end_date, start_date, limit=5)
                m0 = metrics_list[0].model_dump() if metrics_list else {}
                snapshot[ticker] = {
                    "last_price": float(prices[-1].close) if prices else None,
                    "price_count": len(prices),
                    "metrics": m0,
                    "line_items": line_items_list[0].model_dump() if line_items_list else {},
                    "news_count": len(news),
                    "news_titles": [n.title for n in news[:5]],
                }
            except Exception as e:
                logger.debug("Snapshot failed for ticker", ticker=ticker, error=str(e))
                snapshot[ticker] = {"error": str(e)}
        return snapshot

    def _refresh_data(
        self,
        tickers: List[str],
        start_date: str,
        end_date: str,
        parallel: bool = True,
        max_workers: Optional[int] = None,
        financial_limit: int = 1,
    ):
        """
        Refresh market data for all tickers (with optional parallel execution)

        Args:
            tickers: List of tickers to refresh
            start_date: Start date for price data
            end_date: End date for analysis
            parallel: If True, fetch data in parallel (default: True)
            max_workers: Maximum number of worker threads (default: None = auto)
        """

        def refresh_ticker(ticker: str):
            """Refresh data for a single ticker"""
            try:
                attempts = 0
                while True:
                    attempts += 1
                    try:
                        # Fetch prices (will be cached)
                        self.data_provider.get_prices(ticker, start_date, end_date)
                        # Fetch financial metrics
                        self.data_provider.get_financial_metrics(
                            ticker, end_date, limit=financial_limit
                        )
                        # Fetch line items
                        self.data_provider.get_line_items(
                            ticker,
                            ["revenue", "net_income", "free_cash_flow", "total_debt"],
                            end_date,
                            limit=financial_limit,
                        )
                        break
                    except Exception:
                        if attempts >= 3:
                            raise
                        time.sleep(0.2 * attempts)
                return ticker, True, None
            except Exception as e:
                logger.warning("Data refresh failed", ticker=ticker, error=str(e))
                return ticker, False, str(e)

        if parallel and len(tickers) > 10:
            # Use parallel execution for large ticker lists
            logger.info("Refreshing data in parallel", ticker_count=len(tickers))
            success_count = 0
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {executor.submit(refresh_ticker, ticker): ticker for ticker in tickers}
                for future in as_completed(futures):
                    ticker, success, error = future.result()
                    if success:
                        success_count += 1
            logger.info("Data refresh complete", success_count=success_count, total=len(tickers))
        else:
            # Sequential execution for small lists
            for ticker in tickers:
                refresh_ticker(ticker)

    def _run_agents(
        self,
        tickers: List[str],
        start_date: str,
        end_date: str,
        batch_size: int = 100,
        active_agent_keys: Optional[List[str]] = None,
    ) -> Dict[str, Dict[str, AgentSignal]]:
        """
        Run registered agents on tickers (with optional parallel execution)

        Args:
            tickers: List of tickers to analyze
            start_date: Analysis start date
            end_date: Analysis end date
            batch_size: Number of tickers to process per batch (for large universes)
            active_agent_keys: Subset of agent keys to run (default: all registered)
        """
        agents = self.registry.get_active(active_agent_keys)
        agent_signals = {}
        self._agent_errors = {}

        # For large universes, process in batches
        use_batching = len(tickers) > batch_size

        if self.parallel_agents and len(agents) > 1:
            # Run agents in parallel
            logger.info(
                "Running agents in parallel", agent_count=len(agents), ticker_count=len(tickers)
            )
            completed_agents = 0
            total_agents = len(agents)

            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = {
                    executor.submit(
                        self._run_single_agent,
                        agent_key,
                        agent,
                        tickers,
                        start_date,
                        end_date,
                        batch_size,
                    ): agent_key
                    for agent_key, agent in agents.items()
                }

                for future in as_completed(futures):
                    agent_key = futures[future]
                    try:
                        signals = future.result()
                        agent_signals[agent_key] = signals
                        completed_agents += 1

                        # Log progress for larger runs
                        if total_agents > 5 or len(tickers) > 10:
                            logger.info(
                                "Agent progress",
                                completed=completed_agents,
                                total=total_agents,
                                pct=round(completed_agents / total_agents * 100, 1),
                            )
                    except Exception as e:
                        logger.error("Agent execution failed", agent=agent_key, error=str(e))
                        self._agent_errors[agent_key] = str(e)
                        # Default to neutral signals on error
                        agent_signals[agent_key] = {
                            ticker: AgentSignal(
                                signal="neutral", confidence=0, reasoning=f"Agent error: {str(e)}"
                            )
                            for ticker in tickers
                        }
                        completed_agents += 1

            logger.info("All agents complete", total_agents=total_agents)
        else:
            # Sequential execution
            for agent_key, agent in agents.items():
                signals = self._run_single_agent(
                    agent_key, agent, tickers, start_date, end_date, batch_size
                )
                agent_signals[agent_key] = signals

        return agent_signals

    def _run_single_agent(
        self,
        agent_key: str,
        agent,
        tickers: List[str],
        start_date: str,
        end_date: str,
        batch_size: int,
    ) -> Dict[str, AgentSignal]:
        """Run a single agent on tickers"""
        dossiers = getattr(self, "_ticker_dossiers", {}) or {}
        analyze_kw = {
            "dossiers": dossiers,
            "agent_key": agent_key,
            "llm_cache": True,
            "llm_budget": getattr(self, "_llm_budget", {"remaining": 10**9}),
        }
        try:
            use_batching = len(tickers) > batch_size

            logger.info(
                "Running agent",
                agent=agent.name,
                agent_key=agent_key,
                ticker_count=len(tickers),
                batching=use_batching,
            )

            if use_batching:
                # Process in batches
                all_signals = {}
                total_batches = (len(tickers) + batch_size - 1) // batch_size

                for batch_num in range(total_batches):
                    batch_start = batch_num * batch_size
                    batch_end = min((batch_num + 1) * batch_size, len(tickers))
                    batch_tickers = tickers[batch_start:batch_end]

                    logger.info(
                        "Processing batch",
                        agent=agent.name,
                        batch=batch_num + 1,
                        total_batches=total_batches,
                        batch_size=len(batch_tickers),
                    )

                    try:
                        batch_signals = agent.analyze_multiple(
                            batch_tickers,
                            start_date,
                            end_date,
                            parallel=True,
                            max_workers=min(2, len(batch_tickers)),
                            **analyze_kw,
                        )
                        all_signals.update(batch_signals)
                    except Exception as e:
                        logger.warning(
                            "Batch failed, using neutral signals",
                            agent=agent.name,
                            batch=batch_num + 1,
                            error=str(e),
                        )
                        # Default to neutral for failed batch
                        for ticker in batch_tickers:
                            all_signals[ticker] = AgentSignal(
                                signal="neutral",
                                confidence=0,
                                reasoning=f"Batch processing error: {str(e)}",
                            )

                logger.info(
                    "Agent complete",
                    agent=agent.name,
                    signals_generated=len(all_signals),
                )
                return all_signals
            else:
                # Process all at once (with limited parallel ticker processing for local Ollama)
                # For local LLM, limit to 1-2 concurrent per agent to avoid overwhelming Ollama
                # With 21 agents, this still allows good parallelization
                signals = agent.analyze_multiple(
                    tickers,
                    start_date,
                    end_date,
                    parallel=True,
                    max_workers=min(2, len(tickers)),
                    **analyze_kw,
                )
                logger.info(
                    "Agent complete",
                    agent=agent.name,
                    signals_generated=len(signals),
                )
                return signals

        except Exception as e:
            logger.error("Agent execution failed", agent=agent.name, error=str(e))
            # Default to neutral signals on error
            return {
                ticker: AgentSignal(
                    signal="neutral", confidence=0, reasoning=f"Agent error: {str(e)}"
                )
                for ticker in tickers
            }

    def _persist_learning_artifacts(
        self,
        *,
        run_id: str,
        run_date: str,
        run_config: Dict[str, Any],
        portfolio: Any,
        portfolio_after: Dict[str, Any],
        agent_signals: Dict[str, Dict[str, AgentSignal]],
        risk_analysis: Dict[str, Any],
        decisions: Dict[str, Any],
        execution_results: Dict[str, Any],
        cc_results: List[Dict[str, Any]],
        csp_results: List[Dict[str, Any]],
        scan_cache: Optional[Any],
        learning_context: Dict[str, Any],
        recent_orders: Optional[List[Dict[str, Any]]] = None,
        agent_weights: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        """Append ledgers and optional S3 upload; independent of scan_cache save success."""
        regime_mode = (run_config.get("regime") or {}).get("mode")

        try:
            from src.performance.fill_ledger import append_fills_from_run

            append_fills_from_run(
                run_id=run_id,
                run_date=run_date,
                decisions=decisions,
                risk_analysis=risk_analysis,
                execution_results=execution_results,
                recent_orders=recent_orders,
            )
        except Exception as e:
            logger.warning("Fill ledger append failed", error=str(e))

        try:
            from src.performance.weekly_ledger import (
                append_ledger_entry,
                build_tickers_from_run,
                position_open_dates,
            )

            prev_opens = position_open_dates()
            port_before = portfolio.model_dump()
            ticker_map = build_tickers_from_run(
                port_before,
                {t: d.model_dump() for t, d in decisions.items()},
                risk_analysis,
                {
                    ak: {t: s.model_dump() for t, s in ts.items()}
                    for ak, ts in agent_signals.items()
                },
            )
            position_opens = dict(prev_opens)
            for t, d in decisions.items():
                if d.action == "buy" and d.quantity > 0:
                    position_opens[t] = run_date
                    if t in ticker_map:
                        ticker_map[t]["opened_this_run"] = True
            append_ledger_entry(
                run_id=run_id,
                run_date=run_date,
                active_agents=run_config.get("active_agents") or [],
                tickers=ticker_map,
                position_opens=position_opens,
                regime=(run_config.get("regime") or {}).get("mode"),
            )
        except Exception as e:
            logger.error("Weekly ledger append failed — scorecard fallback may be delayed", error=str(e))

        try:
            from src.performance.decision_ledger import append_decisions_from_run

            append_decisions_from_run(
                run_id=run_id,
                run_date=run_date,
                regime=run_config.get("regime"),
                decisions={t: d.model_dump() for t, d in decisions.items()},
                risk_analysis=risk_analysis,
                agent_signals={
                    ak: {t: s.model_dump() for t, s in ts.items()}
                    for ak, ts in agent_signals.items()
                },
                execution_results=execution_results,
            )
        except Exception as e:
            logger.warning("Decision ledger append failed", error=str(e))

        try:
            from src.performance.options_ledger import append_cc_results, append_csp_results

            append_cc_results(
                run_id=run_id, run_date=run_date, cc_results=cc_results, regime=regime_mode
            )
            append_csp_results(
                run_id=run_id, run_date=run_date, csp_results=csp_results, regime=regime_mode
            )
        except Exception as e:
            logger.warning("Options ledger append failed", error=str(e))

        try:
            from src.performance.counterfactual_ledger import append_counterfactuals_from_run

            agg: Dict[str, Dict[str, Any]] = {}
            weights = agent_weights or {}
            for t in (decisions or {}):
                agg[t] = self.portfolio_manager._aggregate_signals(t, agent_signals, weights)
            append_counterfactuals_from_run(
                run_id=run_id,
                run_date=run_date,
                decisions=decisions,
                aggregated_signals=agg,
                risk_analysis=risk_analysis,
                min_buy_confidence=int(run_config.get("min_buy_confidence", 60)),
                min_sell_confidence=int(run_config.get("min_sell_confidence", 60)),
            )
        except Exception as e:
            logger.warning("Counterfactual ledger append failed", error=str(e))

        try:
            from src.performance.fill_ledger import recent_fills
            from src.performance.portfolio_attribution import append_weekly_attribution

            opt_premium = sum(
                float(r.get("estimated_premium") or r.get("premium") or 0)
                for r in (cc_results or []) + (csp_results or [])
                if isinstance(r, dict) and r.get("status") == "executed"
            )
            attr = append_weekly_attribution(
                run_id=run_id,
                run_date=run_date,
                portfolio_before=portfolio.model_dump(),
                portfolio_after=portfolio_after,
                risk_analysis=risk_analysis,
                fills=recent_fills(run_id=run_id),
                options_premium_usd=opt_premium,
            )
            learning_context["portfolio_attribution"] = attr
        except Exception as e:
            logger.warning("Portfolio attribution append failed", error=str(e))

        if scan_cache is not None and not learning_context.get("scan_cache_save_error"):
            try:
                from src.scan_cache.remote_store import upload_run

                if upload_run(run_id):
                    learning_context["s3_run_uploaded"] = True
            except Exception as e:
                logger.warning("S3 scan upload failed", error=str(e))

        return learning_context

    def _update_agent_weights(
        self,
        scan_cache: Optional[Any] = None,
        run_config: Optional[Dict[str, Any]] = None,
        learning_context: Optional[Dict[str, Any]] = None,
        run_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Update agent weights based on performance (scan cache + cycle tracker data)."""
        run_config = run_config or {}
        learning_context = learning_context or {}
        meta: Dict[str, Any] = {"weight_changes": [], "weight_skips": [], "promotion": {}}
        try:
            cache_added = 0
            if scan_cache is not None:
                cache_added = self.performance_tracker.load_from_scan_cache(scan_cache, limit=5)
            ledger_count = int(
                learning_context.get("ledger_run_count_after")
                or learning_context.get("ledger_run_count")
                or 0
            )
            if cache_added == 0 and ledger_count >= 2:
                self.performance_tracker.load_from_weekly_ledger(limit_pairs=5)
            scorecard_agents = {}
            sc_full: Dict[str, Any] = {}
            try:
                from src.backtesting.agent_evaluator import blend_scorecard_metrics, load_scorecard

                sc_full = load_scorecard()
                regime_mode = (run_config.get("regime") or {}).get("mode") or "neutral"
                scorecard_agents = blend_scorecard_metrics(sc_full, regime_mode)
            except Exception:
                pass

            portfolio_metrics: Dict[str, float] = {}
            attribution_weeks = 0
            if run_id:
                try:
                    from src.performance.portfolio_attribution import (
                        agent_dollar_metrics,
                        attribution_week_count,
                    )

                    portfolio_metrics = agent_dollar_metrics(run_id)
                    attribution_weeks = attribution_week_count()
                except Exception:
                    pass

            current_weights = self.registry.get_weights(
                regime_mode=(run_config.get("regime") or {}).get("mode")
            )
            dollar_blend = float(run_config.get("dollar_blend", 0.30))
            new_weights, weight_meta = self.performance_tracker.calculate_weights_from_performance(
                min_weight=0.1,
                max_weight=3.0,
                smoothing_factor=0.2,
                scorecard_metrics=scorecard_agents,
                decay_half_life_weeks=8.0,
                current_weights=current_weights,
                min_observations_for_move=15,
                max_weight_delta_per_run=0.15,
                portfolio_metrics=portfolio_metrics,
                dollar_blend=dollar_blend,
                attribution_weeks=attribution_weeks,
            )
            meta["weight_changes"] = weight_meta.get("weight_changes", [])
            meta["weight_skips"] = weight_meta.get("weight_skips", [])
            meta["dollar_blend_active"] = weight_meta.get("dollar_blend_active", False)

            from src.performance.promotion_gates import evaluate_proposal

            promo = evaluate_proposal(
                proposed_weights=new_weights,
                proposed_policy=(run_config.get("policy_calibration") or {}),
                scan_cache=scan_cache,
                baseline_weights=current_weights,
            )
            meta["promotion"] = promo

            if new_weights and promo.get("promote", True):
                updated_count = 0
                regime_mode = (run_config.get("regime") or {}).get("mode")
                by_regime = (sc_full.get("by_regime") or {}).get(regime_mode or "") or {}
                regime_agents = (by_regime.get("agents") or {}) if isinstance(by_regime, dict) else {}
                use_regime = regime_mode and len(regime_agents) >= 6

                for agent_key, new_weight in new_weights.items():
                    old_weight = current_weights.get(agent_key, 1.0)
                    if abs(new_weight - old_weight) > 0.01:
                        self.registry.update_weight(
                            agent_key,
                            new_weight,
                            regime_mode=regime_mode if use_regime else None,
                        )
                        updated_count += 1
                        logger.info(
                            "Updated agent weight",
                            agent=agent_key,
                            old_weight=round(old_weight, 2),
                            new_weight=round(new_weight, 2),
                        )

                if updated_count > 0:
                    self.registry.save_weights_to_config(regime_mode=regime_mode if use_regime else None)
                    logger.info(
                        "Agent weights updated based on performance",
                        updated_count=updated_count,
                        total_agents=len(new_weights),
                    )
            elif new_weights and not promo.get("promote", True):
                logger.warning("Weight update skipped by promotion gate", reason=promo.get("reason"))
                meta["weight_skips"].append(
                    {"agent": "*", "reason": f"promotion_gate:{promo.get('reason')}"}
                )
            else:
                logger.debug("No performance data available for weight adjustment")

        except Exception as e:
            logger.error("Error updating agent weights", error=str(e))
        return meta

    def _merge_feedback_refresh(
        self,
        learning_context: Dict[str, Any],
        scan_cache: Any,
        run_config: Dict[str, Any],
        phase: str = "before",
    ) -> Dict[str, Any]:
        """Run refresh_feedback_from_cache and merge metadata into learning_context."""
        try:
            from src.backtesting.feedback import refresh_feedback_from_cache
            from src.backtesting.agent_evaluator import load_scorecard

            fb_meta = refresh_feedback_from_cache(
                scan_cache,
                max_run_pairs=int(run_config.get("scorecard_run_pairs", 20)),
            )
            learning_context["feedback_refresh_ok"] = True
            for k in (
                "scan_cache_run_count",
                "ledger_run_count",
                "scorecard_agent_count",
                "scorecard_pairs_used",
                "scorecard_skip_reason",
                "scorecard_progress",
                "scorecard_progress_required",
                "wrote_scorecard_file",
                "wrote_agent_feedback",
                "scorecard_source",
            ):
                if isinstance(fb_meta, dict) and k in fb_meta:
                    learning_context[k] = fb_meta[k]

            sc_agents = (load_scorecard() or {}).get("agents") or {}
            present = len(sc_agents) > 0
            if phase == "before":
                learning_context["scan_cache_run_count_before"] = learning_context.get(
                    "scan_cache_run_count", 0
                )
                learning_context["ledger_run_count_before"] = learning_context.get(
                    "ledger_run_count", 0
                )
                learning_context["scorecard_present"] = present
            else:
                learning_context["scan_cache_run_count_after"] = learning_context.get(
                    "scan_cache_run_count", 0
                )
                learning_context["ledger_run_count_after"] = learning_context.get(
                    "ledger_run_count", 0
                )
                learning_context["scorecard_present_after"] = present
                if present:
                    learning_context["scorecard_present"] = True
        except Exception as e:
            logger.warning("Agent feedback refresh failed", phase=phase, error=str(e))
            learning_context["feedback_refresh_error"] = str(e)
        return learning_context
