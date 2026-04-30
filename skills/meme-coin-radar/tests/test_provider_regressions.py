from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.config import Settings
from scripts.history_store import cleanup_old_snapshots
from scripts.providers import binance as binance_provider
from scripts.providers.common import FetchStatus
from scripts.providers.intel import (
    _resolve_panews_cli,
    _resolve_surf_bin,
    _resolve_surf_social_cmd,
    _run_command,
    fetch_social_intel,
)
from scripts.providers import okx as okx_provider
from scripts.radar_logic import score_candidate


class ProviderResolutionTest(unittest.TestCase):
    """Regression tests for provider CLI resolution (review-report.md fixes)."""

    @patch.dict(os.environ, {}, clear=True)
    @patch("scripts.providers.intel.shutil.which", return_value=None)
    def test_panews_cli_returns_none_when_no_candidates(self, _mock_which) -> None:
        with patch("pathlib.Path.exists", return_value=False):
            result = _resolve_panews_cli()
        self.assertIsNone(result)

    @patch("pathlib.Path.exists", return_value=True)
    @patch.dict(os.environ, {"RADAR_PANEWS_CLI": "/custom/panews/cli.mjs"})
    def test_panews_cli_prefers_env_override(self, _mock_exists) -> None:
        result = _resolve_panews_cli()
        self.assertIsNotNone(result)
        self.assertEqual(str(result), "/custom/panews/cli.mjs")

    @patch.dict(os.environ, {}, clear=True)
    def test_surf_bin_prefers_env_override(self) -> None:
        with patch("scripts.providers.intel.shutil.which", side_effect=lambda x: x if x == "/custom/surf" else None):
            with patch.dict(os.environ, {"RADAR_SURF_BIN": "/custom/surf"}):
                result = _resolve_surf_bin()
        self.assertEqual(result, "/custom/surf")

    @patch.dict(os.environ, {}, clear=True)
    @patch("scripts.providers.intel.shutil.which", return_value="surf")
    def test_surf_bin_falls_back_to_path(self, _mock_which) -> None:
        result = _resolve_surf_bin()
        self.assertEqual(result, "surf")

    @patch.dict(os.environ, {"RADAR_SURF_SOCIAL_CMD": "search-social-posts"})
    def test_surf_social_cmd_uses_env_override(self) -> None:
        result = _resolve_surf_social_cmd()
        self.assertEqual(result, "search-social-posts")

    def test_surf_social_cmd_defaults_to_search_social(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            result = _resolve_surf_social_cmd()
        self.assertEqual(result, "search-social")


class QuotaHandlingTest(unittest.TestCase):
    """Regression tests for quota/rate-limit error classification."""

    @patch("scripts.providers.intel.subprocess.run")
    def test_run_command_detects_free_quota_exhausted(self, mock_run) -> None:
        mock_run.return_value = MagicMock(returncode=4, stdout="", stderr="Error: free_quota_exhausted")
        raw, status = _run_command(["surf", "test"], source="surf-test")
        self.assertIsNone(raw)
        self.assertFalse(status.ok)
        self.assertEqual(status.error_type, FetchStatus.RATE_LIMIT)

    @patch("scripts.providers.intel.subprocess.run")
    def test_run_command_detects_paid_balance_zero(self, mock_run) -> None:
        mock_run.return_value = MagicMock(returncode=4, stdout="", stderr="Error: PAID_BALANCE_ZERO")
        raw, status = _run_command(["surf", "test"], source="surf-test")
        self.assertEqual(status.error_type, FetchStatus.RATE_LIMIT)

    @patch("scripts.providers.intel.subprocess.run")
    def test_run_command_detects_rate_limited(self, mock_run) -> None:
        mock_run.return_value = MagicMock(returncode=429, stdout="", stderr="rate_limited: too many requests")
        raw, status = _run_command(["surf", "test"], source="surf-test")
        self.assertEqual(status.error_type, FetchStatus.RATE_LIMIT)

    @patch("scripts.providers.intel.subprocess.run")
    def test_run_command_detects_unauthorized(self, mock_run) -> None:
        mock_run.return_value = MagicMock(returncode=401, stdout="", stderr="unauthorized: invalid api key")
        raw, status = _run_command(["surf", "test"], source="surf-test")
        self.assertEqual(status.error_type, FetchStatus.AUTH_ERROR)


class ProviderRegressionTest(unittest.TestCase):
    @patch("scripts.providers.okx._okx_public_json")
    def test_okx_btc_status_uses_http_api(self, mock_okx_public_json) -> None:
        mock_okx_public_json.return_value = (
            {
                "code": "0",
                "data": [
                    {
                        "instId": "BTC-USDT-SWAP",
                        "last": "100000",
                        "open24h": "98000",
                    }
                ],
            },
            FetchStatus(ok=True, source="okx-market-ticker"),
        )

        data = okx_provider.btc_status()

        self.assertEqual(data["source"], "okx")
        self.assertEqual(data["price"], 100000.0)
        self.assertEqual(data["direction"], "up")
        self.assertEqual(mock_okx_public_json.call_args.kwargs["source"], "okx-market-ticker")

    @patch("scripts.providers.okx._okx_public_json")
    def test_okx_swap_tickers_uses_http_api(self, mock_okx_public_json) -> None:
        mock_okx_public_json.return_value = (
            {
                "code": "0",
                "data": [
                    {
                        "instId": "DOGE-USDT-SWAP",
                        "last": "0.25",
                        "high24h": "0.30",
                        "low24h": "0.20",
                        "volCcy24h": "123456",
                        "open24h": "0.20",
                    },
                    {
                        "instId": "BTC-USD-SWAP",
                        "last": "1",
                        "high24h": "1",
                        "low24h": "1",
                        "volCcy24h": "1",
                        "open24h": "1",
                    },
                ],
            },
            FetchStatus(ok=True, source="okx-market-tickers"),
        )

        items = okx_provider.swap_tickers()

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["symbol"], "DOGE")
        self.assertAlmostEqual(items[0]["chg24h_pct"], 25.0, places=6)
        self.assertEqual(mock_okx_public_json.call_args.kwargs["params"], {"instType": "SWAP"})

    @patch("scripts.providers.okx._okx_private_json")
    def test_okx_account_equity_falls_back_to_positions(self, mock_okx_private_json) -> None:
        mock_okx_private_json.side_effect = [
            (
                None,
                FetchStatus(ok=False, error_type=FetchStatus.AUTH_ERROR, source="okx-account-balance"),
            ),
            (
                {
                    "code": "0",
                    "data": [
                        {"margin": "12.5"},
                        {"margin": "7.5"},
                    ],
                },
                FetchStatus(ok=True, source="okx-account-positions"),
            ),
        ]

        total = okx_provider.account_equity()

        self.assertEqual(total, 20.0)

    def test_score_candidate_uses_ticker_low_for_intraday_position(self) -> None:
        result = score_candidate(
            symbol="TEST",
            ticker={
                "price": 100.0,
                "chg24h": 10.0,
                "high24h": 120.0,
                "low24h": 80.0,
                "volume": 2_000_000.0,
                "source": "test",
            },
            funding={"fundingRate_pct": 0.01, "source": "test"},
            alpha={"count24h": 1000},
            klines=[(90.0, 100.0, 80.0, 95.0, 1000.0, 1)] * 50,
            btc_dir="up",
            missing_fields=[],
            settings=Settings(),
            onchain_data={"price_info": {"maxPrice": "120"}},
        )
        self.assertAlmostEqual(result["meta"]["day_pos"], 0.5, places=6)

    @patch("scripts.providers.binance.http_json_safe")
    def test_futures_ticker_uses_http_api_without_cli(self, mock_http_json_safe) -> None:
        binance_provider._TICKER_24H_CACHE = None
        binance_provider._TICKER_24H_CACHE_TS = 0.0
        mock_http_json_safe.return_value = (
            [
                {
                    "symbol": "TESTUSDT",
                    "lastPrice": "1.25",
                    "priceChangePercent": "12.5",
                    "highPrice": "1.50",
                    "lowPrice": "1.00",
                    "quoteVolume": "12345.6",
                }
            ],
            FetchStatus(ok=True, source="binance-ticker24hr-all"),
        )

        data, status = binance_provider.futures_ticker("TEST")

        self.assertTrue(status.ok)
        self.assertIsNotNone(data)
        assert data is not None
        self.assertEqual(data["source"], "binance")
        self.assertEqual(data["price"], 1.25)
        self.assertEqual(mock_http_json_safe.call_args.args[0], "https://fapi.binance.com/fapi/v1/ticker/24hr")

    @patch("scripts.providers.binance.http_json_safe")
    def test_open_interest_returns_tuple_status(self, mock_http_json_safe) -> None:
        mock_http_json_safe.side_effect = [
            (
                {"openInterest": "2500", "time": 1234567890},
                FetchStatus(ok=True, source="binance-oi"),
            ),
            (
                [{"sumOpenInterest": "2000"}, {"sumOpenInterest": "2400"}],
                FetchStatus(ok=True, source="binance-oi-hist"),
            ),
        ]

        data, status = binance_provider.open_interest("TEST")

        self.assertTrue(status.ok)
        self.assertIsNotNone(data)
        assert data is not None
        self.assertEqual(data["oi"], 2500.0)
        self.assertEqual(data["source"], "binance")
        self.assertAlmostEqual(data["oi_change_pct"], 25.0, places=6)

    def test_cleanup_old_snapshots_ignores_non_daily_filenames(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            history = output_dir / "history"
            history.mkdir(parents=True, exist_ok=True)
            (history / "ticker_20000101.json").write_text("{}", encoding="utf-8")
            (history / "social_2000010101.json").write_text("{}", encoding="utf-8")
            (history / "intel_cache_panews_rankings_en.json").write_text("{}", encoding="utf-8")

            removed = cleanup_old_snapshots(output_dir, keep_days=30)

            self.assertEqual(removed, 2)
            self.assertFalse((history / "ticker_20000101.json").exists())
            self.assertFalse((history / "social_2000010101.json").exists())
            self.assertTrue((history / "intel_cache_panews_rankings_en.json").exists())

    @patch("scripts.providers.intel.load_recent_social_snapshot", return_value=None)
    @patch("scripts.providers.intel.fetch_panews_polymarket_snapshot")
    @patch("scripts.providers.intel.fetch_panews_calendar")
    @patch("scripts.providers.intel.fetch_panews_events")
    @patch("scripts.providers.intel.fetch_panews_news")
    @patch("scripts.providers.intel.fetch_surf_social")
    @patch("scripts.providers.intel.fetch_surf_news")
    def test_panews_hot_rank_requires_exact_keyword(
        self,
        mock_surf_news,
        mock_surf_social,
        mock_panews_news,
        mock_panews_events,
        mock_panews_calendar,
        mock_panews_polymarket,
        _mock_recent_snapshot,
    ) -> None:
        ok_payload = {"ok": True, "source": "test", "fetched_at": 1, "confidence": 1.0, "data": {}}
        mock_surf_news.return_value = {**ok_payload, "data": {"article_count": 0, "headlines": [], "event_tags": []}}
        mock_surf_social.return_value = {**ok_payload, "data": {"mentions_24h": 0, "kol_mentions": 0}}
        mock_panews_news.return_value = {**ok_payload, "data": {"article_count": 0, "headlines": []}}
        mock_panews_events.return_value = {**ok_payload, "data": {"event_count": 0}}
        mock_panews_calendar.return_value = {**ok_payload, "data": {"calendar_flags": []}}
        mock_panews_polymarket.return_value = {**ok_payload, "data": {"score": None, "labels": []}}

        with tempfile.TemporaryDirectory() as tmpdir:
            result = fetch_social_intel(
                symbol="INJ",
                output_dir=Path(tmpdir),
                panews_context={
                    "panews_rankings": ok_payload,
                    "panews_hooks": {"ok": True, "source": "test", "fetched_at": 1, "confidence": 1.0, "data": {"items": [{"keyword": "INJECTIVE"}]}},
                    "panews_polymarket": mock_panews_polymarket.return_value,
                },
            )

        self.assertIsNone(result["panews_hot_rank"])
