"""News Sentiment Analyst agent (hybrid sentiment lane)."""

from src.agents.base import BaseAgent
from src.agents.hybrid import HybridAgentMixin
from src.agents.inputs import AgentInputs
from src.agents.prompt_helpers import format_analyst_for_prompt


class NewsSentimentAnalystAgent(BaseAgent, HybridAgentMixin):
    hybrid_lane = "sentiment"
    hybrid_profile = "news_heavy"

    def __init__(self, weight: float = 1.0):
        super().__init__(
            name="News Sentiment Analyst",
            description="News-Based Sentiment Expert",
            investing_style="News flow, analyst revisions, media sentiment",
            weight=weight,
            llm_model="ollama-llama",
            llm_provider="ollama",
        )

    def enrich_inputs(self, inputs: AgentInputs) -> AgentInputs:
        if hasattr(self.data_provider, "get_analyst_recommendations"):
            recs = self.data_provider.get_analyst_recommendations(inputs.ticker)
            inputs.extras["analyst_summary"] = format_analyst_for_prompt(recs or [], max_periods=4)
        return inputs

    def analyze(self, ticker: str, start_date: str, end_date: str, **kwargs):
        return self.run_hybrid_analysis(ticker, start_date, end_date, **kwargs)
