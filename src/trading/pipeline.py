"""Weekly trading pipeline"""

from typing import List, Dict, Optional, Any
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from dateutil.relativedelta import relativedelta
import structlog
import time
import uuid
from src.agents.registry import get_registry
from src.agents.base import AgentSignal
from src.risk.manager import RiskManager
from src.portfolio.manager import PortfolioManager
from src.portfolio.models import Portfolio
from src.data.providers.aggregator import get_data_provider
from src.performance.tracker import PerformanceTracker
from src.performance.cycle_tracker import CyclePerformanceTracker

# Lazy import for Alpaca broker (only needed when executing trades)
def get_alpaca_broker():
    """Lazy import of Alpaca broker. Returns None if Alpaca not installed or keys not configured."""
    try:
        from src.config.settings import settings
        if not settings.alpaca_api_key or not settings.alpaca_secret_key:
            logger.info("Alpaca keys not configured - set ALPACA_API_KEY and ALPACA_SECRET_KEY in .env for --execute")
            return None
        from src.broker.alpaca import AlpacaBroker
        return AlpacaBroker
    except ImportError as e:
        logger.warning("Alpaca broker not available", error=str(e))
        return None

logger = structlog.get_logger()


class TradingPipeline:
    """Main trading pipeline for weekly execution"""
    
    def __init__(self, parallel_agents: bool = True, max_workers: Optional[int] = None, broker=None):
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
        self.data_provider = get_data_provider()
        self.performance_tracker = PerformanceTracker()
        self.cycle_tracker = CyclePerformanceTracker()
        self.parallel_agents = parallel_agents
        self.max_workers = max_workers
        logger.info(
            "Initialized trading pipeline",
            parallel_agents=parallel_agents,
            max_workers=max_workers,
        )
    
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
            logger.info("Syncing portfolio from broker (decisions will use live cash and positions)")
            try:
                portfolio = self.broker.sync_portfolio()
            except Exception as e:
                logger.error("Portfolio sync failed; aborting run to avoid decisions on bogus data", error=str(e))
                raise SystemExit(1)
            try:
                open_orders = self.broker.get_open_orders(limit=50)
                recent_orders = self.broker.get_recent_orders(limit=20)
            except Exception as e:
                logger.warning("Could not fetch orders from broker", error=str(e))
        else:
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
            logger.info("Pending orders by symbol (will cap decisions)", pending=pending_orders_by_symbol)

        if not self._broker_class:
            logger.error("Alpaca keys required but not configured. Set ALPACA_API_KEY and ALPACA_SECRET_KEY in .env. No fallback.")
            raise SystemExit(1)

        # 2. Calculate date range (last 3 months for analysis)
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - relativedelta(months=3)).strftime("%Y-%m-%d")
        
        # 3. Refresh data (right before trading)
        logger.info("Refreshing market data", start_date=start_date, end_date=end_date)
        self._refresh_data(tickers, start_date, end_date)

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

        if scan_cache is not None and run_config.get("refresh_agent_feedback", True):
            try:
                from src.backtesting.feedback import refresh_feedback_from_cache

                refresh_feedback_from_cache(
                    scan_cache,
                    max_run_pairs=int(run_config.get("scorecard_run_pairs", 20)),
                )
            except Exception as e:
                logger.warning("Agent feedback refresh failed", error=str(e))
        
        # 4. Run all agents
        logger.info("Running agent analysis")
        agent_signals = self._run_agents(tickers, start_date, end_date)
        
        # 5. Calculate risk limits
        logger.info("Calculating risk limits")
        risk_analysis = self.risk_manager.calculate_position_limits(
            tickers, portfolio, start_date, end_date
        )
        
        # 6. Get agent weights
        agent_weights = self.registry.get_weights()
        
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
                enable_conviction_rebalance=bool(run_config.get("enable_conviction_rebalance", False)),
                conviction_score_gap=int(run_config.get("conviction_score_gap", 25)),
                min_hold_confidence_for_rotation=int(
                    run_config.get("min_hold_confidence_for_rotation", 45)
                ),
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

        cc_lot_tickers = getattr(self.portfolio_manager, "_last_cc_lot_tickers", [])
        
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
                )
        else:
            logger.info("Dry run mode - trades not executed")

        # 8b. Covered call execution (after equity trades settle)
        cc_results: List[Dict] = []
        csp_results: List[Dict] = []
        if enable_cc and execute and self.broker and cc_lot_tickers:
            try:
                from src.options.covered_calls import CoveredCallManager
                logger.info("Running covered call step", cc_lot_tickers=cc_lot_tickers)
                cc_portfolio = self.broker.sync_portfolio()
                cc_manager = CoveredCallManager()
                cc_scores = {
                    t: self.portfolio_manager._score_covered_call(t, agent_signals, agent_weights)
                    for t in cc_lot_tickers
                }
                cc_results = cc_manager.execute_covered_calls(
                    broker=self.broker,
                    portfolio=cc_portfolio,
                    cc_lot_tickers=cc_lot_tickers,
                    cc_scores=cc_scores,
                    current_prices={t: risk_analysis[t]["current_price"] for t in risk_analysis},
                )
            except Exception as e:
                logger.error("Covered call step failed (non-fatal)", error=str(e))
                cc_results = [{"status": "error", "reason": str(e)}]

        csp_lot_tickers = getattr(self.portfolio_manager, "_last_csp_tickers", [])
        csp_scores_map = getattr(self.portfolio_manager, "_last_csp_scores", {})
        if enable_csp and execute and self.broker and csp_lot_tickers:
            try:
                from src.options.cash_secured_puts import CashSecuredPutManager

                logger.info("Running cash-secured put step", csp_tickers=csp_lot_tickers)
                csp_mgr = CashSecuredPutManager()
                csp_results = csp_mgr.execute_cash_secured_puts(
                    broker=self.broker,
                    csp_tickers=csp_lot_tickers,
                    csp_scores=csp_scores_map,
                    current_prices={t: risk_analysis[t]["current_price"] for t in risk_analysis},
                )
            except Exception as e:
                logger.error("CSP step failed (non-fatal)", error=str(e))
                csp_results = [{"status": "error", "reason": str(e)}]
        
        # 9. Track performance from previous cycle
        current_prices = {t: risk_analysis[t]['current_price'] for t in risk_analysis.keys()}
        self.cycle_tracker.record_cycle(
            agent_signals=agent_signals,
            decisions=decisions,
            current_prices=current_prices,
            date=end_date,
        )
        
        # 10. Update agent weights based on performance (use scan cache when available)
        self._update_agent_weights(scan_cache=scan_cache)
        
        # 10b. Portfolio after execution (for cache)
        portfolio_after = portfolio.model_dump()
        if execute and self.broker:
            try:
                portfolio_after = self.broker.sync_portfolio().model_dump()
            except Exception as e:
                logger.warning("Could not sync portfolio after execution for cache", error=str(e))
        
        # 11. Persist full run to scan cache only for official weekly universe runs (never for test/debug/exploratory)
        run_id = None
        if scan_cache is not None and run_config.get("save_to_cache") is True:
            duration_seconds = time.time() - run_start
            run_id = f"{end_date}_{uuid.uuid4().hex[:8]}"
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
            )
        
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

        results = {
            "run_id": run_id,
            "timestamp": datetime.now().isoformat(),
            "tickers": tickers,
            "portfolio": port_dict,
            "open_orders": open_orders,
            "recent_orders": recent_orders,
            "broker_used": broker_used,
            'agent_signals': {
                agent_key: {
                    ticker: signal.model_dump()
                    for ticker, signal in ticker_signals.items()
                }
                for agent_key, ticker_signals in agent_signals.items()
            },
            'risk_analysis': risk_analysis,
            'decisions': {
                ticker: decision.model_dump()
                for ticker, decision in decisions.items()
            },
            'execution_results': execution_results,
            'covered_call_results': cc_results,
            'csp_results': csp_results,
        }
        
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
                    ["revenue", "net_income", "free_cash_flow", "total_debt", "shareholders_equity"],
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
                # Fetch prices (will be cached)
                self.data_provider.get_prices(ticker, start_date, end_date)
                # Fetch financial metrics
                self.data_provider.get_financial_metrics(ticker, end_date, limit=10)
                # Fetch line items
                self.data_provider.get_line_items(
                    ticker,
                    ["revenue", "net_income", "free_cash_flow", "total_debt"],
                    end_date,
                    limit=10
                )
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
    ) -> Dict[str, Dict[str, AgentSignal]]:
        """
        Run all registered agents on tickers (with optional parallel execution)
        
        Args:
            tickers: List of tickers to analyze
            start_date: Analysis start date
            end_date: Analysis end date
            batch_size: Number of tickers to process per batch (for large universes)
        """
        agents = self.registry.get_all()
        agent_signals = {}
        
        # For large universes, process in batches
        use_batching = len(tickers) > batch_size
        
        if self.parallel_agents and len(agents) > 1:
            # Run agents in parallel
            logger.info("Running agents in parallel", agent_count=len(agents), ticker_count=len(tickers))
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
                                pct=round(completed_agents / total_agents * 100, 1)
                            )
                    except Exception as e:
                        logger.error("Agent execution failed", agent=agent_key, error=str(e))
                        # Default to neutral signals on error
                        agent_signals[agent_key] = {
                            ticker: AgentSignal(
                                signal="neutral",
                                confidence=0,
                                reasoning=f"Agent error: {str(e)}"
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
                        # Enable parallel processing for batches (but limit concurrency for local Ollama)
                        batch_signals = agent.analyze_multiple(
                            batch_tickers,
                            start_date,
                            end_date,
                            parallel=True,
                            max_workers=min(2, len(batch_tickers))  # Limit to 2 concurrent per agent for local Ollama
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
                                reasoning=f"Batch processing error: {str(e)}"
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
                    max_workers=min(2, len(tickers))  # Limit to 2 concurrent per agent for local Ollama
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
                    signal="neutral",
                    confidence=0,
                    reasoning=f"Agent error: {str(e)}"
                )
                for ticker in tickers
            }
    
    def _update_agent_weights(self, scan_cache: Optional[Any] = None):
        """Update agent weights based on performance (scan cache + cycle tracker data)."""
        try:
            if scan_cache is not None:
                self.performance_tracker.load_from_scan_cache(scan_cache, limit=5)
            scorecard_agents = {}
            try:
                from src.backtesting.agent_evaluator import load_scorecard

                sc = load_scorecard()
                for ak, row in (sc.get("agents") or {}).items():
                    if isinstance(row, dict) and row.get("directional_observations", 0):
                        scorecard_agents[ak] = row
            except Exception:
                pass
            new_weights = self.performance_tracker.calculate_weights_from_performance(
                min_weight=0.1,
                max_weight=3.0,
                smoothing_factor=0.2,
                scorecard_metrics=scorecard_agents,
                decay_half_life_weeks=8.0,
            )
            
            if new_weights:
                # Update weights in registry
                updated_count = 0
                for agent_key, new_weight in new_weights.items():
                    old_weight = self.registry.get_weights().get(agent_key, 1.0)
                    if abs(new_weight - old_weight) > 0.01:  # Only update if significant change
                        self.registry.update_weight(agent_key, new_weight)
                        updated_count += 1
                        logger.info(
                            "Updated agent weight",
                            agent=agent_key,
                            old_weight=round(old_weight, 2),
                            new_weight=round(new_weight, 2),
                        )
                
                if updated_count > 0:
                    # Save updated weights
                    self.registry.save_weights_to_config()
                    logger.info(
                        "Agent weights updated based on performance",
                        updated_count=updated_count,
                        total_agents=len(new_weights),
                    )
            else:
                logger.debug("No performance data available for weight adjustment")
            
        except Exception as e:
            logger.error("Error updating agent weights", error=str(e))

