"""Valuation Analyst agent (hybrid valuation lane)."""

from src.agents.base import BaseAgent
from src.agents.hybrid import HybridAgentMixin


class ValuationAnalystAgent(BaseAgent, HybridAgentMixin):
    hybrid_lane = "valuation"
    hybrid_profile = "relative"

    def __init__(self, weight: float = 1.0):
        super().__init__(
            name="Valuation Analyst",
            description="Valuation Expert",
            investing_style="Relative and intrinsic valuation multiples",
            weight=weight,
            llm_model="ollama-llama",
            llm_provider="ollama",
        )

    def analyze(self, ticker: str, start_date: str, end_date: str, **kwargs):
        return self.run_hybrid_analysis(ticker, start_date, end_date, **kwargs)
