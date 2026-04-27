from __future__ import annotations

import math
import time
from typing import Any, Callable

try:
    from .paper_order_manager import create_position_from_result
    from .skill_dispatcher import (
        binance_exchange_info,
        binance_new_algo_order,
        binance_new_order,
        binance_test_order,
    )
except ImportError:
    from paper_order_manager import create_position_from_result
    from skill_dispatcher import (
        binance_exchange_info,
        binance_new_algo_order,
        binance_new_order,
        binance_test_order,
    )


def _count_decimals(value: str) -> int:
    if "." not in value:
        return 0
    return len(value.rstrip("0").split(".")[-1])


def _round_to_step(value: float, step: float, precision: int | None = None) -> float:
    if step <= 0:
        return round(value, precision or 8)
    rounded = math.floor(value / step) * step
    if precision is None:
        return rounded
    return round(rounded, precision)


def _normalize_quantity(quantity: float, exchange_info: dict[str, Any] | None) -> float:
    if quantity <= 0:
        return 0.0
    if not exchange_info:
        return round(quantity, 3)
    filters = exchange_info.get("filters", {})
    lot_filter = filters.get("LOT_SIZE", {})
    step_size = float(lot_filter.get("stepSize", "0") or 0)
    min_qty = float(lot_filter.get("minQty", "0") or 0)
    precision = exchange_info.get("quantityPrecision")
    normalized = _round_to_step(quantity, step_size, precision)
    if min_qty > 0 and normalized < min_qty:
        normalized = min_qty
    return normalized


def _normalize_price(price: float, exchange_info: dict[str, Any] | None) -> float:
    if price <= 0:
        return 0.0
    if not exchange_info:
        return round(price, 6)
    filters = exchange_info.get("filters", {})
    price_filter = filters.get("PRICE_FILTER", {})
    tick_size_raw = str(price_filter.get("tickSize", "0") or 0)
    tick_size = float(tick_size_raw)
    precision = exchange_info.get("pricePrecision")
    if precision is None and tick_size > 0:
        precision = _count_decimals(tick_size_raw)
    return _round_to_step(price, tick_size, precision)


