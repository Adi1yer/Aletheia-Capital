"""Mohnish Pabrai investment agent (hybrid value lane)."""

from src.agents.base import BaseAgent
from src.agents.hybrid import HybridAgentMixin


class MohnishPabraiAgent(BaseAgent, HybridAgentMixin):
    hybrid_lane = "value"
    hybrid_profile = "deep_value"

    def __init__(self, weight: float = 1.0):
        super().__init__(
            name="Mohnish Pabrai",
            description="Value Investor",
            investing_style="Low-risk, high-uncertainty bets; clone great investors; deep value",
            weight=weight,
            llm_model="ollama-llama",
            llm_provider="ollama",
        )

    def analyze(self, ticker: str, start_date: str, end_date: str, **kwargs):
        return self.run_hybrid_analysis(ticker, start_date, end_date, **kwargs)
