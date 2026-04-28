from __future__ import annotations

from typing import Any

try:
    from .history_store import load_closed_positions
except ImportError:
    from history_store import load_closed_positions


def score_bucket(score: float | int | None) -> str:
    value = float(score or 0.0)
    if value >= 80:
        return "80+"
    if value >= 70:
        return "70-79"
    if value >= 55:
        return "55-69"
    return "<55"


def data_quality_tier(score: float | int | None) -> str:
    value = float(score or 0.0)
    if value >= 8:
        return "A"
    if value >= 6:
        return "B"
    if value >= 4:
        return "C"
    return "D"


def _new_group() -> dict[str, Any]:
    return {
        "trades": 0,
        "wins": 0,
        "tp1_hits": 0,
        "full_tp_hits": 0,
        "stop_losses": 0,
        "net_pnl": 0.0,
    }


def _finalize_group_stats(groups: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    for stats in groups.values():
        trades = int(stats.get("trades", 0))
        stats["raw_win_rate"] = stats.get("wins", 0) / trades if trades else 0.0
        stats["tp1_hit_rate"] = stats.get("tp1_hits", 0) / trades if trades else 0.0
        stats["full_tp_rate"] = stats.get("full_tp_hits", 0) / trades if trades else 0.0
        stats["stop_loss_rate"] = stats.get("stop_losses", 0) / trades if trades else 0.0
    return groups


def _update_group(groups: dict[str, dict[str, Any]], key: str, position: dict[str, Any]) -> None:
    stats = groups.setdefault(key, _new_group())
    pnl = float(position.get("realized_pnl", 0.0))
    stats["trades"] += 1
    stats["wins"] += 1 if pnl > 0 else 0
    stats["tp1_hits"] += 1 if position.get("tp1_hit") else 0
    stats["full_tp_hits"] += 1 if position.get("exit_reason") == "take_profit" else 0
    stats["stop_losses"] += 1 if position.get("exit_reason") == "stop_loss" else 0
    stats["net_pnl"] += pnl


def _build_breakdown(closed: list[dict[str, Any]]) -> dict[str, Any]:
    breakdown: dict[str, Any] = {
        "strategy_mode": {},
        "plan_profile": {},
        "protection_strategy": {},
        "direction": {},
        "score_bucket": {},
        "data_quality_tier": {},
        "candidate_source": {},
        "narrative_label": {},
    }
    for pos in closed:
        _update_group(breakdown["strategy_mode"], str(pos.get("strategy_mode") or "unknown"), pos)
        _update_group(breakdown["plan_profile"], str(pos.get("plan_profile") or "unknown"), pos)
        _update_group(breakdown["protection_strategy"], str(pos.get("protection_strategy") or "unknown"), pos)
        _update_group(breakdown["direction"], str(pos.get("direction") or "unknown"), pos)
        _update_group(breakdown["score_bucket"], score_bucket(pos.get("final_score")), pos)
        tier = str(pos.get("data_quality_tier") or data_quality_tier(pos.get("data_quality_score")))
        _update_group(breakdown["data_quality_tier"], tier, pos)
        for source in pos.get("candidate_sources", []) or []:
            _update_group(breakdown["candidate_source"], str(source), pos)
        for label in pos.get("narrative_labels", []) or []:
            _update_group(breakdown["narrative_label"], str(label), pos)

    for key, groups in breakdown.items():
        breakdown[key] = _finalize_group_stats(groups)
    return breakdown


def compute_metrics_from_closed(
    closed: list[dict[str, Any]],
    account: dict[str, Any],
    open_positions: dict[str, Any] | None = None,
) -> dict[str, Any]:
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
        "breakdown": _build_breakdown(closed),
    }


def compute_metrics(output_dir, account: dict[str, Any], open_positions: dict[str, Any] | None = None) -> dict[str, Any]:
    closed = load_closed_positions(output_dir)
    return compute_metrics_from_closed(closed, account, open_positions)
