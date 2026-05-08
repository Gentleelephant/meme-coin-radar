"""
Test size guard and progressive downsampling for result.json.
"""

import json
import sys
import tempfile
from pathlib import Path

# Add scripts directory to path
scripts_dir = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(scripts_dir))

from size_guard import (
    downsample_candidate,
    downsample_results,
    estimate_json_size,
    save_with_size_guard,
)


def test_estimate_json_size():
    """Test JSON size estimation."""
    test_data = {"symbol": "PEPE", "final_score": 62, "nested": {"a": 1, "b": 2}}
    estimated = estimate_json_size(test_data)

    assert estimated > 0
    assert estimated < 1000


def test_downsample_candidate():
    """Test candidate downsampling removes large fields."""
    large_candidate = {
        "symbol": "PEPE",
        "final_score": 62,
        "oos": 70,
        "ers": 65,
        "direction": "long",
        "meta": {
            "market_cap": 1000000,
            "turnover_ratio": 0.5,
            "day_pos": 0.8,
            "count24h": 1000,
            "address": "0x1234567890abcdef",
            "chain": "solana",
            "klines": [1, 2, 3] * 100,  # Large data
        },
        "trade_plan": {
            "entry_low": 0.001,
            "entry_high": 0.002,
            "stop_loss": 0.0005,
            "take_profit_1": 0.003,
            "take_profit_2": 0.005,
            "plan_profile": "meme_onchain",
            "rr": 3.5,
        },
        "execution_result": {
            "status": "pending",
            "mode": "paper",
            "order_id": "abc123",
            "details": {"extra": "data"},
        },
    }

    downsized = downsample_candidate(large_candidate)

    # Core fields should be preserved
    assert downsized["symbol"] == "PEPE"
    assert downsized["final_score"] == 62
    assert downsized["direction"] == "long"

    # Meta should be reduced
    assert "market_cap" in downsized["meta"]
    assert "klines" not in downsized["meta"]

    # Trade plan should be simplified
    assert "plan_profile" in downsized["trade_plan"]
    assert "entry_low" not in downsized["trade_plan"]
    assert "stop_loss" not in downsized["trade_plan"]

    # Execution result should be minimal
    assert downsized["execution_result"]["status"] == "pending"
    assert "order_id" not in downsized["execution_result"]


def test_downsample_results():
    """Test results downsampling reduces size."""
    large_results = [
        {
            "symbol": f"COIN{i}",
            "final_score": 100 - i * 5,
            "meta": {"klines": [1, 2, 3] * 100, "data": "x" * 1000},
            "trade_plan": {"entry_low": 0.001, "stop_loss": 0.0005, "plan_profile": "test"},
        }
        for i in range(20)
    ]

    target_size = 10000  # 10KB for testing

    downsized = downsample_results(large_results, target_size)

    # Should return a list
    assert isinstance(downsized, list)

    # Should be sorted by score
    scores = [r.get("final_score", 0) for r in downsized]
    assert scores == sorted(scores, reverse=True)


def test_save_with_size_guard_small():
    """Test save_with_size_guard with small data (no downsampling)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        small_data = {"symbol": "PEPE", "final_score": 62}

        result = save_with_size_guard("result.json", small_data, tmp_path)

        result_path = tmp_path / "result.json"
        assert result_path.exists()
        data = json.loads(result_path.read_text())
        assert data["symbol"] == "PEPE"
        assert data["final_score"] == 62


def test_save_with_size_guard_list():
    """Test save_with_size_guard with list data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        list_data = [{"symbol": "PEPE", "final_score": 62}]

        result = save_with_size_guard("result.json", list_data, tmp_path)

        result_path = tmp_path / "result.json"
        assert result_path.exists()
        data = json.loads(result_path.read_text())
        assert isinstance(data, list)
        assert data[0]["symbol"] == "PEPE"


def test_save_with_size_guard_splitting():
    """Test save_with_size_guard splits data when too large."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        # Create data that's too large
        large_list = [
            {
                "symbol": f"COIN{i}",
                "final_score": 90,
                "meta": {"klines": [1, 2, 3] * 10000},
                "trade_plan": {"entry_low": 0.001},
            }
            for i in range(100)
        ]

        # Use a very small max size to force splitting
        save_with_size_guard("result.json", large_list, tmp_path, max_size_bytes=1000)

        # Should have created split files
        meta_path = tmp_path / "result_meta.json"
        full_path = tmp_path / "result_full.json"
        assert meta_path.exists() or full_path.exists()


if __name__ == "__main__":
    test_estimate_json_size()
    print("✅ test_estimate_json_size passed")

    test_downsample_candidate()
    print("✅ test_downsample_candidate passed")

    test_downsample_results()
    print("✅ test_downsample_results passed")

    test_save_with_size_guard_small()
    print("✅ test_save_with_size_guard_small passed")

    test_save_with_size_guard_list()
    print("✅ test_save_with_size_guard_list passed")

    test_save_with_size_guard_splitting()
    print("✅ test_save_with_size_guard_splitting passed")

    print("\n✅ All tests passed!")