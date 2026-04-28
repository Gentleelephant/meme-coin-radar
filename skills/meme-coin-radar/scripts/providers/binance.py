from __future__ import annotations

import json
import shlex
import time

from typing import Any, Optional

from . import hyperliquid
from .common import FetchStatus, http_json_safe, json_out, run

# Official Binance skill references:
BINANCE_ALPHA_TOKEN_LIST_CMD = "npx -y @binance/binance-cli alpha token-list --json"
BINANCE_FUTURES_ORDER_BASE = ["npx", "-y", "@binance/binance-cli", "futures-usds"]

_TICKER_24H_CACHE: dict[str, dict[str, Any]] | None = None
_TICKER_24H_CACHE_TTL_SECONDS = 60
_TICKER_24H_CACHE_TS: float = 0.0
_PREMIUM_INDEX_CACHE: dict[str, dict[str, Any]] | None = None
_PREMIUM_INDEX_CACHE_TTL_SECONDS = 900  # 15 minutes
_PREMIUM_INDEX_CACHE_TS: float = 0.0
_FUTURES_SYMBOLS_CACHE: set[str] | None = None
_FUTURES_SYMBOLS_CACHE_TTL_SECONDS = 900
_FUTURES_SYMBOLS_CACHE_TS: float = 0.0


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


def _cache_is_fresh(ts: float, ttl_seconds: int) -> bool:
    return ts > 0 and (time.time() - ts) <= ttl_seconds


def _load_all_tickers_24h() -> tuple[dict[str, dict[str, Any]] | None, FetchStatus]:
    global _TICKER_24H_CACHE, _TICKER_24H_CACHE_TS
    if _TICKER_24H_CACHE is not None and _cache_is_fresh(_TICKER_24H_CACHE_TS, _TICKER_24H_CACHE_TTL_SECONDS):
        return _TICKER_24H_CACHE, FetchStatus(ok=True, source="binance-ticker24hr-cache")

    data, status = http_json_safe(
        "https://fapi.binance.com/fapi/v1/ticker/24hr",
        timeout=12,
        source="binance-ticker24hr-all",
    )
    if not status.ok:
        return None, status

    items = data if isinstance(data, list) else []
    if not items:
        return None, FetchStatus(
            ok=False,
            error_type=FetchStatus.PARSE_ERROR,
            message="ticker24hr returned no list data",
            latency_ms=status.latency_ms,
            source="binance-ticker24hr-all",
        )

    parsed: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol", "")).upper()
        if not symbol:
            continue
        parsed[symbol] = item

    if not parsed:
        return None, FetchStatus(
            ok=False,
            error_type=FetchStatus.PARSE_ERROR,
            message="ticker24hr parse yielded no symbols",
            latency_ms=status.latency_ms,
            source="binance-ticker24hr-all",
        )

    _TICKER_24H_CACHE = parsed
    _TICKER_24H_CACHE_TS = time.time()
    return parsed, status


def futures_ticker(symbol: str) -> tuple[Optional[dict[str, Any]], FetchStatus]:
    target = f"{symbol.upper()}USDT"
    ticker_map, status = _load_all_tickers_24h()
    item = ticker_map.get(target) if ticker_map else None
    if not item:
        fallback = hyperliquid.ticker(symbol)
        if fallback:
            return fallback, FetchStatus(ok=True, latency_ms=status.latency_ms, source="hyperliquid-fallback")
        return None, status
    return {
        "price": float(str(item.get("lastPrice", 0) or 0)),
        "chg24h": float(str(item.get("priceChangePercent", 0) or 0)),
        "high24h": float(str(item.get("highPrice", 0) or 0)),
        "low24h": float(str(item.get("lowPrice", 0) or 0)),
        "volume": float(str(item.get("quoteVolume", 0) or 0)),
        "raw": item,
        "source": "binance",
    }, status


def futures_funding(symbol: str) -> tuple[Optional[dict[str, Any]], FetchStatus]:
    target = f"{symbol.upper()}USDT"
    premium_map, funding_status = _load_all_premium_index()
    item = premium_map.get(target) if premium_map else None
    if not item:
        premium = _premium_index_funding(symbol)
        if premium:
            return premium, FetchStatus(ok=True, latency_ms=funding_status.latency_ms, source=premium.get("source", "binance"))
        fallback = hyperliquid.funding(symbol)
        if fallback:
            return fallback, FetchStatus(ok=True, latency_ms=funding_status.latency_ms, source="hyperliquid-fallback")
        return None, FetchStatus(
            ok=False,
            error_type=FetchStatus.FIELD_NOT_SUPPORTED,
            message=f"{target} not found in funding response",
            latency_ms=funding_status.latency_ms,
            source="binance-fundingInfo",
        )

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
        premium = _premium_index_funding(symbol)
        if premium:
            return premium, FetchStatus(ok=True, latency_ms=funding_status.latency_ms, source=premium.get("source", "binance"))
        fallback = hyperliquid.funding(symbol)
        if fallback:
            return fallback, FetchStatus(ok=True, latency_ms=funding_status.latency_ms, source="hyperliquid-fallback")
        return None, FetchStatus(
            ok=False,
            error_type=FetchStatus.PARSE_ERROR,
            message=f"{target} funding rate missing",
            latency_ms=funding_status.latency_ms,
            source="binance-fundingInfo",
        )

    return {
        "fundingRate_pct": funding_rate_pct,
        "nextFundingTime": item.get("nextFundingTime") or item.get("fundingTime") or item.get("updateTime", ""),
        "raw": item,
        "source": "binance",
    }, funding_status


