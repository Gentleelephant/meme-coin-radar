#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from .config import ensure_output_dir, load_settings
    from .history_store import load_paper_account, load_paper_metrics, load_paper_positions
    from .paper_analytics import compute_metrics
    from .paper_reconciler import reconcile_all_positions, ticks_from_klines
    from .paper_strategy_feedback import save_strategy_feedback
    from .skill_dispatcher import batch_binance
except ImportError:
    from config import ensure_output_dir, load_settings
    from history_store import load_paper_account, load_paper_metrics, load_paper_positions
    from paper_analytics import compute_metrics
    from paper_reconciler import reconcile_all_positions, ticks_from_klines
    from paper_strategy_feedback import save_strategy_feedback
    from skill_dispatcher import batch_binance


def _base_output_dir() -> Path:
    settings = load_settings()
    return ensure_output_dir(settings.output_dir)


def _latest_scan_dir(base_dir: Path) -> Path | None:
    candidates = sorted((path for path in base_dir.glob("scan_*") if path.is_dir()), reverse=True)
    return candidates[0] if candidates else None


def _run_auto_scan(*, execute_paper: bool) -> int:
    env = os.environ.copy()
    env["RADAR_AUTO_EXECUTE_PAPER_TRADES"] = "true" if execute_paper else "false"
    script_path = Path(__file__).with_name("auto-run.py")
    completed = subprocess.run([sys.executable, str(script_path)], env=env, check=False)
    return int(completed.returncode)


def _save_review_artifact(base_dir: Path, payload: dict[str, Any]) -> Path:
    target_dir = _latest_scan_dir(base_dir) or base_dir
    path = target_dir / "16_strategy_review.json"
    path.write_text(json.dumps(payload, indent=2, default=str, ensure_ascii=False), encoding="utf-8")
    return path


def action_scan_only() -> int:
    return _run_auto_scan(execute_paper=False)


def action_scan_and_trade() -> int:
    return _run_auto_scan(execute_paper=True)


def action_reconcile_and_update_metrics(base_dir: Path) -> int:
    positions = load_paper_positions(base_dir)
    symbols = list(positions.keys())
    if not symbols:
        account = load_paper_account(base_dir)
        metrics = load_paper_metrics(base_dir) or compute_metrics(base_dir, account, positions)
        print(json.dumps({"updated_positions": 0, "closed_positions": 0, "metrics": metrics}, indent=2, ensure_ascii=False))
        return 0

    batch = batch_binance(symbols)
    results = batch.get("results", {})
    tick_map = {
        symbol: ticks_from_klines((results.get(symbol) or {}).get("klines"))
        for symbol in symbols
    }
    reconcile_result = reconcile_all_positions(base_dir, tick_map=tick_map)
    feedback = save_strategy_feedback(base_dir)
    payload = {
        "action": "reconcile_and_update_metrics",
        "generated_at": datetime.now().isoformat(),
        "reconcile_result": reconcile_result,
        "strategy_feedback_summary": {
            "total_closed_trades": feedback.get("total_closed_trades", 0),
            "suggestions": feedback.get("suggestions", []),
        },
    }
    _save_review_artifact(base_dir, payload)
    print(json.dumps(payload, indent=2, default=str, ensure_ascii=False))
    return 0


def action_strategy_review(base_dir: Path) -> int:
    feedback = save_strategy_feedback(base_dir)
    path = _save_review_artifact(
        base_dir,
        {
            "action": "strategy_review",
            "generated_at": datetime.now().isoformat(),
            "feedback": feedback,
        },
    )
    print(f"strategy_review saved: {path}")
    print(json.dumps(feedback, indent=2, default=str, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Paper trading control loop entrypoints for meme-coin-radar.")
    parser.add_argument(
        "action",
        choices=["scan_only", "scan_and_trade", "reconcile_and_update_metrics", "strategy_review"],
        help="Control-loop action to run.",
    )
    parser.add_argument("--dir", default=None, help="Base output directory containing history/ and scan_*.")
    args = parser.parse_args()

    base_dir = Path(args.dir).expanduser().resolve() if args.dir else _base_output_dir()

    if args.action == "scan_only":
        return action_scan_only()
    if args.action == "scan_and_trade":
        return action_scan_and_trade()
    if args.action == "reconcile_and_update_metrics":
        return action_reconcile_and_update_metrics(base_dir)
    if args.action == "strategy_review":
        return action_strategy_review(base_dir)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
