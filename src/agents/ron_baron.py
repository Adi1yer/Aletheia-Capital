"""Ron Baron investment agent (hybrid growth lane)."""

from src.agents.base import BaseAgent
from src.agents.hybrid import HybridAgentMixin


class RonBaronAgent(BaseAgent, HybridAgentMixin):
    hybrid_lane = "growth"
    hybrid_profile = "growth"

    def __init__(self, weight: float = 1.0):
        super().__init__(
            name="Ron Baron",
            description="Long-term growth investor",
            investing_style="Long-term compounders and growth franchises",
            weight=weight,
            llm_model="ollama-llama",
            llm_provider="ollama",
        )

    def analyze(self, ticker: str, start_date: str, end_date: str, **kwargs):
        return self.run_hybrid_analysis(ticker, start_date, end_date, **kwargs)
