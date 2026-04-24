from __future__ import annotations

from typing import Optional

from . import hyperliquid
from .common import http_json, json_out

# Official Binance skill references:
# - alpha token-list
# - futures-usds ticker24hr-price-change-statistics
# - futures-usds get-funding-rate-info
# - futures-usds kline-candlestick-data
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
    global _FUNDING_INFO_CACHE
    if _FUNDING_INFO_CACHE is None:
        _FUNDING_INFO_CACHE = json_out(BINANCE_FUTURES_FUNDING_INFO_CMD, timeout=15)
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
    data = http_json(f"https://fapi.binance.com/fapi/v1/premiumIndex?symbol={symbol.upper()}USDT", timeout=10)
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
