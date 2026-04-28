from __future__ import annotations

import copy
import time
import uuid
from typing import Any

try:
    from .history_store import (
        append_paper_event,
        load_paper_account,
        load_paper_orders,
        load_paper_positions,
        save_paper_account,
        save_paper_orders,
        save_paper_positions,
    )
    from .paper_analytics import data_quality_tier
except ImportError:
    from history_store import (
        append_paper_event,
        load_paper_account,
        load_paper_orders,
        load_paper_positions,
        save_paper_account,
        save_paper_orders,
        save_paper_positions,
    )
    from paper_analytics import data_quality_tier


ORDER_NEW = "NEW"
ORDER_ACTIVE = "ACTIVE"
ORDER_TRIGGERED = "TRIGGERED"
ORDER_PARTIALLY_FILLED = "PARTIALLY_FILLED"
ORDER_FILLED = "FILLED"
ORDER_REJECTED = "REJECTED"
ORDER_CANCELED = "CANCELED"
ORDER_EXPIRED = "EXPIRED"

POSITION_PENDING = "PENDING"
POSITION_OPEN = "OPEN"
POSITION_PARTIALLY_CLOSED = "PARTIALLY_CLOSED"
POSITION_CLOSED = "CLOSED"
POSITION_LIQUIDATED = "LIQUIDATED"
POSITION_REJECTED = "REJECTED"
POSITION_CANCELED = "CANCELED"


def _now_ts() -> int:
    return int(time.time())


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def load_state(output_dir) -> dict[str, Any]:
    return {
        "positions": load_paper_positions(output_dir),
        "orders": load_paper_orders(output_dir),
        "account": load_paper_account(output_dir),
    }


def save_state(output_dir, positions: dict[str, Any], orders: dict[str, Any], account: dict[str, Any]) -> None:
    save_paper_positions(output_dir, positions)
    save_paper_orders(output_dir, orders)
    save_paper_account(output_dir, account)


def ensure_account(output_dir, starting_equity: float = 10000.0) -> dict[str, Any]:
    account = load_paper_account(output_dir)
    if account:
        return account
    account = {
        "starting_equity": starting_equity,
        "total_equity": starting_equity,
        "current_equity": starting_equity,
        "available_equity": starting_equity,
        "used_margin": 0.0,
        "free_margin": starting_equity,
        "realized_pnl": 0.0,
        "unrealized_pnl": 0.0,
        "fees_paid": 0.0,
        "closed_entry_fees_paid": 0.0,
        "closed_total_fees_paid": 0.0,
        "peak_equity": starting_equity,
        "max_drawdown": 0.0,
        "liquidation_threshold": 0.0,
        "updated_at": _now_ts(),
    }
    save_paper_account(output_dir, account)
    return account


