"""Ben Graham investment agent (hybrid value lane)."""

from src.agents.base import BaseAgent
from src.agents.hybrid import HybridAgentMixin


class BenGrahamAgent(BaseAgent, HybridAgentMixin):
    hybrid_lane = "value"
    hybrid_profile = "graham"

    def __init__(self, weight: float = 1.0):
        super().__init__(
            name="Ben Graham",
            description="The Father of Value Investing",
            investing_style="Margin of safety, defensive balance sheet, undervalued equities",
            weight=weight,
            llm_model="ollama-llama",
            llm_provider="ollama",
        )

    def analyze(self, ticker: str, start_date: str, end_date: str, **kwargs):
        return self.run_hybrid_analysis(ticker, start_date, end_date, **kwargs)
