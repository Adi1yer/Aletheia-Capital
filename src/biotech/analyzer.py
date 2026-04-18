"""LLM analysis for biotech snapshots."""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from src.biotech.models import BiotechAnalysisOutput, BiotechSnapshot
from src.biotech.prompts import SYSTEM_BIOTECH_IP, user_prompt_from_snapshot
from src.biotech.snapshot_compact import snapshot_json_for_llm
from src.llm.models import get_llm_for_agent
from src.llm.utils import call_llm_with_retry
import structlog

logger = structlog.get_logger()


def analyze_snapshot(
    snapshot: BiotechSnapshot, intraweek_context: str = ""
) -> BiotechAnalysisOutput:
    user = user_prompt_from_snapshot(
        snapshot_json_for_llm(snapshot), intraweek_context=intraweek_context
    )
    # Prefer DeepSeek when DEEPSEEK_API_KEY is set (same routing as trading agents).
    llm = get_llm_for_agent("deepseek-v3", "deepseek")
    messages = [
        SystemMessage(content=SYSTEM_BIOTECH_IP),
        HumanMessage(content=user),
    ]
    out = call_llm_with_retry(llm, messages, BiotechAnalysisOutput)
    if out.prob_success_low > out.prob_success_high:
        out.prob_success_low, out.prob_success_high = out.prob_success_high, out.prob_success_low
    return out