def _build_validation_orders(execution: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    entry = execution.get("entry_order", {})
    stop_loss = execution.get("stop_loss_order", {})
    take_profits = execution.get("take_profit_orders", [])
    items = [("entry", entry), ("stop_loss", stop_loss)]
    for index, order in enumerate(take_profits, 1):
        items.append((f"take_profit_{index}", order))
    return items


def _has_required_protection(plan: dict[str, Any]) -> bool:
    stop_loss = plan.get("stop_loss_order") or {}
    take_profits = plan.get("take_profit_orders") or []
    return bool(stop_loss.get("stop_price")) and len(take_profits) >= 1


def execute_paper_bracket(
    result: dict[str, Any],
    output_dir,
    execution_mode: str = "paper",
    validate_with_binance: bool = False,
    exchange_info_fetcher: Callable[[str], dict[str, Any] | None] = binance_exchange_info,
    order_validator: Callable[..., dict[str, Any]] = binance_test_order,
    entry_runner: Callable[..., dict[str, Any]] = binance_new_order,
    algo_runner: Callable[..., dict[str, Any]] = binance_new_algo_order,
) -> dict[str, Any]:
    plan = result.get("trade_plan") or {}
    execution = dict(plan.get("execution") or {})
    symbol = execution.get("symbol") or f"{result.get('symbol', '').upper()}USDT"
    if not execution or not symbol:
        return {
            "symbol": result.get("symbol", ""),
            "status": "skipped",
            "reason": "missing_execution_plan",
            "protected": False,
            "mode": execution_mode,
        }

    exchange_info = exchange_info_fetcher(symbol.replace("USDT", "")) if exchange_info_fetcher else None
    quantity = _normalize_quantity(float(execution.get("quantity", 0) or 0), exchange_info)
    entry_price = _normalize_price(float(execution.get("entry_price", 0) or 0), exchange_info)
    stop_price = _normalize_price(float(execution.get("stop_loss", 0) or 0), exchange_info)
    tp_orders = []
    for order in execution.get("take_profit_orders", []):
        tp_orders.append({
            **order,
            "stop_price": _normalize_price(float(order.get("stop_price", 0) or 0), exchange_info),
            "quantity": _normalize_quantity(float(order.get("quantity", 0) or 0), exchange_info),
        })

    entry_order = {
        **(execution.get("entry_order") or {}),
        "quantity": quantity,
        "price": entry_price if (execution.get("entry_order") or {}).get("price") is not None else None,
    }
    stop_loss_order = {
        **(execution.get("stop_loss_order") or {}),
        "stop_price": stop_price,
        "quantity": quantity,
    }
    if plan.get("protection_required") and not _has_required_protection({
        "stop_loss_order": stop_loss_order,
        "take_profit_orders": tp_orders,
    }):
        return {
            "symbol": symbol,
            "status": "rejected_unprotected",
            "reason": "protection_required_but_incomplete",
            "protected": False,
            "mode": execution_mode,
        }

    validation: dict[str, Any] = {}
    if validate_with_binance and execution_mode in {"paper_validate", "binance_live"}:
        for label, order in _build_validation_orders({
            "entry_order": entry_order,
            "stop_loss_order": stop_loss_order,
            "take_profit_orders": tp_orders,
        }):
            params = {
                "symbol": symbol,
                "side": order.get("side"),
                "type": order.get("type"),
                "quantity": order.get("quantity"),
                "price": order.get("price"),
                "stop_price": order.get("stop_price"),
                "activation_price": order.get("activate_price"),
                "callback_rate": order.get("callback_rate"),
                "reduce_only": order.get("reduce_only"),
                "working_type": order.get("working_type"),
                "price_protect": order.get("price_protect"),
                "time_in_force": order.get("time_in_force"),
            }
            validation[label] = order_validator(**params)

    live_entry = None
    live_stop = None
    live_take_profits: list[dict[str, Any]] = []
    if execution_mode == "binance_live":
        live_entry = entry_runner(
            symbol=symbol,
            side=entry_order.get("side"),
            type=entry_order.get("type"),
            quantity=entry_order.get("quantity"),
            price=entry_order.get("price"),
            time_in_force=entry_order.get("time_in_force"),
            new_order_resp_type="RESULT",
        )
        if live_entry.get("ok"):
            live_stop = algo_runner(
                algo_type=stop_loss_order.get("algo_type", "STOP_MARKET"),
                symbol=symbol,
                side=stop_loss_order.get("side"),
                type=stop_loss_order.get("type"),
                quantity=stop_loss_order.get("quantity"),
                trigger_price=stop_loss_order.get("stop_price"),
                activate_price=stop_loss_order.get("activate_price"),
                callback_rate=stop_loss_order.get("callback_rate"),
                reduce_only=stop_loss_order.get("reduce_only"),
                working_type=stop_loss_order.get("working_type"),
                price_protect=stop_loss_order.get("price_protect"),
            )
            for order in tp_orders:
                live_take_profits.append(
                    algo_runner(
                        algo_type="TAKE_PROFIT_MARKET",
                        symbol=symbol,
                        side=order.get("side"),
                        type=order.get("type"),
                        quantity=order.get("quantity"),
                        trigger_price=order.get("stop_price"),
                        reduce_only=order.get("reduce_only"),
                        working_type=order.get("working_type"),
                        price_protect=order.get("price_protect"),
                    )
                )
    execution["quantity"] = quantity
    execution["entry_price"] = entry_price
    execution["stop_loss"] = stop_price
    execution["entry_order"] = entry_order
    execution["stop_loss_order"] = stop_loss_order
    execution["take_profit_orders"] = tp_orders
    plan["execution"] = execution
    result["trade_plan"] = plan

    payload = create_position_from_result(
        result,
        output_dir=output_dir,
        execution_mode=execution_mode,
        validation=validation,
    )
    payload["entry_order"] = entry_order
    payload["stop_loss_order"] = stop_loss_order
    payload["take_profit_orders"] = tp_orders
    payload["protected"] = True
    payload["mode"] = execution_mode
    payload["live_entry"] = live_entry
    payload["live_stop_loss"] = live_stop
    payload["live_take_profits"] = live_take_profits
    if execution_mode == "paper_validate" and validation:
        payload["status"] = "validated" if all(item.get("ok") for item in validation.values()) else "paper_validation_failed"
    elif execution_mode == "binance_live":
        payload["status"] = "live_submitted" if live_entry and live_entry.get("ok") else "live_submit_failed"
    return payload
