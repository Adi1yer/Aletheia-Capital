"""Technicals Analyst agent (hybrid technicals lane)."""

from src.agents.base import BaseAgent
from src.agents.hybrid import HybridAgentMixin


class TechnicalsAnalystAgent(BaseAgent, HybridAgentMixin):
    hybrid_lane = "technicals"
    hybrid_profile = "default"

    def __init__(self, weight: float = 1.0):
        super().__init__(
            name="Technicals Analyst",
            description="Technical Analysis Expert",
            investing_style="Price action, moving averages, momentum — no chart patterns",
            weight=weight,
            llm_model="ollama-llama",
            llm_provider="ollama",
        )

    def analyze(self, ticker: str, start_date: str, end_date: str, **kwargs):
        return self.run_hybrid_analysis(ticker, start_date, end_date, **kwargs)
