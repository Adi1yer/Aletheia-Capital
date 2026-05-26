"""Stanley Druckenmiller investment agent (hybrid macro lane)."""

from src.agents.base import BaseAgent
from src.agents.hybrid import HybridAgentMixin


class StanleyDruckenmillerAgent(BaseAgent, HybridAgentMixin):
    hybrid_lane = "macro"
    hybrid_profile = "macro"

    def __init__(self, weight: float = 1.0):
        super().__init__(
            name="Stanley Druckenmiller",
            description="Macro Trader",
            investing_style="Macro themes, momentum, risk management",
            weight=weight,
            llm_model="ollama-llama",
            llm_provider="ollama",
        )

    def analyze(self, ticker: str, start_date: str, end_date: str, **kwargs):
        return self.run_hybrid_analysis(ticker, start_date, end_date, **kwargs)
