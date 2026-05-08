from __future__ import annotations

import unittest
from pathlib import Path

import yaml

from scripts.versioning import load_project_version, version_file_path


SKILL_MD_PATH = Path(__file__).resolve().parents[1] / "SKILL.md"


def _parse_skill_frontmatter(path: Path) -> dict:
    """Parse YAML frontmatter from SKILL.md."""
    content = path.read_text(encoding="utf-8")
    if not content.startswith("---"):
        return {}
    _, frontmatter, _ = content.split("---", 2)
    return yaml.safe_load(frontmatter) or {}


class VersioningTest(unittest.TestCase):
    def test_load_project_version_from_version_file(self) -> None:
        expected = version_file_path().read_text(encoding="utf-8").strip()
        self.assertEqual(load_project_version(), expected)

    def test_version_matches_skill_metadata(self) -> None:
        """VERSION and SKILL.md metadata.version must be in sync."""
        version = load_project_version()
        skill_meta = _parse_skill_frontmatter(SKILL_MD_PATH)
        skill_version = skill_meta.get("version", "")
        self.assertEqual(
            skill_version,
            version,
            f"SKILL.md version ({skill_version}) != VERSION ({version})",
        )
