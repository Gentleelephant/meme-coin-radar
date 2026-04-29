from __future__ import annotations

import unittest
from unittest.mock import patch

from scripts.providers.common import CommandResult
from scripts.providers.onchainos import hot_tokens


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
