"""Automatic short put buy-to-close to free collateral when cash is negative.

CRO sign-off requirements:
1. Buy-to-close only. Never sell to open, never roll, never touch calls.
2. Order: in-the-money puts first, then most collateral freed per dollar of buyback cost.
3. Limit orders only, with a cap per contract and a cap per run.
4. Confirm exact contract symbol from broker's position list.
5. If positions or cash read fails, place nothing and alert.
6. Log free cash before and after each run.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List, Optional

import structlog

if TYPE_CHECKING:
    from src.broker.alpaca import AlpacaBroker

logger = structlog.get_logger()


def calculate_free_cash(
    account_cash: float,
    option_positions: List[Dict],
    open_orders: Optional[List[Dict]] = None,
) -> float:
    """Calculate free cash = account cash - short put collateral - pending STO put orders.
    
    Args:
        account_cash: Raw cash from broker account
        option_positions: List of option positions from broker
        open_orders: List of open orders (optional, for counting pending STO puts)
    
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
            qty = int(pos.get("qty") or 0)
        except (TypeError, ValueError):
            qty = 0
        if strike > 0 and qty > 0:
            short_put_collateral += strike * 100.0 * qty
    
    # Count pending sell-to-open put orders
    pending_put_collateral = 0.0
    for order in open_orders or []:
        if str(order.get("side") or "").lower() != "sell":
            continue
        symbol = str(order.get("symbol") or "")
        parsed = parse_occ_symbol(symbol)
        if not parsed or parsed.get("option_type") != "put":
            continue
        strike = float(parsed.get("strike") or 0.0)
        try:
            # Use total qty minus filled qty for open orders
            qty = int(order.get("qty") or 0)
            filled = int(order.get("filled_qty") or 0)
            remaining = max(0, qty - filled)
        except (TypeError, ValueError):
            remaining = 0
        if strike > 0 and remaining > 0:
            pending_put_collateral += strike * 100.0 * remaining
    
    free = account_cash - short_put_collateral - pending_put_collateral
    return free


