"""Charlie Munger investment agent (hybrid value lane)."""

from src.agents.base import BaseAgent
from src.agents.hybrid import HybridAgentMixin


class CharlieMungerAgent(BaseAgent, HybridAgentMixin):
    hybrid_lane = "value"
    hybrid_profile = "munger"

    def __init__(self, weight: float = 1.0):
        super().__init__(
            name="Charlie Munger",
            description="Berkshire Vice Chairman",
            investing_style="Quality businesses at fair prices; mental models and moats",
            weight=weight,
            llm_model="ollama-llama",
            llm_provider="ollama",
        )

    def analyze(self, ticker: str, start_date: str, end_date: str, **kwargs):
        return self.run_hybrid_analysis(ticker, start_date, end_date, **kwargs)
