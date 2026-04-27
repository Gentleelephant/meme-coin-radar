from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.config import Settings
from scripts.execution_binance import execute_paper_bracket
from scripts.paper_reconciler import PriceTick, reconcile_all_positions
from scripts.radar_logic import build_trade_plan, calc_trend_structure, score_candidate
from scripts.scoring_modules import score_social_momentum


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
        self.assertIn("execution", plan)
        self.assertEqual(plan["execution"]["entry_order"]["type"], "MARKET")
        self.assertEqual(plan["execution"]["stop_loss_order"]["trailing"]["mode"], "break_even")

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

    def test_social_intel_boosts_social_heat_v2(self) -> None:
        settings = Settings(min_recommend_score=75.0)
        base_kwargs = {
            "symbol": "PEPE",
            "ticker": {"price": 1.0, "chg24h": 18.0, "volume": 120_000_000, "source": "test"},
            "funding": {"fundingRate_pct": 0.1, "source": "test"},
            "alpha": {"count24h": 60000, "pct": 12.0},
            "klines": [(1, 1.1, 0.95, 1.02, 1)] * 50,
            "btc_dir": "up",
            "missing_fields": [],
            "settings": settings,
            "mapping_confidence": "high",
            "onchain_data": {
                "price_info": {"marketCap": "25000000", "volume24H": "28000000", "holders": "10000", "txs24H": "8500"},
                "advanced_info": {"top10HoldPercent": "20"},
                "cluster_overview": {"clusterConcentration": "Low", "rugPullPercent": "10", "holderNewAddressPercent": "16"},
                "signals": [{"triggerWalletCount": "3", "walletType": "1", "soldRatioPercent": "20"}],
                "tracker_items": [{"userAddress": "0x1"}],
                "okx_x_rank": 6,
                "hot_token": {"txsBuy": "4200", "txsSell": "1700"},
            },
        }
        cold = score_candidate(**base_kwargs)
        hot = score_candidate(
            **base_kwargs,
            social_intel={
                "social_mentions_24h": 180,
                "social_growth_6h": 0.9,
                "mindshare_score": 4.0,
                "global_news_count_24h": 4,
                "panews_article_count_24h": 3,
                "panews_editorial_keywords": ["pepe", "meme"],
                "panews_event_count_7d": 1,
                "narrative_labels": ["meme"],
            },
        )
        self.assertGreater(hot["module_scores"]["social_heat"], cold["module_scores"]["social_heat"])
        self.assertGreater(hot["oos"], cold["oos"])
        self.assertIn("social_momentum", hot["module_scores"])
        self.assertIn("news_narrative", hot["module_scores"])

    def test_social_momentum_requires_positive_growth_for_bonus(self) -> None:
        cold = score_social_momentum(okx_x_rank=10, social_mentions_24h=50, social_growth_6h=0.0, mindshare_score=None, alpha_count24h=60000)
        hot = score_social_momentum(okx_x_rank=10, social_mentions_24h=50, social_growth_6h=0.6, mindshare_score=None, alpha_count24h=60000)
        self.assertGreater(hot, cold)

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

    def test_execute_paper_bracket_creates_protected_orders(self) -> None:
        output_dir = Path(tempfile.mkdtemp(prefix="radar-paper-"))
        result = {
            "symbol": "SOL",
            "decision": "recommend_paper_trade",
            "direction": "long",
            "strategy_mode": "majors_cex",
            "trade_plan": {
                "execution": {
                    "symbol": "SOLUSDT",
                    "quantity": 2.4,
                    "entry_price": 180.0,
                    "entry_order": {"side": "BUY", "type": "MARKET", "price": None, "time_in_force": None},
                    "stop_loss_order": {
                        "side": "SELL",
                        "type": "STOP_MARKET",
                        "stop_price": 171.0,
                        "reduce_only": True,
                        "working_type": "MARK_PRICE",
                        "price_protect": True,
                    },
                    "take_profit_orders": [
                        {"side": "SELL", "type": "TAKE_PROFIT_MARKET", "stop_price": 190.0, "quantity": 1.2, "reduce_only": True, "working_type": "MARK_PRICE", "price_protect": True},
                        {"side": "SELL", "type": "TAKE_PROFIT_MARKET", "stop_price": 198.0, "quantity": 1.2, "reduce_only": True, "working_type": "MARK_PRICE", "price_protect": True},
                    ],
                }
            },
        }
        execution = execute_paper_bracket(
            result,
            output_dir=output_dir,
            execution_mode="paper",
            validate_with_binance=False,
            exchange_info_fetcher=lambda _symbol: None,
        )
        self.assertEqual(execution["status"], "PENDING")
        self.assertTrue(execution["protected"])
        self.assertEqual(execution["entry_order"]["side"], "BUY")
        self.assertEqual(execution["stop_loss_order"]["side"], "SELL")
        self.assertEqual(len(execution["take_profit_orders"]), 2)

    def test_reconcile_position_hits_take_profit_and_updates_metrics(self) -> None:
        output_dir = Path(tempfile.mkdtemp(prefix="radar-reconcile-"))
        result = {
            "symbol": "SOL",
            "decision": "recommend_paper_trade",
            "direction": "long",
            "strategy_mode": "majors_cex",
            "candidate_sources": ["alpha_hot", "key_coins"],
            "oos": 72,
            "ers": 74,
            "final_score": 73,
            "trade_plan": {
                "execution": {
                    "symbol": "SOLUSDT",
                    "leverage": 3,
                    "quantity": 2.0,
                    "entry_price": 100.0,
                    "stop_loss": 95.0,
                    "entry_order": {"side": "BUY", "type": "MARKET", "price": None, "time_in_force": None},
                    "stop_loss_order": {
                        "side": "SELL",
                        "type": "STOP_MARKET",
                        "stop_price": 95.0,
                        "reduce_only": True,
                        "working_type": "MARK_PRICE",
                        "price_protect": True,
                    },
                    "take_profit_orders": [
                        {"side": "SELL", "type": "TAKE_PROFIT_MARKET", "stop_price": 105.0, "quantity": 1.0, "reduce_only": True, "working_type": "MARK_PRICE", "price_protect": True},
                        {"side": "SELL", "type": "TAKE_PROFIT_MARKET", "stop_price": 108.0, "quantity": 1.0, "reduce_only": True, "working_type": "MARK_PRICE", "price_protect": True},
                    ],
                }
            },
        }
        execute_paper_bracket(
            result,
            output_dir=output_dir,
            execution_mode="paper",
            validate_with_binance=False,
            exchange_info_fetcher=lambda _symbol: None,
        )
        tick_map = {
            "SOLUSDT": [
                PriceTick(open=100.0, high=103.0, low=99.0, close=102.0, volume=1000.0, timestamp=1),
                PriceTick(open=102.0, high=106.0, low=101.0, close=105.0, volume=1000.0, timestamp=2),
                PriceTick(open=105.0, high=109.0, low=104.0, close=108.0, volume=1000.0, timestamp=3),
            ]
        }
        reconciled = reconcile_all_positions(output_dir, tick_map=tick_map)
        self.assertEqual(reconciled["closed_positions"], 1)
        self.assertEqual(reconciled["metrics"]["total_trades"], 1)
        self.assertGreater(reconciled["metrics"]["raw_win_rate"], 0.0)
        self.assertGreater(reconciled["metrics"]["tp1_hit_rate"], 0.0)
        self.assertGreater(reconciled["account"]["current_equity"], reconciled["account"]["starting_equity"])
        self.assertIn("long", reconciled["metrics"]["breakdown"]["direction"])
        self.assertIn("70-79", reconciled["metrics"]["breakdown"]["score_bucket"])

    def test_break_even_trailing_moves_stop_after_tp1(self) -> None:
        output_dir = Path(tempfile.mkdtemp(prefix="radar-break-even-"))
        result = {
            "symbol": "SOL",
            "decision": "recommend_paper_trade",
            "direction": "long",
            "strategy_mode": "majors_cex",
            "candidate_sources": ["alpha_hot"],
            "oos": 78,
            "ers": 72,
            "final_score": 75,
            "trade_plan": {
                "execution": {
                    "symbol": "SOLUSDT",
                    "leverage": 3,
                    "quantity": 2.0,
                    "entry_price": 100.0,
                    "stop_loss": 95.0,
                    "entry_order": {"side": "BUY", "type": "MARKET", "price": None, "time_in_force": None},
                    "stop_loss_order": {
                        "side": "SELL",
                        "type": "STOP_MARKET",
                        "algo_type": "STOP_MARKET",
                        "stop_price": 95.0,
                        "reduce_only": True,
                        "working_type": "MARK_PRICE",
                        "price_protect": True,
                        "trailing": {"mode": "break_even", "activation": "tp1_hit", "break_even_offset_bps": 5.0, "enabled": True},
                    },
                    "take_profit_orders": [
                        {"side": "SELL", "type": "TAKE_PROFIT_MARKET", "stop_price": 105.0, "quantity": 1.0, "reduce_only": True, "working_type": "MARK_PRICE", "price_protect": True},
                        {"side": "SELL", "type": "TAKE_PROFIT_MARKET", "stop_price": 110.0, "quantity": 1.0, "reduce_only": True, "working_type": "MARK_PRICE", "price_protect": True},
                    ],
                }
            },
        }
        execute_paper_bracket(
            result,
            output_dir=output_dir,
            execution_mode="paper",
            validate_with_binance=False,
            exchange_info_fetcher=lambda _symbol: None,
        )
        tick_map = {
            "SOLUSDT": [
                PriceTick(open=100.0, high=103.0, low=99.0, close=102.0, volume=1000.0, timestamp=1),
                PriceTick(open=102.0, high=106.0, low=101.0, close=105.0, volume=1000.0, timestamp=2),
                PriceTick(open=105.0, high=105.0, low=99.0, close=100.0, volume=1000.0, timestamp=3),
            ]
        }
        reconciled = reconcile_all_positions(output_dir, tick_map=tick_map)
        self.assertEqual(reconciled["closed_positions"], 1)
        self.assertGreater(reconciled["metrics"]["raw_win_rate"], 0.0)
        self.assertGreater(reconciled["account"]["realized_pnl"], 0.0)


if __name__ == "__main__":
    unittest.main()
