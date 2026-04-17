"""News Sentiment Analyst agent"""

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import HumanMessage
from src.agents.base import BaseAgent, AgentSignal
from src.llm.utils import call_llm_with_retry
from src.agents.prompt_helpers import format_analyst_for_prompt, JSON_ONLY_INSTRUCTION, AGENT_JSON_EXAMPLE, with_performance_feedback
from src.llm.utils import call_llm_with_retry
from pydantic import BaseModel, Field
from typing_extensions import Literal
import structlog

logger = structlog.get_logger()


class NewsSentimentAnalystSignal(BaseModel):
    """News Sentiment Analyst style signal"""
    signal: Literal["bullish", "bearish", "neutral"]
    confidence: int = Field(ge=0, le=100)
    reasoning: str


class NewsSentimentAnalystAgent(BaseAgent):
    """News Sentiment Analyst - News-Based Sentiment Expert agent"""
    
    def __init__(self, weight: float = 1.0):
        super().__init__(
            name="News Sentiment Analyst",
            description="News-Based Sentiment Expert",
            investing_style="Focuses on news sentiment analysis including company news, analyst reports, and media coverage. Identifies sentiment-driven opportunities based on news flow and market perception",
            weight=weight,
            llm_model="ollama-llama",
            llm_provider="ollama",
        )
    
    def analyze(self, ticker: str, start_date: str, end_date: str, **kwargs) -> AgentSignal:
        """Analyze using news sentiment analysis"""
        logger.info("Starting News Sentiment Analyst analysis", ticker=ticker)
        
        data_provider = self.data_provider
        
        metrics = data_provider.get_financial_metrics(ticker, end_date, limit=1)
        if not metrics:
            logger.warning("No financial metrics found", ticker=ticker)
            return AgentSignal(
                signal="neutral",
                confidence=0,
                reasoning="Insufficient data for analysis"
            )
        
        # Get company news if available
        news = data_provider.get_company_news(ticker, end_date, start_date, limit=10)
        
        # Get price data for news impact analysis
        prices = data_provider.get_prices(ticker, start_date, end_date)
        current_price = prices[-1].close if prices else None
        price_change = ((current_price - prices[0].close) / prices[0].close * 100) if prices and len(prices) > 0 else 0
        
        market_cap = data_provider.get_market_cap(ticker, end_date)
        
        # Prepare news summary
        news_summary = ""
        if news:
            news_summary = "\n".join([f"- {n.title} ({n.date.strftime('%Y-%m-%d')})" for n in news[:5]])
        else:
            news_summary = "No recent news available"
        
        # Analyst recommendations (Finnhub when FINNHUB_API_KEY set)
        analyst_recs = data_provider.get_analyst_recommendations(ticker) if hasattr(data_provider, "get_analyst_recommendations") else []
        analyst_summary = format_analyst_for_prompt(analyst_recs, max_periods=4)
        
        analysis_data = {
            "ticker": ticker,
            "metrics": metrics[0].model_dump() if metrics else {},
            "market_cap": market_cap,
            "current_price": current_price,
            "price_change_pct": price_change,
            "news_summary": news_summary,
            "analyst_summary": analyst_summary,
        }
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", with_performance_feedback(f"""You are a News Sentiment Analyst, a news-based sentiment expert. Analyze this stock using news sentiment analysis:

Key Criteria:
1. Company news sentiment (positive/negative/neutral)
2. Analyst coverage and recommendations
3. Media coverage and public perception
4. News impact on stock price
5. Sentiment trends and momentum
6. Contrarian opportunities (negative news on good companies)
7. News-driven catalysts and events

Investment Style: {self.investing_style}

Analyze the provided data and news, and provide your investment signal based on news sentiment.

""" + JSON_ONLY_INSTRUCTION, self)),
            ("human", """Ticker: {ticker}

Financial Metrics:
{metrics}

Market Cap: {market_cap}
Current Price: {current_price}
Price Change %: {price_change_pct}

Recent News:
{news_summary}

{analyst_summary}

Provide your analysis as JSON: signal, confidence (0-100), reasoning. Output only one JSON object. Example: """ + AGENT_JSON_EXAMPLE + """
""")
        ])
        
        formatted_prompt = prompt.format(
            ticker=ticker,
            metrics=str(analysis_data["metrics"]),
            market_cap=market_cap or "Unknown",
            current_price=current_price or "Unknown",
            price_change_pct=f"{price_change:.2f}%",
            news_summary=news_summary,
            analyst_summary=analyst_summary,
        )
        
        try:
            llm = self.get_llm()
            response = call_llm_with_retry(
                llm=llm,
                prompt=HumanMessage(content=formatted_prompt),
                output_model=NewsSentimentAnalystSignal,
            )

            return self.safe_signal_from_response(response)
        except Exception as e:
            logger.error("LLM call failed", ticker=ticker, error=str(e))
            return AgentSignal(
                signal="neutral",
                confidence=0,
                reasoning=f"Analysis error: {str(e)}",
            )

