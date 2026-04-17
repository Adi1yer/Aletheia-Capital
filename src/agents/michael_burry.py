"""Michael Burry investment agent"""

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import HumanMessage
from src.agents.base import BaseAgent, AgentSignal
from src.llm.utils import call_llm_with_retry
from src.agents.prompt_helpers import format_insider_for_prompt, JSON_ONLY_INSTRUCTION, AGENT_JSON_EXAMPLE, with_performance_feedback
from src.llm.utils import call_llm_with_retry
from pydantic import BaseModel, Field
from typing_extensions import Literal
import structlog

logger = structlog.get_logger()


class BurrySignal(BaseModel):
    """Michael Burry style signal"""
    signal: Literal["bullish", "bearish", "neutral"]
    confidence: int = Field(ge=0, le=100)
    reasoning: str


class MichaelBurryAgent(BaseAgent):
    """Michael Burry - Contrarian Deep Value Investor agent"""
    
    def __init__(self, weight: float = 1.0):
        super().__init__(
            name="Michael Burry",
            description="Contrarian Deep Value Investor",
            investing_style="Focuses on deep value opportunities, contrarian positions, and identifying market inefficiencies. Seeks undervalued assets with strong fundamentals that the market has overlooked or misunderstood",
            weight=weight,
            llm_model="ollama-llama",
            llm_provider="ollama",
        )
    
    def analyze(self, ticker: str, start_date: str, end_date: str, **kwargs) -> AgentSignal:
        """Analyze using Burry's contrarian value principles"""
        logger.info("Starting Burry analysis", ticker=ticker)
        
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
            ["total_debt", "cash_and_equivalents", "shareholders_equity", "net_income", "free_cash_flow", "total_assets"],
            end_date,
            limit=1
        )
        
        market_cap = data_provider.get_market_cap(ticker, end_date)
        prices = data_provider.get_prices(ticker, start_date, end_date)
        current_price = prices[-1].close if prices else None
        insider_trades = data_provider.get_insider_trades(ticker, end_date, start_date, limit=20)
        insider_summary = format_insider_for_prompt(insider_trades, max_entries=15)
        
        analysis_data = {
            "ticker": ticker,
            "metrics": metrics[0].model_dump() if metrics else {},
            "line_items": line_items[0].model_dump() if line_items else {},
            "market_cap": market_cap,
            "current_price": current_price,
            "insider_summary": insider_summary,
        }
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", with_performance_feedback(f"""You are Michael Burry, a contrarian deep value investor. Analyze this stock using Burry's investment principles:

Key Criteria:
1. Deep value - stock trading significantly below intrinsic value
2. Strong balance sheet with low debt
3. Market inefficiency or mispricing opportunity
4. Contrarian position - going against market consensus
5. Fundamental analysis over market sentiment
6. Focus on asset value and liquidation value
7. Patience for value realization

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

{insider_summary}

Provide your analysis as JSON: signal, confidence (0-100), reasoning. Output only one JSON object. Example: """ + AGENT_JSON_EXAMPLE + """
""")
        ])
        
        formatted_prompt = prompt.format(
            ticker=ticker,
            metrics=str(analysis_data["metrics"]),
            line_items=str(analysis_data["line_items"]),
            market_cap=market_cap or "Unknown",
            current_price=current_price or "Unknown",
            insider_summary=insider_summary,
        )
        
        try:
            llm = self.get_llm()
            response = call_llm_with_retry(
                llm=llm,
                prompt=HumanMessage(content=formatted_prompt),
                output_model=BurrySignal,
            )

            return self.safe_signal_from_response(response)
        except Exception as e:
            logger.error("LLM call failed", ticker=ticker, error=str(e))
            return AgentSignal(
                signal="neutral",
                confidence=0,
                reasoning=f"Analysis error: {str(e)}",
            )

