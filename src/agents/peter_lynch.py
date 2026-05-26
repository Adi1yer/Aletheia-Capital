"""Peter Lynch investment agent (hybrid growth lane)."""

from src.agents.base import BaseAgent
from src.agents.hybrid import HybridAgentMixin


class PeterLynchAgent(BaseAgent, HybridAgentMixin):
    hybrid_lane = "growth"
    hybrid_profile = "lynch"

    def __init__(self, weight: float = 1.0):
        super().__init__(
            name="Peter Lynch",
            description="Growth at reasonable price",
            investing_style="GARP; understand what you own; growth at reasonable price",
            weight=weight,
            llm_model="ollama-llama",
            llm_provider="ollama",
        )

    def analyze(self, ticker: str, start_date: str, end_date: str, **kwargs):
        return self.run_hybrid_analysis(ticker, start_date, end_date, **kwargs)
