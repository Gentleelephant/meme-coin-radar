from __future__ import annotations

from dataclasses import dataclass
from typing import Any

try:
    from .history_store import append_closed_position, load_closed_positions, save_paper_metrics
    from .paper_order_manager import (
        ORDER_ACTIVE,
        ORDER_CANCELED,
        ORDER_EXPIRED,
        ORDER_FILLED,
        ORDER_TRIGGERED,
        POSITION_CANCELED,
        POSITION_CLOSED,
        POSITION_LIQUIDATED,
        POSITION_OPEN,
        POSITION_PARTIALLY_CLOSED,
        POSITION_PENDING,
        load_state,
        record_event,
        save_state,
    )
except ImportError:
    from history_store import append_closed_position, load_closed_positions, save_paper_metrics
    from paper_order_manager import (
        ORDER_ACTIVE,
        ORDER_CANCELED,
        ORDER_EXPIRED,
        ORDER_FILLED,
        ORDER_TRIGGERED,
        POSITION_CANCELED,
        POSITION_CLOSED,
        POSITION_LIQUIDATED,
        POSITION_OPEN,
        POSITION_PARTIALLY_CLOSED,
        POSITION_PENDING,
        load_state,
        record_event,
        save_state,
    )


@dataclass
class PriceTick:
    open: float
    high: float
    low: float
    close: float
    volume: float
    timestamp: int


def ticks_from_klines(klines: list | None) -> list[PriceTick]:
    ticks: list[PriceTick] = []
    for idx, item in enumerate(klines or []):
        if not isinstance(item, (list, tuple)) or len(item) < 5:
            continue
        try:
            timestamp = int(item[5]) if len(item) > 5 else idx
            ticks.append(
                PriceTick(
                    open=float(item[0]),
                    high=float(item[1]),
                    low=float(item[2]),
                    close=float(item[3]),
                    volume=float(item[4]),
                    timestamp=timestamp,
                )
            )
        except (TypeError, ValueError):
            continue
    return ticks


def _apply_slippage(price: float, direction: str, bps: float, favorable: bool = False) -> float:
    if price <= 0:
        return price
    sign = -1 if favorable else 1
    if direction == "short":
        sign *= -1
    return price * (1 + sign * bps / 10000)


def _position_notional(position: dict[str, Any]) -> float:
    return float(position.get("remaining_qty", 0.0)) * float(position.get("entry_avg_price") or position.get("planned_entry_price") or 0.0)


def _compute_unrealized(position: dict[str, Any], mark_price: float) -> float:
    qty = float(position.get("remaining_qty", 0.0))
    entry = float(position.get("entry_avg_price") or position.get("planned_entry_price") or 0.0)
    if qty <= 0 or entry <= 0 or mark_price <= 0:
        return 0.0
    if position.get("direction") == "long":
        return (mark_price - entry) * qty
    return (entry - mark_price) * qty


def _realize_close(position: dict[str, Any], qty: float, price: float, fee_bps: float) -> tuple[float, float]:
    entry = float(position.get("entry_avg_price") or position.get("planned_entry_price") or 0.0)
    if qty <= 0 or entry <= 0:
        return 0.0, 0.0
    pnl = (price - entry) * qty if position.get("direction") == "long" else (entry - price) * qty
    fee = abs(price * qty) * fee_bps / 10000
    return pnl - fee, fee


