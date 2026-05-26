"""Michael Burry investment agent (hybrid distress lane)."""

from src.agents.base import BaseAgent
from src.agents.hybrid import HybridAgentMixin


class MichaelBurryAgent(BaseAgent, HybridAgentMixin):
    hybrid_lane = "distress"
    hybrid_profile = "default"

    def __init__(self, weight: float = 1.0):
        super().__init__(
            name="Michael Burry",
            description="Contrarian Investor",
            investing_style="Deep value, distress, contrarian macro",
            weight=weight,
            llm_model="ollama-llama",
            llm_provider="ollama",
        )

    def analyze(self, ticker: str, start_date: str, end_date: str, **kwargs):
        return self.run_hybrid_analysis(ticker, start_date, end_date, **kwargs)
