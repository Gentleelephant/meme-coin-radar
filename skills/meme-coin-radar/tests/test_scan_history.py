"""
Test scan history, trend analysis, and watchlist management (Issue #5).
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

scripts_dir = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(scripts_dir))

from history_store import (
    analyze_score_trend,
    compute_consecutive_top5,
    compute_consecutive_not_top10,
    load_scan_history,
    load_watchlist,
    save_scan_history,
    update_watchlist,
)


def _make_history(symbol: str, scores: list[int], ers: list[int]) -> list[dict]:
    """Helper to create scan history for testing."""
    history = []
    ts_prefix = "2026-05-08T10:00:00Z" if len(scores) <= 1 else "2026-05-08T"
    for i, (s, e) in enumerate(zip(scores, ers)):
        history.append({
            "timestamp": f"{ts_prefix}{10 + i:02d}:00:00Z",
            "symbol": symbol,
            "final_score": s,
            "ers": e,
            "decision": "watch_only",
            "direction": "long",
        })
    return history


def test_save_and_load_scan_history():
    """Test saving and loading scan history."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        scored = [
            {"symbol": "PEPEUSDT", "final_score": 62, "oos": 70, "ers": 65, "decision": "watch_only", "direction": "long", "name": "PEPEUSDT"},
            {"symbol": "DOGEUSDT", "final_score": 55, "oos": 50, "ers": 60, "decision": "watch_only", "direction": "long", "name": "DOGEUSDT"},
        ]

        path = save_scan_history(tmp_path, scored)
        assert path.exists()

        loaded = load_scan_history(tmp_path)
        assert len(loaded) == 2
        assert loaded[0]["symbol"] == "PEPEUSDT"
        assert loaded[1]["symbol"] == "DOGEUSDT"


def test_trend_insufficient_data():
    """Test trend analysis with insufficient data."""
    history = _make_history("PEPEUSDT", [60], [65])
    trend = analyze_score_trend(history, "PEPEUSDT")
    assert trend["trend"] == "insufficient_data"


def test_trend_rising():
    """Test rising trend detection."""
    history = _make_history("PEPEUSDT", [50, 55, 60, 65, 70, 75], [60, 62, 65, 68, 70, 73])
    trend = analyze_score_trend(history, "PEPEUSDT")
    assert trend["score_trend"] == "rising"


def test_trend_falling():
    """Test falling trend detection."""
    history = _make_history("PEPEUSDT", [75, 70, 65, 60, 55, 50], [73, 70, 68, 65, 62, 60])
    trend = analyze_score_trend(history, "PEPEUSDT")
    assert trend["score_trend"] == "falling"


def test_trend_stable():
    """Test stable trend detection."""
    history = _make_history("PEPEUSDT", [60, 61, 59, 62, 60, 61], [65, 66, 64, 67, 65, 66])
    trend = analyze_score_trend(history, "PEPEUSDT")
    assert trend["score_trend"] == "stable"


def test_compute_consecutive_top5():
    """Test consecutive top 5 ERS ranking computation."""
    history = [
        {"timestamp": "2026-05-08T10:00:00Z", "symbol": "PEPEUSDT", "ers": 90},
        {"timestamp": "2026-05-08T10:00:00Z", "symbol": "COIN2", "ers": 80},
        {"timestamp": "2026-05-08T10:00:00Z", "symbol": "COIN3", "ers": 70},
        {"timestamp": "2026-05-08T10:00:00Z", "symbol": "COIN4", "ers": 60},
        {"timestamp": "2026-05-08T10:00:00Z", "symbol": "COIN5", "ers": 50},
        {"timestamp": "2026-05-08T10:00:00Z", "symbol": "COIN6", "ers": 40},
        {"timestamp": "2026-05-08T11:00:00Z", "symbol": "PEPEUSDT", "ers": 85},
        {"timestamp": "2026-05-08T11:00:00Z", "symbol": "COIN2", "ers": 75},
        {"timestamp": "2026-05-08T11:00:00Z", "symbol": "COIN3", "ers": 65},
        {"timestamp": "2026-05-08T11:00:00Z", "symbol": "COIN7", "ers": 55},
        {"timestamp": "2026-05-08T11:00:00Z", "symbol": "COIN8", "ers": 45},
    ]
    streak = compute_consecutive_top5("PEPEUSDT", history)
    assert streak == 2


def test_update_watchlist():
    """Test watchlist auto-management."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        # Create history with PEPE in top 5 for 3 consecutive scans
        history = []
        for ts_idx in range(3):
            ts = f"2026-05-08T{10 + ts_idx:02d}:00:00Z"
            history.append({"timestamp": ts, "symbol": "PEPEUSDT", "ers": 90, "final_score": 75, "decision": "watch_only", "direction": "long"})
            for i in range(2, 8):
                history.append({"timestamp": ts, "symbol": f"COIN{i}", "ers": 90 - 10 * (i - 1), "final_score": 70 - 5 * (i - 1), "decision": "watch_only", "direction": "long"})

        candidates = [{"symbol": "PEPEUSDT", "ers": 90, "final_score": 75}]

        watchlist = update_watchlist(tmp_path, candidates, history)
        assert len(watchlist.get("coins", [])) == 1
        assert watchlist["coins"][0]["symbol"] == "PEPEUSDT"
        assert watchlist["coins"][0]["reason"] == "ers_top5_streak"


def test_watchlist_persistence():
    """Test watchlist saves to disk and loads back."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        # Build history with 3 rounds, each with PEPE in top 5
        history = []
        for round_idx in range(3):
            ts = f"2026-05-08T{10 + round_idx:02d}:00:00Z"
            history.append({"timestamp": ts, "symbol": "PEPEUSDT", "ers": 90, "final_score": 75, "decision": "watch_only", "direction": "long"})
            for i in range(2, 7):
                history.append({"timestamp": ts, "symbol": f"COIN{i}", "ers": 90 - 10 * (i - 1), "final_score": 70 - 5 * (i - 1), "decision": "watch_only", "direction": "long"})

        candidates = [{"symbol": "PEPEUSDT", "ers": 90, "final_score": 75}]
        update_watchlist(tmp_path, candidates, history)

        # Load and verify
        watchlist = load_watchlist(tmp_path)
        assert len(watchlist.get("coins", [])) >= 1
        assert watchlist["coins"][0]["symbol"] == "PEPEUSDT"


if __name__ == "__main__":
    test_save_and_load_scan_history()
    print("✅ test_save_and_load_scan_history passed")

    test_trend_insufficient_data()
    print("✅ test_trend_insufficient_data passed")

    test_trend_rising()
    print("✅ test_trend_rising passed")

    test_trend_falling()
    print("✅ test_trend_falling passed")

    test_trend_stable()
    print("✅ test_trend_stable passed")

    test_compute_consecutive_top5()
    print("✅ test_compute_consecutive_top5 passed")

    test_update_watchlist()
    print("✅ test_update_watchlist passed")

    test_watchlist_persistence()
    print("✅ test_watchlist_persistence passed")

    print("\n✅ All scan history / watchlist tests passed!")