"""Sentiment Analyst agent"""

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import HumanMessage
from src.agents.base import BaseAgent, AgentSignal
from src.llm.utils import call_llm_with_retry
from src.agents.prompt_helpers import compute_return_vs_index, JSON_ONLY_INSTRUCTION, AGENT_JSON_EXAMPLE, with_performance_feedback
from src.llm.utils import call_llm_with_retry
from pydantic import BaseModel, Field
from typing_extensions import Literal
import structlog

logger = structlog.get_logger()


class SentimentAnalystSignal(BaseModel):
    """Sentiment Analyst style signal"""
    signal: Literal["bullish", "bearish", "neutral"]
    confidence: int = Field(ge=0, le=100)
    reasoning: str


class SentimentAnalystAgent(BaseAgent):
    """Sentiment Analyst - Market Sentiment Expert agent"""
    
    def __init__(self, weight: float = 1.0):
        super().__init__(
            name="Sentiment Analyst",
            description="Market Sentiment Expert",
            investing_style="Focuses on market sentiment analysis including investor sentiment, analyst sentiment, and market psychology. Identifies sentiment-driven opportunities and contrarian signals",
            weight=weight,
            llm_model="ollama-llama",
            llm_provider="ollama",
        )
    
    def analyze(self, ticker: str, start_date: str, end_date: str, **kwargs) -> AgentSignal:
        """Analyze using sentiment analysis"""
        logger.info("Starting Sentiment Analyst analysis", ticker=ticker)
        
        data_provider = self.data_provider
        
        metrics = data_provider.get_financial_metrics(ticker, end_date, limit=1)
        if not metrics:
            logger.warning("No financial metrics found", ticker=ticker)
            return AgentSignal(
                signal="neutral",
                confidence=0,
                reasoning="Insufficient data for analysis"
            )
        
        # Get price data for sentiment indicators
        prices = data_provider.get_prices(ticker, start_date, end_date)
        if not prices:
            logger.warning("No price data found", ticker=ticker)
            return AgentSignal(
                signal="neutral",
                confidence=0,
                reasoning="Insufficient price data for analysis"
            )
        
        # Calculate price momentum and volatility as sentiment proxies
        current_price = prices[-1].close
        price_change = ((current_price - prices[0].close) / prices[0].close * 100) if len(prices) > 0 else 0
        
        # Get recent price volatility and volume (prompt asks for "price momentum, volume")
        recent_prices = prices[-20:] if len(prices) >= 20 else prices
        price_volatility = 0
        if len(recent_prices) > 1:
            returns = [(recent_prices[i].close - recent_prices[i-1].close) / recent_prices[i-1].close for i in range(1, len(recent_prices))]
            price_volatility = (sum([r**2 for r in returns]) / len(returns))**0.5 * 100 if returns else 0
        avg_volume = sum([p.volume for p in recent_prices]) / len(recent_prices) if recent_prices else 0
        recent_volume = prices[-1].volume if prices else 0
        volume_ratio = recent_volume / avg_volume if avg_volume > 0 else 1.0

        market_cap = data_provider.get_market_cap(ticker, end_date)
        # Relative strength vs market (SPY)
        spy_prices = data_provider.get_prices("SPY", start_date, end_date)
        return_vs_spy = compute_return_vs_index(prices, spy_prices)
        return_vs_spy_str = f"{return_vs_spy:+.2f}%" if return_vs_spy is not None else "N/A"

        analysis_data = {
            "ticker": ticker,
            "metrics": metrics[0].model_dump() if metrics else {},
            "market_cap": market_cap,
            "current_price": current_price,
            "price_change_pct": price_change,
            "volatility_pct": price_volatility,
            "avg_volume": avg_volume,
            "recent_volume": recent_volume,
            "volume_ratio": volume_ratio,
            "return_vs_spy": return_vs_spy_str,
        }
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", with_performance_feedback(f"""You are a Sentiment Analyst, a market sentiment expert. Analyze this stock using sentiment analysis:

Key Criteria:
1. Investor sentiment indicators (price momentum, volume)
2. Market psychology and behavioral factors
3. Contrarian sentiment signals (extreme pessimism/optimism)
4. Price action and volatility patterns
5. Relative strength vs market
6. Sentiment-driven opportunities
7. Risk sentiment and fear/greed indicators

Investment Style: {self.investing_style}

Analyze the provided data and provide your investment signal based on sentiment.

""" + JSON_ONLY_INSTRUCTION, self)),
            ("human", """Ticker: {ticker}

Financial Metrics:
{metrics}

Market Cap: {market_cap}
Current Price: {current_price}
Price Change %: {price_change_pct}
Volatility %: {volatility_pct}
Avg Volume (20d): {avg_volume}
Recent Volume: {recent_volume}
Volume Ratio (recent/avg): {volume_ratio}
Return vs SPY (period): {return_vs_spy}

Provide your analysis as JSON: signal, confidence (0-100), reasoning. Output only one JSON object. Example: """ + AGENT_JSON_EXAMPLE + """
""")
        ])
        
        formatted_prompt = prompt.format(
            ticker=ticker,
            metrics=str(analysis_data["metrics"]),
            market_cap=market_cap or "Unknown",
            current_price=current_price or "Unknown",
            price_change_pct=f"{price_change:.2f}%",
            volatility_pct=f"{price_volatility:.2f}%",
            avg_volume=f"{avg_volume:,.0f}" if avg_volume else "N/A",
            recent_volume=f"{recent_volume:,.0f}" if recent_volume else "N/A",
            volume_ratio=f"{volume_ratio:.2f}x",
            return_vs_spy=return_vs_spy_str,
        )
        
        try:
            llm = self.get_llm()
            response = call_llm_with_retry(
                llm=llm,
                prompt=HumanMessage(content=formatted_prompt),
                output_model=SentimentAnalystSignal,
            )

            return self.safe_signal_from_response(response)
        except Exception as e:
            logger.error("LLM call failed", ticker=ticker, error=str(e))
            return AgentSignal(
                signal="neutral",
                confidence=0,
                reasoning=f"Analysis error: {str(e)}",
            )

