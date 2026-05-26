"""Chamath Palihapitiya investment agent (hybrid growth lane)."""

from src.agents.base import BaseAgent
from src.agents.hybrid import HybridAgentMixin


class ChamathPalihapitiyaAgent(BaseAgent, HybridAgentMixin):
    hybrid_lane = "growth"
    hybrid_profile = "disruptive"

    def __init__(self, weight: float = 1.0):
        super().__init__(
            name="Chamath Palihapitiya",
            description="Growth / SPAC investor",
            investing_style="Technology platforms and disruptive growth",
            weight=weight,
            llm_model="ollama-llama",
            llm_provider="ollama",
        )

    def analyze(self, ticker: str, start_date: str, end_date: str, **kwargs):
        return self.run_hybrid_analysis(ticker, start_date, end_date, **kwargs)