def reconcile_all_positions(
    output_dir,
    tick_map: dict[str, list[PriceTick]],
    fee_bps: float = 4.0,
    slippage_bps: float = 3.0,
    entry_expire_bars: int = 6,
    position_max_age_bars: int = 48,
    tp1_hit_timeout_bars: int = 24,
) -> dict[str, Any]:
    state = load_state(output_dir)
    positions = state["positions"]
    orders = state["orders"]
    account = state["account"] or {}

    updated_positions: list[dict[str, Any]] = []
    closed_positions: list[dict[str, Any]] = []

    for symbol, position in list(positions.items()):
        ticks = [tick for tick in tick_map.get(symbol, []) if tick.timestamp > int(position.get("last_reconciled_ts") or 0)]
        if not ticks:
            continue

        entry_order = orders.get((position.get("entry_order_ids") or [None])[0])
        stop_ids = position.get("stop_loss_order_ids") or []
        tp_ids = position.get("take_profit_order_ids") or []
        stop_order = orders.get(stop_ids[0]) if stop_ids else None
        tp_orders = [orders[oid] for oid in tp_ids if oid in orders]

        for tick in ticks:
            position["age_bars"] = int(position.get("age_bars", 0)) + 1
            position["last_reconciled_ts"] = tick.timestamp

            if position["status"] == POSITION_PENDING and entry_order:
                should_fill = False
                fill_price = 0.0
                if entry_order.get("order_type") == "MARKET":
                    should_fill = True
                    fill_price = _apply_slippage(tick.open, position.get("direction"), slippage_bps)
                elif entry_order.get("order_type") == "LIMIT":
                    limit_price = float(entry_order.get("price") or 0.0)
                    if limit_price > 0 and tick.low <= limit_price <= tick.high:
                        should_fill = True
                        fill_price = _apply_slippage(limit_price, position.get("direction"), slippage_bps)

                if should_fill:
                    entry_order["status"] = ORDER_FILLED
                    entry_order["filled_at"] = tick.timestamp
                    entry_order["fill_price"] = fill_price
                    entry_order["fill_qty"] = float(entry_order.get("quantity") or 0.0)
                    fee = abs(fill_price * entry_order["fill_qty"]) * fee_bps / 10000
                    entry_order["fee_paid"] = fee
                    position["entry_avg_price"] = fill_price
                    position["opened_qty"] = entry_order["fill_qty"]
                    position["remaining_qty"] = entry_order["fill_qty"]
                    position["fee_paid"] = float(position.get("fee_paid", 0.0)) + fee
                    position["status"] = POSITION_OPEN
                    position["opened_at"] = tick.timestamp
                    if stop_order:
                        stop_order["status"] = ORDER_ACTIVE
                    for order in tp_orders:
                        order["status"] = ORDER_ACTIVE
                    record_event(output_dir, position, entry_order.get("order_id"), "POSITION_OPENED", {"fill_price": fill_price})
                elif position["age_bars"] >= entry_expire_bars:
                    position["status"] = POSITION_CANCELED
                    position["closed_at"] = tick.timestamp
                    entry_order["status"] = ORDER_EXPIRED
                    if stop_order:
                        stop_order["status"] = ORDER_CANCELED
                    for order in tp_orders:
                        order["status"] = ORDER_CANCELED
                    record_event(output_dir, position, entry_order.get("order_id"), "POSITION_CANCELED", {"reason": "entry_expired"})

            if position["status"] not in {POSITION_OPEN, POSITION_PARTIALLY_CLOSED}:
                continue

            entry_price = float(position.get("entry_avg_price") or 0.0)
            remaining_qty = float(position.get("remaining_qty") or 0.0)
            if remaining_qty <= 0:
                continue

            unrealized = _compute_unrealized(position, tick.close)
            position["unrealized_pnl"] = unrealized
            mfe = (tick.high - entry_price) if position.get("direction") == "long" else (entry_price - tick.low)
            mae = (entry_price - tick.low) if position.get("direction") == "long" else (tick.high - entry_price)
            position["max_favorable_excursion"] = max(float(position.get("max_favorable_excursion", 0.0)), mfe)
            position["max_adverse_excursion"] = max(float(position.get("max_adverse_excursion", 0.0)), mae)

            liquidation_price = position.get("liquidation_price")
            if liquidation_price:
                if position.get("direction") == "long" and tick.low <= liquidation_price:
                    pnl, fee = _realize_close(position, remaining_qty, float(liquidation_price), fee_bps)
                    position["realized_pnl"] = float(position.get("realized_pnl", 0.0)) + pnl
                    position["fee_paid"] = float(position.get("fee_paid", 0.0)) + fee
                    position["closed_qty"] = float(position.get("closed_qty", 0.0)) + remaining_qty
                    position["remaining_qty"] = 0.0
                    position["status"] = POSITION_LIQUIDATED
                    position["closed_at"] = tick.timestamp
                    position["exit_reason"] = "liquidation"
                    if stop_order:
                        stop_order["status"] = ORDER_CANCELED
                    for order in tp_orders:
                        order["status"] = ORDER_CANCELED
                    record_event(output_dir, position, None, "POSITION_LIQUIDATED", {"price": liquidation_price})
                    break
                if position.get("direction") == "short" and tick.high >= liquidation_price:
                    pnl, fee = _realize_close(position, remaining_qty, float(liquidation_price), fee_bps)
                    position["realized_pnl"] = float(position.get("realized_pnl", 0.0)) + pnl
                    position["fee_paid"] = float(position.get("fee_paid", 0.0)) + fee
                    position["closed_qty"] = float(position.get("closed_qty", 0.0)) + remaining_qty
                    position["remaining_qty"] = 0.0
                    position["status"] = POSITION_LIQUIDATED
                    position["closed_at"] = tick.timestamp
                    position["exit_reason"] = "liquidation"
                    if stop_order:
                        stop_order["status"] = ORDER_CANCELED
                    for order in tp_orders:
                        order["status"] = ORDER_CANCELED
                    record_event(output_dir, position, None, "POSITION_LIQUIDATED", {"price": liquidation_price})
                    break

            check_stop_first = position.get("direction") == "long"
            ordered_checks = []
            if check_stop_first:
                ordered_checks.append(("stop", stop_order))
                ordered_checks.extend(("tp", order) for order in tp_orders)
            else:
                ordered_checks.extend(("tp", order) for order in tp_orders)
                ordered_checks.append(("stop", stop_order))

            triggered = False
            for order_type, order in ordered_checks:
                if not order or order.get("status") != ORDER_ACTIVE:
                    continue
                trigger_price = float(order.get("trigger_price") or 0.0)
                if trigger_price <= 0:
                    continue
                hit = False
                if order_type == "stop":
                    hit = tick.low <= trigger_price if position.get("direction") == "long" else tick.high >= trigger_price
                else:
                    hit = tick.high >= trigger_price if position.get("direction") == "long" else tick.low <= trigger_price
                if not hit:
                    continue

                order["status"] = ORDER_TRIGGERED
                order["triggered_at"] = tick.timestamp
                fill_price = _apply_slippage(trigger_price, position.get("direction"), slippage_bps, favorable=(order_type == "tp"))
                fill_qty = min(float(order.get("quantity") or remaining_qty), float(position.get("remaining_qty") or 0.0))
                pnl, fee = _realize_close(position, fill_qty, fill_price, fee_bps)
                position["realized_pnl"] = float(position.get("realized_pnl", 0.0)) + pnl
                position["fee_paid"] = float(position.get("fee_paid", 0.0)) + fee
                position["closed_qty"] = float(position.get("closed_qty", 0.0)) + fill_qty
                position["remaining_qty"] = max(float(position.get("remaining_qty", 0.0)) - fill_qty, 0.0)
                order["status"] = ORDER_FILLED
                order["filled_at"] = tick.timestamp
                order["fill_price"] = fill_price
                order["fill_qty"] = fill_qty
                order["fee_paid"] = fee
                event_type = "STOP_LOSS_HIT" if order_type == "stop" else "TAKE_PROFIT_HIT"
                record_event(output_dir, position, order.get("order_id"), event_type, {"fill_price": fill_price, "fill_qty": fill_qty})

                if order_type == "tp":
                    if not position.get("tp1_hit"):
                        position["tp1_hit"] = True
                        position["bars_since_tp1"] = 0
                    if position["remaining_qty"] > 0:
                        position["status"] = POSITION_PARTIALLY_CLOSED
                        if stop_order and stop_order.get("status") == ORDER_ACTIVE:
                            stop_order["quantity"] = position["remaining_qty"]
                    else:
                        position["status"] = POSITION_CLOSED
                        position["closed_at"] = tick.timestamp
                        position["exit_reason"] = "take_profit"
                        if stop_order and stop_order.get("status") == ORDER_ACTIVE:
                            stop_order["status"] = ORDER_CANCELED
                        for other in tp_orders:
                            if other.get("status") == ORDER_ACTIVE:
                                other["status"] = ORDER_CANCELED
                else:
                    position["status"] = POSITION_CLOSED
                    position["closed_at"] = tick.timestamp
                    position["exit_reason"] = "stop_loss"
                    for other in tp_orders:
                        if other.get("status") == ORDER_ACTIVE:
                            other["status"] = ORDER_CANCELED
                triggered = True
                break

            if triggered and position["status"] in {POSITION_CLOSED, POSITION_LIQUIDATED}:
                break

            if position.get("tp1_hit"):
                position["bars_since_tp1"] = int(position.get("bars_since_tp1") or 0) + 1
                if position["remaining_qty"] > 0 and position["bars_since_tp1"] >= tp1_hit_timeout_bars:
                    close_price = tick.close
                    fill_qty = float(position.get("remaining_qty") or 0.0)
                    pnl, fee = _realize_close(position, fill_qty, close_price, fee_bps)
                    position["realized_pnl"] = float(position.get("realized_pnl", 0.0)) + pnl
                    position["fee_paid"] = float(position.get("fee_paid", 0.0)) + fee
                    position["closed_qty"] = float(position.get("closed_qty", 0.0)) + fill_qty
                    position["remaining_qty"] = 0.0
                    position["status"] = POSITION_CLOSED
                    position["closed_at"] = tick.timestamp
                    position["exit_reason"] = "tp1_timeout"
                    if stop_order and stop_order.get("status") == ORDER_ACTIVE:
                        stop_order["status"] = ORDER_CANCELED
                    for other in tp_orders:
                        if other.get("status") == ORDER_ACTIVE:
                            other["status"] = ORDER_CANCELED
                    record_event(output_dir, position, None, "POSITION_CLOSED", {"reason": "tp1_timeout", "price": close_price})
                    break

            if position["age_bars"] >= position_max_age_bars and position["remaining_qty"] > 0:
                close_price = tick.close
                fill_qty = float(position.get("remaining_qty") or 0.0)
                pnl, fee = _realize_close(position, fill_qty, close_price, fee_bps)
                position["realized_pnl"] = float(position.get("realized_pnl", 0.0)) + pnl
                position["fee_paid"] = float(position.get("fee_paid", 0.0)) + fee
                position["closed_qty"] = float(position.get("closed_qty", 0.0)) + fill_qty
                position["remaining_qty"] = 0.0
                position["status"] = POSITION_CLOSED
                position["closed_at"] = tick.timestamp
                position["exit_reason"] = "position_timeout"
                if stop_order and stop_order.get("status") == ORDER_ACTIVE:
                    stop_order["status"] = ORDER_CANCELED
                for other in tp_orders:
                    if other.get("status") == ORDER_ACTIVE:
                        other["status"] = ORDER_CANCELED
                record_event(output_dir, position, None, "POSITION_CLOSED", {"reason": "position_timeout", "price": close_price})
                break

        if position["status"] in {POSITION_CLOSED, POSITION_LIQUIDATED, POSITION_CANCELED}:
            closed_positions.append(position.copy())
            append_closed_position(output_dir, position)
            positions.pop(symbol, None)
        else:
            updated_positions.append(position)

    total_realized = sum(float(pos.get("realized_pnl", 0.0)) for pos in positions.values())
    total_unrealized = sum(float(pos.get("unrealized_pnl", 0.0)) for pos in positions.values())
    used_margin = sum(float(pos.get("margin", 0.0)) for pos in positions.values() if pos.get("status") in {POSITION_PENDING, POSITION_OPEN, POSITION_PARTIALLY_CLOSED})
    liquidation_threshold = sum(float(pos.get("liquidation_threshold", 0.0)) for pos in positions.values() if pos.get("status") in {POSITION_PENDING, POSITION_OPEN, POSITION_PARTIALLY_CLOSED})

    starting_equity = float(account.get("starting_equity", 10000.0) or 10000.0)
    fees_paid = sum(float(pos.get("fee_paid", 0.0)) for pos in positions.values()) + sum(float(pos.get("fee_paid", 0.0)) for pos in closed_positions)
    current_equity = starting_equity + float(account.get("realized_pnl", 0.0)) + total_realized + total_unrealized - fees_paid
    account["used_margin"] = used_margin
    account["free_margin"] = max(current_equity - used_margin, 0.0)
    account["available_equity"] = account["free_margin"]
    account["realized_pnl"] = float(account.get("realized_pnl", 0.0)) + sum(float(pos.get("realized_pnl", 0.0)) for pos in closed_positions)
    account["unrealized_pnl"] = total_unrealized
    account["fees_paid"] = fees_paid
    account["total_equity"] = current_equity
    account["current_equity"] = current_equity
    account["peak_equity"] = max(float(account.get("peak_equity", starting_equity)), current_equity)
    peak = float(account.get("peak_equity", current_equity))
    account["max_drawdown"] = max(float(account.get("max_drawdown", 0.0)), (peak - current_equity) / peak if peak > 0 else 0.0)
    account["liquidation_threshold"] = liquidation_threshold

    save_state(output_dir, positions, orders, account)
    metrics = compute_metrics(output_dir, account, positions)
    save_paper_metrics(output_dir, metrics)
    return {
        "updated_positions": len(updated_positions),
        "closed_positions": len(closed_positions),
        "account": account,
        "metrics": metrics,
    }


