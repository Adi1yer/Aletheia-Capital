"""Congressional Trader agent (hybrid congressional lane)."""

from src.agents.base import BaseAgent
from src.agents.hybrid import HybridAgentMixin
from src.agents.inputs import AgentInputs


class CongressionalTraderAgent(BaseAgent, HybridAgentMixin):
    hybrid_lane = "congressional"
    hybrid_profile = "default"

    def __init__(self, weight: float = 1.0):
        super().__init__(
            name="Congressional Trader",
            description="Emulates congressional trading activity",
            investing_style="Follows STOCK Act disclosures; net buy/sell flow",
            weight=weight,
            llm_model="ollama-llama",
            llm_provider="ollama",
        )

    def enrich_inputs(self, inputs: AgentInputs) -> AgentInputs:
        provider = self.data_provider
        if hasattr(provider, "get_congressional_trades"):
            trades = provider.get_congressional_trades(
                inputs.ticker, inputs.end_date, inputs.start_date, limit=50
            )
            inputs.extras["congressional_trades"] = trades or []
        else:
            inputs.extras["congressional_trades"] = []
        return inputs

    def analyze(self, ticker: str, start_date: str, end_date: str, **kwargs):
        return self.run_hybrid_analysis(ticker, start_date, end_date, **kwargs)