def _load_all_premium_index() -> tuple[dict[str, dict[str, Any]] | None, FetchStatus]:
    global _PREMIUM_INDEX_CACHE, _PREMIUM_INDEX_CACHE_TS
    if _PREMIUM_INDEX_CACHE is not None and _cache_is_fresh(_PREMIUM_INDEX_CACHE_TS, _PREMIUM_INDEX_CACHE_TTL_SECONDS):
        return _PREMIUM_INDEX_CACHE, FetchStatus(ok=True, source="binance-premiumIndex-cache")

    data, status = http_json_safe(
        "https://fapi.binance.com/fapi/v1/premiumIndex",
        timeout=12,
        source="binance-premiumIndex-all",
    )
    if not status.ok:
        return None, status

    items = data if isinstance(data, list) else []
    if not items:
        return None, FetchStatus(
            ok=False,
            error_type=FetchStatus.PARSE_ERROR,
            message="premiumIndex returned no list data",
            latency_ms=status.latency_ms,
            source="binance-premiumIndex-all",
        )

    parsed: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol", "")).upper()
        if not symbol:
            continue
        parsed[symbol] = item

    if not parsed:
        return None, FetchStatus(
            ok=False,
            error_type=FetchStatus.PARSE_ERROR,
            message="premiumIndex parse yielded no symbols",
            latency_ms=status.latency_ms,
            source="binance-premiumIndex-all",
        )

    _PREMIUM_INDEX_CACHE = parsed
    _PREMIUM_INDEX_CACHE_TS = time.time()
    return parsed, status


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


def futures_klines(symbol: str, interval: str = "1h", limit: int = 50) -> tuple[Optional[list], FetchStatus]:
    data, status = http_json_safe(
        f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol.upper()}USDT&interval={interval}&limit={limit}",
        timeout=12,
        source=f"binance-klines-{interval}",
    )
    if not data:
        fallback = hyperliquid.klines(symbol, interval=interval, limit=limit)
        if fallback:
            return fallback, FetchStatus(ok=True, latency_ms=status.latency_ms, source="hyperliquid-fallback")
        return None, status

    items = data if isinstance(data, list) else data.get("data", [])
    if not items:
        fallback = hyperliquid.klines(symbol, interval=interval, limit=limit)
        if fallback:
            return fallback, FetchStatus(ok=True, latency_ms=status.latency_ms, source="hyperliquid-fallback")
        return None, FetchStatus(
            ok=False,
            error_type=FetchStatus.FIELD_NOT_SUPPORTED,
            message=f"{symbol.upper()}USDT returned empty {interval} klines",
            latency_ms=status.latency_ms,
            source=f"binance-klines-{interval}",
        )

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
                    int(item[0]),
                ))
            except (ValueError, TypeError):
                continue
    if result:
        return result, status
    fallback = hyperliquid.klines(symbol, interval=interval, limit=limit)
    if fallback:
        return fallback, FetchStatus(ok=True, latency_ms=status.latency_ms, source="hyperliquid-fallback")
    return None, FetchStatus(
        ok=False,
        error_type=FetchStatus.PARSE_ERROR,
        message=f"{symbol.upper()}USDT {interval} klines parse failed",
        latency_ms=status.latency_ms,
        source=f"binance-klines-{interval}",
    )


def open_interest(symbol: str) -> tuple[Optional[dict[str, Any]], FetchStatus]:
    sym = symbol.upper()
    url = f"https://fapi.binance.com/fapi/v1/openInterest?symbol={sym}USDT"
    data, status = http_json_safe(url, timeout=10, source="binance-oi")

    if not status.ok or not isinstance(data, dict):
        return None, status

    try:
        oi = float(data.get("openInterest", 0))
        ts = int(data.get("time", 0))
    except (ValueError, TypeError):
        return None, FetchStatus(
            ok=False,
            error_type=FetchStatus.PARSE_ERROR,
            message=f"{sym}USDT open interest parse failed",
            latency_ms=status.latency_ms,
            source="binance-oi",
        )

    # Historical OI for 24h change direction (1d period, last 2 points)
    oi_change_pct = 0.0
    hist_url = f"https://fapi.binance.com/fapi/v1/openInterestHist?symbol={sym}USDT&period=1d&limit=2"
    hist, _hist_status = http_json_safe(hist_url, timeout=10, source="binance-oi-hist")
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
    }, status


