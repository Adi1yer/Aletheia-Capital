"""Crypto trading pipeline - runs crypto agents on crypto symbols with crypto broker."""

from typing import List, Dict, Optional, Any
from datetime import datetime
from dateutil.relativedelta import relativedelta
import structlog
import time

from src.agents.registry import get_registry
from src.agents.base import AgentSignal
from src.agents.crypto_analyst import CryptoAnalystAgent
from src.risk.manager import RiskManager
from src.portfolio.manager import PortfolioManager
from src.portfolio.models import Portfolio
from src.data.providers.aggregator import get_data_provider
from src.data.providers.crypto import CRYPTO_IDS

logger = structlog.get_logger()

DEFAULT_CRYPTO_TICKERS = ["BTC", "ETH", "SOL"]


class CryptoTradingPipeline:
    """Pipeline for crypto trading - uses CryptoBroker and CryptoAnalystAgent."""

    def __init__(self):
        self.risk_manager = RiskManager()
        self.portfolio_manager = PortfolioManager()
        self.data_provider = get_data_provider()
        self._crypto_registry = None
        logger.info("Initialized crypto trading pipeline")

    def _get_crypto_registry(self):
        """Get or create registry with only crypto agents."""
        if self._crypto_registry is None:
            from src.agents.registry import AgentRegistry
            reg = AgentRegistry()
            reg.register(CryptoAnalystAgent(weight=1.0))
            self._crypto_registry = reg
        return self._crypto_registry

    def run(
        self,
        tickers: Optional[List[str]] = None,
        execute: bool = False,
        scan_cache: Optional[Any] = None,
        run_config: Optional[Dict[str, Any]] = None,
    ) -> Dict:
        """Run crypto trading cycle."""
        tickers = tickers or DEFAULT_CRYPTO_TICKERS
        tickers = [t.upper() for t in tickers if t.upper() in CRYPTO_IDS]
        if not tickers:
            tickers = list(DEFAULT_CRYPTO_TICKERS)

        run_config = run_config or {}
        run_config.setdefault("execute", execute)
        run_config.setdefault("crypto", True)
        run_start = time.time()

        logger.info("Starting crypto trading cycle", ticker_count=len(tickers), execute=execute)

        from src.broker.crypto import CryptoBroker
        broker = CryptoBroker(paper=True)
        portfolio = broker.sync_portfolio()

        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - relativedelta(days=90)).strftime("%Y-%m-%d")

        # Refresh crypto data
        for t in tickers:
            try:
                self.data_provider.get_prices(t, start_date, end_date)
            except Exception as e:
                logger.warning("Crypto data refresh failed", ticker=t, error=str(e))

        # Run crypto agent(s)
        registry = self._get_crypto_registry()
        agent_signals: Dict[str, Dict[str, AgentSignal]] = {}
        for agent_key, agent in registry.get_all().items():
            signals = agent.analyze_multiple(tickers, start_date, end_date, parallel=True)
            agent_signals[agent_key] = signals

        risk_analysis = self.risk_manager.calculate_position_limits(
            tickers, portfolio, start_date, end_date
        )
        agent_weights = registry.get_weights()

        decisions = self.portfolio_manager.generate_decisions(
            tickers=tickers,
            agent_signals=agent_signals,
            risk_analysis=risk_analysis,
            portfolio=portfolio,
            agent_weights=agent_weights,
        )

        execution_results = None
        if execute:
            current_prices = {t: risk_analysis[t]["current_price"] for t in risk_analysis}
            execution_results = broker.execute_decisions(decisions, current_prices)
            logger.info("Crypto trades executed", results=execution_results)
        else:
            logger.info("Crypto dry run - trades not executed")

        results = {
            "timestamp": datetime.now().isoformat(),
            "tickers": tickers,
            "portfolio": portfolio.model_dump(),
            "agent_signals": {
                k: {t: s.model_dump() for t, s in v.items()}
                for k, v in agent_signals.items()
            },
            "risk_analysis": risk_analysis,
            "decisions": {t: d.model_dump() for t, d in decisions.items()},
            "execution_results": execution_results,
        }

        # Do not cache crypto runs; cache is for weekly stock universe runs only.

        logger.info("Crypto trading cycle complete", decision_count=len(decisions))
        return results
