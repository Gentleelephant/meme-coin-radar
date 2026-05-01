from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from scripts.config import Settings


class ConfigTest(unittest.TestCase):
    def test_run_mode_and_target_symbols_from_env(self) -> None:
        with patch.dict(
            os.environ,
            {
                "RADAR_RUN_MODE": "monitor",
                "RADAR_TARGET_SYMBOLS": "pepe, wif ,PEPE",
            },
            clear=False,
        ):
            settings = Settings()
        self.assertEqual(settings.run_mode, "monitor")
        self.assertEqual(settings.target_symbols, ("PEPE", "WIF"))
