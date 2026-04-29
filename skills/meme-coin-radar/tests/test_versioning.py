from __future__ import annotations

import unittest

from scripts.versioning import load_project_version, version_file_path


class VersioningTest(unittest.TestCase):
    def test_load_project_version_from_version_file(self) -> None:
        expected = version_file_path().read_text(encoding="utf-8").strip()
        self.assertEqual(load_project_version(), expected)