def compute_metrics(output_dir, account: dict[str, Any], open_positions: dict[str, Any] | None = None) -> dict[str, Any]:
    closed = load_closed_positions(output_dir)
    total = len(closed)
    wins = [pos for pos in closed if float(pos.get("realized_pnl", 0.0)) > 0]
    losses = [pos for pos in closed if float(pos.get("realized_pnl", 0.0)) <= 0]
    tp1_hits = [pos for pos in closed if pos.get("tp1_hit")]
    full_tp = [pos for pos in closed if pos.get("exit_reason") == "take_profit"]
    stop_losses = [pos for pos in closed if pos.get("exit_reason") == "stop_loss"]
    profit_sum = sum(float(pos.get("realized_pnl", 0.0)) for pos in wins)
    loss_sum = abs(sum(float(pos.get("realized_pnl", 0.0)) for pos in losses))
    raw_win_rate = len(wins) / total if total else 0.0
    tp1_hit_rate = len(tp1_hits) / total if total else 0.0
    full_tp_rate = len(full_tp) / total if total else 0.0
    stop_loss_rate = len(stop_losses) / total if total else 0.0
    profit_factor = profit_sum / loss_sum if loss_sum > 0 else None

    breakdown: dict[str, Any] = {"strategy_mode": {}, "candidate_source": {}}
    for pos in closed:
        mode = str(pos.get("strategy_mode") or "unknown")
        breakdown["strategy_mode"].setdefault(mode, {"trades": 0, "wins": 0, "net_pnl": 0.0})
        breakdown["strategy_mode"][mode]["trades"] += 1
        breakdown["strategy_mode"][mode]["wins"] += 1 if float(pos.get("realized_pnl", 0.0)) > 0 else 0
        breakdown["strategy_mode"][mode]["net_pnl"] += float(pos.get("realized_pnl", 0.0))
        for source in pos.get("candidate_sources", []) or []:
            breakdown["candidate_source"].setdefault(source, {"trades": 0, "wins": 0, "net_pnl": 0.0})
            breakdown["candidate_source"][source]["trades"] += 1
            breakdown["candidate_source"][source]["wins"] += 1 if float(pos.get("realized_pnl", 0.0)) > 0 else 0
            breakdown["candidate_source"][source]["net_pnl"] += float(pos.get("realized_pnl", 0.0))

    return {
        "total_trades": total,
        "raw_win_rate": raw_win_rate,
        "tp1_hit_rate": tp1_hit_rate,
        "full_tp_rate": full_tp_rate,
        "stop_loss_rate": stop_loss_rate,
        "profit_factor": profit_factor,
        "net_pnl": float(account.get("realized_pnl", 0.0)),
        "current_equity": float(account.get("current_equity", account.get("total_equity", 0.0))),
        "open_positions": len(open_positions or {}),
        "breakdown": breakdown,
    }
