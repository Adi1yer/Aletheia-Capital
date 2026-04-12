"""Portfolio management agent - makes final trading decisions"""

from typing import Dict, List, Literal, Optional
from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import HumanMessage
from src.agents.base import AgentSignal
from src.portfolio.models import Portfolio, Position
from src.risk.manager import RiskManager
from src.llm.models import get_llm_for_agent
from src.llm.utils import call_llm_with_retry
from src.agents.prompt_helpers import JSON_ONLY_INSTRUCTION, PM_JSON_EXAMPLE
import structlog
import json

logger = structlog.get_logger()


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
        current_prices = {t: risk_analysis[t]['current_price'] for t in tickers}
        
        for ticker in tickers:
            if ticker not in risk_analysis:
                decisions[ticker] = PortfolioDecision(
                    action="hold",
                    quantity=0,
                    confidence=0,
                    reasoning="No risk analysis available"
                )
                continue
            
            # Calculate allowed actions (capped by pending orders)
            allowed_actions = self._calculate_allowed_actions(
                ticker, portfolio, current_prices, risk_analysis[ticker],
                pending_orders=pending_orders_by_symbol.get(ticker),
            )
            
            # Aggregate weighted signals
            aggregated_signal = self._aggregate_signals(
                ticker, agent_signals, agent_weights
            )
            
            # If only hold is allowed, default to hold
            if set(allowed_actions.keys()) == {"hold"}:
                decisions[ticker] = PortfolioDecision(
                    action="hold",
                    quantity=0,
                    confidence=0,
                    reasoning="No valid trade available"
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
                    action="hold",
                    quantity=0,
                    confidence=0,
                    reasoning=f"Decision error: {str(e)}"
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
    ) -> Dict[str, PortfolioDecision]:
        """
        Deterministic portfolio-level rebalance:
        - Sell existing long positions when aggregated signal is bearish with high confidence
        - Allocate available cash (plus sale proceeds) across bullish names proportionally to confidence
        - Never opens new shorts (sell only if we hold; cover only if already short)
        """
        pending_orders_by_symbol = pending_orders_by_symbol or {}
        decisions: Dict[str, PortfolioDecision] = {}

        current_prices = {t: (risk_analysis.get(t) or {}).get("current_price", 0.0) for t in tickers}

        # 1) Determine sell candidates (free cash first)
        proceeds = 0.0
        sell_quantities: Dict[str, int] = {}
        for ticker in tickers:
            risk = risk_analysis.get(ticker)
            price = float(current_prices.get(ticker) or 0.0)
            if not risk or price <= 0:
                continue
            aggregated = self._aggregate_signals(ticker, agent_signals, agent_weights)
            position = portfolio.get_position(ticker)
            pending = pending_orders_by_symbol.get(ticker) or {}
            pending_sell = int(pending.get("sell_qty", 0) or 0)

            if position.long > 0 and aggregated["signal"] == "bearish" and aggregated["confidence"] >= min_sell_confidence:
                qty = max(0, int(position.long) - pending_sell)
                if qty > 0:
                    sell_quantities[ticker] = qty
                    proceeds += qty * price

        # 2) Compute budget for buys
        equity = portfolio.get_equity({t: float(p) for t, p in current_prices.items() if p})
        buffer = max(0.0, float(equity) * float(cash_buffer_pct))
        budget = max(0.0, float(portfolio.cash) + float(proceeds) - buffer)

        # 3) Pick buy candidates and allocate by confidence
        buy_candidates = []
        buy_candidate_set: set = set()
        for ticker in tickers:
            risk = risk_analysis.get(ticker)
            price = float(current_prices.get(ticker) or 0.0)
            if not risk or price <= 0:
                continue
            aggregated = self._aggregate_signals(ticker, agent_signals, agent_weights)
            if aggregated["signal"] == "bullish" and aggregated["confidence"] >= min_buy_confidence:
                buy_candidates.append((ticker, int(aggregated["confidence"])))

        buy_candidates.sort(key=lambda x: x[1], reverse=True)
        buy_candidates = buy_candidates[: max(0, int(max_buy_tickers))]
        buy_candidate_set = {t for t, _ in buy_candidates}
        total_score = sum(score for _, score in buy_candidates) or 0

        # 4) Build decisions
        # Start with sells and any covers (if short exists)
        for ticker in tickers:
            position = portfolio.get_position(ticker)
            risk = risk_analysis.get(ticker)
            price = float(current_prices.get(ticker) or 0.0)
            if not risk or price <= 0:
                decisions[ticker] = PortfolioDecision(action="hold", quantity=0, confidence=0, reasoning="No risk/price data")
                continue

            aggregated = self._aggregate_signals(ticker, agent_signals, agent_weights)
            allowed = self._calculate_allowed_actions(
                ticker,
                portfolio,
                {t: float(p) for t, p in current_prices.items() if p},
                risk,
                pending_orders=pending_orders_by_symbol.get(ticker),
            )

            if ticker in sell_quantities and "sell" in allowed:
                qty = min(int(sell_quantities[ticker]), int(allowed["sell"]))
                decisions[ticker] = PortfolioDecision(
                    action="sell",
                    quantity=qty,
                    confidence=int(aggregated["confidence"]),
                    reasoning=f"Rebalance: bearish {aggregated['confidence']}",
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

            # placeholder; may become buy below
            hold_reason = self._explain_hold(
                ticker, aggregated, position,
                min_buy_confidence, min_sell_confidence,
                buy_candidate_set, budget,
            )
            decisions[ticker] = PortfolioDecision(
                action="hold",
                quantity=0,
                confidence=int(aggregated["confidence"]),
                reasoning=hold_reason,
            )

        # 5) Allocate buys (respect budget + risk remaining limit + pending buys)
        if budget > 0 and total_score > 0:
            for ticker, score in buy_candidates:
                if budget <= 0:
                    break
                risk = risk_analysis.get(ticker) or {}
                price = float(current_prices.get(ticker) or 0.0)
                if price <= 0:
                    continue
                pending = pending_orders_by_symbol.get(ticker) or {}
                pending_buy = int(pending.get("buy_qty", 0) or 0)

                # Risk cap: remaining_position_limit is additional dollars allowed by risk
                remaining_dollars = float(risk.get("remaining_position_limit") or 0.0)
                max_by_risk = int(remaining_dollars // price) if remaining_dollars > 0 else 0
                max_by_cash = int(budget // price)
                max_buy = max(0, min(max_by_risk, max_by_cash) - pending_buy)
                if max_buy <= 0:
                    continue

                alloc = budget * (float(score) / float(total_score))
                qty = min(max_buy, int(alloc // price))
                if qty <= 0:
                    continue

                decisions[ticker] = PortfolioDecision(
                    action="buy",
                    quantity=qty,
                    confidence=int(score),
                    reasoning=f"Rebalance: bullish {score}",
                )
                budget -= qty * price

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

    def _calculate_allowed_actions(
        self,
        ticker: str,
        portfolio: Portfolio,
        current_prices: Dict[str, float],
        risk_data: Dict,
        pending_orders: Optional[Dict[str, int]] = None,
    ) -> Dict[str, int]:
        """Calculate allowed actions and max quantities. Caps by open orders so we don't over-order."""
        position = portfolio.get_position(ticker)
        price = current_prices[ticker]
        remaining_limit = risk_data['remaining_position_limit']
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

        # Short side: currently we support **closing** existing shorts (cover),
        # but we do not open new short positions in this portfolio manager.
        if position and position.short > 0:
            allowed["cover"] = position.short

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
        
        for agent_key, ticker_signals in agent_signals.items():
            if ticker not in ticker_signals:
                continue
            
            signal = ticker_signals[ticker]
            weight = agent_weights.get(agent_key, 1.0)
            weighted_confidence = signal.confidence * weight
            
            if signal.signal == "bullish":
                bullish_score += weighted_confidence
            elif signal.signal == "bearish":
                bearish_score += weighted_confidence
            
            total_weight += weight
            signal_details.append({
                'agent': agent_key,
                'signal': signal.signal,
                'confidence': signal.confidence,
                'weight': weight,
                'reasoning': signal.reasoning[:100],  # Truncate for LLM
            })
        
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
            'signal': overall_signal,
            'confidence': overall_confidence,
            'bullish_score': bullish_score,
            'bearish_score': bearish_score,
            'details': signal_details,
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
        pending_note = ""
        if pending_buy_qty or pending_sell_qty:
            pending_note = f"\nOpen orders (not yet filled): {pending_buy_qty} shares on buy, {pending_sell_qty} on sell. Allowed quantities below already account for these.\n"

        prompt = ChatPromptTemplate.from_messages([
            ("system", """You are a portfolio manager making trading decisions.

Inputs:
- Aggregated agent signals (weighted by agent performance)
- Allowed actions with maximum quantities (already validated against cash, margin, risk limits, and any open orders)

Your task: Pick one allowed action per ticker and a quantity ≤ the max. Keep reasoning concise (max 100 chars).

""" + JSON_ONLY_INSTRUCTION),
            ("human", """Ticker: {ticker}
Current Price: ${price:.2f}
{pending_note}
Aggregated Signal:
{signal}

Allowed Actions (with max quantities):
{allowed}

Return exactly one JSON object with keys: action, quantity, confidence, reasoning. No other text.
Example: """ + PM_JSON_EXAMPLE + """
""")
        ])
        
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
        return PortfolioDecision(action=action, quantity=quantity, confidence=confidence, reasoning=reasoning)

