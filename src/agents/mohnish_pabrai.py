"""Mohnish Pabrai investment agent"""

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import HumanMessage
from src.agents.base import BaseAgent, AgentSignal
from src.agents.prompt_helpers import JSON_ONLY_INSTRUCTION, AGENT_JSON_EXAMPLE, with_performance_feedback
from src.llm.utils import call_llm_with_retry
from pydantic import BaseModel, Field
from typing_extensions import Literal
import structlog

logger = structlog.get_logger()


class PabraiSignal(BaseModel):
    """Mohnish Pabrai style signal"""
    signal: Literal["bullish", "bearish", "neutral"]
    confidence: int = Field(ge=0, le=100)
    reasoning: str


class MohnishPabraiAgent(BaseAgent):
    """Mohnish Pabrai - Cloning Great Investors agent"""
    
    def __init__(self, weight: float = 1.0):
        super().__init__(
            name="Mohnish Pabrai",
            description="Cloning Great Investors",
            investing_style="Focuses on concentrated value investing, cloning successful investors, and finding undervalued businesses with wide moats. Emphasizes low risk, high uncertainty investments",
            weight=weight,
            llm_model="ollama-llama",
            llm_provider="ollama",
        )
    
    def analyze(self, ticker: str, start_date: str, end_date: str, **kwargs) -> AgentSignal:
        """Analyze using Pabrai's value investing principles"""
        logger.info("Starting Pabrai analysis", ticker=ticker)
        
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
            ["revenue", "net_income", "free_cash_flow", "total_debt", "shareholders_equity", "roe"],
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
            ("system", with_performance_feedback(f"""You are Mohnish Pabrai, a value investor who clones great investors. Analyze this stock using Pabrai's investment principles:

Key Criteria:
1. Wide economic moats and competitive advantages
2. Undervalued relative to intrinsic value
3. Low risk, high uncertainty (asymmetric risk/reward)
4. Concentrated positions in best ideas
5. Strong return on equity and capital efficiency
6. Simple, understandable businesses
7. Long-term value creation potential

Investment Style: {self.investing_style}

Analyze the provided financial data and provide your investment signal.

""" + JSON_ONLY_INSTRUCTION, self, ticker)),
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
                output_model=PabraiSignal,
            )

            return self.safe_signal_from_response(response)
        except Exception as e:
            logger.error("LLM call failed", ticker=ticker, error=str(e))
            return AgentSignal(
                signal="neutral",
                confidence=0,
                reasoning=f"Analysis error: {str(e)}",
            )

