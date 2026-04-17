"""Valuation Analyst agent"""

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import HumanMessage
from src.agents.base import BaseAgent, AgentSignal
from src.agents.prompt_helpers import JSON_ONLY_INSTRUCTION, AGENT_JSON_EXAMPLE, with_performance_feedback
from src.llm.utils import call_llm_with_retry
from pydantic import BaseModel, Field
from typing_extensions import Literal
import structlog

logger = structlog.get_logger()


class ValuationAnalystSignal(BaseModel):
    """Valuation Analyst style signal"""
    signal: Literal["bullish", "bearish", "neutral"]
    confidence: int = Field(ge=0, le=100)
    reasoning: str


class ValuationAnalystAgent(BaseAgent):
    """Valuation Analyst - Technical Valuation Expert agent"""
    
    def __init__(self, weight: float = 1.0):
        super().__init__(
            name="Valuation Analyst",
            description="Technical Valuation Expert",
            investing_style="Focuses on comprehensive valuation analysis using multiple methodologies including DCF, relative valuation, sum-of-parts, and asset-based valuation. Provides objective valuation assessment",
            weight=weight,
            llm_model="ollama-llama",
            llm_provider="ollama",
        )
    
    def analyze(self, ticker: str, start_date: str, end_date: str, **kwargs) -> AgentSignal:
        """Analyze using comprehensive valuation methodologies"""
        logger.info("Starting Valuation Analyst analysis", ticker=ticker)
        
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
            ["revenue", "net_income", "free_cash_flow", "ebitda", "total_debt", "cash_and_equivalents", "shareholders_equity"],
            end_date,
            limit=1
        )
        
        market_cap = data_provider.get_market_cap(ticker, end_date)
        prices = data_provider.get_prices(ticker, start_date, end_date)
        current_price = prices[-1].close if prices else None
        
        analysis_data = {
            "ticker": ticker,
            "metrics": metrics[0].model_dump() if metrics else {},
            "line_items": line_items[0].model_dump() if line_items else {},
            "market_cap": market_cap,
            "current_price": current_price,
        }
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", with_performance_feedback(f"""You are a Valuation Analyst, a technical valuation expert. Analyze this stock using comprehensive valuation methodologies:

Key Criteria:
1. Discounted Cash Flow (DCF) valuation
2. Relative valuation multiples (P/E, P/B, EV/EBITDA, P/S)
3. Sum-of-parts valuation (if applicable)
4. Asset-based valuation
5. Fair value estimation vs current market price
6. Valuation sensitivity analysis
7. Risk-adjusted valuation

Investment Style: {self.investing_style}

Analyze the provided financial data and provide your investment signal based on valuation.

""" + JSON_ONLY_INSTRUCTION, self)),
            ("human", """Ticker: {ticker}

Financial Metrics:
{metrics}

Financial Line Items:
{line_items}

Market Cap: {market_cap}
Current Price: {current_price}

Provide your analysis as JSON: signal, confidence (0-100), reasoning. Output only one JSON object. Example: """ + AGENT_JSON_EXAMPLE + """
""")
        ])
        
        formatted_prompt = prompt.format(
            ticker=ticker,
            metrics=str(analysis_data["metrics"]),
            line_items=str(analysis_data["line_items"]),
            market_cap=market_cap or "Unknown",
            current_price=current_price or "Unknown"
        )
        
        try:
            llm = self.get_llm()
            response = call_llm_with_retry(
                llm=llm,
                prompt=HumanMessage(content=formatted_prompt),
                output_model=ValuationAnalystSignal,
            )

            return self.safe_signal_from_response(response)
        except Exception as e:
            logger.error("LLM call failed", ticker=ticker, error=str(e))
            return AgentSignal(
                signal="neutral",
                confidence=0,
                reasoning=f"Analysis error: {str(e)}",
            )

