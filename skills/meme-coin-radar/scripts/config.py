from __future__ import annotations

import os
import tempfile
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


def _get_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _get_list(name: str, default: str) -> tuple[str, ...]:
    raw = _get_env(name, default)
    items: list[str] = []
    for part in raw.split(","):
        value = part.strip().upper()
        if value and value not in items:
            items.append(value)
    return tuple(items)


def _default_output_dir() -> Path:
    xdg_state_home = os.environ.get("XDG_STATE_HOME", "").strip()
    if xdg_state_home:
        return Path(xdg_state_home).expanduser() / "meme-coin-radar"
    return Path("~/.local/state").expanduser() / "meme-coin-radar"


def ensure_output_dir(preferred: Path) -> Path:
    candidates = [preferred, Path(tempfile.gettempdir()) / "meme-coin-radar"]
    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
        except OSError:
            continue
    raise OSError("Unable to create a writable output directory for meme-coin-radar")


@dataclass
class Settings:
    output_dir: Path = field(default_factory=lambda: Path(_get_env("RADAR_OUTPUT_DIR", str(_default_output_dir()))).expanduser())
    run_mode: str = field(default_factory=lambda: _get_env("RADAR_RUN_MODE", "scan").lower())
    target_symbols: tuple[str, ...] = field(default_factory=lambda: _get_list("RADAR_TARGET_SYMBOLS", ""))
    top_n: int = field(default_factory=lambda: _get_int("RADAR_TOP_N", 8))
    recommendation_top_n: int = field(default_factory=lambda: _get_int("RADAR_RECOMMENDATION_TOP_N", 3))
    # Obsidian-aligned thresholds
    min_watch_score: float = field(default_factory=lambda: _get_float("RADAR_MIN_WATCH_SCORE", 50.0))
    min_recommend_score: float = field(default_factory=lambda: _get_float("RADAR_MIN_RECOMMEND_SCORE", 75.0))
    min_direction_bias: float = field(default_factory=lambda: _get_float("RADAR_MIN_DIRECTION_BIAS", 18.0))
    min_direction_gap: float = field(default_factory=lambda: _get_float("RADAR_MIN_DIRECTION_GAP", 6.0))
    min_rr: float = field(default_factory=lambda: _get_float("RADAR_MIN_RR", 1.5))
    stop_loss_atr_mult: float = field(default_factory=lambda: _get_float("RADAR_STOP_LOSS_ATR_MULT", 0.8))
    entry_buffer_atr_mult: float = field(default_factory=lambda: _get_float("RADAR_ENTRY_BUFFER_ATR_MULT", 0.35))
    take_profit_1_r_mult: float = field(default_factory=lambda: _get_float("RADAR_TAKE_PROFIT_1_R_MULT", 1.6))
    take_profit_2_r_mult: float = field(default_factory=lambda: _get_float("RADAR_TAKE_PROFIT_2_R_MULT", 2.4))
    tp1_fraction: float = field(default_factory=lambda: _get_float("RADAR_TP1_FRACTION", 0.5))
    majors_min_rr: float = field(default_factory=lambda: _get_float("RADAR_MAJORS_MIN_RR", 1.8))
    majors_stop_loss_atr_mult: float = field(default_factory=lambda: _get_float("RADAR_MAJORS_STOP_LOSS_ATR_MULT", 0.65))
    majors_entry_buffer_atr_mult: float = field(default_factory=lambda: _get_float("RADAR_MAJORS_ENTRY_BUFFER_ATR_MULT", 0.22))
    majors_take_profit_1_r_mult: float = field(default_factory=lambda: _get_float("RADAR_MAJORS_TAKE_PROFIT_1_R_MULT", 1.2))
    majors_take_profit_2_r_mult: float = field(default_factory=lambda: _get_float("RADAR_MAJORS_TAKE_PROFIT_2_R_MULT", 2.1))
    majors_tp1_fraction: float = field(default_factory=lambda: _get_float("RADAR_MAJORS_TP1_FRACTION", 0.6))
    require_protection: bool = field(default_factory=lambda: _get_bool("RADAR_REQUIRE_PROTECTION", True))
    require_dual_tp: bool = field(default_factory=lambda: _get_bool("RADAR_REQUIRE_DUAL_TP", True))
    trailing_mode: str = field(default_factory=lambda: _get_env("RADAR_TRAILING_MODE", "break_even"))
    trailing_callback_rate: float = field(default_factory=lambda: _get_float("RADAR_TRAILING_CALLBACK_RATE", 1.5))
    break_even_offset_bps: float = field(default_factory=lambda: _get_float("RADAR_BREAK_EVEN_OFFSET_BPS", 5.0))
    trailing_activation: str = field(default_factory=lambda: _get_env("RADAR_TRAILING_ACTIVATION", "tp1_hit"))
    majors_trailing_mode: str = field(default_factory=lambda: _get_env("RADAR_MAJORS_TRAILING_MODE", "break_even"))
    majors_trailing_callback_rate: float = field(default_factory=lambda: _get_float("RADAR_MAJORS_TRAILING_CALLBACK_RATE", 1.0))
    majors_break_even_offset_bps: float = field(default_factory=lambda: _get_float("RADAR_MAJORS_BREAK_EVEN_OFFSET_BPS", 3.0))
    execution_mode: str = field(default_factory=lambda: _get_env("RADAR_EXECUTION_MODE", "paper"))
    auto_execute_paper_trades: bool = field(default_factory=lambda: _get_bool("RADAR_AUTO_EXECUTE_PAPER_TRADES", False))
    validate_orders_with_binance: bool = field(default_factory=lambda: _get_bool("RADAR_VALIDATE_ORDERS_WITH_BINANCE", False))
    major_coins: tuple[str, ...] = field(
        default_factory=lambda: _get_list(
            "RADAR_MAJOR_COINS",
            "BTC,ETH,SOL,ZEC,HYPE,BNB,DOGE,AAVE,AVAX,LINK,UNI,ARB,OP,INJ,SEI,TIA,SUI,APT,NEAR,FTM",
        )
    )
    key_coins: tuple[str, ...] = field(
        default_factory=lambda: _get_list(
            "RADAR_KEY_COINS",
            "BTC,ETH,SOL,ZEC,HYPE,BNB,DOGE,PEPE,WIF,SHIB,AAVE,AVAX,LINK,UNI,ARB,OP,INJ,SEI,TIA,SUI,APT,NEAR,FTM",
        )
    )
    # Discovered configurable parameters
    discovery_top_alpha_n: int = field(default_factory=lambda: _get_int("RADAR_DISCOVERY_TOP_ALPHA_N", 15))
    batch_workers: int = field(default_factory=lambda: _get_int("RADAR_BATCH_WORKERS", 12))
    batch_timeout_seconds: int = field(default_factory=lambda: _get_int("RADAR_BATCH_TIMEOUT_SECONDS", 60))


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
