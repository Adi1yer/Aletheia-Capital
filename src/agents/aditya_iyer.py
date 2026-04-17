"""Aditya Iyer investment agent"""

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import HumanMessage
from src.agents.base import BaseAgent, AgentSignal
from src.agents.prompt_helpers import JSON_ONLY_INSTRUCTION, AGENT_JSON_EXAMPLE, with_performance_feedback
from src.llm.utils import call_llm_with_retry
from pydantic import BaseModel, Field
from typing_extensions import Literal
import structlog

logger = structlog.get_logger()


class IyerSignal(BaseModel):
    """Aditya Iyer style signal"""
    signal: Literal["bullish", "bearish", "neutral"]
    confidence: int = Field(ge=0, le=100)
    reasoning: str


class AdityaIyerAgent(BaseAgent):
    """Aditya Iyer - AI Hedge Fund Creator agent"""
    
    def __init__(self, weight: float = 1.0):
        super().__init__(
            name="Aditya Iyer",
            description="AI Hedge Fund Creator",
            investing_style="Focuses on comprehensive multi-factor analysis combining value, growth, technical, and sentiment signals. Emphasizes data-driven decision making and systematic investment approach",
            weight=weight,
            llm_model="ollama-llama",
            llm_provider="ollama",
        )
    
    def analyze(self, ticker: str, start_date: str, end_date: str, **kwargs) -> AgentSignal:
        """Analyze using comprehensive multi-factor analysis"""
        logger.info("Starting Iyer analysis", ticker=ticker)
        
        data_provider = self.data_provider
        
        metrics = data_provider.get_financial_metrics(ticker, end_date, limit=1)
        if not metrics:
            logger.warning("No financial metrics found", ticker=ticker)
            return AgentSignal(
                signal="neutral",
                confidence=0,
                reasoning="Insufficient data for analysis"
            )
        
        line_items = data_provider.get_line_items(
            ticker,
            ["revenue", "net_income", "free_cash_flow", "ebitda", "total_debt", "shareholders_equity", "roe"],
            end_date,
            limit=1
        )
        
        market_cap = data_provider.get_market_cap(ticker, end_date)
        prices = data_provider.get_prices(ticker, start_date, end_date)
        current_price = prices[-1].close if prices else None
        price_change = ((current_price - prices[0].close) / prices[0].close * 100) if prices and len(prices) > 0 else 0
        
        analysis_data = {
            "ticker": ticker,
            "metrics": metrics[0].model_dump() if metrics else {},
            "line_items": line_items[0].model_dump() if line_items else {},
            "market_cap": market_cap,
            "current_price": current_price,
            "price_change_pct": price_change,
        }
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", with_performance_feedback(f"""You are Aditya Iyer, creator of an AI-powered hedge fund system. Analyze this stock using comprehensive multi-factor analysis:

Key Criteria:
1. Value metrics (P/E, P/B, EV/EBITDA relative to peers)
2. Growth metrics (revenue growth, earnings growth, FCF growth)
3. Quality metrics (ROE, debt-to-equity, profit margins)
4. Technical indicators (price momentum, trends)
5. Sentiment and market positioning
6. Risk-adjusted returns and downside protection
7. Systematic, data-driven investment approach

Investment Style: {self.investing_style}

Analyze the provided financial data and provide your investment signal.

""" + JSON_ONLY_INSTRUCTION, self)),
            ("human", """Ticker: {ticker}

Financial Metrics:
{metrics}

Financial Line Items:
{line_items}

Market Cap: {market_cap}
Current Price: {current_price}
Price Change %: {price_change_pct}

Provide your analysis as JSON: signal, confidence (0-100), reasoning. Output only one JSON object. Example: """ + AGENT_JSON_EXAMPLE + """
""")
        ])
        
        formatted_prompt = prompt.format(
            ticker=ticker,
            metrics=str(analysis_data["metrics"]),
            line_items=str(analysis_data["line_items"]),
            market_cap=market_cap or "Unknown",
            current_price=current_price or "Unknown",
            price_change_pct=f"{price_change:.2f}%"
        )
        
        try:
            llm = self.get_llm()
            response = call_llm_with_retry(
                llm=llm,
                prompt=HumanMessage(content=formatted_prompt),
                output_model=IyerSignal,
            )

            return self.safe_signal_from_response(response)
        except Exception as e:
            logger.error("LLM call failed", ticker=ticker, error=str(e))
            return AgentSignal(
                signal="neutral",
                confidence=0,
                reasoning=f"Analysis error: {str(e)}",
            )

