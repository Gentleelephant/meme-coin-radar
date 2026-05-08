"""
Test multi-timeframe klines fetch (Issue #4).
"""

from __future__ import annotations

import sys
from pathlib import Path

scripts_dir = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(scripts_dir))

from skill_dispatcher import _format_klines, _format_multi_tf_klines


def test_format_klines():
    """Test K-line field extraction from Binance format."""
    raw_klines = [
        [100.0, 84.0, 85.5, 83.5, 85.2, 1234567.0, 100.0, 200.0, 300.0],
        [200.0, 85.0, 86.0, 84.0, 85.5, 2345678.0, 200.0, 300.0, 400.0],
    ]
    result = _format_klines(raw_klines)
    assert len(result) == 2
    assert result[0]["open"] == 84.0
    assert result[0]["high"] == 85.5
    assert result[0]["low"] == 83.5
    assert result[0]["close"] == 85.2
    assert result[0]["volume"] == 1234567.0
    assert result[1]["close"] == 85.5


def test_format_klines_empty():
    """Test empty klines returns empty list."""
    from skill_dispatcher import _format_klines
    assert _format_klines(None) == []
    assert _format_klines([]) == []


def test_format_multi_tf_klines():
    """Test multi-tf klines formatting."""
    raw = {
        "klines_15m": [
            [100.0, 84.0, 85.5, 83.5, 85.2, 1234567.0, 100.0, 200.0, 300.0],
        ],
        "klines_5m": [
            [200.0, 85.0, 86.0, 84.0, 85.5, 2345678.0, 200.0, 300.0, 400.0],
        ],
    }
    result = _format_multi_tf_klines(raw)
    assert "klines_15m" in result
    assert "klines_5m" in result
    assert result["klines_15m"][0]["open"] == 84.0
    assert result["klines_5m"][0]["close"] == 85.5
    assert result["klines_5m"][0]["volume"] == 2345678.0


def test_format_multi_tf_klines_limit():
    """Test multi-tf klines respects the limit parameter."""
    raw = {
        "klines_15m": [
            [i * 100.0, 80.0 + i, 85.0 + i, 78.0 + i, 82.0 + i, 1000000.0, 0, 0, 0]
            for i in range(100)
        ],
    }
    result = _format_multi_tf_klines(raw)
    result = _format_multi_tf_klines(raw)
    assert len(result.get("klines_15m", [])) <= 50


if __name__ == "__main__":
    test_format_klines()
    print("✅ test_format_klines passed")

    test_format_klines_empty()
    print("✅ test_format_klines_empty passed")

    test_format_multi_tf_klines()
    print("✅ test_format_multi_tf_klines passed")

    test_format_multi_tf_klines_limit()
    print("✅ test_format_multi_tf_klines_limit passed")

    print("\n✅ All multi-tf klines tests passed!")