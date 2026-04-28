"""
历史快照存储 (History Snapshots) — roadmap P1-2
────────────────────────────────────────────────
保存每次扫描的关键数据快照，用于计算相对强弱指标：
  - volume_vs_7d_avg
  - atr_pct_vs_30d_avg
  - alpha_count24h_vs_7d_avg
  - oi_vs_7d_avg

存储结构:
  $XDG_STATE_HOME/meme-coin-radar/history/
  或 ~/.local/state/meme-coin-radar/history/
  若状态目录不可写则回退到系统临时目录下的 meme-coin-radar/history/
    ticker_YYYYMMDD.json   ← 每日 ticker 快照
    alpha_YYYYMMDD.json    ← 每日 Alpha count24h 快照
    oi_YYYYMMDD.json       ← 每日 OI 快照（可选）

历史数据保留策略：最近 30 天
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


def _today() -> str:
    return datetime.now().strftime("%Y%m%d")


def _past_dates(days: int) -> list[str]:
    base = datetime.now()
    return [(base - timedelta(days=i)).strftime("%Y%m%d") for i in range(1, days + 1)]


def history_dir(output_dir: Path) -> Path:
    hdir = output_dir / "history"
    hdir.mkdir(parents=True, exist_ok=True)
    return hdir


def save_ticker_snapshot(
    output_dir: Path,
    tickers: list[dict],
) -> Path:
    """Save today's ticker snapshot. Returns file path."""
    hdir = history_dir(output_dir)
    path = hdir / f"ticker_{_today()}.json"
    snapshot = {
        "date": _today(),
        "count": len(tickers),
        "data": {
            t["symbol"].upper(): {
                "price": t.get("last", t.get("price", 0)),
                "chg24h_pct": t.get("chg24h_pct", 0),
                "volume": t.get("vol24h", t.get("volume", 0)),
            }
            for t in tickers
            if t.get("symbol")
        },
    }
    path.write_text(json.dumps(snapshot, indent=2, default=str), encoding="utf-8")
    return path


def save_alpha_snapshot(
    output_dir: Path,
    alpha_dict: dict,
) -> Path:
    """Save today's Alpha count24h snapshot."""
    hdir = history_dir(output_dir)
    path = hdir / f"alpha_{_today()}.json"
    snapshot = {
        "date": _today(),
        "count": len(alpha_dict),
        "data": {
            sym.upper(): {"count24h": data.get("count24h", 0), "pct": data.get("pct", 0)}
            for sym, data in alpha_dict.items()
        },
    }
    path.write_text(json.dumps(snapshot, indent=2, default=str), encoding="utf-8")
    return path


def save_social_snapshot(
    output_dir: Path,
    social_intel: dict[str, dict[str, Any]],
    timestamp_label: str | None = None,
) -> Path:
    hdir = history_dir(output_dir)
    stamp = timestamp_label or datetime.now().strftime("%Y%m%d%H")
    path = hdir / f"social_{stamp}.json"
    snapshot = {
        "timestamp": stamp,
        "count": len(social_intel),
        "data": social_intel,
    }
    path.write_text(json.dumps(snapshot, indent=2, default=str, ensure_ascii=False), encoding="utf-8")
    return path


def load_recent_social_snapshot(
    output_dir: Path,
    symbol: str,
    hours_back: int,
    before_ts: datetime | None = None,
) -> dict[str, Any] | None:
    hdir = history_dir(output_dir)
    symbol = symbol.upper()
    anchor = before_ts or datetime.now()
    for hour in range(hours_back, hours_back + 24):
        stamp = (anchor - timedelta(hours=hour)).strftime("%Y%m%d%H")
        path = hdir / f"social_{stamp}.json"
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            entry = data.get("data", {}).get(symbol)
            if isinstance(entry, dict):
                return entry
        except json.JSONDecodeError:
            continue
    return None


def load_ticker_history(
    output_dir: Path,
    symbol: str,
    days: int = 7,
) -> list[dict[str, Any]]:
    """Load historical ticker data for a symbol. Returns list of daily records."""
    hdir = history_dir(output_dir)
    symbol = symbol.upper()
    results = []
    for date_str in _past_dates(days):
        path = hdir / f"ticker_{date_str}.json"
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            symbol_data = data.get("data", {}).get(symbol)
            if symbol_data:
                results.append({"date": date_str, **symbol_data})
        except (json.JSONDecodeError, KeyError):
            continue
    return results


def load_alpha_history(
    output_dir: Path,
    symbol: str,
    days: int = 7,
) -> list[dict[str, Any]]:
    """Load historical Alpha count24h for a symbol."""
    hdir = history_dir(output_dir)
    symbol = symbol.upper()
    results = []
    for date_str in _past_dates(days):
        path = hdir / f"alpha_{date_str}.json"
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            symbol_data = data.get("data", {}).get(symbol)
            if symbol_data:
                results.append({"date": date_str, **symbol_data})
        except (json.JSONDecodeError, KeyError):
            continue
    return results


