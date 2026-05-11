"""Base class for investment agents"""

from abc import ABC, abstractmethod
from typing import Dict, List, Literal, Optional
from pydantic import BaseModel, Field
import structlog

logger = structlog.get_logger()


class AgentSignal(BaseModel):
    """Standardized agent signal output"""
    signal: Literal["bullish", "bearish", "neutral"]
    confidence: int = Field(ge=0, le=100, description="Confidence score 0-100")
    reasoning: str = Field(description="Reasoning for the signal")


class BaseAgent(ABC):
    """Base class for all investment agents"""
    
    def __init__(
        self,
        name: str,
        description: str,
        investing_style: str,
        weight: float = 1.0,
        llm_model: str = "ollama-llama",
        llm_provider: str = "ollama",
    ):
        """
        Initialize agent
        
        Args:
            name: Agent display name
            description: Short description
            investing_style: Investment philosophy/style
            weight: Initial weight for signal aggregation (default 1.0)
            llm_model: LLM model name to use
            llm_provider: LLM provider name
        """
        self.name = name
        self.description = description
        self.investing_style = investing_style
        self.weight = weight
        self.llm_model = llm_model
        self.llm_provider = llm_provider
        self._data_provider = None
        logger.info("Initialized agent", agent=name, weight=weight)

    @property
    def data_provider(self):
        if self._data_provider is None:
            from src.data.providers.aggregator import get_data_provider

            self._data_provider = get_data_provider()
        return self._data_provider

    @data_provider.setter
    def data_provider(self, value):
        self._data_provider = value
    
    @abstractmethod
    def analyze(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
        **kwargs
    ) -> AgentSignal:
        """
        Analyze a ticker and return a signal
        
        Args:
            ticker: Stock ticker symbol
            start_date: Analysis start date (YYYY-MM-DD)
            end_date: Analysis end date (YYYY-MM-DD)
            **kwargs: Additional context/data
        
        Returns:
            AgentSignal with signal, confidence, and reasoning
        """
        pass
    
    def get_llm(self):
        """Get LLM instance for this agent"""
        from src.llm.models import get_llm_for_agent

        return get_llm_for_agent(self.llm_model, self.llm_provider)

    @staticmethod
    def safe_signal_from_response(response, default_reasoning: str = "Response parse error") -> "AgentSignal":
        """Extract signal, confidence, reasoning from LLM response; tolerate KeyError/AttributeError from malformed keys."""
        try:
            return AgentSignal(
                signal=response.signal,
                confidence=response.confidence,
                reasoning=response.reasoning,
            )
        except (KeyError, AttributeError, TypeError):
            return AgentSignal(signal="neutral", confidence=0, reasoning=default_reasoning)
    
    def analyze_multiple(
        self,
        tickers: List[str],
        start_date: str,
        end_date: str,
        parallel: bool = True,
        max_workers: Optional[int] = None,
        **kwargs
    ) -> Dict[str, AgentSignal]:
        """
        Analyze multiple tickers (with optional parallel processing)
        
        Args:
            tickers: List of ticker symbols
            start_date: Analysis start date
            end_date: Analysis end date
            parallel: If True, process tickers in parallel (default: True)
            max_workers: Maximum number of worker threads (default: None = auto)
            **kwargs: Additional context
        
        Returns:
            Dictionary mapping ticker to AgentSignal
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FutureTimeoutError
        import signal
        
        results = {}
        
        # Use parallel processing for multiple tickers
        if parallel and len(tickers) > 1:
            logger.info(
                "Processing tickers in parallel",
                agent=self.name,
                ticker_count=len(tickers),
                max_workers=max_workers or min(len(tickers), 5)  # Limit to 5 concurrent LLM calls per agent
            )
            
            def analyze_ticker(ticker: str) -> tuple[str, AgentSignal]:
                """Analyze a single ticker with timeout protection"""
                try:
                    signal = self.analyze(ticker, start_date, end_date, **kwargs)
                    # Ensure we can read .signal (guard against malformed LLM response objects)
                    _ = signal.signal
                    logger.info("Agent analysis complete", agent=self.name, ticker=ticker, signal=signal.signal)
                    return ticker, signal
                except Exception as e:
                    logger.error("Agent analysis failed", agent=self.name, ticker=ticker, error=str(e))
                    return ticker, AgentSignal(
                        signal="neutral",
                        confidence=0,
                        reasoning=f"Analysis failed: {str(e)}"
                    )
            
            # Process tickers in parallel with limited concurrency
            # Limit to 5 workers per agent to avoid overwhelming Ollama
            workers = max_workers or min(len(tickers), 5)
            completed = 0
            
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {executor.submit(analyze_ticker, ticker): ticker for ticker in tickers}
                
                for future in as_completed(futures):
                    try:
                        ticker, signal = future.result(timeout=300)  # 5 minute timeout per ticker
                        results[ticker] = signal
                        completed += 1
                        if len(tickers) > 10:  # Only log progress for larger batches
                            logger.info(
                                "Progress",
                                agent=self.name,
                                completed=completed,
                                total=len(tickers),
                                pct=round(completed / len(tickers) * 100, 1)
                            )
                    except FutureTimeoutError:
                        ticker = futures[future]
                        logger.warning("Analysis timeout", agent=self.name, ticker=ticker)
                        results[ticker] = AgentSignal(
                            signal="neutral",
                            confidence=0,
                            reasoning="Analysis timed out after 5 minutes"
                        )
                    except Exception as e:
                        ticker = futures[future]
                        logger.error("Unexpected error", agent=self.name, ticker=ticker, error=str(e))
                        results[ticker] = AgentSignal(
                            signal="neutral",
                            confidence=0,
                            reasoning=f"Unexpected error: {str(e)}"
                        )
        else:
            # Sequential processing for single ticker or when parallel is disabled
            for ticker in tickers:
                try:
                    signal = self.analyze(ticker, start_date, end_date, **kwargs)
                    _ = signal.signal  # validate before using
                    results[ticker] = signal
                    logger.info("Agent analysis complete", agent=self.name, ticker=ticker, signal=signal.signal)
                except Exception as e:
                    logger.error("Agent analysis failed", agent=self.name, ticker=ticker, error=str(e))
                    results[ticker] = AgentSignal(
                        signal="neutral",
                        confidence=0,
                        reasoning=f"Analysis failed: {str(e)}"
                    )
        
        return results
    
    def update_weight(self, new_weight: float):
        """Update agent weight based on performance"""
        old_weight = self.weight
        self.weight = max(0.0, min(2.0, new_weight))  # Clamp between 0 and 2
        logger.info("Updated agent weight", agent=self.name, old_weight=old_weight, new_weight=self.weight)

