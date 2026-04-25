from __future__ import annotations

import time

from typing import Any, Optional

from . import hyperliquid
from .common import FetchStatus, http_json, http_json_safe, json_out, json_out_safe

# Official Binance skill references:
BINANCE_ALPHA_TOKEN_LIST_CMD = "npx -y @binance/binance-cli alpha token-list --json"
BINANCE_FUTURES_TICKER_CMD = (
    "npx -y @binance/binance-cli futures-usds ticker24hr-price-change-statistics --symbol {symbol}USDT --json"
)
BINANCE_FUTURES_FUNDING_INFO_CMD = (
    "npx -y @binance/binance-cli futures-usds get-funding-rate-info --json"
)
BINANCE_FUTURES_KLINES_CMD = (
    "npx -y @binance/binance-cli futures-usds kline-candlestick-data --symbol {symbol}USDT --interval {interval} --limit {limit} --json"
)

_FUNDING_INFO_CACHE: dict | list | None = None
_FUNDING_CACHE_TTL_SECONDS = 900  # 15 minutes
_FUNDING_CACHE_TS: float = 0.0


def alpha_token_list() -> dict:
    data = json_out(BINANCE_ALPHA_TOKEN_LIST_CMD, timeout=40)
    if not data:
        return {}
    items = data if isinstance(data, list) else data.get("data", [])
    result = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol", "")).upper()
        try:
            result[symbol] = {
                "count24h": int(item.get("count24h") or 0),
                "pct": float(item.get("percentChange24h") or 0),
                "score": float(item.get("score") or 0),
                "hotTag": str(item.get("hotTag", "")),
                "chainName": str(item.get("chainName", "")),
            }
        except (ValueError, TypeError):
            continue
    return result


def futures_ticker(symbol: str) -> Optional[dict]:
    data = json_out(BINANCE_FUTURES_TICKER_CMD.format(symbol=symbol.upper()), timeout=15)
    if not data:
        return hyperliquid.ticker(symbol)

    if isinstance(data, dict) and not data.get("data"):
        item = data
    elif isinstance(data, list) and data:
        item = data[0] if isinstance(data[0], dict) else {}
    else:
        maybe = data.get("data") if isinstance(data, dict) else None
        item = maybe[0] if isinstance(maybe, list) and maybe else {}

    if not item:
        return hyperliquid.ticker(symbol)
    return {
        "price": float(str(item.get("lastPrice", 0) or 0)),
        "chg24h": float(str(item.get("priceChangePercent", 0) or 0)),
        "high24h": float(str(item.get("highPrice", 0) or 0)),
        "low24h": float(str(item.get("lowPrice", 0) or 0)),
        "volume": float(str(item.get("quoteVolume", 0) or 0)),
        "raw": item,
        "source": "binance",
    }


def futures_funding(symbol: str) -> Optional[dict]:
    global _FUNDING_INFO_CACHE, _FUNDING_CACHE_TS
    now = time.time()
    if _FUNDING_INFO_CACHE is None or (now - _FUNDING_CACHE_TS) > _FUNDING_CACHE_TTL_SECONDS:
        _FUNDING_INFO_CACHE = json_out(BINANCE_FUTURES_FUNDING_INFO_CMD, timeout=15)
        _FUNDING_CACHE_TS = now
    data = _FUNDING_INFO_CACHE
    if not data:
        return _premium_index_funding(symbol) or hyperliquid.funding(symbol)

    items = data if isinstance(data, list) else (
        data.get("data", []) if isinstance(data, dict) and isinstance(data.get("data"), list) else [data]
    )
    target = f"{symbol.upper()}USDT"
    item = next(
        (entry for entry in items if isinstance(entry, dict) and str(entry.get("symbol", "")).upper() == target),
        None,
    )
    if not item:
        return _premium_index_funding(symbol) or hyperliquid.funding(symbol)

    funding_rate_pct = None
    for key in ("lastFundingRate", "fundingRate"):
        value = item.get(key)
        if value not in (None, ""):
            try:
                funding_rate_pct = float(str(value)) * 100
                break
            except (ValueError, TypeError):
                continue

    if funding_rate_pct is None:
        return _premium_index_funding(symbol) or hyperliquid.funding(symbol)

    return {
        "fundingRate_pct": funding_rate_pct,
        "nextFundingTime": item.get("nextFundingTime") or item.get("fundingTime") or item.get("updateTime", ""),
        "raw": item,
        "source": "binance",
    }


