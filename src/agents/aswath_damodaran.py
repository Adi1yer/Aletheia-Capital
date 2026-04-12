"""Aswath Damodaran investment agent"""

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import HumanMessage
from src.agents.base import BaseAgent, AgentSignal
from src.agents.prompt_helpers import JSON_ONLY_INSTRUCTION, AGENT_JSON_EXAMPLE
from src.llm.utils import call_llm_with_retry
from src.llm.utils import call_llm_with_retry
from pydantic import BaseModel, Field
from typing_extensions import Literal
import structlog

logger = structlog.get_logger()


class DamodaranSignal(BaseModel):
    """Aswath Damodaran style signal"""
    signal: Literal["bullish", "bearish", "neutral"]
    confidence: int = Field(ge=0, le=100)
    reasoning: str


class AswathDamodaranAgent(BaseAgent):
    """Aswath Damodaran - The Dean of Valuation agent"""
    
    def __init__(self, weight: float = 1.0):
        super().__init__(
            name="Aswath Damodaran",
            description="The Dean of Valuation",
            investing_style="Focuses on intrinsic valuation using DCF models, relative valuation, and risk assessment. Emphasizes understanding the story behind numbers and proper risk-adjusted returns",
            weight=weight,
            llm_model="ollama-llama",
            llm_provider="ollama",
        )
    
    def analyze(self, ticker: str, start_date: str, end_date: str, **kwargs) -> AgentSignal:
        """Analyze using Damodaran's valuation principles"""
        logger.info("Starting Damodaran analysis", ticker=ticker)
        
        data_provider = self.data_provider
        
        # Get financial metrics
        metrics = data_provider.get_financial_metrics(ticker, end_date, limit=1)
        if not metrics:
            logger.warning("No financial metrics found", ticker=ticker)
            return AgentSignal(
                signal="neutral",
                confidence=0,
                reasoning="Insufficient data for analysis"
            )
        
        # Get line items for DCF analysis
        line_items = data_provider.get_line_items(
            ticker,
            ["revenue", "net_income", "free_cash_flow", "ebitda", "total_debt", "cash_and_equivalents"],
            end_date,
            limit=1
        )
        
        # Get market cap
        market_cap = data_provider.get_market_cap(ticker, end_date)
        
        # Get price data for valuation context
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
            ("system", f"""You are Aswath Damodaran, the Dean of Valuation. Analyze this stock using rigorous valuation principles:

Key Criteria:
1. Intrinsic value estimation using DCF methodology
2. Relative valuation (P/E, P/B, EV/EBITDA multiples)
3. Risk assessment and cost of capital
4. Growth sustainability and quality of earnings
5. Cash flow generation and reinvestment needs
6. Story-driven valuation (narrative + numbers)

Investment Style: {self.investing_style}

Analyze the provided financial data and provide your investment signal based on valuation.

""" + JSON_ONLY_INSTRUCTION),
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
                output_model=DamodaranSignal,
            )

            return self.safe_signal_from_response(response)
        except Exception as e:
            logger.error("LLM call failed", ticker=ticker, error=str(e))
            return AgentSignal(
                signal="neutral",
                confidence=0,
                reasoning=f"Analysis error: {str(e)}",
            )

