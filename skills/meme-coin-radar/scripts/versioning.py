from __future__ import annotations

from pathlib import Path


DEFAULT_RADAR_VERSION = "0.0.0-dev"


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def version_file_path() -> Path:
    return project_root() / "VERSION"


def load_project_version() -> str:
    path = version_file_path()
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        return DEFAULT_RADAR_VERSION
    return value or DEFAULT_RADAR_VERSION
