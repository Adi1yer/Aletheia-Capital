"""Fundamentals Analyst agent (hybrid value lane)."""

from src.agents.base import BaseAgent
from src.agents.hybrid import HybridAgentMixin


class FundamentalsAnalystAgent(BaseAgent, HybridAgentMixin):
    hybrid_lane = "value"
    hybrid_profile = "neutral_fundamentals"

    def __init__(self, weight: float = 1.0):
        super().__init__(
            name="Fundamentals Analyst",
            description="Fundamental Analysis Expert",
            investing_style="Objective assessment of profitability, solvency, and cash flow",
            weight=weight,
            llm_model="ollama-llama",
            llm_provider="ollama",
        )

    def analyze(self, ticker: str, start_date: str, end_date: str, **kwargs):
        return self.run_hybrid_analysis(ticker, start_date, end_date, **kwargs)
