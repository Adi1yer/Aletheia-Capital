"""Congressional Trader agent - emulates trades by US Congress members (STOCK Act disclosures)."""

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import HumanMessage
from src.agents.base import BaseAgent, AgentSignal
from src.agents.prompt_helpers import JSON_ONLY_INSTRUCTION, AGENT_JSON_EXAMPLE, with_performance_feedback
from src.llm.utils import call_llm_with_retry
from pydantic import BaseModel, Field
from typing_extensions import Literal
import structlog

logger = structlog.get_logger()


class CongressionalSignal(BaseModel):
    """Congressional trader style signal"""
    signal: Literal["bullish", "bearish", "neutral"]
    confidence: int = Field(ge=0, le=100)
    reasoning: str


def _format_congressional_for_prompt(trades: list, max_entries: int = 20) -> str:
    """Format congressional trades for prompt."""
    if not trades:
        return "No recent congressional trading activity for this ticker."
    lines = ["Recent congressional activity (STOCK Act disclosures):"]
    for t in trades[:max_entries]:
        date = t.get("date", "?")[:10] if t.get("date") else "?"
        name = t.get("name", "?")
        tx = t.get("transaction_type", "?")
        amount = t.get("amount_range", "")
        party = t.get("party", "")
        extra = f" ({party})" if party else ""
        lines.append(f"  {date} - {name}{extra}: {tx} {amount}")
    return "\n".join(lines)


class CongressionalTraderAgent(BaseAgent):
    """Congressional Trader - Emulates trades by US Congress members based on disclosed transactions."""

    def __init__(self, weight: float = 1.0):
        super().__init__(
            name="Congressional Trader",
            description="Emulates congressional trading activity",
            investing_style="Follows disclosed trades by US Congress members (STOCK Act) to hedge against insider information",
            weight=weight,
            llm_model="ollama-llama",
            llm_provider="ollama",
        )

    def analyze(self, ticker: str, start_date: str, end_date: str, **kwargs) -> AgentSignal:
        logger.info("Starting Congressional Trader analysis", ticker=ticker)

        provider = self.data_provider
        if not hasattr(provider, "get_congressional_trades"):
            return AgentSignal(
                signal="neutral",
                confidence=0,
                reasoning="Congressional trades data not available (no API key configured).",
            )

        trades = provider.get_congressional_trades(ticker, end_date, start_date, limit=50)
        summary = _format_congressional_for_prompt(trades)

        # Rule-based net flow for fallback
        buys = sum(1 for t in trades if t.get("transaction_type") == "buy")
        sells = sum(1 for t in trades if t.get("transaction_type") == "sell")
        net = buys - sells
        total = len([t for t in trades if t.get("transaction_type") in ("buy", "sell")])

        if total == 0:
            return AgentSignal(
                signal="neutral",
                confidence=0,
                reasoning="No congressional trades found for this ticker in the period.",
            )

        prompt = ChatPromptTemplate.from_messages([
            ("system", with_performance_feedback("""You are a Congressional Trader agent. You analyze disclosed stock trades by US Congress members (STOCK Act).
Congress members have historically outperformed the market. Your job is to emulate their trades.

Rules:
- If politicians are net buying (more purchases than sales), signal bullish.
- If politicians are net selling (more sales than purchases), signal bearish.
- Confidence should reflect the strength of the signal (number of trades, clarity of direction).
- If data is sparse or mixed, use neutral with lower confidence.

""" + JSON_ONLY_INSTRUCTION + """
""", self)),
            ("human", """Ticker: {ticker}

{summary}

Net flow: {buys} buys, {sells} sells (total {total} trades)

Output only one JSON object with signal, confidence, reasoning. Example: """ + AGENT_JSON_EXAMPLE + """
""")
        ])

        formatted = prompt.format(
            ticker=ticker,
            summary=summary,
            buys=buys,
            sells=sells,
            total=total,
        )

        try:
            llm = self.get_llm()
            response = call_llm_with_retry(
                llm=llm,
                prompt=HumanMessage(content=formatted),
                output_model=CongressionalSignal,
            )
            return self.safe_signal_from_response(response)
        except Exception as e:
            logger.error("Congressional Trader LLM failed", ticker=ticker, error=str(e))
            # Fallback to rule-based
            if net > 2:
                sig, conf = "bullish", min(70, 40 + net * 5)
            elif net < -2:
                sig, conf = "bearish", min(70, 40 + abs(net) * 5)
            else:
                sig, conf = "neutral", 40
            return AgentSignal(
                signal=sig,
                confidence=conf,
                reasoning=f"Rule-based: {buys} buys, {sells} sells. Congress net {'buying' if net > 0 else 'selling' if net < 0 else 'neutral'}.",
            )
