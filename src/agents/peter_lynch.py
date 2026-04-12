"""Peter Lynch investment agent"""

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import HumanMessage
from src.agents.base import BaseAgent, AgentSignal
from src.agents.prompt_helpers import JSON_ONLY_INSTRUCTION, AGENT_JSON_EXAMPLE
from src.llm.utils import call_llm_with_retry
from pydantic import BaseModel, Field
from typing_extensions import Literal
import structlog

logger = structlog.get_logger()


class LynchSignal(BaseModel):
    """Peter Lynch style signal"""
    signal: Literal["bullish", "bearish", "neutral"]
    confidence: int = Field(ge=0, le=100)
    reasoning: str


class PeterLynchAgent(BaseAgent):
    """Peter Lynch - Growth at a Reasonable Price (GARP) agent"""
    
    def __init__(self, weight: float = 1.0):
        super().__init__(
            name="Peter Lynch",
            description="Growth at a Reasonable Price (GARP)",
            investing_style="Focuses on growth at a reasonable price (GARP), investing in what you know, and finding undervalued growth stocks. Emphasizes PEG ratio and understanding the business",
            weight=weight,
            llm_model="ollama-llama",
            llm_provider="ollama",
        )
    
    def analyze(self, ticker: str, start_date: str, end_date: str, **kwargs) -> AgentSignal:
        """Analyze using Lynch's GARP principles"""
        logger.info("Starting Lynch analysis", ticker=ticker)
        
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
            ["revenue", "net_income", "earnings_growth", "revenue_growth", "free_cash_flow"],
            end_date,
            limit=1
        )
        
        market_cap = data_provider.get_market_cap(ticker, end_date)
        
        analysis_data = {
            "ticker": ticker,
            "metrics": metrics[0].model_dump() if metrics else {},
            "line_items": line_items[0].model_dump() if line_items else {},
            "market_cap": market_cap,
        }
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", f"""You are Peter Lynch, a legendary growth investor. Analyze this stock using Lynch's investment principles:

Key Criteria:
1. Growth at a reasonable price (GARP) - PEG ratio < 1.0 ideal
2. Understandable business model
3. Consistent earnings growth (15-25% annually)
4. Strong revenue growth
5. Reasonable P/E ratio relative to growth rate
6. Low debt and strong balance sheet
7. Invest in what you know - simple, understandable businesses

Investment Style: {self.investing_style}

Analyze the provided financial data and provide your investment signal.

""" + JSON_ONLY_INSTRUCTION),
            ("human", """Ticker: {ticker}

Financial Metrics:
{metrics}

Financial Line Items:
{line_items}

Market Cap: {market_cap}

Provide your analysis as JSON: signal, confidence (0-100), reasoning. Output only one JSON object. Example: """ + AGENT_JSON_EXAMPLE + """
""")
        ])
        
        formatted_prompt = prompt.format(
            ticker=ticker,
            metrics=str(analysis_data["metrics"]),
            line_items=str(analysis_data["line_items"]),
            market_cap=market_cap or "Unknown"
        )
        
        try:
            llm = self.get_llm()
            response = call_llm_with_retry(
                llm=llm,
                prompt=HumanMessage(content=formatted_prompt),
                output_model=LynchSignal,
            )

            return self.safe_signal_from_response(response)
        except Exception as e:
            logger.error("LLM call failed", ticker=ticker, error=str(e))
            return AgentSignal(
                signal="neutral",
                confidence=0,
                reasoning=f"Analysis error: {str(e)}",
            )

