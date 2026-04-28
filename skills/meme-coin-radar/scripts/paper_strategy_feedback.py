#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from .history_store import (
        load_closed_positions,
        load_paper_account,
        load_paper_metrics,
        save_paper_strategy_feedback,
    )
    from .paper_analytics import compute_metrics_from_closed
except ImportError:
    from history_store import (
        load_closed_positions,
        load_paper_account,
        load_paper_metrics,
        save_paper_strategy_feedback,
    )
    from paper_analytics import compute_metrics_from_closed


def _best_groups(groups: dict[str, dict[str, Any]], *, min_trades: int = 3, top_n: int = 3) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for key, stats in (groups or {}).items():
        trades = int(stats.get("trades", 0))
        if trades < min_trades:
            continue
        items.append(
            {
                "group": key,
                "trades": trades,
                "raw_win_rate": float(stats.get("raw_win_rate", 0.0)),
                "tp1_hit_rate": float(stats.get("tp1_hit_rate", 0.0)),
                "full_tp_rate": float(stats.get("full_tp_rate", 0.0)),
                "stop_loss_rate": float(stats.get("stop_loss_rate", 0.0)),
                "net_pnl": float(stats.get("net_pnl", 0.0)),
            }
        )
    items.sort(key=lambda item: (item["raw_win_rate"], item["net_pnl"], item["tp1_hit_rate"]), reverse=True)
    return items[:top_n]


def _worst_groups(groups: dict[str, dict[str, Any]], *, min_trades: int = 3, top_n: int = 3) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for key, stats in (groups or {}).items():
        trades = int(stats.get("trades", 0))
        if trades < min_trades:
            continue
        items.append(
            {
                "group": key,
                "trades": trades,
                "raw_win_rate": float(stats.get("raw_win_rate", 0.0)),
                "tp1_hit_rate": float(stats.get("tp1_hit_rate", 0.0)),
                "full_tp_rate": float(stats.get("full_tp_rate", 0.0)),
                "stop_loss_rate": float(stats.get("stop_loss_rate", 0.0)),
                "net_pnl": float(stats.get("net_pnl", 0.0)),
            }
        )
    items.sort(key=lambda item: (item["raw_win_rate"], item["net_pnl"], -item["stop_loss_rate"]))
    return items[:top_n]


def _recent_windows(closed: list[dict[str, Any]], account: dict[str, Any]) -> dict[str, Any]:
    windows: dict[str, Any] = {}
    for size in (20, 50, 100):
        subset = closed[-size:] if len(closed) > size else closed
        if not subset:
            windows[f"last_{size}"] = {"total_trades": 0}
            continue
        windows[f"last_{size}"] = compute_metrics_from_closed(subset, account, {})
    return windows


def _suggestions(metrics: dict[str, Any], recent: dict[str, Any]) -> list[dict[str, str]]:
    suggestions: list[dict[str, str]] = []
    plan_groups = (metrics.get("breakdown") or {}).get("plan_profile", {})
    protection_groups = (metrics.get("breakdown") or {}).get("protection_strategy", {})
    recent20 = recent.get("last_20") or {}

    if metrics.get("tp1_hit_rate", 0.0) >= 0.6 and metrics.get("full_tp_rate", 0.0) <= 0.25:
        suggestions.append(
            {
                "scope": "take_profit",
                "message": "TP1命中率高但最终走到TP2的比例偏低，建议提高TP1分批比例，或下调主流币TP2倍数。",
            }
        )

    majors_breakout = plan_groups.get("majors_breakout_confirmed") or {}
    if majors_breakout.get("trades", 0) >= 3 and majors_breakout.get("stop_loss_rate", 0.0) >= 0.55:
        suggestions.append(
            {
                "scope": "majors_breakout_confirmed",
                "message": "主流突破模板止损占比偏高，建议收紧entry buffer，或提高ERS门槛后再执行。",
            }
        )

    break_even = protection_groups.get("break_even") or {}
    if break_even.get("trades", 0) >= 3 and break_even.get("raw_win_rate", 0.0) < 0.4:
        suggestions.append(
            {
                "scope": "break_even",
                "message": "break-even保护策略近期胜率偏弱，建议复核激活条件是否过早，或提高TP1触发后的剩余仓位止盈纪律。",
            }
        )

    if recent20.get("total_trades", 0) >= 5 and recent20.get("raw_win_rate", 0.0) < 0.35:
        suggestions.append(
            {
                "scope": "recent_window",
                "message": "最近20笔胜率显著走弱，建议降低自动执行频率，只保留高ERS或高数据质量候选。",
            }
        )

    if not suggestions:
        suggestions.append(
            {
                "scope": "steady_state",
                "message": "近期表现没有明显异常，建议继续积累样本，优先观察不同plan_profile和source组合的差异。",
            }
        )
    return suggestions


def build_strategy_feedback(output_dir: Path, *, min_group_trades: int = 3) -> dict[str, Any]:
    account = load_paper_account(output_dir)
    metrics = load_paper_metrics(output_dir)
    closed = load_closed_positions(output_dir)
    recent = _recent_windows(closed, account)
    breakdown = metrics.get("breakdown") or {}

    feedback = {
        "generated_at": datetime.now().isoformat(),
        "total_closed_trades": len(closed),
        "headline_metrics": {
            "raw_win_rate": metrics.get("raw_win_rate", 0.0),
            "tp1_hit_rate": metrics.get("tp1_hit_rate", 0.0),
            "full_tp_rate": metrics.get("full_tp_rate", 0.0),
            "stop_loss_rate": metrics.get("stop_loss_rate", 0.0),
            "profit_factor": metrics.get("profit_factor"),
            "net_pnl": metrics.get("net_pnl", 0.0),
        },
        "recent_windows": recent,
        "best_groups": {
            "strategy_mode": _best_groups(breakdown.get("strategy_mode", {}), min_trades=min_group_trades),
            "plan_profile": _best_groups(breakdown.get("plan_profile", {}), min_trades=min_group_trades),
            "candidate_source": _best_groups(breakdown.get("candidate_source", {}), min_trades=min_group_trades),
        },
        "worst_groups": {
            "strategy_mode": _worst_groups(breakdown.get("strategy_mode", {}), min_trades=min_group_trades),
            "plan_profile": _worst_groups(breakdown.get("plan_profile", {}), min_trades=min_group_trades),
            "candidate_source": _worst_groups(breakdown.get("candidate_source", {}), min_trades=min_group_trades),
        },
        "plan_profile_comparison": breakdown.get("plan_profile", {}),
        "protection_strategy_comparison": breakdown.get("protection_strategy", {}),
        "direction_comparison": breakdown.get("direction", {}),
        "suggestions": _suggestions(metrics, recent),
    }
    return feedback


def save_strategy_feedback(output_dir: Path, *, min_group_trades: int = 3) -> dict[str, Any]:
    feedback = build_strategy_feedback(output_dir, min_group_trades=min_group_trades)
    save_paper_strategy_feedback(output_dir, feedback)
    return feedback
