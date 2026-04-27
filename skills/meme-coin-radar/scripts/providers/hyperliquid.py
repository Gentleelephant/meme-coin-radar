from __future__ import annotations

import time
from typing import Optional

from .common import http_json

HL_CACHE_TTL = 15
_HL_META_CACHE = {"ts": 0.0, "data": None}


def _post(payload: dict, timeout: int = 15) -> Optional[dict | list]:
    return http_json("https://api.hyperliquid.xyz/info", timeout=timeout, method="POST", body=payload)


def _meta_and_ctxs(force: bool = False) -> tuple[list, list]:
    now = time.time()
    if not force and _HL_META_CACHE["data"] and now - _HL_META_CACHE["ts"] < HL_CACHE_TTL:
        return _HL_META_CACHE["data"]

    data = _post({"type": "metaAndAssetCtxs"}, timeout=20)
    if isinstance(data, list) and len(data) >= 2:
        universe = data[0].get("universe", []) if isinstance(data[0], dict) else []
        ctxs = data[1] if isinstance(data[1], list) else []
        _HL_META_CACHE["ts"] = now
        _HL_META_CACHE["data"] = (universe, ctxs)
        return universe, ctxs
    return [], []


def ctx_map() -> dict:
    universe, ctxs = _meta_and_ctxs()
    result = {}
    for asset, ctx in zip(universe, ctxs):
        if not isinstance(asset, dict) or not isinstance(ctx, dict):
            continue
        name = str(asset.get("name", "")).upper()
        if name:
            result[name] = {"asset": asset, "ctx": ctx}
    return result


def btc_status() -> dict:
    payload = ctx_map().get("BTC", {})
    ctx = payload.get("ctx", {})
    try:
        last = float(str(ctx.get("markPx", "0")))
        open24h = float(str(ctx.get("prevDayPx", "0")))
        chg = (last - open24h) / open24h * 100 if open24h > 0 else 0.0
        return {
            "price": last,
            "open24h": open24h,
            "chg24h_pct": chg,
            "direction": "up" if chg > 2 else ("down" if chg < -2 else "neutral"),
            "raw": ctx,
            "source": "hyperliquid",
        }
    except (ValueError, TypeError):
        return {}


def swap_tickers() -> list:
    result = []
    for symbol, payload in ctx_map().items():
        ctx = payload.get("ctx", {})
        try:
            last = float(str(ctx.get("markPx", "0")))
            open24h = float(str(ctx.get("prevDayPx", "0")))
            vol = float(str(ctx.get("dayNtlVlm", "0")))
            chg = (last - open24h) / open24h * 100 if open24h > 0 else 0.0
            result.append({
                "instId": f"{symbol}-USDT-SWAP",
                "symbol": symbol,
                "last": last,
                "high24h": last,
                "low24h": last,
                "vol24h": vol,
                "open24h": open24h,
                "chg24h_pct": chg,
                "source": "hyperliquid",
            })
        except (ValueError, TypeError):
            continue
    return result


def ticker(symbol: str) -> Optional[dict]:
    payload = ctx_map().get(symbol.upper(), {})
    ctx = payload.get("ctx", {})
    if not ctx:
        return None
    try:
        price = float(str(ctx.get("markPx", "0")))
        prev = float(str(ctx.get("prevDayPx", "0")))
        chg = (price - prev) / prev * 100 if prev > 0 else 0.0
        return {
            "price": price,
            "chg24h": chg,
            "high24h": price,
            "low24h": price,
            "volume": float(str(ctx.get("dayNtlVlm", "0"))),
            "raw": ctx,
            "source": "hyperliquid",
        }
    except (ValueError, TypeError):
        return None


def funding(symbol: str) -> Optional[dict]:
    payload = ctx_map().get(symbol.upper(), {})
    ctx = payload.get("ctx", {})
    if not ctx:
        return None
    try:
        return {
            "fundingRate_pct": float(str(ctx.get("funding", "0"))) * 100,
            "nextFundingTime": "",
            "raw": ctx,
            "source": "hyperliquid",
        }
    except (ValueError, TypeError):
        return None


def klines(symbol: str, interval: str = "1h", limit: int = 50) -> Optional[list]:
    interval_map = {"15m": "15m", "1h": "1h", "4h": "4h", "1d": "1d"}
    hl_interval = interval_map.get(interval, "1h")
    end_ms = int(time.time() * 1000)
    span_ms = {
        "15m": 15 * 60 * 1000,
        "1h": 60 * 60 * 1000,
        "4h": 4 * 60 * 60 * 1000,
        "1d": 24 * 60 * 60 * 1000,
    }[hl_interval]
    start_ms = end_ms - limit * span_ms
    data = _post({
        "type": "candleSnapshot",
        "req": {
            "coin": symbol.upper(),
            "interval": hl_interval,
            "startTime": start_ms,
            "endTime": end_ms,
        },
    }, timeout=20)
    if not isinstance(data, list) or not data:
        return None

    result = []
    for item in data[-limit:]:
        if not isinstance(item, dict):
            continue
        try:
            result.append((
                float(str(item.get("o", "0"))),
                float(str(item.get("h", "0"))),
                float(str(item.get("l", "0"))),
                float(str(item.get("c", "0"))),
                float(str(item.get("v", "0"))),
                int(item.get("t", 0) or 0),
            ))
        except (ValueError, TypeError):
            continue
    return result if result else None