def compute_relative_metrics(
    output_dir: Path,
    symbol: str,
    current_volume: float | None = None,
    current_atr_pct: float | None = None,
    current_alpha_count: int | None = None,
) -> dict[str, Any]:
    """
    Compute relative metrics vs historical averages.
    Returns dict with ratios and raw averages.
    """
    metrics: dict[str, Any] = {}

    # Volume vs 7d avg
    if current_volume is not None:
        hist = load_ticker_history(output_dir, symbol, days=7)
        vols = [h["volume"] for h in hist if h.get("volume")]
        if vols:
            avg_7d = sum(vols) / len(vols)
            metrics["volume_vs_7d_avg"] = current_volume / avg_7d if avg_7d > 0 else None
            metrics["volume_7d_avg"] = avg_7d
        else:
            metrics["volume_vs_7d_avg"] = None

    # ATR vs 30d avg (placeholder — requires daily ATR snapshots)
    # For now, compute from ticker price history as proxy
    if current_atr_pct is not None:
        hist = load_ticker_history(output_dir, symbol, days=30)
        # Use price change abs as ATR proxy if real ATR not stored
        price_changes = [abs(h.get("chg24h_pct", 0)) for h in hist if h.get("chg24h_pct") is not None]
        if price_changes:
            avg_30d = sum(price_changes) / len(price_changes)
            metrics["atr_proxy_vs_30d_avg"] = current_atr_pct / (avg_30d / 100) if avg_30d > 0 else None
            metrics["atr_proxy_30d_avg"] = avg_30d / 100
        else:
            metrics["atr_proxy_vs_30d_avg"] = None

    # Alpha count vs 7d avg
    if current_alpha_count is not None:
        hist = load_alpha_history(output_dir, symbol, days=7)
        counts = [h["count24h"] for h in hist if h.get("count24h") is not None]
        if counts:
            avg_7d = sum(counts) / len(counts)
            metrics["alpha_count_vs_7d_avg"] = current_alpha_count / avg_7d if avg_7d > 0 else None
            metrics["alpha_count_7d_avg"] = avg_7d
        else:
            metrics["alpha_count_vs_7d_avg"] = None

    return metrics


def cleanup_old_snapshots(output_dir: Path, keep_days: int = 30) -> int:
    """Remove snapshot files older than keep_days. Returns count of removed files."""
    hdir = history_dir(output_dir)
    cutoff = datetime.now() - timedelta(days=keep_days)
    removed = 0
    for path in hdir.glob("*.json"):
        try:
            date_str = path.stem.split("_")[-1]
            file_date = None
            for fmt in ("%Y%m%d", "%Y%m%d%H"):
                try:
                    file_date = datetime.strptime(date_str, fmt)
                    break
                except ValueError:
                    continue
            if file_date is None:
                continue
            if file_date < cutoff:
                path.unlink()
                removed += 1
        except (ValueError, OSError):
            continue
    return removed


def paper_positions_path(output_dir: Path) -> Path:
    return history_dir(output_dir) / "paper_positions.json"


def load_paper_positions(output_dir: Path) -> dict[str, Any]:
    path = paper_positions_path(output_dir)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def save_paper_positions(output_dir: Path, positions: dict[str, Any]) -> Path:
    path = paper_positions_path(output_dir)
    path.write_text(json.dumps(positions, indent=2, default=str, ensure_ascii=False), encoding="utf-8")
    return path


def paper_orders_path(output_dir: Path) -> Path:
    return history_dir(output_dir) / "paper_orders.json"


def load_paper_orders(output_dir: Path) -> dict[str, Any]:
    path = paper_orders_path(output_dir)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def save_paper_orders(output_dir: Path, orders: dict[str, Any]) -> Path:
    path = paper_orders_path(output_dir)
    path.write_text(json.dumps(orders, indent=2, default=str, ensure_ascii=False), encoding="utf-8")
    return path


def paper_account_path(output_dir: Path) -> Path:
    return history_dir(output_dir) / "paper_account.json"


def load_paper_account(output_dir: Path) -> dict[str, Any]:
    path = paper_account_path(output_dir)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def save_paper_account(output_dir: Path, account: dict[str, Any]) -> Path:
    path = paper_account_path(output_dir)
    path.write_text(json.dumps(account, indent=2, default=str, ensure_ascii=False), encoding="utf-8")
    return path


def paper_metrics_path(output_dir: Path) -> Path:
    return history_dir(output_dir) / "paper_metrics.json"


def save_paper_metrics(output_dir: Path, metrics: dict[str, Any]) -> Path:
    path = paper_metrics_path(output_dir)
    path.write_text(json.dumps(metrics, indent=2, default=str, ensure_ascii=False), encoding="utf-8")
    return path


def load_paper_metrics(output_dir: Path) -> dict[str, Any]:
    path = paper_metrics_path(output_dir)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def paper_strategy_feedback_path(output_dir: Path) -> Path:
    return history_dir(output_dir) / "paper_strategy_feedback.json"


def save_paper_strategy_feedback(output_dir: Path, feedback: dict[str, Any]) -> Path:
    path = paper_strategy_feedback_path(output_dir)
    path.write_text(json.dumps(feedback, indent=2, default=str, ensure_ascii=False), encoding="utf-8")
    return path


def load_paper_strategy_feedback(output_dir: Path) -> dict[str, Any]:
    path = paper_strategy_feedback_path(output_dir)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def paper_events_path(output_dir: Path) -> Path:
    return history_dir(output_dir) / "paper_events.jsonl"


def append_paper_event(output_dir: Path, event: dict[str, Any]) -> Path:
    path = paper_events_path(output_dir)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, default=str, ensure_ascii=False) + "\n")
    return path


def paper_closed_positions_path(output_dir: Path) -> Path:
    return history_dir(output_dir) / "paper_closed_positions.jsonl"


def append_closed_position(output_dir: Path, position: dict[str, Any]) -> Path:
    path = paper_closed_positions_path(output_dir)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(position, default=str, ensure_ascii=False) + "\n")
    return path


def load_closed_positions(output_dir: Path) -> list[dict[str, Any]]:
    path = paper_closed_positions_path(output_dir)
    if not path.exists():
        return []
    results: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw:
            continue
        try:
            item = json.loads(raw)
            if isinstance(item, dict):
                results.append(item)
        except json.JSONDecodeError:
            continue
    return results
