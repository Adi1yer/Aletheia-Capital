"""Warren Buffett investment agent"""

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import HumanMessage
from src.agents.base import BaseAgent, AgentSignal
from src.agents.prompt_helpers import format_insider_for_prompt, JSON_ONLY_INSTRUCTION, AGENT_JSON_EXAMPLE, with_performance_feedback
from src.llm.utils import call_llm_with_retry
from pydantic import BaseModel, Field
from typing_extensions import Literal
import structlog

logger = structlog.get_logger()


class BuffettSignal(BaseModel):
    """Warren Buffett style signal"""
    signal: Literal["bullish", "bearish", "neutral"]
    confidence: int = Field(ge=0, le=100)
    reasoning: str


class WarrenBuffettAgent(BaseAgent):
    """Warren Buffett - The Oracle of Omaha agent"""
    
    def __init__(self, weight: float = 1.0):
        super().__init__(
            name="Warren Buffett",
            description="The Oracle of Omaha",
            investing_style="Seeks companies with strong fundamentals and competitive advantages through value investing and long-term ownership",
            weight=weight,
            llm_model="ollama-llama",
            llm_provider="ollama",
        )
    
    def analyze(self, ticker: str, start_date: str, end_date: str, **kwargs) -> AgentSignal:
        """Analyze using Buffett's principles"""
        logger.info("Starting Buffett analysis", ticker=ticker)
        
        # Fetch data
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
        
        # Get line items
        line_items = data_provider.get_line_items(
            ticker,
            ["revenue", "net_income", "free_cash_flow", "total_debt", "shareholders_equity"],
            end_date,
            limit=1
        )
        
        # Get market cap
        market_cap = data_provider.get_market_cap(ticker, end_date)
        # Insider activity (management conviction)
        insider_trades = data_provider.get_insider_trades(ticker, end_date, start_date, limit=20)
        insider_summary = format_insider_for_prompt(insider_trades, max_entries=15)
        
        analysis_data = {
            "ticker": ticker,
            "metrics": metrics[0].model_dump() if metrics else {},
            "line_items": line_items[0].model_dump() if line_items else {},
            "market_cap": market_cap,
            "insider_summary": insider_summary,
        }
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", with_performance_feedback(f"""You are Warren Buffett, the Oracle of Omaha. Analyze this stock using Buffett's investment principles:

Key Criteria:
1. Strong competitive moat and sustainable competitive advantages
2. Consistent earnings growth and high return on equity
3. Low debt and strong balance sheet
4. Management quality and shareholder-friendly policies (consider insider buying/selling as a signal)
5. Reasonable valuation relative to intrinsic value
6. Long-term business prospects

Investment Style: {self.investing_style}

Analyze the provided financial data and provide your investment signal.

""" + JSON_ONLY_INSTRUCTION, self)),
            ("human", """Ticker: {ticker}

Financial Metrics:
{metrics}

Financial Line Items:
{line_items}

Market Cap: {market_cap}

{insider_summary}

Provide your analysis as JSON: signal, confidence (0-100), reasoning. Output only one JSON object. Example: """ + AGENT_JSON_EXAMPLE + """
""")
        ])
        
        formatted_prompt = prompt.format(
            ticker=ticker,
            metrics=str(analysis_data["metrics"]),
            line_items=str(analysis_data["line_items"]),
            market_cap=market_cap or "Unknown",
            insider_summary=insider_summary,
        )
        
        # Call LLM
        try:
            llm = self.get_llm()
            response = call_llm_with_retry(
                llm=llm,
                prompt=HumanMessage(content=formatted_prompt),
                output_model=BuffettSignal,
            )

            return self.safe_signal_from_response(response)
        except Exception as e:
            logger.error("LLM call failed", ticker=ticker, error=str(e))
            return AgentSignal(
                signal="neutral",
                confidence=0,
                reasoning=f"Analysis error: {str(e)}",
            )

