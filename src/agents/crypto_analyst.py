"""Crypto Analyst agent - technical and momentum analysis for cryptocurrency."""

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import HumanMessage
from src.agents.base import BaseAgent, AgentSignal
from src.agents.prompt_helpers import JSON_ONLY_INSTRUCTION, AGENT_JSON_EXAMPLE
from src.llm.utils import call_llm_with_retry
from pydantic import BaseModel, Field
from typing_extensions import Literal
import structlog

logger = structlog.get_logger()


class CryptoAnalystSignal(BaseModel):
    """Crypto Analyst style signal"""
    signal: Literal["bullish", "bearish", "neutral"]
    confidence: int = Field(ge=0, le=100)
    reasoning: str


class CryptoAnalystAgent(BaseAgent):
    """Crypto Analyst - Technical and momentum analysis for cryptocurrency."""

    def __init__(self, weight: float = 1.0):
        super().__init__(
            name="Crypto Analyst",
            description="Crypto technical and momentum analyst",
            investing_style="Analyzes crypto price action, momentum, volume, and market structure. 24/7 market requires different risk parameters than equities.",
            weight=weight,
            llm_model="ollama-llama",
            llm_provider="ollama",
        )

    def analyze(self, ticker: str, start_date: str, end_date: str, **kwargs) -> AgentSignal:
        logger.info("Starting Crypto Analyst analysis", ticker=ticker)

        provider = self.data_provider
        prices = provider.get_prices(ticker, start_date, end_date)
        if not prices:
            return AgentSignal(
                signal="neutral",
                confidence=0,
                reasoning="No price data for this crypto symbol.",
            )

        current_price = prices[-1].close
        high_price = max(p.high for p in prices)
        low_price = min(p.low for p in prices)
        price_change = ((current_price - prices[0].close) / prices[0].close * 100) if prices else 0

        recent = prices[-20:] if len(prices) >= 20 else prices
        sma_20 = sum(p.close for p in recent) / len(recent) if recent else current_price
        longer = prices[-50:] if len(prices) >= 50 else prices
        sma_50 = sum(p.close for p in longer) / len(longer) if longer else current_price

        avg_vol = sum(p.volume for p in recent) / len(recent) if recent and any(p.volume for p in recent) else 1
        vol_ratio = (prices[-1].volume / avg_vol) if avg_vol else 1.0

        metrics = {}
        if hasattr(provider, "get_crypto_metrics"):
            metrics = provider.get_crypto_metrics(ticker)

        prompt = ChatPromptTemplate.from_messages([
            ("system", """You are a Crypto Analyst. Analyze this cryptocurrency using technical and momentum metrics.
Crypto trades 24/7 and is more volatile than equities. Consider:
1. Price trend and momentum
2. Moving averages (SMA 20, SMA 50)
3. Volume confirmation
4. Support/resistance from recent high/low
5. Market cap and liquidity if available

""" + JSON_ONLY_INSTRUCTION + """
"""),
            ("human", """Ticker: {ticker}

Price Data:
- Current: ${current_price:.2f}
- Period High: ${high_price:.2f}
- Period Low: ${low_price:.2f}
- Price Change %: {price_change:.2f}%
- SMA 20: ${sma_20:.2f}
- SMA 50: ${sma_50:.2f}
- Volume ratio (recent/avg): {volume_ratio:.2f}
{metrics_str}

Output only one JSON object with signal, confidence, reasoning. Example: """ + AGENT_JSON_EXAMPLE + """
""")
        ])

        metrics_str = "\n".join(f"- {k}: {v}" for k, v in metrics.items()) if metrics else ""
        formatted = prompt.format(
            ticker=ticker,
            current_price=current_price,
            high_price=high_price,
            low_price=low_price,
            price_change=price_change,
            sma_20=sma_20,
            sma_50=sma_50,
            volume_ratio=vol_ratio,
            metrics_str=metrics_str,
        )

        try:
            llm = self.get_llm()
            response = call_llm_with_retry(
                llm=llm,
                prompt=HumanMessage(content=formatted),
                output_model=CryptoAnalystSignal,
            )
            return self.safe_signal_from_response(response)
        except Exception as e:
            logger.error("Crypto Analyst LLM failed", ticker=ticker, error=str(e))
            sig = "bullish" if price_change > 5 else "bearish" if price_change < -5 else "neutral"
            conf = min(70, 40 + abs(int(price_change)))
            return AgentSignal(
                signal=sig,
                confidence=conf,
                reasoning=f"Rule-based: price change {price_change:.1f}%, SMA20 vs SMA50.",
            )
