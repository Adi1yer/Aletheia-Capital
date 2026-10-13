"""Automatic short put buy-to-close to free collateral when cash is negative.

CRO sign-off requirements:
1. Buy-to-close only. Never sell to open, never roll, never touch calls.
2. Order: in-the-money puts first, then most collateral freed per dollar of buyback cost.
3. Limit orders only, with a cap per contract and a cap per run.
4. Confirm exact contract symbol from broker's position list.
5. If positions or cash read fails, place nothing and alert.
6. Log free cash before and after each run.

CFO requirements:
a. Limit price from live quote (ask + buffer), include fees in cost.
b. Cancel failed/timed-out BTC orders and count partial fills.
c. Handle negative qty from Alpaca (use abs), verify shape.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List, Optional

import structlog

if TYPE_CHECKING:
    from src.broker.alpaca import AlpacaBroker

logger = structlog.get_logger()

# Alpaca options fee: $0.65 per contract (industry standard)
OPTIONS_FEE_PER_CONTRACT = 0.65


def calculate_free_cash(
    account_cash: float,
    option_positions: List[Dict],
    open_orders: Optional[List[Dict]] = None,
) -> float:
    """Calculate free cash = account cash - short put collateral - pending STO/BTC orders.
    
    Args:
        account_cash: Raw cash from broker account
        option_positions: List of option positions from broker
        open_orders: List of open orders (optional, for counting pending STO/BTC puts)
    
    Returns:
        Free cash available (can be negative)
    """
    from src.options.wheel_lifecycle import parse_occ_symbol
    
    # Count existing short put collateral
    short_put_collateral = 0.0
    for pos in option_positions or []:
        if str(pos.get("side") or "").lower() != "short":
            continue
        parsed = parse_occ_symbol(str(pos.get("symbol") or ""))
        if not parsed or parsed.get("option_type") != "put":
            continue
        strike = float(parsed.get("strike") or 0.0)
        try:
            # CFO review (c): Alpaca may return negative qty for shorts
            qty = abs(int(pos.get("qty") or 0))
        except (TypeError, ValueError):
            qty = 0
        if strike > 0 and qty > 0:
            short_put_collateral += strike * 100.0 * qty
    
    # Count pending sell-to-open put orders (reserve collateral)
    # AND pending buy-to-close put orders (reduce available cash by cost)
    pending_sto_collateral = 0.0
    pending_btc_cost = 0.0
    
    for order in open_orders or []:
        symbol = str(order.get("symbol") or "")
        parsed = parse_occ_symbol(symbol)
        if not parsed or parsed.get("option_type") != "put":
            continue
        
        side = str(order.get("side") or "").lower()
        strike = float(parsed.get("strike") or 0.0)
        try:
            qty = int(order.get("qty") or 0)
            filled = int(order.get("filled_qty") or 0)
            remaining = max(0, qty - filled)
        except (TypeError, ValueError):
            remaining = 0
        
        if strike > 0 and remaining > 0:
            if side == "sell":
                # Pending STO: reserves collateral
                pending_sto_collateral += strike * 100.0 * remaining
            elif side == "buy":
                # Pending BTC: estimate cost at strike (conservative)
                # Real cost from limit price would be better but not always available
                pending_btc_cost += strike * 100.0 * remaining
    
    free = account_cash - short_put_collateral - pending_sto_collateral - pending_btc_cost
    return free


def rank_puts_for_buyback(
    option_positions: List[Dict],
    current_prices: Dict[str, float],
) -> List[Dict]:
    """Rank short puts for buyback: ITM first, then best collateral/cost ratio.
    
    CFO review (c): Handle negative qty from Alpaca using abs().
    
    Args:
        option_positions: List of option positions from broker
        current_prices: Dict mapping underlying ticker to current price
    
    Returns:
        List of short put positions ranked for buyback, each with ranking metadata
    """
    from src.options.wheel_lifecycle import parse_occ_symbol
    
    candidates = []
    for pos in option_positions or []:
        if str(pos.get("side") or "").lower() != "short":
            continue
        
        parsed = parse_occ_symbol(str(pos.get("symbol") or ""))
        if not parsed or parsed.get("option_type") != "put":
            continue
        
        symbol = str(pos.get("symbol") or "")
        underlying = parsed["underlying"]
        strike = float(parsed.get("strike") or 0.0)
        
        try:
            # CFO review (c): Alpaca may return negative qty for short positions
            raw_qty = int(pos.get("qty") or 0)
            qty = abs(raw_qty)
        except (TypeError, ValueError):
            qty = 0
        
        if qty <= 0 or strike <= 0:
            continue
        
        # Get current underlying price
        current_price = current_prices.get(underlying, 0.0)
        
        # Calculate moneyness (positive = ITM)
        itm_amount = max(0.0, strike - current_price) if current_price > 0 else 0.0
        is_itm = itm_amount > 0
        
        # Get buyback cost estimate (use mark or current_price from position)
        # CFO requirement (a): We'll fetch live quotes later; this is just for ranking
        buyback_cost_per_contract = 0.0
        for price_field in ["current_price", "mark_price", "market_value"]:
            try:
                val = float(pos.get(price_field) or 0.0)
                if val > 0:
                    if price_field == "market_value":
                        # market_value is total, divide by qty and abs
                        buyback_cost_per_contract = abs(val / qty)
                    else:
                        # per-share price, multiply by 100
                        buyback_cost_per_contract = abs(val) * 100.0
                    break
            except (TypeError, ValueError, ZeroDivisionError):
                continue
        
        # If we can't get cost, we can't rank it properly
        if buyback_cost_per_contract <= 0:
            logger.warning(
                "Cannot estimate buyback cost for put",
                symbol=symbol,
                underlying=underlying,
            )
            continue
        
        collateral = strike * 100.0 * qty
        collateral_per_dollar = collateral / buyback_cost_per_contract if buyback_cost_per_contract > 0 else 0
        
        candidates.append({
            "symbol": symbol,
            "underlying": underlying,
            "strike": strike,
            "qty": qty,
            "is_itm": is_itm,
            "itm_amount": itm_amount,
            "buyback_cost_estimate": buyback_cost_per_contract,
            "collateral": collateral,
            "collateral_per_dollar": collateral_per_dollar,
            "position": pos,
        })
    
    # Sort: ITM first (descending by ITM amount), then by collateral_per_dollar (descending)
    # ITM puts are highest priority, then we want the best bang for buck
    candidates.sort(
        key=lambda x: (
            -1 if x["is_itm"] else 0,  # ITM first
            -x["itm_amount"],  # Most ITM first
            -x["collateral_per_dollar"],  # Best collateral/cost ratio
        ),
        reverse=False,
    )
    
    return candidates


def get_live_buyback_quote(
    broker: "AlpacaBroker",
    symbol: str,
    qty: int,
    ask_buffer_pct: float = 0.05,
) -> Optional[Dict]:
    """Fetch live quote for put buy-to-close and calculate limit price with buffer.
    
    CFO requirement (a): Base limit price on live ask (not position mark) with buffer.
    Include fees in total cost estimate.
    
    Args:
        broker: Broker instance
        symbol: Option contract symbol
        qty: Number of contracts to close
        ask_buffer_pct: Buffer above ask (default 5%)
    
    Returns:
        Dict with limit_price and total_cost, or None if quote unavailable
    """
    try:
        # Fetch live quote for the option contract
        if not hasattr(broker, "client"):
            logger.warning("Broker missing client attribute for quote fetch", symbol=symbol)
            return None
        
        # Try to get option quote - Alpaca doesn't have a direct option quote API
        # We'll use get_option_contracts and check the ask_price field
        try:
            contracts = broker.get_option_contracts(
                underlying=symbol[:symbol.find("2") if "2" in symbol else 0] or symbol[:4],
                limit=100,
            )
            contract = None
            for c in contracts or []:
                if str(c.get("symbol") or "") == symbol:
                    contract = c
                    break
            
            if not contract:
                logger.warning("Contract not found in chain for quote", symbol=symbol)
                return None
            
            # Get ask price
            ask = float(contract.get("ask_price") or contract.get("ask") or 0.0)
            if ask <= 0:
                # Fallback to mid if ask unavailable
                bid = float(contract.get("bid_price") or contract.get("bid") or 0.0)
                if bid > 0 and ask <= 0:
                    ask = bid * 1.1  # Conservative estimate
                else:
                    logger.warning("No valid ask/bid for contract", symbol=symbol)
                    return None
            
            # Apply buffer
            limit_price_per_share = ask * (1.0 + ask_buffer_pct)
            
            # Calculate total cost including fees
            cost_per_contract = (limit_price_per_share * 100.0) + OPTIONS_FEE_PER_CONTRACT
            total_cost = cost_per_contract * qty
            
            return {
                "limit_price": round(limit_price_per_share, 2),
                "ask": round(ask, 2),
                "cost_per_contract": round(cost_per_contract, 2),
                "total_cost": round(total_cost, 2),
                "qty": qty,
            }
        except Exception as e:
            logger.warning("Failed to fetch live quote for contract", symbol=symbol, error=str(e))
            return None
    except Exception as e:
        logger.error("Quote fetch exception", symbol=symbol, error=str(e))
        return None


def execute_auto_put_buyback(
    broker: "AlpacaBroker",
    current_prices: Dict[str, float],
    *,
    max_cost_per_contract: float = 500.0,
    max_total_cost: float = 2000.0,
    ask_buffer_pct: float = 0.05,
    execute: bool = False,
) -> List[Dict]:
    """Automatically buy back short puts when free cash is negative.
    
    CRO Requirements:
    1. Buy-to-close only
    2. Order: ITM puts first, then best collateral/cost ratio
    3. Limit orders only with per-contract and per-run caps
    4. Confirm exact contract symbol from broker positions
    5. If reads fail, alert and place nothing
    6. Log free cash before and after
    
    CFO Requirements:
    a. Limit price from live quote (ask + buffer), include fees
    b. Cancel failed/timed-out orders, count partial fills
    c. Handle negative qty from Alpaca
    
    Args:
        broker: Broker instance
        current_prices: Current prices for underlyings
        max_cost_per_contract: Maximum debit per contract (default $500)
        max_total_cost: Maximum total debit per run (default $2000)
        ask_buffer_pct: Buffer above ask for limit price (default 5%)
        execute: If False, dry-run only (default False, must set AUTO_PUT_BUYBACK=1)
    
    Returns:
        List of results for each action taken
    """
    from src.utils.alerts import send_alert
    
    results: List[Dict] = []
    
    # Requirement 5: If reads fail, place nothing and alert
    try:
        account = broker.get_account()
        account_cash = float(account.get("cash") or 0.0)
    except Exception as e:
        logger.error("Failed to fetch account cash - ALERT", error=str(e))
        alert_msg = f"Auto put buyback: account read failed - {str(e)[:100]}"
        send_alert("Auto Put Buyback Alert", alert_msg, {"error": str(e)})
        results.append({
            "status": "alert",
            "reason": "account_read_failed",
            "error": str(e)[:200],
        })
        return results
    
    try:
        option_positions = broker.get_option_positions() or []
    except Exception as e:
        logger.error("Failed to fetch option positions - ALERT", error=str(e))
        alert_msg = f"Auto put buyback: positions read failed - {str(e)[:100]}"
        send_alert("Auto Put Buyback Alert", alert_msg, {"error": str(e)})
        results.append({
            "status": "alert",
            "reason": "positions_read_failed",
            "error": str(e)[:200],
        })
        return results
    
    # CRO requirement (5): Fail closed if open orders read fails
    try:
        open_orders = broker.get_open_orders(limit=100) or []
    except Exception as e:
        logger.error("Failed to fetch open orders - ALERT (fail closed)", error=str(e))
        alert_msg = f"Auto put buyback: open orders read failed (fail closed) - {str(e)[:100]}"
        send_alert("Auto Put Buyback Alert", alert_msg, {"error": str(e)})
        results.append({
            "status": "alert",
            "reason": "open_orders_read_failed_fail_closed",
            "error": str(e)[:200],
        })
        return results
    
    # Requirement 6: Log free cash before
    free_cash_before = calculate_free_cash(account_cash, option_positions, open_orders)
    logger.info(
        "Auto put buyback - free cash check",
        account_cash=round(account_cash, 2),
        free_cash_before=round(free_cash_before, 2),
        execute=execute,
    )
    
    # Only proceed if free cash is negative
    if free_cash_before >= 0:
        logger.info("Free cash is non-negative; no buyback needed", free_cash=round(free_cash_before, 2))
        results.append({
            "status": "skipped",
            "reason": "free_cash_non_negative",
            "free_cash": round(free_cash_before, 2),
        })
        return results
    
    # Requirement 2: Rank puts for buyback (ITM first, then best collateral/cost)
    ranked_puts = rank_puts_for_buyback(option_positions, current_prices)
    
    if not ranked_puts:
        logger.warning("No short puts found to buy back despite negative free cash")
        alert_msg = f"Auto put buyback: no puts to buyback, free cash = ${free_cash_before:.2f}"
        send_alert("Auto Put Buyback Alert", alert_msg, {"free_cash": free_cash_before})
        results.append({
            "status": "alert",
            "reason": "no_puts_to_buyback",
            "free_cash": round(free_cash_before, 2),
        })
        return results
    
    logger.info(
        "Ranked short puts for buyback",
        count=len(ranked_puts),
        free_cash=round(free_cash_before, 2),
        shortage=round(abs(free_cash_before), 2),
    )
    
    # Requirement 3: Track caps
    total_cost = 0.0
    total_collateral_freed = 0.0
    contracts_closed = 0
    current_free_cash = free_cash_before
    
    for put in ranked_puts:
        # Requirement 4: Confirm exact symbol from broker positions
        symbol = put["symbol"]
        underlying = put["underlying"]
        strike = put["strike"]
        qty = put["qty"]  # CRO (7): Support qty > 1
        collateral = put["collateral"]
        
        # CFO (a): Fetch live quote for limit price
        quote = get_live_buyback_quote(broker, symbol, qty, ask_buffer_pct)
        if not quote:
            logger.warning("No live quote available for put", symbol=symbol)
            results.append({
                "status": "skipped",
                "symbol": symbol,
                "underlying": underlying,
                "reason": "no_live_quote",
                "qty": qty,
            })
            continue
        
        limit_price = quote["limit_price"]
        cost_with_fees = quote["total_cost"]
        
        # Check per-contract cap (CRO requirement 4: stop whole run if hit)
        cost_per_contract_check = quote["cost_per_contract"]
        if cost_per_contract_check > max_cost_per_contract:
            logger.error(
                "Put exceeds per-contract cost cap - STOPPING WHOLE RUN",
                symbol=symbol,
                cost=round(cost_per_contract_check, 2),
                cap=round(max_cost_per_contract, 2),
            )
            alert_msg = f"Auto put buyback: per-contract cap hit (${cost_per_contract_check:.2f} > ${max_cost_per_contract:.2f}) - STOPPED"
            send_alert("Auto Put Buyback Alert", alert_msg, {
                "symbol": symbol,
                "cost": cost_per_contract_check,
                "cap": max_cost_per_contract,
            })
            results.append({
                "status": "alert",
                "symbol": symbol,
                "underlying": underlying,
                "reason": f"per_contract_cap_hit_stop_{cost_per_contract_check:.0f}>{max_cost_per_contract:.0f}",
                "cost_per_contract": round(cost_per_contract_check, 2),
                "cap": round(max_cost_per_contract, 2),
            })
            # STOP the whole run
            break
        
        # Check total run cap
        if total_cost + cost_with_fees > max_total_cost:
            logger.warning(
                "Run cost cap reached; stopping buyback",
                total_cost=round(total_cost, 2),
                cap=round(max_total_cost, 2),
            )
            alert_msg = f"Auto put buyback: run cap reached (${total_cost + cost_with_fees:.2f} > ${max_total_cost:.2f})"
            send_alert("Auto Put Buyback Alert", alert_msg, {
                "total_cost": total_cost,
                "cap": max_total_cost,
            })
            results.append({
                "status": "alert",
                "reason": f"run_cap_reached_{total_cost + cost_with_fees:.0f}>{max_total_cost:.0f}",
                "total_cost": round(total_cost, 2),
                "cap": round(max_total_cost, 2),
            })
            break
        
        # Requirement 1: Buy-to-close only
        # Requirement 3: Limit orders only
        
        if not execute:
            logger.info(
                "DRY RUN: Would buy-to-close put",
                symbol=symbol,
                underlying=underlying,
                strike=strike,
                qty=qty,
                limit_price=limit_price,
                cost_with_fees=round(cost_with_fees, 2),
                collateral_freed=round(collateral, 2),
            )
            results.append({
                "status": "dry_run",
                "symbol": symbol,
                "underlying": underlying,
                "strike": strike,
                "qty": qty,
                "limit_price": limit_price,
                "cost_with_fees": round(cost_with_fees, 2),
                "collateral_freed": round(collateral, 2),
            })
            # Update tracking for dry run
            total_cost += cost_with_fees
            total_collateral_freed += collateral
            contracts_closed += qty
            # CRO (1): Fix free cash calculation
            current_free_cash = free_cash_before + total_collateral_freed - total_cost
        else:
            try:
                # Submit buy-to-close limit order
                order = broker.submit_option_order(
                    contract_symbol=symbol,
                    qty=qty,  # CRO (7): Support qty > 1
                    side="buy",  # BUY to close
                    order_type="limit",
                    limit_price=limit_price,
                    wait_fill=True,
                    fill_timeout_s=45.0,
                )
                
                # CFO (b): Handle fill, timeout, and cancellation
                ok = bool(order) and order.get("fill_ok") is True
                timed_out = bool(order) and order.get("fill", {}).get("timed_out") is True
                
                if ok:
                    # Successful fill
                    try:
                        fill = (order or {}).get("fill") or {}
                        avg = float(fill.get("filled_avg_price") or order.get("filled_avg_price") or 0.0)
                        filled_qty = int(fill.get("filled_qty") or qty)
                        if avg > 0:
                            actual_cost = (abs(avg) * 100.0 * filled_qty) + (OPTIONS_FEE_PER_CONTRACT * filled_qty)
                        else:
                            actual_cost = cost_with_fees
                        actual_collateral_freed = strike * 100.0 * filled_qty
                    except (TypeError, ValueError):
                        actual_cost = cost_with_fees
                        actual_collateral_freed = collateral
                        filled_qty = qty
                    
                    logger.info(
                        "Put buy-to-close executed",
                        symbol=symbol,
                        underlying=underlying,
                        strike=strike,
                        qty=filled_qty,
                        cost=round(actual_cost, 2),
                        collateral_freed=round(actual_collateral_freed, 2),
                    )
                    
                    results.append({
                        "status": "executed",
                        "symbol": symbol,
                        "underlying": underlying,
                        "strike": strike,
                        "qty": filled_qty,
                        "limit_price": limit_price,
                        "cost_with_fees": round(actual_cost, 2),
                        "collateral_freed": round(actual_collateral_freed, 2),
                        "order": order,
                    })
                    
                    total_cost += actual_cost
                    total_collateral_freed += actual_collateral_freed
                    contracts_closed += filled_qty
                    
                elif timed_out:
                    # CFO (b): Order timed out - cancel and count partial fills
                    order_id = order.get("order_id") or order.get("id")
                    partial_filled_qty = 0
                    partial_cost = 0.0
                    partial_collateral = 0.0
                    
                    if order_id:
                        try:
                            # Cancel the order
                            broker.cancel_order(str(order_id))
                            # Get final fill status
                            final_order = broker.get_order(str(order_id))
                            if final_order:
                                partial_filled_qty = int(final_order.get("filled_qty") or 0)
                                if partial_filled_qty > 0:
                                    avg = float(final_order.get("filled_avg_price") or 0.0)
                                    if avg > 0:
                                        partial_cost = (abs(avg) * 100.0 * partial_filled_qty) + (OPTIONS_FEE_PER_CONTRACT * partial_filled_qty)
                                    partial_collateral = strike * 100.0 * partial_filled_qty
                        except Exception as cancel_err:
                            logger.warning("Failed to cancel timed-out order", order_id=order_id, error=str(cancel_err))
                    
                    logger.warning(
                        "Put buy-to-close timed out",
                        symbol=symbol,
                        underlying=underlying,
                        partial_filled_qty=partial_filled_qty,
                        partial_cost=round(partial_cost, 2) if partial_cost > 0 else None,
                    )
                    
                    results.append({
                        "status": "timed_out",
                        "symbol": symbol,
                        "underlying": underlying,
                        "strike": strike,
                        "qty": qty,
                        "partial_filled_qty": partial_filled_qty,
                        "partial_cost": round(partial_cost, 2) if partial_cost > 0 else 0.0,
                        "partial_collateral_freed": round(partial_collateral, 2) if partial_collateral > 0 else 0.0,
                        "order": order,
                    })
                    
                    # Count partial fills
                    if partial_filled_qty > 0:
                        total_cost += partial_cost
                        total_collateral_freed += partial_collateral
                        contracts_closed += partial_filled_qty
                else:
                    # Failed order
                    fill = (order or {}).get("fill") if isinstance(order, dict) else {}
                    detail = ""
                    if isinstance(order, dict):
                        detail = str(
                            order.get("error")
                            or (fill or {}).get("status")
                            or order.get("status")
                            or ""
                        )[:80]
                    
                    logger.warning(
                        "Put buy-to-close failed",
                        symbol=symbol,
                        underlying=underlying,
                        detail=detail,
                    )
                    
                    results.append({
                        "status": "failed",
                        "symbol": symbol,
                        "underlying": underlying,
                        "reason": f"order_or_fill_{detail}" if detail else "order_or_fill",
                        "order": order,
                    })
            except Exception as e:
                logger.error("Put buy-to-close exception", symbol=symbol, error=str(e))
                results.append({
                    "status": "failed",
                    "symbol": symbol,
                    "underlying": underlying,
                    "reason": "exception",
                    "error": str(e)[:200],
                })
        
        # CRO (1): Fix free cash calculation and CRO (8): Log after each close
        current_free_cash = free_cash_before + total_collateral_freed - total_cost
        logger.info(
            "Free cash after close",
            symbol=symbol,
            free_cash=round(current_free_cash, 2),
            collateral_freed=round(total_collateral_freed, 2),
            total_cost=round(total_cost, 2),
        )
        
        if current_free_cash >= 0:
            logger.info(
                "Free cash restored to non-negative; stopping buyback",
                free_cash=round(current_free_cash, 2),
                contracts_closed=contracts_closed,
            )
            break
    
    # Requirement 6: Log free cash after
    # CRO (9): Report unknown if final re-read fails
    free_cash_after_status = "calculated"
    if execute and contracts_closed > 0:
        try:
            final_account = broker.get_account()
            final_cash = float(final_account.get("cash") or 0.0)
            final_positions = broker.get_option_positions() or []
            final_orders = broker.get_open_orders(limit=100) or []
            free_cash_after = calculate_free_cash(final_cash, final_positions, final_orders)
            free_cash_after_status = "refreshed"
        except Exception as e:
            logger.error("Failed to refresh final state - reporting as unknown", error=str(e))
            free_cash_after = current_free_cash
            free_cash_after_status = "unknown_read_failed"
    else:
        free_cash_after = current_free_cash
    
    logger.info(
        "Auto put buyback complete",
        execute=execute,
        contracts_closed=contracts_closed,
        total_cost=round(total_cost, 2),
        total_collateral_freed=round(total_collateral_freed, 2),
        free_cash_before=round(free_cash_before, 2),
        free_cash_after=round(free_cash_after, 2),
        free_cash_after_status=free_cash_after_status,
        improvement=round(free_cash_after - free_cash_before, 2),
    )
    
    # Send alert if we executed anything
    if execute and contracts_closed > 0:
        alert_msg = f"Auto put buyback: closed {contracts_closed} contracts, freed ${total_collateral_freed:.2f} collateral for ${total_cost:.2f} cost, free cash: ${free_cash_before:.2f} → ${free_cash_after:.2f}"
        send_alert("Auto Put Buyback Executed", alert_msg, {
            "contracts_closed": contracts_closed,
            "total_cost": total_cost,
            "total_collateral_freed": total_collateral_freed,
            "free_cash_before": free_cash_before,
            "free_cash_after": free_cash_after,
        })
    
    return results
