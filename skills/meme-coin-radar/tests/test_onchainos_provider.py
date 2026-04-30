from __future__ import annotations

import unittest
from unittest.mock import patch

from scripts.providers.common import CommandResult, FetchStatus
from scripts.providers.onchainos import hot_tokens, token_snapshot, tracker_activities


class OnchainosProviderTest(unittest.TestCase):
    @patch("scripts.providers.onchainos.shutil.which", return_value="/usr/local/bin/onchainos")
    @patch("scripts.providers.onchainos.run")
    def test_hot_tokens_prefers_default_json_output(self, mock_run, _mock_which) -> None:
        mock_run.return_value = CommandResult(
            returncode=0,
            stdout='{"ok": true, "data": [{"tokenSymbol": "TEST"}]}',
            stderr="",
            timed_out=False,
        )

        items, status = hot_tokens(ranking_type=4, chain="solana", limit=1, time_frame=4)

        self.assertTrue(status.ok)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["tokenSymbol"], "TEST")
        self.assertNotIn("--format json", mock_run.call_args.args[0])

    @patch("scripts.providers.onchainos.shutil.which", return_value="/usr/local/bin/onchainos")
    @patch("scripts.providers.onchainos.run")
    def test_hot_tokens_falls_back_to_legacy_format_flag(self, mock_run, _mock_which) -> None:
        mock_run.side_effect = [
            CommandResult(returncode=0, stdout="table output", stderr="", timed_out=False),
            CommandResult(returncode=0, stdout='{"data": [{"tokenSymbol": "TEST"}]}', stderr="", timed_out=False),
        ]

        items, status = hot_tokens(ranking_type=4, chain="solana", limit=1, time_frame=4)

        self.assertTrue(status.ok)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["tokenSymbol"], "TEST")
        self.assertEqual(mock_run.call_count, 2)
        self.assertIn("--format json", mock_run.call_args.args[0])

    @patch("scripts.providers.onchainos.shutil.which", return_value="/usr/local/bin/onchainos")
    @patch("scripts.providers.onchainos.run")
    def test_tracker_activities_no_limit_flag(self, mock_run, _mock_which) -> None:
        mock_run.return_value = CommandResult(
            returncode=0,
            stdout='{"ok": true, "data": [{"txHash": "0xabc"}]}',
            stderr="",
            timed_out=False,
        )

        items, status = tracker_activities(tracker_type="smart_money", chain="solana", trade_type=1)

        self.assertTrue(status.ok)
        self.assertEqual(len(items), 1)
        called_cmd = mock_run.call_args.args[0]
        self.assertNotIn("--limit", called_cmd)
        self.assertIn("tracker activities", called_cmd)
        self.assertIn("--tracker-type smart_money", called_cmd)

    @patch("scripts.providers.onchainos.shutil.which", return_value="/usr/local/bin/onchainos")
    @patch("scripts.providers.onchainos.run")
    def test_json_command_classifies_auth_error(self, mock_run, _mock_which) -> None:
        mock_run.return_value = CommandResult(
            returncode=1,
            stdout="",
            stderr="request failed: unauthorized: invalid api key",
            timed_out=False,
        )

        items, status = hot_tokens(ranking_type=4, chain="solana", limit=1, time_frame=4)

        self.assertFalse(status.ok)
        self.assertEqual(status.error_type, FetchStatus.AUTH_ERROR)
        self.assertIn("unauthorized", status.message.lower())

    @patch("scripts.providers.onchainos.shutil.which", return_value="/usr/local/bin/onchainos")
    @patch("scripts.providers.onchainos.run")
    def test_json_command_classifies_unexpected_argument(self, mock_run, _mock_which) -> None:
        mock_run.return_value = CommandResult(
            returncode=1,
            stdout="",
            stderr="error: unexpected argument '--limit' found",
            timed_out=False,
        )

        items, status = hot_tokens(ranking_type=4, chain="solana", limit=1, time_frame=4)

        self.assertFalse(status.ok)
        self.assertNotEqual(status.error_type, FetchStatus.AUTH_ERROR)
        self.assertIn("unexpected argument", status.message.lower())

    @patch("scripts.providers.onchainos.token_price_info")
    @patch("scripts.providers.onchainos.token_advanced_info")
    @patch("scripts.providers.onchainos.token_cluster_overview")
    @patch("scripts.providers.onchainos.token_cluster_top_holders")
    @patch("scripts.providers.onchainos.token_holders")
    @patch("scripts.providers.onchainos.token_trades")
    def test_token_snapshot_lite_only_two_calls(
        self,
        mock_trades,
        mock_holders,
        mock_cluster_top,
        mock_cluster_ov,
        mock_advanced,
        mock_price,
    ) -> None:
        mock_price.return_value = ({"price": 1.0}, FetchStatus(ok=True, source="test"))
        mock_advanced.return_value = ({"risk": "low"}, FetchStatus(ok=True, source="test"))

        result = token_snapshot("0xADDR", chain="solana", depth="lite")

        self.assertEqual(result["price_info"]["price"], 1.0)
        self.assertEqual(result["advanced_info"]["risk"], "low")
        self.assertTrue(mock_price.called)
        self.assertTrue(mock_advanced.called)
        self.assertFalse(mock_cluster_ov.called)
        self.assertFalse(mock_cluster_top.called)
        self.assertFalse(mock_holders.called)
        self.assertFalse(mock_trades.called)
        # Skipped fields must report optional_unavailable, not source_unavailable
        for key in ("cluster_overview", "cluster_top_holders", "holders", "trades"):
            self.assertEqual(result["status"][key]["error_type"], FetchStatus.OPTIONAL_UNAVAILABLE)

    @patch("scripts.providers.onchainos.token_price_info")
    @patch("scripts.providers.onchainos.token_advanced_info")
    @patch("scripts.providers.onchainos.token_cluster_overview")
    @patch("scripts.providers.onchainos.token_cluster_top_holders")
    @patch("scripts.providers.onchainos.token_holders")
    @patch("scripts.providers.onchainos.token_trades")
    def test_token_snapshot_deep_only_four_calls(
        self,
        mock_trades,
        mock_holders,
        mock_cluster_top,
        mock_cluster_ov,
        mock_advanced,
        mock_price,
    ) -> None:
        mock_cluster_ov.return_value = ({"rug": 0.1}, FetchStatus(ok=True, source="test"))
        mock_cluster_top.return_value = ({"top10": 50}, FetchStatus(ok=True, source="test"))
        mock_holders.return_value = ([{"addr": "a"}], FetchStatus(ok=True, source="test"))
        mock_trades.return_value = ([{"tx": "x"}], FetchStatus(ok=True, source="test"))

        result = token_snapshot("0xADDR", chain="solana", depth="deep")

        self.assertFalse(mock_price.called)
        self.assertFalse(mock_advanced.called)
        self.assertTrue(mock_cluster_ov.called)
        self.assertTrue(mock_cluster_top.called)
        self.assertTrue(mock_holders.called)
        self.assertTrue(mock_trades.called)
        self.assertEqual(result["cluster_overview"]["rug"], 0.1)

    @patch("scripts.providers.onchainos.shutil.which", return_value="/usr/local/bin/onchainos")
    @patch("scripts.providers.onchainos.run")
    def test_auth_error_retries_once(self, mock_run, _mock_which) -> None:
        mock_run.side_effect = [
            CommandResult(returncode=1, stdout="", stderr="unauthorized: token expired", timed_out=False),
            CommandResult(returncode=0, stdout='{"ok": true, "data": [{"tokenSymbol": "RETRY"}]}', stderr="", timed_out=False),
        ]

        items, status = hot_tokens(ranking_type=4, chain="solana", limit=1, time_frame=4)

        self.assertTrue(status.ok)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["tokenSymbol"], "RETRY")
        self.assertEqual(mock_run.call_count, 2)

    @patch("scripts.providers.onchainos.shutil.which", return_value="/usr/local/bin/onchainos")
    @patch("scripts.providers.onchainos.run")
    def test_wallet_status_preflight_failure_does_not_conflate(self, mock_run, _mock_which) -> None:
        mock_run.return_value = CommandResult(
            returncode=1, stdout="", stderr="connection refused", timed_out=False,
        )
        from scripts.providers.onchainos import wallet_status

        data, status = wallet_status()
        self.assertFalse(status.ok)
        self.assertEqual(status.error_type, FetchStatus.NETWORK)
        # Must NOT contain loggedIn, so downstream must not assume "not logged in"
        self.assertFalse(data.get("loggedIn", False))

    @patch("scripts.providers.onchainos.shutil.which", return_value="/usr/local/bin/onchainos")
    @patch("scripts.providers.onchainos.run")
    def test_wallet_status_success_not_logged_in(self, mock_run, _mock_which) -> None:
        mock_run.return_value = CommandResult(
            returncode=0, stdout='{"loggedIn": false, "accountCount": 0}', stderr="", timed_out=False,
        )
        from scripts.providers.onchainos import wallet_status

        data, status = wallet_status()
        self.assertTrue(status.ok)
        self.assertFalse(data.get("loggedIn"))
        self.assertEqual(data.get("accountCount"), 0)

    @patch("scripts.providers.onchainos.token_cluster_overview")
    @patch("scripts.providers.onchainos.token_cluster_top_holders")
    @patch("scripts.providers.onchainos.token_holders")
    @patch("scripts.providers.onchainos.token_trades")
    def test_tradable_candidate_receives_deep_fields(self, mock_trades, mock_holders, mock_cluster_top, mock_cluster_ov) -> None:
        # Simulate deep snapshot: cluster/holders/trades fields must be present
        mock_cluster_ov.return_value = ({"rugPullPercent": 0.1}, FetchStatus(ok=True, source="test"))
        mock_cluster_top.return_value = ({"top5": 45}, FetchStatus(ok=True, source="test"))
        mock_holders.return_value = ([{"addr": "a"}], FetchStatus(ok=True, source="test"))
        mock_trades.return_value = ([{"tx": "x"}], FetchStatus(ok=True, source="test"))

        result = token_snapshot("0xADDR", chain="solana", depth="deep")

        # Deep fields needed by hard reject gates must be populated
        self.assertIn("rugPullPercent", result["cluster_overview"])
        self.assertIsNotNone(result["cluster_top_holders"])
        self.assertIsNotNone(result["holders"])
        self.assertIsNotNone(result["trades"])
