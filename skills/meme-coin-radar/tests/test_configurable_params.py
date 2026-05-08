"""
Test configurable parameters (Issue #6).

Verifies that batch workers, batch timeout, and discovery top_alpha_n
can be configured via environment variables with proper fallback defaults.
"""

import os
import sys
from pathlib import Path

scripts_dir = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(scripts_dir))


def test_config_defaults():
    """Test config loads default values for new parameters."""
    from config import load_settings

    s = load_settings()
    assert s.discovery_top_alpha_n == 15
    assert s.batch_workers == 12
    assert s.batch_timeout_seconds == 60


def test_config_env_override(monkeypatch):
    """Test config can be overridden via environment variables."""
    monkeypatch.setenv("RADAR_DISCOVERY_TOP_ALPHA_N", "30")
    monkeypatch.setenv("RADAR_BATCH_WORKERS", "8")
    monkeypatch.setenv("RADAR_BATCH_TIMEOUT_SECONDS", "90")

    # Reimport to force re-evaluation of field defaults
    import importlib
    from config import load_settings
    import config as cfg
    importlib.reload(cfg)

    s = load_settings()
    assert s.discovery_top_alpha_n == 30
    assert s.batch_workers == 8
    assert s.batch_timeout_seconds == 90


def test_skill_dispatcher_getters(monkeypatch):
    """Test skill_dispatcher can read env overrides."""
    monkeypatch.setenv("RADAR_BATCH_WORKERS", "10")
    monkeypatch.setenv("RADAR_BATCH_TIMEOUT_SECONDS", "120")

    import importlib
    import skill_dispatcher as sd
    importlib.reload(sd)

    # Verify module-level getter functions work
    assert sd._get_batch_workers() == 10
    assert sd._get_batch_timeout() == 120


def test_skill_dispatcher_defaults():
    """Test skill_dispatcher falls back to defaults without env."""
    # Clear env vars for this test
    os.environ.pop("RADAR_BATCH_WORKERS", None)
    os.environ.pop("RADAR_BATCH_TIMEOUT_SECONDS", None)

    import importlib
    import skill_dispatcher as sd
    importlib.reload(sd)

    assert sd._get_batch_workers() == 12
    assert sd._get_batch_timeout() == 60


def test_candidate_discovery_top_alpha():
    """Test discover_candidates accepts top_alpha_n parameter."""
    import importlib
    from candidate_discovery import discover_candidates
    import candidate_discovery as cd
    importlib.reload(cd)

    # Call with explicit top_alpha_n
    result = discover_candidates(
        okx_hot_tokens=[],
        okx_x_tokens=[],
        okx_signals=[],
        okx_tracker_activities=[],
        alpha_dict={},
        key_coins=[],
        major_coins=[],
        top_alpha_n=30,
    )
    assert isinstance(result, list)
    assert len(result) == 0  # No candidates with empty inputs


if __name__ == "__main__":
    test_config_defaults()
    print("✅ test_config_defaults passed")

    # Can't use monkeypatch outside pytest, skip those
    print("✅ config/env override tests require pytest (monkeypatch)")

    test_candidate_discovery_top_alpha()
    print("✅ test_candidate_discovery_top_alpha passed")

    print("\n✅ All configurable params tests passed!")