def futures_exchange_info(symbol: str) -> Optional[dict[str, Any]]:
    data, status = http_json_safe(
        f"https://fapi.binance.com/fapi/v1/exchangeInfo?symbol={symbol.upper()}USDT",
        timeout=10,
        source="binance-exchangeInfo",
    )
    if not status.ok or not isinstance(data, dict):
        return None
    symbols = data.get("symbols", [])
    if not isinstance(symbols, list) or not symbols:
        return None
    item = symbols[0] if isinstance(symbols[0], dict) else None
    if not item:
        return None
    filters = {}
    for row in item.get("filters", []):
        if isinstance(row, dict) and row.get("filterType"):
            filters[str(row["filterType"])] = row
    return {
        "symbol": item.get("symbol", ""),
        "pricePrecision": item.get("pricePrecision"),
        "quantityPrecision": item.get("quantityPrecision"),
        "filters": filters,
        "raw": item,
    }


def futures_tradable_symbols() -> tuple[set[str], FetchStatus]:
    global _FUTURES_SYMBOLS_CACHE, _FUTURES_SYMBOLS_CACHE_TS
    now = time.time()
    if _FUTURES_SYMBOLS_CACHE is not None and (now - _FUTURES_SYMBOLS_CACHE_TS) <= _FUTURES_SYMBOLS_CACHE_TTL_SECONDS:
        return _FUTURES_SYMBOLS_CACHE, FetchStatus(ok=True, source="binance-exchangeInfo-cache")

    data, status = http_json_safe(
        "https://fapi.binance.com/fapi/v1/exchangeInfo",
        timeout=12,
        source="binance-exchangeInfo-all",
    )
    if not status.ok or not isinstance(data, dict):
        return set(), status

    symbols = data.get("symbols", [])
    if not isinstance(symbols, list):
        return set(), FetchStatus(
            ok=False,
            error_type=FetchStatus.PARSE_ERROR,
            message="exchangeInfo symbols missing",
            latency_ms=status.latency_ms,
            source="binance-exchangeInfo-all",
        )

    tradable = {
        str(item.get("symbol", "")).replace("USDT", "")
        for item in symbols
        if isinstance(item, dict)
        and str(item.get("quoteAsset", "")).upper() == "USDT"
        and str(item.get("contractType", "")).upper() == "PERPETUAL"
        and str(item.get("status", "")).upper() == "TRADING"
        and str(item.get("symbol", "")).upper().endswith("USDT")
    }
    _FUTURES_SYMBOLS_CACHE = tradable
    _FUTURES_SYMBOLS_CACHE_TS = now
    return tradable, status


def _build_futures_order_command(endpoint: str, **params: Any) -> str:
    parts = [*BINANCE_FUTURES_ORDER_BASE, endpoint]
    for key, value in params.items():
        if value in (None, ""):
            continue
        flag = f"--{key.replace('_', '-')}"
        parts.append(flag)
        parts.append(str(value).lower() if isinstance(value, bool) else str(value))
    parts.append("--json")
    return " ".join(shlex.quote(part) for part in parts)


def _run_order_command(endpoint: str, **params: Any) -> dict[str, Any]:
    command = _build_futures_order_command(endpoint, **params)
    result = run(command, timeout=30)
    raw = result.stdout
    if result.timed_out:
        return {"ok": False, "endpoint": endpoint, "command": command, "error": result.stderr or "command timed out"}
    if result.returncode not in (0,):
        return {"ok": False, "endpoint": endpoint, "command": command, "error": result.stderr or result.stdout or "command failed"}
    if not raw:
        return {"ok": True, "endpoint": endpoint, "command": command, "response": {}}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = {"raw": raw}
    return {"ok": True, "endpoint": endpoint, "command": command, "response": parsed}


def futures_test_order(**params: Any) -> dict[str, Any]:
    return _run_order_command("test-order", **params)


def futures_new_order(**params: Any) -> dict[str, Any]:
    return _run_order_command("new-order", **params)


def futures_new_algo_order(**params: Any) -> dict[str, Any]:
    return _run_order_command("new-algo-order", **params)


__all__ = [
    "alpha_token_list",
    "futures_exchange_info",
    "futures_funding",
    "futures_klines",
    "futures_new_algo_order",
    "futures_new_order",
    "futures_test_order",
    "futures_ticker",
    "futures_tradable_symbols",
    "open_interest",
]
