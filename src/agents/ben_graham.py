"""Ben Graham investment agent"""

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import HumanMessage
from src.agents.base import BaseAgent, AgentSignal
from src.agents.prompt_helpers import format_insider_for_prompt, JSON_ONLY_INSTRUCTION, AGENT_JSON_EXAMPLE, with_performance_feedback
from src.llm.utils import call_llm_with_retry
from pydantic import BaseModel, Field
from typing_extensions import Literal
import structlog

logger = structlog.get_logger()


class GrahamSignal(BaseModel):
    """Ben Graham style signal"""
    signal: Literal["bullish", "bearish", "neutral"]
    confidence: int = Field(ge=0, le=100)
    reasoning: str


class BenGrahamAgent(BaseAgent):
    """Ben Graham - The Father of Value Investing agent"""
    
    def __init__(self, weight: float = 1.0):
        super().__init__(
            name="Ben Graham",
            description="The Father of Value Investing",
            investing_style="Seeks undervalued stocks with strong balance sheets, low debt, and significant margin of safety. Focuses on intrinsic value, book value, and defensive investing principles",
            weight=weight,
            llm_model="ollama-llama",
            llm_provider="ollama",
        )
    
    def analyze(self, ticker: str, start_date: str, end_date: str, **kwargs) -> AgentSignal:
        """Analyze using Graham's value investing principles"""
        logger.info("Starting Graham analysis", ticker=ticker)
        
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
            ["total_debt", "cash_and_equivalents", "shareholders_equity", "net_income", "total_assets", "dividends_and_other_cash_distributions"],
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
            ("system", with_performance_feedback(f"""You are Ben Graham, the Father of Value Investing. Analyze this stock using Graham's principles:

Key Criteria:
1. Margin of safety - stock trading below intrinsic value
2. Strong balance sheet with low debt-to-equity
3. Consistent earnings and dividend history
4. Price-to-book ratio below 1.5 (ideally)
5. Current ratio > 2.0 (liquidity)
6. Earnings stability and predictability
7. Defensive investing - focus on safety of principal

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

Provide your analysis as JSON with: signal ("bullish"/"bearish"/"neutral"), confidence (0-100), reasoning (brief).
Output only one JSON object, no other text. Example: """ + AGENT_JSON_EXAMPLE + """
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
                output_model=GrahamSignal,
            )

            return self.safe_signal_from_response(response)
        except Exception as e:
            logger.error("LLM call failed", ticker=ticker, error=str(e))
            return AgentSignal(
                signal="neutral",
                confidence=0,
                reasoning=f"Analysis error: {str(e)}",
            )

