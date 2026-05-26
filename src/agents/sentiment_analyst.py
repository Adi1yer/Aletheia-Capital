"""Sentiment Analyst agent (hybrid sentiment lane)."""

from src.agents.base import BaseAgent
from src.agents.hybrid import HybridAgentMixin


class SentimentAnalystAgent(BaseAgent, HybridAgentMixin):
    hybrid_lane = "sentiment"
    hybrid_profile = "price_sentiment"

    def __init__(self, weight: float = 1.0):
        super().__init__(
            name="Sentiment Analyst",
            description="Market Sentiment Expert",
            investing_style="Price/volume sentiment and market psychology",
            weight=weight,
            llm_model="ollama-llama",
            llm_provider="ollama",
        )

    def analyze(self, ticker: str, start_date: str, end_date: str, **kwargs):
        return self.run_hybrid_analysis(ticker, start_date, end_date, **kwargs)
