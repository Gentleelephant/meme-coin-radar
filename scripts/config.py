from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _get_env(name: str, default: str) -> str:
    return os.environ.get(name, default).strip()


def _get_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return float(raw.strip())


def _get_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return int(raw.strip())


def _get_list(name: str, default: str) -> tuple[str, ...]:
    raw = _get_env(name, default)
    return tuple(part.strip().upper() for part in raw.split(",") if part.strip())


@dataclass
class Settings:
    output_dir: Path = field(default_factory=lambda: Path(_get_env("RADAR_OUTPUT_DIR", "~/meme-radar")).expanduser())
    top_n: int = field(default_factory=lambda: _get_int("RADAR_TOP_N", 8))
    recommendation_top_n: int = field(default_factory=lambda: _get_int("RADAR_RECOMMENDATION_TOP_N", 3))
    min_watch_score: float = field(default_factory=lambda: _get_float("RADAR_MIN_WATCH_SCORE", 30.0))
    min_recommend_score: float = field(default_factory=lambda: _get_float("RADAR_MIN_RECOMMEND_SCORE", 45.0))
    min_direction_bias: float = field(default_factory=lambda: _get_float("RADAR_MIN_DIRECTION_BIAS", 18.0))
    min_direction_gap: float = field(default_factory=lambda: _get_float("RADAR_MIN_DIRECTION_GAP", 6.0))
    key_coins: tuple[str, ...] = field(
        default_factory=lambda: _get_list(
            "RADAR_KEY_COINS",
            "BTC,ETH,SOL,ZEC,HYPE,BNB,DOGE,PEPE,WIF,SHIB,AAVE,AVAX,LINK,UNI,ARB,OP,INJ,SEI,TIA,SUI,APT,NEAR,FTM",
        )
    )


def load_settings() -> Settings:
    _load_dotenv(Path(".env"))
    return Settings()


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
