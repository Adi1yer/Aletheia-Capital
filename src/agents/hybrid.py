"""Hybrid rule-first agents with bounded LLM explanation."""

from __future__ import annotations

from typing import Literal, Optional, Type

import structlog
from langchain_core.messages import HumanMessage
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field
from typing_extensions import Literal as TL

from src.agents.base import AgentSignal, BaseAgent
from src.agents.inputs import AgentInputs, resolve_agent_inputs
from src.agents.prompt_helpers import (
    CONFIDENCE_DISCIPLINE,
    HYBRID_JSON_EXAMPLE,
    JSON_ONLY_INSTRUCTION,
    format_dossier_for_prompt,
    format_rule_score_for_prompt,
    with_performance_feedback,
)
from src.agents.scoring.models import RuleScore
from src.agents.scoring.registry import run_scorer
from src.llm.utils import call_llm_with_retry

logger = structlog.get_logger()


class HybridExplainOutput(BaseModel):
    signal: TL["bullish", "bearish", "neutral"]
    confidence: int = Field(ge=0, le=100)
    reasoning: str
    override: bool = False
    override_reason: str = ""


class HybridAgentMixin:
    """Mixin: resolve dossier → rule score → optional LLM explain."""

    hybrid_lane: str = "value"
    hybrid_profile: str = "default"
    hybrid_signal_model: Type[BaseModel] = HybridExplainOutput

    def persona_lens(self) -> str:
        return self.investing_style

    def enrich_inputs(self, inputs: AgentInputs) -> AgentInputs:
        """Override for lane-specific provider fetches (congressional, analyst recs)."""
        return inputs

    def compute_rule_score(self, inputs: AgentInputs) -> RuleScore:
        return run_scorer(self.hybrid_lane, inputs, self.hybrid_profile)

    def run_hybrid_analysis(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
        **kwargs,
    ) -> AgentSignal:
        dossier = kwargs.get("dossier")
        if isinstance(kwargs.get("dossiers"), dict):
            dossier = kwargs["dossiers"].get(ticker) or dossier

        inputs = resolve_agent_inputs(
            ticker,
            start_date,
            end_date,
            dossier,
            self.data_provider,
            extras=kwargs.get("extras"),
        )
        inputs = self.enrich_inputs(inputs)

        rule = self.compute_rule_score(inputs)
        if rule.rule_confidence == 0 and not rule.checks:
            return AgentSignal(
                signal="neutral",
                confidence=0,
                reasoning=rule.facts.get("reason", "Insufficient data for analysis"),
            )

        llm_budget = kwargs.get("llm_budget") if isinstance(kwargs.get("llm_budget"), dict) else {}
        agent_key = str(kwargs.get("agent_key") or "")
        lane = str(getattr(self, "hybrid_lane", "") or "other")
        if rule.skip_llm or (rule.rule_confidence >= 70 and rule.passed_count() >= 3):
            names = ", ".join(c.get("name", "") for c in rule.checks if c.get("pass"))
            return AgentSignal(
                signal=rule.suggested_signal,
                confidence=rule.rule_confidence,
                reasoning=f"Rule engine ({rule.lane}): {names}",
            )
        lane_remaining = (llm_budget.get("per_lane") or {}).get(lane)
        if llm_budget.get("remaining", 0) <= 0 or (lane_remaining is not None and int(lane_remaining) <= 0):
            return AgentSignal(
                signal=rule.suggested_signal,
                confidence=rule.rule_confidence,
                reasoning=f"Rule engine ({rule.lane}): LLM budget exhausted",
            )
        llm_budget["remaining"] = int(llm_budget.get("remaining", 0)) - 1
        llm_budget["used"] = int(llm_budget.get("used", 0)) + 1
        if lane_remaining is not None:
            llm_budget["per_lane"][lane] = int(lane_remaining) - 1

        return self.explain_with_llm(ticker, inputs, rule)

    def explain_with_llm(
        self,
        ticker: str,
        inputs: AgentInputs,
        rule: RuleScore,
    ) -> AgentSignal:
        rule_block = format_rule_score_for_prompt(rule)
        dossier_block = format_dossier_for_prompt(inputs)

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    with_performance_feedback(
                        f"""You are {self.name}. {self.persona_lens()}

A deterministic rule engine produced the analysis below. Your job:
1. Explain the rule outcome in your investor voice.
2. Adjust confidence by at most ±15 from rule confidence ({rule.rule_confidence}).
3. Keep the suggested signal unless you set override=true with a cited fact from the data.

{CONFIDENCE_DISCIPLINE}

{JSON_ONLY_INSTRUCTION}
""",
                        self,
                        ticker,
                    ),
                ),
                (
                    "human",
                    """## Rule engine
{rule_block}

## Data
{dossier_block}

Respond with JSON: signal, confidence, reasoning, override (bool), override_reason.
Example: """
                    + HYBRID_JSON_EXAMPLE,
                ),
            ]
        )
        formatted = prompt.format(rule_block=rule_block, dossier_block=dossier_block)
        try:
            llm = self.get_llm()
            response = call_llm_with_retry(
                llm=llm,
                prompt=HumanMessage(content=formatted),
                output_model=self.hybrid_signal_model,
            )
            return self._finalize_signal(response, rule)
        except Exception as e:
            logger.error("Hybrid LLM failed", agent=self.name, ticker=ticker, error=str(e))
            return AgentSignal(
                signal=rule.suggested_signal,
                confidence=rule.rule_confidence,
                reasoning=f"Rule-based ({rule.lane}); LLM unavailable: {e}",
            )

    def _finalize_signal(self, response: HybridExplainOutput, rule: RuleScore) -> AgentSignal:
        sig = rule.suggested_signal
        if getattr(response, "override", False) and getattr(response, "override_reason", "").strip():
            reason = str(getattr(response, "override_reason", "")).lower()
            check_names = [str(c.get("name", "")).lower() for c in (rule.checks or [])]
            if any(name and name in reason for name in check_names):
                sig = response.signal

        lo = max(0, rule.rule_confidence - 15)
        hi = min(85 if rule.passed_count() < 3 else 90, rule.rule_confidence + 15)
        conf = max(lo, min(hi, int(response.confidence)))

        return AgentSignal(signal=sig, confidence=conf, reasoning=response.reasoning.strip())

