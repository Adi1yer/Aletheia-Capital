"""Warren Buffett investment agent (hybrid value lane)."""

from src.agents.base import BaseAgent
from src.agents.hybrid import HybridAgentMixin


class WarrenBuffettAgent(BaseAgent, HybridAgentMixin):
    """Warren Buffett - The Oracle of Omaha"""

    hybrid_lane = "value"
    hybrid_profile = "buffett"

    def __init__(self, weight: float = 1.0):
        super().__init__(
            name="Warren Buffett",
            description="The Oracle of Omaha",
            investing_style=(
                "Seeks companies with strong fundamentals and competitive advantages "
                "through value investing and long-term ownership"
            ),
            weight=weight,
            llm_model="ollama-llama",
            llm_provider="ollama",
        )

    def analyze(self, ticker: str, start_date: str, end_date: str, **kwargs):
        return self.run_hybrid_analysis(ticker, start_date, end_date, **kwargs)