def create_position_from_result(
    result: dict[str, Any],
    output_dir,
    execution_mode: str = "paper",
    validation: dict[str, Any] | None = None,
    existing_position_policy: str = "skip",
) -> dict[str, Any]:
    state = load_state(output_dir)
    positions = state["positions"]
    orders = state["orders"]
    account = ensure_account(output_dir)

    plan = result.get("trade_plan") or {}
    execution = copy.deepcopy(plan.get("execution") or {})
    social_snapshot = copy.deepcopy((result.get("meta") or {}).get("social_intel") or {})
    symbol = execution.get("symbol") or f"{result.get('symbol', '').upper()}USDT"
    if not execution or not symbol:
        return {
            "symbol": symbol,
            "status": "skipped",
            "reason": "missing_execution_plan",
            "protected": False,
            "mode": execution_mode,
        }

    existing = positions.get(symbol)
    if isinstance(existing, dict) and existing.get("status") in {
        POSITION_PENDING,
        POSITION_OPEN,
        POSITION_PARTIALLY_CLOSED,
    }:
        return {
            "symbol": symbol,
            "status": "skipped_existing_position",
            "reason": "open_position_exists",
            "protected": bool(existing.get("protected")),
            "mode": execution_mode,
            "existing_position": existing,
        }

    position_id = _new_id("pos")
    created_at = _now_ts()
    quality_score = int((result.get("module_scores") or {}).get("data_quality", 0) or 0)

    entry_order_id = _new_id("ord")
    stop_loss_order_id = _new_id("ord")
    tp_order_ids = [_new_id("ord") for _ in execution.get("take_profit_orders", [])]

    leverage = int(execution.get("leverage") or 1)
    quantity = float(execution.get("quantity") or 0.0)
    entry_price = float(execution.get("entry_price") or 0.0)
    notional = quantity * entry_price
    margin = notional / leverage if leverage > 0 else notional
    liquidation_threshold = margin * 0.9
    liquidation_price = None
    stop_loss = float(execution.get("stop_loss") or 0.0)
    if quantity > 0:
        liquidation_move = liquidation_threshold / quantity
        liquidation_price = entry_price - liquidation_move if result.get("direction") == "long" else entry_price + liquidation_move

    entry_order = {
        "order_id": entry_order_id,
        "position_id": position_id,
        "symbol": symbol,
        "side": execution.get("entry_order", {}).get("side"),
        "order_role": "ENTRY",
        "order_type": execution.get("entry_order", {}).get("type"),
        "quantity": quantity,
        "price": execution.get("entry_order", {}).get("price"),
        "trigger_price": None,
        "reduce_only": False,
        "status": ORDER_ACTIVE,
        "created_at": created_at,
        "triggered_at": None,
        "filled_at": None,
        "fill_price": None,
        "fill_qty": 0.0,
        "fee_paid": 0.0,
    }
    orders[entry_order_id] = entry_order

    stop_loss_order = {
        "order_id": stop_loss_order_id,
        "position_id": position_id,
        "symbol": symbol,
        "side": execution.get("stop_loss_order", {}).get("side"),
        "order_role": "STOP_LOSS",
        "order_type": execution.get("stop_loss_order", {}).get("type"),
        "quantity": quantity,
        "price": None,
        "trigger_price": execution.get("stop_loss_order", {}).get("stop_price"),
        "reduce_only": True,
        "algo_type": execution.get("stop_loss_order", {}).get("algo_type"),
        "status": ORDER_NEW,
        "created_at": created_at,
        "triggered_at": None,
        "filled_at": None,
        "fill_price": None,
        "fill_qty": 0.0,
        "fee_paid": 0.0,
        "activate_price": execution.get("stop_loss_order", {}).get("activate_price"),
        "callback_rate": execution.get("stop_loss_order", {}).get("callback_rate"),
        "trailing": copy.deepcopy(execution.get("stop_loss_order", {}).get("trailing") or {}),
    }
    orders[stop_loss_order_id] = stop_loss_order

    take_profit_order_ids: list[str] = []
    for order_id, order_payload in zip(tp_order_ids, execution.get("take_profit_orders", [])):
        take_profit_order_ids.append(order_id)
        orders[order_id] = {
            "order_id": order_id,
            "position_id": position_id,
            "symbol": symbol,
            "side": order_payload.get("side"),
            "order_role": "TAKE_PROFIT",
            "order_type": order_payload.get("type"),
            "quantity": float(order_payload.get("quantity") or 0.0),
            "price": None,
            "trigger_price": order_payload.get("stop_price"),
            "reduce_only": True,
            "status": ORDER_NEW,
            "created_at": created_at,
            "triggered_at": None,
            "filled_at": None,
            "fill_price": None,
            "fill_qty": 0.0,
            "fee_paid": 0.0,
            "fraction": order_payload.get("fraction"),
        }

    position = {
        "position_id": position_id,
        "symbol": symbol,
        "strategy_mode": result.get("strategy_mode"),
        "plan_profile": plan.get("plan_profile"),
        "protection_strategy": plan.get("protection_strategy", plan.get("trailing_mode", "fixed")),
        "tp1_fraction": float(plan.get("tp1_fraction") or 0.0),
        "why_this_plan": plan.get("why_this_plan"),
        "decision": result.get("decision"),
        "direction": result.get("direction"),
        "candidate_sources": result.get("candidate_sources", []),
        "oos": result.get("oos", 0),
        "ers": result.get("ers", 0),
        "final_score": result.get("final_score", result.get("total", 0)),
        "data_quality_score": quality_score,
        "data_quality_tier": data_quality_tier(quality_score),
        "entry_reasons": result.get("entry_reasons", []),
        "risk_notes": result.get("risk_notes", []),
        "social_snapshot": social_snapshot,
        "narrative_labels": social_snapshot.get("narrative_labels", []),
        "trailing_mode": str((execution.get("stop_loss_order", {}).get("trailing") or {}).get("mode") or "none"),
        "trailing_active": False,
        "trailing_anchor_price": None,
        "entry_order_ids": [entry_order_id],
        "stop_loss_order_ids": [stop_loss_order_id],
        "take_profit_order_ids": take_profit_order_ids,
        "planned_entry_price": entry_price,
        "planned_stop_loss": stop_loss,
        "planned_take_profit_1": float(execution.get("take_profit_orders", [{}])[0].get("stop_price") or 0.0) if execution.get("take_profit_orders") else 0.0,
        "planned_take_profit_2": float(execution.get("take_profit_orders", [{}, {}])[1].get("stop_price") or 0.0) if len(execution.get("take_profit_orders", [])) > 1 else 0.0,
        "entry_avg_price": None,
        "opened_qty": 0.0,
        "closed_qty": 0.0,
        "remaining_qty": quantity,
        "realized_pnl": 0.0,
        "unrealized_pnl": 0.0,
        "fee_paid": 0.0,
        "entry_fee_paid": 0.0,
        "max_favorable_excursion": 0.0,
        "max_adverse_excursion": 0.0,
        "leverage": leverage,
        "margin": margin,
        "liquidation_price": liquidation_price,
        "liquidation_threshold": liquidation_threshold,
        "status": POSITION_PENDING,
        "mode": execution_mode,
        "protected": True,
        "validation": validation or {},
        "trade_plan": plan,
        "meta_snapshot": result.get("meta", {}),
        "created_at": created_at,
        "opened_at": None,
        "closed_at": None,
        "last_reconciled_ts": 0,
        "age_bars": 0,
        "bars_since_tp1": None,
        "tp1_hit": False,
        "exit_reason": None,
    }
    positions[symbol] = position

    account["used_margin"] = float(account.get("used_margin", 0.0)) + margin
    account["free_margin"] = max(float(account.get("total_equity", account.get("current_equity", 0.0))) - account["used_margin"], 0.0)
    account["available_equity"] = account["free_margin"]
    account["liquidation_threshold"] = float(account.get("liquidation_threshold", 0.0)) + liquidation_threshold
    account["updated_at"] = created_at

    save_state(output_dir, positions, orders, account)

    append_paper_event(output_dir, {
        "event_id": _new_id("evt"),
        "position_id": position_id,
        "order_id": entry_order_id,
        "event_type": "POSITION_CREATED",
        "payload": {"symbol": symbol},
        "snapshot": position,
        "ts": created_at,
    })
    return position


def record_event(output_dir, position: dict[str, Any], order_id: str | None, event_type: str, payload: dict[str, Any] | None = None) -> None:
    append_paper_event(output_dir, {
        "event_id": _new_id("evt"),
        "position_id": position.get("position_id"),
        "order_id": order_id,
        "event_type": event_type,
        "payload": payload or {},
        "snapshot": position,
        "ts": _now_ts(),
    })
