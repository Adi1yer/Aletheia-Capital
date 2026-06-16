"""Portfolio management agent - makes final trading decisions"""

from typing import Any, Dict, List, Literal, Optional, Set, Tuple
from datetime import datetime
from pydantic import BaseModel, Field
from src.agents.base import AgentSignal
from src.agents.lane_ensemble import build_lane_signals
from src.agents.registry import get_registry
from src.portfolio.models import Portfolio, Position
from src.risk.manager import RiskManager
from src.llm.utils import call_llm_with_retry
from src.agents.prompt_helpers import JSON_ONLY_INSTRUCTION, PM_JSON_EXAMPLE
import structlog
import json

logger = structlog.get_logger()

GROWTH_LANES: Set[str] = {"growth"}
VALUE_LANES: Set[str] = {"value", "valuation"}


class PortfolioDecision(BaseModel):
    """Final trading decision for a ticker"""

    action: Literal["buy", "sell", "short", "cover", "hold"]
    quantity: int = Field(ge=0, description="Number of shares")
    confidence: int = Field(ge=0, le=100)
    reasoning: str


class PortfolioManagerOutput(BaseModel):
    """Portfolio manager output"""

    decisions: Dict[str, PortfolioDecision] = Field(description="Ticker to decision mapping")


class PortfolioManager:
    """Makes final trading decisions based on agent signals and risk limits"""

    def __init__(self):
        self.risk_manager = RiskManager()
        self._last_rebalance_diagnostics: Dict[str, Any] = {}
        self._last_cc_lot_tickers: List[str] = []
        self._last_csp_tickers: List[str] = []
        self._last_csp_scores: Dict[str, int] = {}

    def generate_decisions(
        self,
        tickers: List[str],
        agent_signals: Dict[str, Dict[str, AgentSignal]],  # agent_key -> ticker -> signal
        risk_analysis: Dict[str, Dict],
        portfolio: Portfolio,
        agent_weights: Dict[str, float],
        pending_orders_by_symbol: Optional[Dict[str, Dict[str, int]]] = None,
    ) -> Dict[str, PortfolioDecision]:
        """
        Generate final trading decisions.
        Accounts for open (pending) orders so we don't recommend more size than intended.
        """
        logger.info("Generating portfolio decisions", ticker_count=len(tickers))
        pending_orders_by_symbol = pending_orders_by_symbol or {}

        decisions = {}
        current_prices = {t: risk_analysis[t]["current_price"] for t in tickers}

        for ticker in tickers:
            if ticker not in risk_analysis:
                decisions[ticker] = PortfolioDecision(
                    action="hold", quantity=0, confidence=0, reasoning="No risk analysis available"
                )
                continue

            # Calculate allowed actions (capped by pending orders)
            allowed_actions = self._calculate_allowed_actions(
                ticker,
                portfolio,
                current_prices,
                risk_analysis[ticker],
                pending_orders=pending_orders_by_symbol.get(ticker),
            )

            # Aggregate weighted signals
            aggregated_signal = self._aggregate_signals(ticker, agent_signals, agent_weights)

            # If only hold is allowed, default to hold
            if set(allowed_actions.keys()) == {"hold"}:
                decisions[ticker] = PortfolioDecision(
                    action="hold", quantity=0, confidence=0, reasoning="No valid trade available"
                )
                continue

            # Generate decision using LLM (pass pending order context when present)
            pending = pending_orders_by_symbol.get(ticker) or {}
            try:
                decision = self._generate_decision_with_llm(
                    ticker,
                    aggregated_signal,
                    allowed_actions,
                    current_prices[ticker],
                    pending_buy_qty=pending.get("buy_qty", 0) or 0,
                    pending_sell_qty=pending.get("sell_qty", 0) or 0,
                )
                decisions[ticker] = decision
            except Exception as e:
                logger.error("Decision generation failed", ticker=ticker, error=str(e))
                decisions[ticker] = PortfolioDecision(
                    action="hold", quantity=0, confidence=0, reasoning=f"Decision error: {str(e)}"
                )

        logger.info("Portfolio decisions generated", decision_count=len(decisions))
        return decisions

    def generate_rebalance_decisions(
        self,
        tickers: List[str],
        agent_signals: Dict[str, Dict[str, AgentSignal]],
        risk_analysis: Dict[str, Dict],
        portfolio: Portfolio,
        agent_weights: Dict[str, float],
        pending_orders_by_symbol: Optional[Dict[str, Dict[str, int]]] = None,
        min_buy_confidence: int = 60,
        min_sell_confidence: int = 60,
        cash_buffer_pct: float = 0.05,
        max_buy_tickers: int = 20,
        enable_covered_calls: bool = False,
        min_cc_score: int = 40,
        next_earnings_by_ticker: Optional[Dict[str, Optional[str]]] = None,
        earnings_blackout_days: int = 0,
        enable_cash_secured_puts: bool = False,
        min_csp_score: int = 40,
        enable_conviction_rebalance: bool = False,
        conviction_score_gap: int = 25,
        min_hold_confidence_for_rotation: int = 45,
        enable_cash_rotation: bool = False,
        cash_rotation_min_edge: int = 5,
        cash_rotation_min_buy_notional_usd: float = 1500.0,
        cash_rotation_min_buy_notional_pct_equity: float = 0.02,
        max_position_pct: float = 0.20,
        max_sector_pct: float = 0.35,
        max_csp_tickers: int = 2,
        max_csp_collateral_pct: float = 0.10,
        wash_sale_days: int = 0,
        buy_disagreement_penalty: int = 5,
        max_cash_rotation_sells: int = 3,
        min_hold_weeks_before_rotation: int = 2,
        min_csp_premium_usd: float = 75.0,
        min_csp_annualized_yield_pct: float = 3.0,
        enable_short_selling: bool = False,
        max_short_position_pct: float = 0.05,
        max_short_tickers: int = 5,
        use_portfolio_optimizer: bool = False,
    ) -> Dict[str, PortfolioDecision]:
        """
        Deterministic portfolio-level rebalance with unified buy / covered-call ranking.

        - Sell existing long positions when aggregated signal is bearish with high confidence
        - Optional conviction rotation: sell weak longs when much stronger buys exist
        - Score every remaining ticker as buy, covered-call, or cash-secured-put candidate
        - Rank all opportunities on one confidence scale and allocate capital top-down
        - CC candidates: buy exactly 100 shares (lot build); the call is sold later by the pipeline
        """
        pending_orders_by_symbol = pending_orders_by_symbol or {}
        decisions: Dict[str, PortfolioDecision] = {}
        next_earnings_by_ticker = next_earnings_by_ticker or {}
        diagnostics: Dict[str, Any] = {
            "ticker_count": len(tickers),
            "min_buy_confidence": int(min_buy_confidence),
            "min_sell_confidence": int(min_sell_confidence),
            "buy_signal_count": 0,
            "sell_signal_on_held_count": 0,
            "buy_candidates_pre_rank": 0,
            "buy_candidates_post_rank": 0,
            "cc_scored_count": 0,
            "cc_passed_threshold_count": 0,
            "buy_blocked_by_risk_or_sizing_count": 0,
            "buy_blockers": {},
            "cash_rotation_sell_count": 0,
            "cash_rotation_skipped_edge": 0,
            "cash_rotation_skipped_risk": 0,
            "cash_rotation_skip_reason": "",
            "enable_cash_rotation": bool(enable_cash_rotation),
            "cc_held_lot_count": 0,
            "cc_lot_build_count": 0,
            "concentration_blocks": 0,
            "sector_blocks": 0,
            "csp_scored_count": 0,
            "csp_collateral_reserved": 0.0,
            "csp_skipped_cap": 0,
            "wash_sale_blocks": 0,
            "buy_disagreement_flags": 0,
            "rotation_sell_tickers": [],
            "csp_skipped_economics": 0,
        }
        self._cash_rotation_reasons: Dict[str, str] = {}
        self._rotation_sell_details: List[Dict[str, Any]] = []

        from src.portfolio.wash_sale import blocked_tickers, record_sell
        from src.portfolio.sectors import get_sector
        from src.performance.weekly_ledger import position_open_dates

        position_open_dates_map = position_open_dates()
        wash_blocked = blocked_tickers(int(wash_sale_days))
        sector_value: Dict[str, float] = {}

        current_prices = {
            t: (risk_analysis.get(t) or {}).get("current_price", 0.0) for t in tickers
        }
        equity = portfolio.get_equity({t: float(p) for t, p in current_prices.items() if p})
        for t, pos in (portfolio.positions or {}).items():
            px = float(current_prices.get(t) or 0.0)
            if pos and pos.long > 0 and px > 0:
                sec = get_sector(t)
                sector_value[sec] = sector_value.get(sec, 0.0) + pos.long * px
        max_csp_collateral = float(equity) * float(max_csp_collateral_pct)
        csp_collateral_used = 0.0

        def _earnings_blocks_buy(t: str) -> bool:
            if earnings_blackout_days <= 0:
                return False
            ed = next_earnings_by_ticker.get(t)
            if not ed:
                return False
            try:
                e_dt = datetime.strptime(str(ed)[:10], "%Y-%m-%d")
                today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
                return abs((e_dt - today).days) <= int(earnings_blackout_days)
            except Exception:
                return False

        aggregated_by_ticker = {
            t: self._aggregate_signals(t, agent_signals, agent_weights) for t in tickers
        }
        lane_bullish = lane_bearish = 0
        for agg in aggregated_by_ticker.values():
            for d in agg.get("details", []):
                a = str(d.get("agent") or "")
                if not a.startswith("lane:"):
                    continue
                if d.get("signal") == "bullish":
                    lane_bullish += 1
                elif d.get("signal") == "bearish":
                    lane_bearish += 1
        diagnostics["lane_contributions"] = {
            "bullish": lane_bullish,
            "bearish": lane_bearish,
            "total": lane_bullish + lane_bearish,
        }

        buy_scores_preview: Dict[str, int] = {}
        for ticker in tickers:
            risk = risk_analysis.get(ticker)
            price = float(current_prices.get(ticker) or 0.0)
            if not risk or price <= 0 or _earnings_blocks_buy(ticker):
                continue
            agg = aggregated_by_ticker[ticker]
            if agg["signal"] == "bullish" and agg["confidence"] >= min_buy_confidence:
                buy_scores_preview[ticker] = int(agg["confidence"])
                diagnostics["buy_signal_count"] += 1
            if (
                agg["signal"] == "bearish"
                and agg["confidence"] >= min_sell_confidence
                and portfolio.get_position(ticker).long > 0
            ):
                diagnostics["sell_signal_on_held_count"] += 1

        max_opp_score = max(buy_scores_preview.values()) if buy_scores_preview else 0

        # 1) Determine sell candidates (free cash first)
        proceeds = 0.0
        sell_quantities: Dict[str, int] = {}
        for ticker in tickers:
            risk = risk_analysis.get(ticker)
            price = float(current_prices.get(ticker) or 0.0)
            if not risk or price <= 0:
                continue
            aggregated = aggregated_by_ticker[ticker]
            position = portfolio.get_position(ticker)
            pending = pending_orders_by_symbol.get(ticker) or {}
            pending_sell = int(pending.get("sell_qty", 0) or 0)

            if (
                position.long > 0
                and aggregated["signal"] == "bearish"
                and aggregated["confidence"] >= min_sell_confidence
            ):
                qty = max(0, int(position.long) - pending_sell)
                if qty > 0:
                    sell_quantities[ticker] = qty
                    proceeds += qty * price
            elif (
                enable_conviction_rebalance
                and position
                and position.long > 0
                and max_opp_score >= min_buy_confidence
                and int(aggregated["confidence"]) < int(min_hold_confidence_for_rotation)
                and max_opp_score - int(aggregated["confidence"]) >= int(conviction_score_gap)
            ):
                qty = max(0, int(position.long) - pending_sell)
                if qty > 0:
                    sell_quantities[ticker] = qty
                    proceeds += qty * price

        # 2) Compute budget for buys + CC lot builds
        buffer = max(0.0, float(equity) * float(cash_buffer_pct))
        budget = max(0.0, float(portfolio.cash) + float(proceeds) - buffer)

        # 3) Score every ticker as buy OR covered-call OR CSP candidate
        buy_candidates: List[Tuple[str, int]] = []
        cc_candidates: List[Tuple[str, int]] = []
        csp_candidates: List[Tuple[str, int]] = []

        for ticker in tickers:
            risk = risk_analysis.get(ticker)
            price = float(current_prices.get(ticker) or 0.0)
            if not risk or price <= 0:
                continue
            if ticker in sell_quantities:
                continue
            if _earnings_blocks_buy(ticker):
                continue

            aggregated = aggregated_by_ticker[ticker]

            slotted = False
            if aggregated["signal"] == "bullish" and aggregated["confidence"] >= min_buy_confidence:
                eff_min = int(min_buy_confidence)
                if self._buy_has_camp_disagreement(ticker, agent_signals):
                    diagnostics["buy_disagreement_flags"] += 1
                    eff_min += int(buy_disagreement_penalty)
                if ticker in wash_blocked:
                    diagnostics["wash_sale_blocks"] += 1
                elif int(aggregated["confidence"]) >= eff_min:
                    buy_candidates.append((ticker, int(aggregated["confidence"])))
                    slotted = True
            if not slotted and enable_covered_calls:
                diagnostics["cc_scored_count"] += 1
                cc_score = self._score_covered_call(ticker, agent_signals, agent_weights)
                if cc_score >= min_cc_score:
                    cc_candidates.append((ticker, int(cc_score)))
                    diagnostics["cc_passed_threshold_count"] += 1
                    slotted = True
            if not slotted and enable_cash_secured_puts:
                diagnostics["csp_scored_count"] += 1
                csp_score = self._score_cash_secured_put(ticker, agent_signals, agent_weights)
                if csp_score >= min_csp_score and self._csp_passes_economics(
                    price,
                    csp_score,
                    min_csp_premium_usd,
                    min_csp_annualized_yield_pct,
                ):
                    csp_candidates.append((ticker, int(csp_score)))
                elif csp_score >= min_csp_score:
                    diagnostics["csp_skipped_economics"] += 1

        diagnostics["buy_candidates_pre_rank"] = len(buy_candidates)
        buy_candidates.sort(key=lambda x: x[1], reverse=True)
        buy_candidates = buy_candidates[: max(0, int(max_buy_tickers))]
        buy_candidate_set = {t for t, _ in buy_candidates}
        diagnostics["buy_candidates_post_rank"] = len(buy_candidates)

        min_rotation_notional = max(
            float(cash_rotation_min_buy_notional_usd),
            float(equity) * float(cash_rotation_min_buy_notional_pct_equity),
        )

        # 3b) Optional cash rotation: sell weaker held longs (not current buy targets) to fund buys
        if enable_cash_rotation and buy_candidates:
            best_buy_score = int(buy_candidates[0][1])
            buy_keys_rotation = {t for t, _ in buy_candidates}
            rotation_excluded: Set[str] = set()
            max_steps = max(len(tickers), 1) + 10
            for _ in range(max_steps):
                if int(diagnostics["cash_rotation_sell_count"]) >= int(max_cash_rotation_sells):
                    diagnostics["cash_rotation_skip_reason"] = "max_rotation_sells_reached"
                    break
                if self._any_buy_allocatable_for_budget(
                    buy_candidates,
                    budget,
                    current_prices,
                    risk_analysis,
                    pending_orders_by_symbol,
                    min_notional=min_rotation_notional,
                ):
                    diagnostics["cash_rotation_skip_reason"] = "buy_meaningfully_allocatable"
                    break
                weakest: Optional[str] = None
                weakest_metric = 10**9
                for t in tickers:
                    if t in sell_quantities or t in rotation_excluded or t in buy_keys_rotation:
                        continue
                    pos = portfolio.get_position(t)
                    if not pos or pos.long <= 0:
                        continue
                    risk = risk_analysis.get(t) or {}
                    price = float(current_prices.get(t) or 0.0)
                    if not risk or price <= 0:
                        continue
                    agg = aggregated_by_ticker.get(t) or {}
                    metric = self._hold_bullish_metric(agg)
                    if metric < weakest_metric:
                        weakest_metric = metric
                        weakest = t
                if weakest is None:
                    break
                if best_buy_score < weakest_metric + int(cash_rotation_min_edge):
                    diagnostics["cash_rotation_skipped_edge"] += 1
                    break
                if not self._rotation_hold_elapsed(
                    weakest, position_open_dates_map, int(min_hold_weeks_before_rotation)
                ):
                    rotation_excluded.add(weakest)
                    diagnostics["cash_rotation_skipped_hold_period"] = int(
                        diagnostics.get("cash_rotation_skipped_hold_period", 0)
                    ) + 1
                    continue
                allowed = self._calculate_allowed_actions(
                    weakest,
                    portfolio,
                    {t: float(p) for t, p in current_prices.items() if p},
                    risk_analysis[weakest],
                    pending_orders=pending_orders_by_symbol.get(weakest),
                )
                if "sell" not in allowed or int(allowed.get("sell", 0) or 0) <= 0:
                    rotation_excluded.add(weakest)
                    diagnostics["cash_rotation_skipped_risk"] += 1
                    continue
                pos_w = portfolio.get_position(weakest)
                pend_w = pending_orders_by_symbol.get(weakest) or {}
                pending_sell_w = int(pend_w.get("sell_qty", 0) or 0)
                qty_w = max(0, int(pos_w.long) - pending_sell_w)
                if qty_w <= 0:
                    rotation_excluded.add(weakest)
                    diagnostics["cash_rotation_skipped_risk"] += 1
                    continue
                sell_quantities[weakest] = qty_w
                px_w = float(current_prices.get(weakest) or 0.0)
                proceeds += qty_w * px_w
                budget = max(0.0, float(portfolio.cash) + float(proceeds) - buffer)
                diagnostics["cash_rotation_sell_count"] += 1
                reason = (
                    f"Cash rotation: sell long to fund buy candidates "
                    f"(held bullish metric {weakest_metric} vs best buy {best_buy_score})"
                )
                self._cash_rotation_reasons[weakest] = reason
                self._rotation_sell_details.append(
                    {
                        "ticker": weakest,
                        "reason": reason,
                        "held_metric": weakest_metric,
                        "best_buy_score": best_buy_score,
                    }
                )

        diagnostics["rotation_sell_tickers"] = list(self._rotation_sell_details)
        unified: List[Tuple[str, int, str]] = []
        for t, s in buy_candidates:
            unified.append((t, s, "buy"))
        for t, s in cc_candidates:
            unified.append((t, s, "cc"))
        for t, s in csp_candidates:
            unified.append((t, s, "csp"))
        unified.sort(key=lambda x: x[1], reverse=True)

        if unified:
            logger.info(
                "Unified opportunity ranking",
                total=len(unified),
                buys=sum(1 for _, _, tp in unified if tp == "buy"),
                ccs=sum(1 for _, _, tp in unified if tp == "cc"),
                csps=sum(1 for _, _, tp in unified if tp == "csp"),
                top5=[(t, s, tp) for t, s, tp in unified[:5]],
            )

        # 4) Build sell / cover / placeholder-hold decisions
        for ticker in tickers:
            position = portfolio.get_position(ticker)
            risk = risk_analysis.get(ticker)
            price = float(current_prices.get(ticker) or 0.0)
            if not risk or price <= 0:
                decisions[ticker] = PortfolioDecision(
                    action="hold", quantity=0, confidence=0, reasoning="No risk/price data"
                )
                continue

            aggregated = aggregated_by_ticker[ticker]
            allowed = self._calculate_allowed_actions(
                ticker,
                portfolio,
                {t: float(p) for t, p in current_prices.items() if p},
                risk,
                pending_orders=pending_orders_by_symbol.get(ticker),
            )

            if ticker in sell_quantities and "sell" in allowed:
                qty = min(int(sell_quantities[ticker]), int(allowed["sell"]))
                bear_sell = (
                    position
                    and position.long > 0
                    and aggregated["signal"] == "bearish"
                    and aggregated["confidence"] >= min_sell_confidence
                )
                reason = self._cash_rotation_reasons.get(ticker)
                if not reason:
                    reason = (
                        f"Rebalance: bearish {aggregated['confidence']}"
                        if bear_sell
                        else f"Conviction rotation: weaker hold vs opportunities (conf {aggregated['confidence']})"
                    )
                decisions[ticker] = PortfolioDecision(
                    action="sell",
                    quantity=qty,
                    confidence=int(aggregated["confidence"]),
                    reasoning=reason,
                )
                continue

            if position.short > 0 and "cover" in allowed:
                decisions[ticker] = PortfolioDecision(
                    action="cover",
                    quantity=int(allowed["cover"]),
                    confidence=int(aggregated["confidence"]),
                    reasoning="Rebalance: close short",
                )
                continue

            hold_reason = self._explain_hold(
                ticker,
                aggregated,
                position,
                min_buy_confidence,
                min_sell_confidence,
                buy_candidate_set,
                budget,
            )
            decisions[ticker] = PortfolioDecision(
                action="hold",
                quantity=0,
                confidence=int(aggregated["confidence"]),
                reasoning=hold_reason,
            )

        # 5) Allocate capital down the unified ranked list
        cc_lot_tickers: List[str] = []
        cc_lot_build_count = 0
        csp_lot_tickers: List[str] = []
        csp_scores: Dict[str, int] = {}
        if unified:
            blocker_counts: Dict[str, int] = {}
            for ticker, score, opp_type in unified:
                risk = risk_analysis.get(ticker) or {}
                price = float(current_prices.get(ticker) or 0.0)
                if price <= 0:
                    continue
                pending = pending_orders_by_symbol.get(ticker) or {}
                pending_buy = int(pending.get("buy_qty", 0) or 0)

                if opp_type == "csp":
                    if len(csp_lot_tickers) >= int(max_csp_tickers):
                        diagnostics["csp_skipped_cap"] += 1
                        continue
                    if budget <= 0:
                        continue
                    strike_approx = price * 0.95
                    collateral = strike_approx * 100.0
                    if collateral <= 0 or budget < collateral * 1.01:
                        continue
                    if csp_collateral_used + collateral > max_csp_collateral:
                        diagnostics["csp_skipped_cap"] += 1
                        continue
                    csp_lot_tickers.append(ticker)
                    csp_scores[ticker] = int(score)
                    budget -= collateral
                    csp_collateral_used += collateral
                    continue

                remaining_dollars = float(risk.get("remaining_position_limit") or 0.0)
                max_by_risk = int(remaining_dollars // price) if remaining_dollars > 0 else 0
                max_by_cash = int(budget // price) if budget > 0 else 0
                max_buy = max(0, min(max_by_risk, max_by_cash) - pending_buy)

                if opp_type == "cc":
                    position = portfolio.get_position(ticker)
                    current_long = position.long if position else 0
                    if current_long >= 100:
                        if ticker not in cc_lot_tickers:
                            cc_lot_tickers.append(ticker)
                        continue
                    if budget <= 0 or max_buy <= 0:
                        blocker = "risk_cap" if max_by_risk <= 0 else "cash_or_pending"
                        blocker_counts[blocker] = blocker_counts.get(blocker, 0) + 1
                        continue
                    needed = max(0, 100 - current_long - pending_buy)
                    if needed <= 0:
                        continue
                    qty = min(needed, max_buy)
                    if qty <= 0 or (current_long + qty) < 100:
                        continue
                    decisions[ticker] = PortfolioDecision(
                        action="buy",
                        quantity=qty,
                        confidence=int(score),
                        reasoning=f"CC lot build: buy to 100 shares (cc_score={score})",
                    )
                    cc_lot_tickers.append(ticker)
                    cc_lot_build_count += 1
                    budget -= qty * price
                else:
                    if budget <= 0 or max_buy <= 0:
                        blocker = "risk_cap" if max_by_risk <= 0 else "cash_or_pending"
                        blocker_counts[blocker] = blocker_counts.get(blocker, 0) + 1
                        continue
                    total_buy_score = sum(s for _, s, tp in unified if tp == "buy") or 1
                    alloc = budget * (float(score) / float(total_buy_score))
                    qty = min(max_buy, int(alloc // price))
                    position = portfolio.get_position(ticker)
                    held_val = (position.long if position else 0) * price
                    max_pos_dollars = float(equity) * float(max_position_pct)
                    if held_val + qty * price > max_pos_dollars:
                        qty = max(0, int((max_pos_dollars - held_val) // price))
                        if qty <= 0:
                            diagnostics["concentration_blocks"] += 1
                            continue
                    sec = get_sector(ticker)
                    if sec != "Unknown":
                        sec_cap = float(equity) * float(max_sector_pct)
                        if sector_value.get(sec, 0.0) + qty * price > sec_cap:
                            diagnostics["sector_blocks"] += 1
                            continue
                    if qty <= 0:
                        blocker_counts["allocation_rounding"] = (
                            blocker_counts.get("allocation_rounding", 0) + 1
                        )
                        continue
                    decisions[ticker] = PortfolioDecision(
                        action="buy",
                        quantity=qty,
                        confidence=int(score),
                        reasoning=f"Rebalance: bullish {score}",
                    )
                    budget -= qty * price
                    if sec != "Unknown":
                        sector_value[sec] = sector_value.get(sec, 0.0) + qty * price
            diagnostics["buy_blocked_by_risk_or_sizing_count"] = int(sum(blocker_counts.values()))
            diagnostics["buy_blockers"] = blocker_counts

        # Existing 100+ share lots eligible for CC (even when bullish consumed the buy slot).
        if enable_covered_calls:
            for t in tickers:
                pos = portfolio.get_position(t)
                if not pos or pos.long < 100:
                    continue
                if t in cc_lot_tickers:
                    continue
                cc_score = self._score_covered_call(t, agent_signals, agent_weights)
                if cc_score >= min_cc_score:
                    cc_lot_tickers.append(t)

        diagnostics["cc_lot_build_count"] = cc_lot_build_count
        diagnostics["cc_held_lot_count"] = max(0, len(cc_lot_tickers) - cc_lot_build_count)
        diagnostics["csp_collateral_reserved"] = round(csp_collateral_used, 2)

        if enable_short_selling:
            short_candidates: List[tuple] = []
            for ticker in tickers:
                pos = portfolio.get_position(ticker)
                if pos and pos.long > 0:
                    continue
                agg = aggregated_by_ticker[ticker]
                if agg["signal"] == "bearish" and agg["confidence"] >= min_sell_confidence:
                    short_candidates.append((ticker, int(agg["confidence"])))
            short_candidates.sort(key=lambda x: -x[1])
            for ticker, score in short_candidates[: int(max_short_tickers)]:
                existing = decisions.get(ticker)
                if existing and existing.action not in ("hold",):
                    continue
                risk = risk_analysis.get(ticker) or {}
                price = float(current_prices.get(ticker) or 0.0)
                if price <= 0:
                    continue
                allowed = self._calculate_allowed_actions(
                    ticker,
                    portfolio,
                    {t: float(p) for t, p in current_prices.items() if p},
                    risk,
                    pending_orders=pending_orders_by_symbol.get(ticker),
                    enable_short_selling=enable_short_selling,
                    max_short_position_pct=max_short_position_pct,
                )
                if "short" not in allowed or int(allowed.get("short", 0) or 0) <= 0:
                    continue
                decisions[ticker] = PortfolioDecision(
                    action="short",
                    quantity=int(allowed["short"]),
                    confidence=score,
                    reasoning=f"Rebalance: bearish short {score}",
                )

        if wash_sale_days > 0:
            for t, d in decisions.items():
                if d.action == "sell" and d.quantity > 0:
                    record_sell(t)

        if cc_lot_tickers:
            logger.info("CC lot builds selected", tickers=cc_lot_tickers)
        if csp_lot_tickers:
            logger.info("CSP candidates selected", tickers=csp_lot_tickers)

        self._last_cc_lot_tickers = cc_lot_tickers
        self._last_csp_tickers = csp_lot_tickers
        self._last_csp_scores = csp_scores

        if use_portfolio_optimizer:
            try:
                from src.portfolio.optimizer import optimize_allocations

                current_prices = {
                    t: float((risk_analysis.get(t) or {}).get("current_price") or 0.0)
                    for t in tickers
                }
                equity = float(portfolio.get_equity(current_prices))
                candidates = []
                for t, d in decisions.items():
                    if d.action != "buy" or d.quantity <= 0:
                        continue
                    risk = risk_analysis.get(t) or {}
                    candidates.append(
                        {
                            "ticker": t,
                            "score": float(d.confidence),
                            "price": float(risk.get("current_price") or 1.0),
                            "sector": str(risk.get("sector") or "unknown"),
                        }
                    )
                opt = optimize_allocations(
                    candidates,
                    equity=max(equity, float(portfolio.cash)),
                    cash_buffer_pct=cash_buffer_pct,
                    max_position_pct=max_position_pct,
                    max_sector_pct=max_sector_pct,
                )
                diagnostics["optimizer_metrics"] = opt.get("metrics") or {}
                for ticker, row in (opt.get("allocations") or {}).items():
                    if ticker in decisions and decisions[ticker].action == "buy":
                        decisions[ticker].quantity = int(row.get("quantity") or decisions[ticker].quantity)
            except Exception:
                diagnostics["optimizer_metrics"] = {"error": "optimizer_failed"}

        self._last_rebalance_diagnostics = diagnostics
        return decisions

    @staticmethod
    def _explain_hold(
        ticker: str,
        aggregated: Dict,
        position,
        min_buy_confidence: int,
        min_sell_confidence: int,
        buy_candidate_set: set,
        budget: float,
    ) -> str:
        sig = aggregated["signal"]
        conf = int(aggregated["confidence"])
        bull = round(aggregated.get("bullish_score", 0), 1)
        bear = round(aggregated.get("bearish_score", 0), 1)

        if sig == "neutral":
            return f"Neutral signal (bull {bull} vs bear {bear}); no clear direction"
        if sig == "bearish":
            if position and position.long > 0:
                if conf < min_sell_confidence:
                    return f"Bearish {conf}% but below sell threshold ({min_sell_confidence}); holding existing long"
                return f"Bearish {conf}%; existing long held (pending/other constraint)"
            return f"Bearish {conf}% (bull {bull} vs bear {bear}); no position to sell"
        # bullish
        if conf < min_buy_confidence:
            return f"Bullish {conf}% but below buy threshold ({min_buy_confidence})"
        if ticker not in buy_candidate_set:
            return f"Bullish {conf}% but outside top buy candidates by rank"
        if budget <= 0:
            return f"Bullish {conf}% but no budget remaining for new buys"
        return f"Bullish {conf}% (bull {bull} vs bear {bear}); sizing produced 0 shares"

    @staticmethod
    def _hold_bullish_metric(aggregated: Dict[str, Any]) -> int:
        """Comparable bullish strength for held names (matches buy-side bullish confidence when bullish)."""
        if aggregated.get("signal") == "bullish":
            return int(aggregated.get("confidence") or 0)
        return int(min(100.0, float(aggregated.get("bullish_score") or 0.0)))

    @staticmethod
    def _rotation_hold_elapsed(
        ticker: str,
        position_open_dates_map: Dict[str, str],
        min_hold_weeks: int,
    ) -> bool:
        if min_hold_weeks <= 0:
            return True
        opened = position_open_dates_map.get(ticker)
        if not opened:
            return True
        try:
            open_dt = datetime.strptime(str(opened)[:10], "%Y-%m-%d")
            today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            weeks = (today - open_dt).days / 7.0
            return weeks >= float(min_hold_weeks)
        except Exception:
            return True

    @staticmethod
    def _csp_passes_economics(
        price: float,
        csp_score: int,
        min_premium_usd: float,
        min_annualized_yield_pct: float,
        days_to_expiry: int = 30,
    ) -> bool:
        """Conservative pre-filter before ranking CSP candidates."""
        if price <= 0:
            return False
        strike = price * (0.94 if csp_score >= 55 else 0.91)
        collateral = strike * 100.0
        if collateral <= 0:
            return False
        est_premium = max(price * 100.0 * 0.003, float(min_premium_usd) * 0.5)
        if est_premium < float(min_premium_usd):
            return False
        annualized = (est_premium / collateral) * (365.0 / max(1, days_to_expiry)) * 100.0
        return annualized >= float(min_annualized_yield_pct)

    @staticmethod
    def _any_buy_allocatable_for_budget(
        buy_candidates: List[Tuple[str, int]],
        budget: float,
        current_prices: Dict[str, float],
        risk_analysis: Dict[str, Dict],
        pending_orders_by_symbol: Dict[str, Dict[str, int]],
        min_notional: float = 1500.0,
    ) -> bool:
        total_buy_score = sum(s for _, s in buy_candidates) or 1
        for ticker, score in buy_candidates:
            risk = risk_analysis.get(ticker) or {}
            price = float(current_prices.get(ticker) or 0.0)
            if price <= 0 or not risk:
                continue
            remaining_dollars = float(risk.get("remaining_position_limit") or 0.0)
            max_by_risk = int(remaining_dollars // price) if remaining_dollars > 0 else 0
            max_by_cash = int(budget // price) if budget > 0 else 0
            pending = pending_orders_by_symbol.get(ticker) or {}
            pending_buy = int(pending.get("buy_qty", 0) or 0)
            max_buy = max(0, min(max_by_risk, max_by_cash) - pending_buy)
            if max_buy < 1:
                continue
            alloc = budget * (float(score) / float(total_buy_score))
            qty = min(max_buy, int(alloc // price))
            if qty >= 1 and (qty * price) >= float(min_notional):
                return True
        return False

    @staticmethod
    def _agent_lane(agent_key: str) -> str:
        registry = get_registry()
        lane = getattr(registry.get(agent_key), "hybrid_lane", "") or ""
        if lane:
            return lane
        legacy_growth = {
            "cathie_wood",
            "chamath_palihapitiya",
            "ron_baron",
            "growth_analyst",
            "phil_fisher",
            "rakesh_jhunjhunwala",
            "aditya_iyer",
        }
        legacy_value = {
            "ben_graham",
            "charlie_munger",
            "warren_buffett",
            "michael_burry",
            "aswath_damodaran",
            "peter_lynch",
            "mohnish_pabrai",
            "valuation_analyst",
            "fundamentals_analyst",
        }
        if agent_key in legacy_growth:
            return "growth"
        if agent_key in legacy_value:
            return "value"
        low = (agent_key or "").lower()
        if "growth" in low:
            return "growth"
        if "value" in low or "valuation" in low:
            return "value"
        return ""

    @staticmethod
    def _buy_has_camp_disagreement(
        ticker: str,
        agent_signals: Dict[str, Dict[str, AgentSignal]],
    ) -> bool:
        """True when value and growth camps disagree on direction for this ticker."""
        value_bull = value_bear = growth_bull = growth_bear = 0
        for agent_key, ticker_signals in agent_signals.items():
            if ticker not in ticker_signals:
                continue
            sig = ticker_signals[ticker]
            sig_signal = sig.signal if hasattr(sig, "signal") else sig.get("signal", "neutral")
            lane = PortfolioManager._agent_lane(agent_key)
            if lane in GROWTH_LANES:
                if sig_signal == "bullish":
                    growth_bull += 1
                elif sig_signal == "bearish":
                    growth_bear += 1
            elif lane in VALUE_LANES:
                if sig_signal == "bullish":
                    value_bull += 1
                elif sig_signal == "bearish":
                    value_bear += 1
        return (value_bull > 0 and growth_bear > 0) or (value_bear > 0 and growth_bull > 0)

    @staticmethod
    def _score_covered_call(
        ticker: str,
        agent_signals: Dict[str, Dict[str, AgentSignal]],
        agent_weights: Dict[str, float],
    ) -> int:
        """Score a ticker for covered-call suitability.

        High score = growth agents bullish AND value agents bearish
        (the stock won't crash but won't rally hard either -- ideal for
        harvesting option premium).
        """
        growth_total = 0
        growth_bullish = 0
        value_total = 0
        value_bearish = 0
        all_confidences: List[float] = []

        for agent_key, ticker_signals in agent_signals.items():
            if ticker not in ticker_signals:
                continue
            sig = ticker_signals[ticker]
            weight = agent_weights.get(agent_key, 1.0)
            sig_signal = sig.signal if hasattr(sig, "signal") else sig.get("signal", "neutral")
            sig_conf = sig.confidence if hasattr(sig, "confidence") else sig.get("confidence", 0)
            all_confidences.append(sig_conf * weight)

            lane = PortfolioManager._agent_lane(agent_key)
            if lane in GROWTH_LANES:
                growth_total += 1
                if sig_signal == "bullish":
                    growth_bullish += 1
            elif lane in VALUE_LANES:
                value_total += 1
                if sig_signal == "bearish":
                    value_bearish += 1

        if growth_total == 0 or value_total == 0:
            return 0

        growth_bull_pct = growth_bullish / growth_total
        value_bear_pct = value_bearish / value_total
        avg_confidence = (sum(all_confidences) / len(all_confidences)) if all_confidences else 0

        return int(min(growth_bull_pct, value_bear_pct) * avg_confidence)

    @staticmethod
    def _score_cash_secured_put(
        ticker: str,
        agent_signals: Dict[str, Dict[str, AgentSignal]],
        agent_weights: Dict[str, float],
    ) -> int:
        """Cash-secured put: value agents bullish, growth agents bearish (inverse of covered call)."""
        growth_total = 0
        growth_bearish = 0
        value_total = 0
        value_bullish = 0
        all_confidences: List[float] = []

        for agent_key, ticker_signals in agent_signals.items():
            if ticker not in ticker_signals:
                continue
            sig = ticker_signals[ticker]
            weight = agent_weights.get(agent_key, 1.0)
            sig_signal = sig.signal if hasattr(sig, "signal") else sig.get("signal", "neutral")
            sig_conf = sig.confidence if hasattr(sig, "confidence") else sig.get("confidence", 0)
            all_confidences.append(sig_conf * weight)

            lane = PortfolioManager._agent_lane(agent_key)
            if lane in GROWTH_LANES:
                growth_total += 1
                if sig_signal == "bearish":
                    growth_bearish += 1
            elif lane in VALUE_LANES:
                value_total += 1
                if sig_signal == "bullish":
                    value_bullish += 1

        if growth_total == 0 or value_total == 0:
            return 0

        growth_bear_pct = growth_bearish / growth_total
        value_bull_pct = value_bullish / value_total
        avg_confidence = (sum(all_confidences) / len(all_confidences)) if all_confidences else 0

        return int(min(growth_bear_pct, value_bull_pct) * avg_confidence)

    def _calculate_allowed_actions(
        self,
        ticker: str,
        portfolio: Portfolio,
        current_prices: Dict[str, float],
        risk_data: Dict,
        pending_orders: Optional[Dict[str, int]] = None,
        enable_short_selling: bool = False,
        max_short_position_pct: float = 0.05,
    ) -> Dict[str, int]:
        """Calculate allowed actions and max quantities. Caps by open orders so we don't over-order."""
        position = portfolio.get_position(ticker)
        price = current_prices[ticker]
        remaining_limit = risk_data["remaining_position_limit"]
        pending = pending_orders or {}
        pending_buy = int(pending.get("buy_qty", 0) or 0)
        pending_sell = int(pending.get("sell_qty", 0) or 0)

        allowed = {"hold": 0}

        # Long side: sell only what we have left after accounting for already-placed sell orders
        if position and position.long > 0:
            allowed["sell"] = max(0, position.long - pending_sell)

        # Buy: cap by cash/risk, then subtract shares we already have on order
        if portfolio.cash > 0 and price > 0:
            max_buy_cash = int(portfolio.cash // price)
            max_buy_limit = int(remaining_limit // price) if remaining_limit > 0 else 0
            max_buy = max(0, min(max_buy_cash, max_buy_limit) - pending_buy)
            if max_buy > 0:
                allowed["buy"] = max_buy

        # Short side: cover existing; optionally open new shorts on bearish signals.
        if position and position.short > 0:
            allowed["cover"] = position.short

        if enable_short_selling and portfolio.cash > 0 and price > 0:
            eq_prices = {k: float(v) for k, v in current_prices.items() if v}
            equity_val = portfolio.get_equity(eq_prices) if eq_prices else float(portfolio.cash)
            max_short_dollars = float(equity_val) * float(max_short_position_pct)
            current_short_val = (position.short if position else 0) * price
            room = max(0.0, max_short_dollars - current_short_val)
            max_short_shares = int(room // price) if room > 0 else 0
            if max_short_shares > 0 and (not position or position.long == 0):
                allowed["short"] = max_short_shares

        return allowed

    def _aggregate_signals(
        self,
        ticker: str,
        agent_signals: Dict[str, Dict[str, AgentSignal]],
        agent_weights: Dict[str, float],
    ) -> Dict:
        """Aggregate signals from all agents with weights"""
        bullish_score = 0.0
        bearish_score = 0.0
        total_weight = 0.0
        signal_details = []

        lane_signals = build_lane_signals(ticker, agent_signals, agent_weights)
        for lane_key, lane_signal in lane_signals.items():
            weight = float(lane_signal.get("weight", 0.0))
            sig_signal = str(lane_signal.get("signal", "neutral"))
            sig_conf = int(lane_signal.get("confidence", 0))
            weighted_confidence = sig_conf * weight
            if sig_signal == "bullish":
                bullish_score += weighted_confidence
            elif sig_signal == "bearish":
                bearish_score += weighted_confidence
            if sig_signal in ("bullish", "bearish") and sig_conf > 0:
                total_weight += weight
            signal_details.append(
                {
                    "agent": lane_key,
                    "signal": sig_signal,
                    "confidence": sig_conf,
                    "weight": weight,
                    "reasoning": str(lane_signal.get("reasoning", ""))[:100],
                }
            )

        # Normalize scores
        if total_weight > 0:
            bullish_score /= total_weight
            bearish_score /= total_weight

        # Determine overall signal (5-point threshold to reduce neutral dead zone)
        if bullish_score > bearish_score + 5:
            overall_signal = "bullish"
            overall_confidence = int(min(100, bullish_score))
        elif bearish_score > bullish_score + 5:
            overall_signal = "bearish"
            overall_confidence = int(min(100, bearish_score))
        else:
            overall_signal = "neutral"
            overall_confidence = int(abs(bullish_score - bearish_score))

        return {
            "signal": overall_signal,
            "confidence": overall_confidence,
            "bullish_score": bullish_score,
            "bearish_score": bearish_score,
            "details": signal_details,
        }

    def _generate_decision_with_llm(
        self,
        ticker: str,
        aggregated_signal: Dict,
        allowed_actions: Dict[str, int],
        current_price: float,
        pending_buy_qty: int = 0,
        pending_sell_qty: int = 0,
    ) -> PortfolioDecision:
        """Generate decision using LLM. Pending quantities are open orders not yet filled."""
        from langchain_core.messages import HumanMessage
        from langchain_core.prompts import ChatPromptTemplate

        from src.llm.models import get_llm_for_agent

        pending_note = ""
        if pending_buy_qty or pending_sell_qty:
            pending_note = f"\nOpen orders (not yet filled): {pending_buy_qty} shares on buy, {pending_sell_qty} on sell. Allowed quantities below already account for these.\n"

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    """You are a portfolio manager making trading decisions.

Inputs:
- Aggregated agent signals (weighted by agent performance)
- Allowed actions with maximum quantities (already validated against cash, margin, risk limits, and any open orders)

Your task: Pick one allowed action per ticker and a quantity ≤ the max. Keep reasoning concise (max 100 chars).

"""
                    + JSON_ONLY_INSTRUCTION,
                ),
                (
                    "human",
                    """Ticker: {ticker}
Current Price: ${price:.2f}
{pending_note}
Aggregated Signal:
{signal}

Allowed Actions (with max quantities):
{allowed}

Return exactly one JSON object with keys: action, quantity, confidence, reasoning. No other text.
Example: """
                    + PM_JSON_EXAMPLE
                    + """
""",
                ),
            ]
        )

        formatted_prompt = prompt.format(
            ticker=ticker,
            price=current_price,
            pending_note=pending_note,
            signal=json.dumps(aggregated_signal, indent=2),
            allowed=json.dumps(allowed_actions, indent=2),
        )

        # Use DeepSeek (when configured) for portfolio decisions, but route
        # through our DeepSeek-aware helper so we don't trigger unsupported
        # `response_format` behavior. If no DEEPSEEK_API_KEY is set, this
        # automatically falls back to Ollama.
        llm = get_llm_for_agent("deepseek-v3", "deepseek")
        response = call_llm_with_retry(
            llm=llm,
            prompt=HumanMessage(content=formatted_prompt),
            output_model=PortfolioDecision,
        )

        # Safely extract fields (DeepSeek sometimes returns quoted keys that raise KeyError)
        try:
            action = response.action
            quantity = getattr(response, "quantity", 0)
            confidence = getattr(response, "confidence", 0)
            reasoning = getattr(response, "reasoning", "") or "Portfolio decision"
        except (KeyError, AttributeError):
            return PortfolioDecision(
                action="hold",
                quantity=0,
                confidence=0,
                reasoning="Decision parse error (malformed LLM response)",
            )
        if action in allowed_actions:
            quantity = min(quantity, allowed_actions[action])
        return PortfolioDecision(
            action=action, quantity=quantity, confidence=confidence, reasoning=reasoning
        )