def _premium_index_funding(symbol: str) -> Optional[dict]:
    data, status = http_json_safe(
        f"https://fapi.binance.com/fapi/v1/premiumIndex?symbol={symbol.upper()}USDT",
        timeout=10,
        source="binance-premiumIndex",
    )
    if not isinstance(data, dict):
        return None
    try:
        return {
            "fundingRate_pct": float(str(data.get("lastFundingRate", "0"))) * 100,
            "nextFundingTime": data.get("nextFundingTime", ""),
            "raw": data,
            "source": "binance",
        }
    except (ValueError, TypeError):
        return None


def futures_klines(symbol: str, interval: str = "1h", limit: int = 50) -> Optional[list]:
    data = json_out(
        BINANCE_FUTURES_KLINES_CMD.format(symbol=symbol.upper(), interval=interval, limit=limit),
        timeout=15,
    )
    if not data:
        return hyperliquid.klines(symbol, interval=interval, limit=limit)

    items = data if isinstance(data, list) else data.get("data", [])
    if not items:
        return hyperliquid.klines(symbol, interval=interval, limit=limit)

    result = []
    for item in items:
        if isinstance(item, (list, tuple)) and len(item) >= 6:
            try:
                result.append((
                    float(item[1]),
                    float(item[2]),
                    float(item[3]),
                    float(item[4]),
                    float(item[5]),
                ))
            except (ValueError, TypeError):
                continue
    return result if result else hyperliquid.klines(symbol, interval=interval, limit=limit)


def open_interest(symbol: str) -> dict[str, Any]:
    """
    Fetch OI with explicit error typing (roadmap P0-2).
    Returns dict always; caller checks 'status' field.
    """
    sym = symbol.upper()
    url = f"https://fapi.binance.com/fapi/v1/openInterest?symbol={sym}USDT"
    data, status = http_json_safe(url, timeout=10, source="binance-oi")

    if not status.ok or not isinstance(data, dict):
        return {
            "oi": None,
            "oi_change_pct": None,
            "timestamp": int(time.time() * 1000),
            "source": "binance",
            "status": status.to_dict(),
            "error_type": status.error_type,
        }

    try:
        oi = float(data.get("openInterest", 0))
        ts = int(data.get("time", 0))
    except (ValueError, TypeError):
        return {
            "oi": None,
            "oi_change_pct": None,
            "timestamp": int(time.time() * 1000),
            "source": "binance",
            "status": status.to_dict(),
            "error_type": FetchStatus.PARSE_ERROR,
        }

    # Historical OI for 24h change direction (1d period, last 2 points)
    oi_change_pct = 0.0
    hist_url = f"https://fapi.binance.com/fapi/v1/openInterestHist?symbol={sym}USDT&period=1d&limit=2"
    hist, hist_status = http_json_safe(hist_url, timeout=10, source="binance-oi-hist")
    if isinstance(hist, list) and len(hist) >= 2:
        try:
            prev = float(hist[-2].get("sumOpenInterest", 0))
            if prev > 0:
                oi_change_pct = (oi - prev) / prev * 100
        except (ValueError, TypeError, KeyError, IndexError):
            pass

    return {
        "oi": oi,
        "oi_change_pct": oi_change_pct,
        "timestamp": ts,
        "source": "binance",
        "status": status.to_dict(),
        "error_type": None,
    }