def rank_puts_for_buyback(
    option_positions: List[Dict],
    current_prices: Dict[str, float],
) -> List[Dict]:
    """Rank short puts for buyback: ITM first, then best collateral/cost ratio.
    
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
            qty = int(pos.get("qty") or 0)
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
        
        collateral = strike * 100.0
        collateral_per_dollar = collateral / buyback_cost_per_contract if buyback_cost_per_contract > 0 else 0
        
        candidates.append({
            "symbol": symbol,
            "underlying": underlying,
            "strike": strike,
            "qty": qty,
            "is_itm": is_itm,
            "itm_amount": itm_amount,
            "buyback_cost": buyback_cost_per_contract,
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


def execute_auto_put_buyback(
    broker: "AlpacaBroker",
    current_prices: Dict[str, float],
    *,
    max_cost_per_contract: float = 500.0,
    max_total_cost: float = 2000.0,
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
    
    Args:
        broker: Broker instance
        current_prices: Current prices for underlyings
        max_cost_per_contract: Maximum debit per contract (default $500)
        max_total_cost: Maximum total debit per run (default $2000)
        execute: If False, dry-run only (default False, must set AUTO_PUT_BUYBACK=1)
    
    Returns:
        List of results for each action taken
    """
    results: List[Dict] = []
    
    # Requirement 5: If reads fail, place nothing and alert
    try:
        account = broker.get_account()
        account_cash = float(account.get("cash") or 0.0)
    except Exception as e:
        logger.error("Failed to fetch account cash - ALERT", error=str(e))
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
        results.append({
            "status": "alert",
            "reason": "positions_read_failed",
            "error": str(e)[:200],
        })
        return results
    
    # Try to get open orders (optional, skip if fails)
    try:
        open_orders = broker.get_open_orders(limit=100) or []
    except Exception as e:
        logger.warning("Failed to fetch open orders; continuing without order collateral", error=str(e))
        open_orders = None
    
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
    total_spent = 0.0
    contracts_closed = 0
    
    for put in ranked_puts:
        # Requirement 4: Confirm exact symbol from broker positions
        symbol = put["symbol"]
        underlying = put["underlying"]
        strike = put["strike"]
        buyback_cost = put["buyback_cost"]
        collateral = put["collateral"]
        
        # Check per-contract cap
        if buyback_cost > max_cost_per_contract:
            logger.warning(
                "Put exceeds per-contract cost cap",
                symbol=symbol,
                cost=round(buyback_cost, 2),
                cap=round(max_cost_per_contract, 2),
            )
            results.append({
                "status": "skipped",
                "symbol": symbol,
                "underlying": underlying,
                "reason": f"exceeds_contract_cap_{buyback_cost:.0f}>{max_cost_per_contract:.0f}",
                "buyback_cost": round(buyback_cost, 2),
            })
            continue
        
        # Check total run cap
        if total_spent + buyback_cost > max_total_cost:
            logger.warning(
                "Run cost cap reached; stopping buyback",
                total_spent=round(total_spent, 2),
                cap=round(max_total_cost, 2),
            )
            results.append({
                "status": "alert",
                "reason": f"run_cap_reached_{total_spent + buyback_cost:.0f}>{max_total_cost:.0f}",
                "total_spent": round(total_spent, 2),
                "cap": round(max_total_cost, 2),
            })
            break
        
        # Requirement 1: Buy-to-close only
        # Requirement 3: Limit orders only at or near the ask
        # Use buyback_cost as limit (it's from mark/current_price, close to ask)
        limit_price = round(buyback_cost / 100.0, 2)  # Convert back to per-share
        
        if not execute:
            logger.info(
                "DRY RUN: Would buy-to-close put",
                symbol=symbol,
                underlying=underlying,
                strike=strike,
                limit_price=limit_price,
                collateral_freed=round(collateral, 2),
            )
            results.append({
                "status": "dry_run",
                "symbol": symbol,
                "underlying": underlying,
                "strike": strike,
                "limit_price": limit_price,
                "buyback_cost": round(buyback_cost, 2),
                "collateral_freed": round(collateral, 2),
            })
            total_spent += buyback_cost
            contracts_closed += 1
        else:
            try:
                # Submit buy-to-close limit order
                order = broker.submit_option_order(
                    contract_symbol=symbol,
                    qty=1,
                    side="buy",  # BUY to close
                    order_type="limit",
                    limit_price=limit_price,
                    wait_fill=True,
                    fill_timeout_s=45.0,
                )
                
                ok = bool(order) and order.get("fill_ok") is True
                if ok:
                    # Get actual fill price
                    try:
                        fill = (order or {}).get("fill") or {}
                        avg = float(fill.get("filled_avg_price") or order.get("filled_avg_price") or 0.0)
                        if avg > 0:
                            actual_cost = abs(avg) * 100.0
                        else:
                            actual_cost = buyback_cost
                    except (TypeError, ValueError):
                        actual_cost = buyback_cost
                    
                    logger.info(
                        "Put buy-to-close executed",
                        symbol=symbol,
                        underlying=underlying,
                        strike=strike,
                        cost=round(actual_cost, 2),
                        collateral_freed=round(collateral, 2),
                    )
                    
                    results.append({
                        "status": "executed",
                        "symbol": symbol,
                        "underlying": underlying,
                        "strike": strike,
                        "limit_price": limit_price,
                        "buyback_cost": round(actual_cost, 2),
                        "collateral_freed": round(collateral, 2),
                        "order": order,
                    })
                    
                    total_spent += actual_cost
                    contracts_closed += 1
                else:
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
        
        # Recalculate free cash after each close
        current_free_cash = free_cash_before + total_spent  # Simplified: spent = collateral freed - cost
        if current_free_cash >= 0:
            logger.info(
                "Free cash restored to non-negative; stopping buyback",
                free_cash=round(current_free_cash, 2),
                contracts_closed=contracts_closed,
            )
            break
    
    # Requirement 6: Log free cash after
    # Refresh positions to get actual final state if we executed
    if execute and contracts_closed > 0:
        try:
            final_account = broker.get_account()
            final_cash = float(final_account.get("cash") or 0.0)
            final_positions = broker.get_option_positions() or []
            final_orders = broker.get_open_orders(limit=100) or []
        except Exception as e:
            logger.warning("Failed to refresh final state", error=str(e))
            final_cash = account_cash
            final_positions = option_positions
            final_orders = open_orders
        
        free_cash_after = calculate_free_cash(final_cash, final_positions, final_orders)
    else:
        free_cash_after = free_cash_before + total_spent
    
    logger.info(
        "Auto put buyback complete",
        execute=execute,
        contracts_closed=contracts_closed,
        total_spent=round(total_spent, 2),
        free_cash_before=round(free_cash_before, 2),
        free_cash_after=round(free_cash_after, 2),
        improvement=round(free_cash_after - free_cash_before, 2),
    )
    
    return results
