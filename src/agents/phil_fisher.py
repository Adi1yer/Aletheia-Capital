"""Phil Fisher investment agent"""

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import HumanMessage
from src.agents.base import BaseAgent, AgentSignal
from src.agents.prompt_helpers import JSON_ONLY_INSTRUCTION, AGENT_JSON_EXAMPLE
from src.llm.utils import call_llm_with_retry
from pydantic import BaseModel, Field
from typing_extensions import Literal
import structlog

logger = structlog.get_logger()


class FisherSignal(BaseModel):
    """Phil Fisher style signal"""
    signal: Literal["bullish", "bearish", "neutral"]
    confidence: int = Field(ge=0, le=100)
    reasoning: str


class PhilFisherAgent(BaseAgent):
    """Phil Fisher - Growth Investing Pioneer agent"""
    
    def __init__(self, weight: float = 1.0):
        super().__init__(
            name="Phil Fisher",
            description="Growth Investing Pioneer",
            investing_style="Focuses on high-quality growth companies with superior management, innovative products, and long-term competitive advantages. Emphasizes scuttlebutt research and 15-point checklist",
            weight=weight,
            llm_model="ollama-llama",
            llm_provider="ollama",
        )
    
    def analyze(self, ticker: str, start_date: str, end_date: str, **kwargs) -> AgentSignal:
        """Analyze using Fisher's growth investing principles"""
        logger.info("Starting Fisher analysis", ticker=ticker)
        
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
            ["revenue", "net_income", "revenue_growth", "earnings_growth", "roe", "free_cash_flow"],
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
            ("system", f"""You are Phil Fisher, a pioneer of growth investing. Analyze this stock using Fisher's investment principles:

Key Criteria:
1. Superior management with integrity and vision
2. High-quality products/services with innovation
3. Strong sales growth potential (15-point checklist)
4. High profit margins and return on equity
5. Effective research and development
6. Strong sales organization and marketing
7. Long-term competitive advantages and moats

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
                output_model=FisherSignal,
            )

            return self.safe_signal_from_response(response)
        except Exception as e:
            logger.error("LLM call failed", ticker=ticker, error=str(e))
            return AgentSignal(
                signal="neutral",
                confidence=0,
                reasoning=f"Analysis error: {str(e)}",
            )

