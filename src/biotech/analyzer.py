"""LLM analysis for biotech snapshots."""

from __future__ import annotations

import json

from langchain_core.messages import HumanMessage, SystemMessage

from src.biotech.models import BiotechAnalysisOutput, BiotechSnapshot
from src.biotech.prompts import SYSTEM_BIOTECH_IP, user_prompt_from_snapshot
from src.llm.models import get_llm_for_agent
from src.llm.utils import call_llm_with_retry
import structlog

logger = structlog.get_logger()


def analyze_snapshot(snapshot: BiotechSnapshot) -> BiotechAnalysisOutput:
    payload = snapshot.model_dump()
    user = user_prompt_from_snapshot(json.dumps(payload, default=str, indent=2))
    llm = get_llm_for_agent("ollama-llama", "ollama")
    messages = [
        SystemMessage(content=SYSTEM_BIOTECH_IP),
        HumanMessage(content=user),
    ]
    out = call_llm_with_retry(llm, messages, BiotechAnalysisOutput)
    if out.prob_success_low > out.prob_success_high:
        out.prob_success_low, out.prob_success_high = out.prob_success_high, out.prob_success_low
    return out
