#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from history_store import load_paper_account, load_paper_metrics, load_paper_orders, load_paper_positions
from paper_analytics import compute_metrics


def _fmt_money(value: float) -> str:
    return f"{value:,.2f}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Show current paper trading account and position status.")
    parser.add_argument("--dir", default=None, help="Radar output directory containing history/")
    args = parser.parse_args()

    output_dir = Path(args.dir).expanduser().resolve() if args.dir else Path.cwd()
    account = load_paper_account(output_dir)
    positions = load_paper_positions(output_dir)
    orders = load_paper_orders(output_dir)
    metrics = load_paper_metrics(output_dir) or compute_metrics(output_dir, account, positions)

    print("=== Paper Trading Status ===")
    if account:
        print(
            "Account: "
            f"equity={_fmt_money(float(account.get('current_equity', account.get('total_equity', 0.0))))} "
            f"free_margin={_fmt_money(float(account.get('free_margin', 0.0)))} "
            f"used_margin={_fmt_money(float(account.get('used_margin', 0.0)))} "
            f"realized_pnl={_fmt_money(float(account.get('realized_pnl', 0.0)))} "
            f"unrealized_pnl={_fmt_money(float(account.get('unrealized_pnl', 0.0)))}"
        )
    else:
        print("Account: no paper account state found")

    print(
        "Metrics: "
        f"closed_trades={metrics.get('total_trades', 0)} "
        f"win_rate={metrics.get('raw_win_rate', 0.0) * 100:.1f}% "
        f"tp1_hit_rate={metrics.get('tp1_hit_rate', 0.0) * 100:.1f}% "
        f"net_pnl={_fmt_money(float(metrics.get('net_pnl', 0.0)))}"
    )

    open_positions = list(positions.values())
    print(f"Open positions: {len(open_positions)}")
    for position in open_positions:
        print(
            f"- {position.get('symbol')} "
            f"status={position.get('status')} "
            f"direction={position.get('direction')} "
            f"remaining_qty={position.get('remaining_qty', 0)} "
            f"entry={position.get('entry_avg_price') or position.get('planned_entry_price')} "
            f"uPnL={_fmt_money(float(position.get('unrealized_pnl', 0.0)))}"
        )

    active_orders = [order for order in orders.values() if order.get("status") in {"NEW", "ACTIVE", "TRIGGERED"}]
    print(f"Active orders: {len(active_orders)}")
    for order in active_orders[:20]:
        trigger = order.get("trigger_price")
        trigger_text = f" trigger={trigger}" if trigger else ""
        print(f"- {order.get('symbol')} {order.get('order_role')} {order.get('status')} qty={order.get('quantity')}{trigger_text}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
