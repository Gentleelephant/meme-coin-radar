from __future__ import annotations

import unittest

from scripts.config import Settings
from scripts.radar_logic import build_trade_plan, calc_trend_structure, score_candidate


class RadarLogicTest(unittest.TestCase):
    def test_calc_trend_structure_bearish(self) -> None:
        self.assertEqual(calc_trend_structure(price=90, ema20=100, ema50=110), "bearish")

    def test_build_trade_plan_short(self) -> None:
        plan = build_trade_plan({
            "direction": "short",
            "can_enter": True,
            "meta": {"price": 100.0, "atr_pct": 0.08, "fr": 0.6, "count24h": 60000},
        })
        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan["setup_label"], "ready")
        self.assertGreater(plan["entry_high"], plan["entry_low"])
        self.assertGreater(plan["stop_loss"], 100.0)
        self.assertLess(plan["take_profit_1"], 100.0)

    def test_score_candidate_blocks_low_confidence_setup(self) -> None:
        settings = Settings(min_watch_score=30.0, min_recommend_score=45.0)
        result = score_candidate(
            symbol="BTC",
            ticker={"price": 100.0, "chg24h": 0.2, "volume": 200_000_000, "source": "test"},
            funding={"fundingRate_pct": 0.01, "source": "test"},
            alpha={},
            klines=[(100, 102, 99, 101, 1)] * 50,
            btc_dir="neutral",
            missing_fields=[],
            settings=settings,
            gmgn_token=None,
            gmgn_security_score_fn=None,
        )
        self.assertGreaterEqual(result["total"], 30)
        self.assertFalse(result["can_enter"])
        self.assertIn(result["direction"], {"long", "short"})


if __name__ == "__main__":
    unittest.main()
