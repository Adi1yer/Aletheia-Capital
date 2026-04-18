"""Technicals Analyst agent"""

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


class TechnicalsAnalystSignal(BaseModel):
    """Technicals Analyst style signal"""
    signal: Literal["bullish", "bearish", "neutral"]
    confidence: int = Field(ge=0, le=100)
    reasoning: str


class TechnicalsAnalystAgent(BaseAgent):
    """Technicals Analyst - Technical Analysis Expert agent"""
    
    def __init__(self, weight: float = 1.0):
        super().__init__(
            name="Technicals Analyst",
            description="Technical Analysis Expert",
            investing_style="Focuses on technical analysis including chart patterns, indicators, support/resistance levels, and price action. Identifies entry/exit points based on technical signals",
            weight=weight,
            llm_model="ollama-llama",
            llm_provider="ollama",
        )
    
    def analyze(self, ticker: str, start_date: str, end_date: str, **kwargs) -> AgentSignal:
        """Analyze using technical analysis"""
        logger.info("Starting Technicals Analyst analysis", ticker=ticker)
        
        data_provider = self.data_provider
        
        # Get price data for technical analysis
        prices = data_provider.get_prices(ticker, start_date, end_date)
        if not prices:
            logger.warning("No price data found", ticker=ticker)
            return AgentSignal(
                signal="neutral",
                confidence=0,
                reasoning="Insufficient price data for technical analysis"
            )
        
        # Calculate technical indicators
        current_price = prices[-1].close
        high_price = max([p.high for p in prices])
        low_price = min([p.low for p in prices])
        
        # Simple moving averages (20 and 50 day approximations)
        recent_prices = prices[-20:] if len(prices) >= 20 else prices
        sma_20 = sum([p.close for p in recent_prices]) / len(recent_prices) if recent_prices else current_price
        
        longer_prices = prices[-50:] if len(prices) >= 50 else prices
        sma_50 = sum([p.close for p in longer_prices]) / len(longer_prices) if longer_prices else current_price
        
        # Price momentum
        price_change = ((current_price - prices[0].close) / prices[0].close * 100) if len(prices) > 0 else 0
        
        # Volume analysis
        avg_volume = sum([p.volume for p in recent_prices]) / len(recent_prices) if recent_prices else 0
        recent_volume = prices[-1].volume if prices else 0
        volume_ratio = recent_volume / avg_volume if avg_volume > 0 else 1.0
        spy_prices = self.data_provider.get_prices("SPY", start_date, end_date)
        return_vs_spy = compute_return_vs_index(prices, spy_prices)
        return_vs_spy_str = f"{return_vs_spy:+.2f}%" if return_vs_spy is not None else "N/A"
        
        analysis_data = {
            "ticker": ticker,
            "current_price": current_price,
            "high_price": high_price,
            "low_price": low_price,
            "sma_20": sma_20,
            "sma_50": sma_50,
            "price_change_pct": price_change,
            "volume_ratio": volume_ratio,
            "return_vs_spy": return_vs_spy_str,
        }
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", with_performance_feedback(f"""You are a Technicals Analyst, a technical analysis expert. Analyze this stock using technical analysis:

Key Criteria:
1. Price trends and momentum
2. Moving averages (SMA 20, SMA 50) and crossovers
3. Support and resistance levels
4. Volume analysis and confirmation
5. Chart patterns (head and shoulders, triangles, etc.)
6. Relative strength indicators
7. Entry/exit signals based on technical setup

Investment Style: {self.investing_style}

Analyze the provided price data and provide your investment signal based on technical analysis.

""" + JSON_ONLY_INSTRUCTION, self, ticker)),
            ("human", """Ticker: {ticker}

Current Price: {current_price}
High Price (period): {high_price}
Low Price (period): {low_price}
SMA 20: {sma_20}
SMA 50: {sma_50}
Price Change %: {price_change_pct}
Volume Ratio: {volume_ratio}
Return vs SPY (period): {return_vs_spy}

Provide your analysis as JSON: signal, confidence (0-100), reasoning. Output only one JSON object. Example: """ + AGENT_JSON_EXAMPLE + """
""")
        ])
        
        formatted_prompt = prompt.format(
            ticker=ticker,
            current_price=current_price or "Unknown",
            high_price=high_price or "Unknown",
            low_price=low_price or "Unknown",
            sma_20=f"{sma_20:.2f}" if sma_20 else "Unknown",
            sma_50=f"{sma_50:.2f}" if sma_50 else "Unknown",
            price_change_pct=f"{price_change:.2f}%",
            volume_ratio=f"{volume_ratio:.2f}x",
            return_vs_spy=return_vs_spy_str,
        )
        
        try:
            llm = self.get_llm()
            response = call_llm_with_retry(
                llm=llm,
                prompt=HumanMessage(content=formatted_prompt),
                output_model=TechnicalsAnalystSignal,
            )

            return self.safe_signal_from_response(response)
        except Exception as e:
            logger.error("LLM call failed", ticker=ticker, error=str(e))
            return AgentSignal(
                signal="neutral",
                confidence=0,
                reasoning=f"Analysis error: {str(e)}",
            )

