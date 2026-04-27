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
        self.assertGreater(plan["rr"], 1.0)

    def test_build_trade_plan_rr_computed(self) -> None:
        plan = build_trade_plan({
            "direction": "long",
            "can_enter": True,
            "meta": {"price": 100.0, "atr_pct": 0.035, "fr": 0.01, "count24h": 60000},
        })
        self.assertIsNotNone(plan)
        assert plan is not None
        # R:R should be computed and reasonable with midpoint entry
        self.assertGreater(plan["rr"], 1.0)
        self.assertEqual(plan["setup_label"], "ready")

    def test_build_trade_plan_rr_downgrade(self) -> None:
        # Simulated scenario where R:R is explicitly bad (<1.5)
        # build_trade_plan itself rarely produces rr<1.5 with the default formula,
        # but we verify the downgrade logic responds correctly when it happens.
        result = {
            "direction": "long",
            "can_enter": True,
            "meta": {"price": 100.0, "atr_pct": 0.10, "fr": 0.01, "count24h": 60000},
        }
        plan = build_trade_plan(result)
        self.assertIsNotNone(plan)
        assert plan is not None
        # If rr >= 1.5 it should stay ready, if <1.5 it should downgrade
        if plan["rr"] >= 1.5:
            self.assertEqual(plan["setup_label"], "ready")
        else:
            self.assertEqual(plan["setup_label"], "watch")
            self.assertIn("can_enter_rr_blocked", result)

    def test_score_candidate_blocks_low_confidence_setup(self) -> None:
        settings = Settings(min_watch_score=50.0, min_recommend_score=75.0)
        result = score_candidate(
            symbol="BTC",
            ticker={"price": 100.0, "chg24h": 0.2, "volume": 200_000_000, "source": "test"},
            funding={"fundingRate_pct": 0.01, "source": "test"},
            alpha={},
            klines=[(100, 102, 99, 101, 1)] * 50,
            btc_dir="neutral",
            missing_fields=[],
            settings=settings,
        )
        # With low momentum it should not be paper-trade ready
        self.assertIn(result["decision"], {"manual_review", "reject", "watch_only"})
        self.assertFalse(result["can_enter"])
        self.assertIn(result["direction"], {"long", "short"})
        self.assertIn("turnover_activity", result["module_scores"])
        self.assertIn("momentum_window", result["module_scores"])
        self.assertIn("execution_mapping", result["module_scores"])
        self.assertIn("oos", result)
        self.assertIn("ers", result)
        self.assertIn("hard_reject", result)
        self.assertIn("needs_manual_review", result)
        self.assertIn("risk_notes", result)

    def test_score_candidate_hard_reject_dev_holding(self) -> None:
        settings = Settings()
        result = score_candidate(
            symbol="SHITCOIN",
            ticker={"price": 0.001, "chg24h": 50.0, "volume": 10_000_000, "source": "test"},
            funding=None,
            alpha={},
            klines=None,
            btc_dir="up",
            missing_fields=[],
            settings=settings,
            onchain_data={
                "price_info": {"liquidity": "100000"},
                "advanced_info": {
                    "devHoldingPercent": "18",
                    "suspiciousHoldingPercent": "2",
                },
            },
        )
        self.assertEqual(result["decision"], "reject")
        self.assertTrue(result["hard_reject"])
        self.assertTrue(any("开发者" in r for r in result["reject_reasons"]))

    def test_score_candidate_monster_candidate(self) -> None:
        settings = Settings(min_recommend_score=75.0)
        # Use rising klines to get bullish trend + meaningful chg4h
        klines_1h = [(i * 0.01, i * 0.01 + 0.05, i * 0.01 - 0.03, i * 0.01 + 0.02, 10) for i in range(50)]
        klines_4h = [(i * 0.04, i * 0.04 + 0.08, i * 0.04 - 0.05, i * 0.04 + 0.05, 100) for i in range(10)]
        result = score_candidate(
            symbol="FARTCOIN",
            ticker={"price": 1.0, "chg24h": 35.0, "volume": 600_000_000, "source": "test"},
            funding={"fundingRate_pct": 1.5, "source": "test"},
            alpha={"count24h": 250_000},
            klines=klines_1h,
            btc_dir="up",
            missing_fields=[],
            settings=settings,
            klines_4h=klines_4h,
            mapping_confidence="high",
            onchain_data={
                "price_info": {
                    "marketCap": "25000000",
                    "volume24H": "30000000",
                    "holders": "12000",
                    "txs24H": "9000",
                    "priceChange4H": "6",
                    "maxPrice": "1.1",
                    "minPrice": "0.7",
                },
                "advanced_info": {
                    "top10HoldPercent": "18",
                    "devHoldingPercent": "4",
                    "suspiciousHoldingPercent": "2",
                },
                "cluster_overview": {
                    "clusterConcentration": "Low",
                    "rugPullPercent": "10",
                    "holderNewAddressPercent": "18",
                },
                "signals": [
                    {"triggerWalletCount": "4", "walletType": "1", "soldRatioPercent": "15"},
                    {"triggerWalletCount": "4", "walletType": "2", "soldRatioPercent": "25"},
                ],
                "tracker_items": [{"userAddress": "0x1"}, {"userAddress": "0x2"}],
                "okx_x_rank": 4,
                "hot_token": {"txsBuy": "5000", "txsSell": "2500"},
            },
        )
        self.assertEqual(result["decision"], "recommend_paper_trade")
        self.assertGreaterEqual(result["oos"], 70)
        self.assertGreaterEqual(result["ers"], 65)
        self.assertGreaterEqual(result["module_scores"]["momentum_window"], 10)
        self.assertGreaterEqual(result["module_scores"]["social_heat"], 3)

    def test_oi_quadrant_scoring(self) -> None:
        settings = Settings()
        result = score_candidate(
            symbol="BTC",
            ticker={"price": 100.0, "chg24h": 5.0, "volume": 200_000_000, "source": "test"},
            funding={"fundingRate_pct": 0.5, "source": "test"},
            alpha={},
            klines=[(100, 102, 99, 101, 1)] * 50,
            btc_dir="neutral",
            missing_fields=[],
            settings=settings,
            oi={"oi": 1000, "oi_change_pct": 5.0, "price_change_pct": 5.0},
        )
        self.assertIn("oi", result["meta"])

    def test_missing_fields_downgrade(self) -> None:
        settings = Settings()
        result = score_candidate(
            symbol="BTC",
            ticker={"price": 100.0, "chg24h": 5.0, "volume": 200_000_000, "source": "test"},
            funding=None,
            alpha={},
            klines=None,
            btc_dir="neutral",
            missing_fields=["atr14", "trend", "oi", "fundingRate", "volume"],
            settings=settings,
        )
        self.assertIn(result["decision"], {"manual_review", "reject", "watch_only"})
        self.assertTrue(result["needs_manual_review"])

    def test_overextended_momentum_scores_lower_than_healthy_window(self) -> None:
        settings = Settings()
        healthy = score_candidate(
            symbol="EARLY",
            ticker={"price": 1.0, "chg24h": 10.0, "volume": 80_000_000, "source": "test"},
            funding={"fundingRate_pct": 0.2, "source": "test"},
            alpha={"count24h": 60000, "pct": 8.0},
            klines=[(1, 1.1, 0.95, 1.02, 1)] * 50,
            btc_dir="up",
            missing_fields=[],
            settings=settings,
        )
        late = score_candidate(
            symbol="LATE",
            ticker={"price": 1.0, "chg24h": 70.0, "volume": 80_000_000, "source": "test"},
            funding={"fundingRate_pct": 0.2, "source": "test"},
            alpha={"count24h": 60000, "pct": 40.0},
            klines=[(1, 1.3, 0.95, 1.25, 1)] * 50,
            btc_dir="up",
            missing_fields=[],
            settings=settings,
        )
        self.assertGreater(healthy["module_scores"]["momentum_window"], late["module_scores"]["momentum_window"])

    def test_high_turnover_but_bad_cluster_is_rejected(self) -> None:
        settings = Settings()
        result = score_candidate(
            symbol="RISKY",
            ticker={"price": 1.0, "chg24h": 12.0, "volume": 90_000_000, "source": "test"},
            funding={"fundingRate_pct": 0.1, "source": "test"},
            alpha={"count24h": 20000, "pct": 5.0},
            klines=[(1, 1.1, 0.95, 1.02, 1)] * 50,
            btc_dir="up",
            missing_fields=[],
            settings=settings,
            mapping_confidence="high",
            onchain_data={
                "price_info": {"marketCap": "40000000", "volume24H": "80000000", "holders": "3000", "txs24H": "6000"},
                "advanced_info": {"top10HoldPercent": "20", "suspiciousHoldingPercent": "5"},
                "cluster_overview": {"clusterConcentration": "High", "rugPullPercent": "80", "holderNewAddressPercent": "20"},
                "hot_token": {"txsBuy": "4000", "txsSell": "1000"},
            },
        )
        self.assertEqual(result["decision"], "reject")

    def test_strong_onchain_without_mapping_becomes_watch_only(self) -> None:
        settings = Settings()
        result = score_candidate(
            symbol="WATCH",
            ticker={"price": 1.0, "chg24h": 10.0, "volume": 50_000_000, "source": "test"},
            funding={"fundingRate_pct": 0.2, "source": "test"},
            alpha={"count24h": 80000, "pct": 10.0},
            klines=[(1, 1.1, 0.95, 1.03, 1)] * 50,
            btc_dir="up",
            missing_fields=[],
            settings=settings,
            tradable=False,
            mapping_confidence="none",
            onchain_data={
                "price_info": {"marketCap": "30000000", "volume24H": "60000000", "holders": "8000", "txs24H": "5000", "maxPrice": "1.1", "minPrice": "0.85"},
                "advanced_info": {"top10HoldPercent": "18", "devHoldingPercent": "3", "suspiciousHoldingPercent": "2"},
                "cluster_overview": {"clusterConcentration": "Low", "rugPullPercent": "10", "holderNewAddressPercent": "16"},
                "signals": [{"triggerWalletCount": "4", "walletType": "1", "soldRatioPercent": "20"}],
                "tracker_items": [{"userAddress": "0x1"}, {"userAddress": "0x2"}],
                "okx_x_rank": 6,
                "hot_token": {"txsBuy": "3000", "txsSell": "1500"},
            },
        )
        self.assertEqual(result["decision"], "watch_only")
        self.assertFalse(result["can_enter"])

    def test_major_coin_mode_uses_cex_profile(self) -> None:
        settings = Settings()
        klines_1h = [(100 + i, 102 + i, 99 + i, 101 + i, 10_000) for i in range(50)]
        klines_4h = [(100 + i * 2, 103 + i * 2, 99 + i * 2, 102 + i * 2, 20_000) for i in range(20)]
        result = score_candidate(
            symbol="SOL",
            ticker={"price": 180.0, "chg24h": 8.0, "volume": 950_000_000, "source": "test"},
            funding={"fundingRate_pct": 0.08, "source": "test"},
            alpha={"count24h": 120000, "pct": 6.0},
            klines=klines_1h,
            klines_4h=klines_4h,
            oi={"oi": 200000000, "oi_change_pct": 7.0, "price_change_pct": 8.0},
            btc_dir="up",
            missing_fields=[],
            settings=settings,
            tradable=True,
            market_type="cex_perp",
            mapping_confidence="native",
            strategy_mode="majors_cex",
            onchain_data={},
        )
        self.assertEqual(result["strategy_mode"], "majors_cex")
        self.assertGreaterEqual(result["ers"], 68)
        self.assertGreaterEqual(result["module_scores"]["market_cap_fit"], 6)
        self.assertIn(result["decision"], {"recommend_paper_trade", "watch_only"})


if __name__ == "__main__":
    unittest.main()
