"""Stanley Druckenmiller investment agent"""

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


class DruckenmillerSignal(BaseModel):
    """Stanley Druckenmiller style signal"""
    signal: Literal["bullish", "bearish", "neutral"]
    confidence: int = Field(ge=0, le=100)
    reasoning: str


class StanleyDruckenmillerAgent(BaseAgent):
    """Stanley Druckenmiller - Macro Trader agent"""
    
    def __init__(self, weight: float = 1.0):
        super().__init__(
            name="Stanley Druckenmiller",
            description="Macro Trader",
            investing_style="Focuses on macro trends, momentum investing, and identifying major market themes. Emphasizes risk management, position sizing, and cutting losses quickly while letting winners run",
            weight=weight,
            llm_model="ollama-llama",
            llm_provider="ollama",
        )
    
    def analyze(self, ticker: str, start_date: str, end_date: str, **kwargs) -> AgentSignal:
        """Analyze using Druckenmiller's macro trading principles"""
        logger.info("Starting Druckenmiller analysis", ticker=ticker)
        
        data_provider = self.data_provider
        
        metrics = data_provider.get_financial_metrics(ticker, end_date, limit=1)
        if not metrics:
            logger.warning("No financial metrics found", ticker=ticker)
            return AgentSignal(
                signal="neutral",
                confidence=0,
                reasoning="Insufficient data for analysis"
            )
        
        # Get price data for momentum analysis
        prices = data_provider.get_prices(ticker, start_date, end_date)
        if not prices:
            logger.warning("No price data found", ticker=ticker)
            return AgentSignal(
                signal="neutral",
                confidence=0,
                reasoning="Insufficient price data for analysis"
            )
        
        line_items = data_provider.get_line_items(
            ticker,
            ["revenue", "net_income", "revenue_growth", "earnings_growth"],
            end_date,
            limit=1
        )
        
        market_cap = data_provider.get_market_cap(ticker, end_date)
        insider_trades = data_provider.get_insider_trades(ticker, end_date, start_date, limit=20)
        insider_summary = format_insider_for_prompt(insider_trades, max_entries=15)
        
        # Macro context: SPY and QQQ returns over same period
        spy_prices = data_provider.get_prices("SPY", start_date, end_date)
        qqq_prices = data_provider.get_prices("QQQ", start_date, end_date)
        spy_return = (spy_prices[-1].close - spy_prices[0].close) / spy_prices[0].close * 100 if spy_prices and len(spy_prices) >= 2 else None
        qqq_return = (qqq_prices[-1].close - qqq_prices[0].close) / qqq_prices[0].close * 100 if qqq_prices and len(qqq_prices) >= 2 else None
        macro_context = f"SPY return (period): {spy_return:.2f}%" if spy_return is not None else "SPY: N/A"
        if qqq_return is not None:
            macro_context += f", QQQ return (period): {qqq_return:.2f}%"
        
        # Calculate momentum metrics
        current_price = prices[-1].close
        price_change = ((current_price - prices[0].close) / prices[0].close * 100) if len(prices) > 0 else 0
        
        analysis_data = {
            "ticker": ticker,
            "metrics": metrics[0].model_dump() if metrics else {},
            "line_items": line_items[0].model_dump() if line_items else {},
            "market_cap": market_cap,
            "current_price": current_price,
            "price_change_pct": price_change,
            "macro_context": macro_context,
            "insider_summary": insider_summary,
        }
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", with_performance_feedback(f"""You are Stanley Druckenmiller, a legendary macro trader. Analyze this stock using Druckenmiller's investment principles:

Key Criteria:
1. Macro trends and major market themes
2. Momentum and price action analysis
3. Strong earnings and revenue growth
4. Risk management and position sizing
5. Cutting losses quickly, letting winners run
6. Identifying inflection points and catalysts
7. Focus on best ideas with high conviction

Investment Style: {self.investing_style}

Analyze the provided financial data and provide your investment signal.

""" + JSON_ONLY_INSTRUCTION, self, ticker)),
            ("human", """Ticker: {ticker}

Market context (macro): {macro_context}

Financial Metrics:
{metrics}

Financial Line Items:
{line_items}

Market Cap: {market_cap}
Current Price: {current_price}
Price Change %: {price_change_pct}

{insider_summary}

Provide your analysis as JSON: signal, confidence (0-100), reasoning. Output only one JSON object. Example: """ + AGENT_JSON_EXAMPLE + """
""")
        ])
        
        formatted_prompt = prompt.format(
            ticker=ticker,
            macro_context=macro_context,
            metrics=str(analysis_data["metrics"]),
            line_items=str(analysis_data["line_items"]),
            market_cap=market_cap or "Unknown",
            current_price=current_price or "Unknown",
            price_change_pct=f"{price_change:.2f}%",
            insider_summary=insider_summary,
        )
        
        try:
            llm = self.get_llm()
            response = call_llm_with_retry(
                llm=llm,
                prompt=HumanMessage(content=formatted_prompt),
                output_model=DruckenmillerSignal,
            )

            return self.safe_signal_from_response(response)
        except Exception as e:
            logger.error("LLM call failed", ticker=ticker, error=str(e))
            return AgentSignal(
                signal="neutral",
                confidence=0,
                reasoning=f"Analysis error: {str(e)}",
            )

