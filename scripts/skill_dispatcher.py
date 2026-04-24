#!/usr/bin/env python3
"""
妖币雷达 Phase 2.0 — Skill Dispatcher
────────────────────────────────────
这一层只暴露项目需要的稳定接口，具体实现下沉到 providers。

Skill 映射关系:
  Step 0  BTC大盘      → okx-cex-market / Hyperliquid fallback
  Step 1  全量Tickers  → okx-cex-market / Hyperliquid fallback
  Step 0.5 BinanceAlpha→ binance-cli alpha token-list
  Step 2  Binance合约  → binance-cli futures-usds (官方 skill 命令名) / Hyperliquid fallback
  Step G1/G2 GMGN热门  → gmgn-market
  Step G3 GMGN信号     → gmgn-market / trading-signal (参考)
  Step G4 GMGN新代币   → gmgn-market
"""
from __future__ import annotations

import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from typing import Optional

from providers.binance import alpha_token_list, futures_funding, futures_klines, futures_ticker
from providers.common import json_out, load_gmgn_key
from providers.gmgn import security_score, signal as gmgn_signal_provider, trenches as gmgn_trenches_provider, trending as gmgn_trending_provider
from providers.hyperliquid import btc_status as hyperliquid_btc_status, swap_tickers as hyperliquid_swap_tickers

BATCH_WORKERS = 8
BATCH_TIMEOUT_SECONDS = 45


def okx_btc_status() -> dict:
    """
    Step 0: 获取 BTC 大盘状态
    优先: okx market ticker BTC-USDT-SWAP --json
    回退: Hyperliquid public perp metadata
    """
    data = json_out("okx market ticker BTC-USDT-SWAP --json", timeout=15)
    if not data:
        return hyperliquid_btc_status()

    items = data if isinstance(data, list) else []
    if not items:
        return hyperliquid_btc_status()

    item = items[0] if isinstance(items[0], dict) else {}
    if item:
        try:
            last = float(str(item.get("last", "0")).replace(",", ""))
            open24h = float(str(item.get("open24h", "0")).replace(",", ""))
            chg = (last - open24h) / open24h * 100 if open24h > 0 else 0.0
            return {
                "price": last,
                "open24h": open24h,
                "chg24h_pct": chg,
                "direction": "up" if chg > 2 else ("down" if chg < -2 else "neutral"),
                "raw": item,
                "source": "okx",
            }
        except (ValueError, TypeError):
            return hyperliquid_btc_status()

    values = items[0] if isinstance(items[0], (list, tuple)) else []
    if len(values) >= 9:
        try:
            last = float(values[1])
            open24h = float(values[7])
            chg = (last - open24h) / open24h * 100 if open24h > 0 else 0.0
            return {
                "price": last,
                "open24h": open24h,
                "chg24h_pct": chg,
                "direction": "up" if chg > 2 else ("down" if chg < -2 else "neutral"),
                "raw": {"instId": values[0], "last": values[1], "open24h": values[7]},
                "source": "okx",
            }
        except (ValueError, TypeError, IndexError):
            return hyperliquid_btc_status()
    return hyperliquid_btc_status()


def okx_swap_tickers() -> list:
    """
    Step 1: 获取全量 USDT-M SWAP tickers
    优先: okx market tickers SWAP --json
    回退: Hyperliquid public perp metadata
    """
    data = json_out("okx market tickers SWAP --json", timeout=20)
    if not data:
        return hyperliquid_swap_tickers()

    items = data if isinstance(data, list) else data.get("data", [])
    result = []
    for item in items:
        if not isinstance(item, dict):
            continue
        inst_id = str(item.get("instId", ""))
        if "-USDT-SWAP" not in inst_id:
            continue
        try:
            last = float(str(item.get("last", 0) or 0).replace(",", ""))
            high = float(str(item.get("high24h", 0) or 0).replace(",", ""))
            low = float(str(item.get("low24h", 0) or 0).replace(",", ""))
            vol = float(str(item.get("volCcy24h", 0) or 0).replace(",", ""))
            open24h = float(str(item.get("open24h", 0) or 0).replace(",", ""))
            chg = (last - open24h) / open24h * 100 if open24h > 0 else 0.0
            result.append({
                "instId": inst_id,
                "symbol": inst_id.replace("-USDT-SWAP", ""),
                "last": last,
                "high24h": high,
                "low24h": low,
                "vol24h": vol,
                "open24h": open24h,
                "chg24h_pct": chg,
                "source": "okx",
            })
        except (ValueError, TypeError):
            continue
    return result if result else hyperliquid_swap_tickers()


def okx_funding_rate(inst_id: str) -> Optional[dict]:
    data = json_out(f"okx market funding-rate {inst_id} --json", timeout=10)
    if not data:
        return None
    items = data if isinstance(data, list) else data.get("data", [])
    if not items or not isinstance(items[0], dict):
        return None
    item = items[0]
    try:
        return {
            "fundingRate_pct": float(str(item.get("fundingRate", "0"))) * 100,
            "nextFundingTime": item.get("nextFundingTime", ""),
            "raw": item,
            "source": "okx",
        }
    except (ValueError, TypeError):
        return None


def binance_alpha() -> dict:
    """官方 Binance skill: `binance-cli alpha token-list --json`."""
    return alpha_token_list()


def binance_ticker(symbol: str) -> Optional[dict]:
    """官方 Binance skill: `binance-cli futures-usds ticker24hr-price-change-statistics`."""
    return futures_ticker(symbol)


def binance_funding(symbol: str) -> Optional[dict]:
    """官方 Binance skill: `binance-cli futures-usds get-funding-rate-info`."""
    return futures_funding(symbol)


def binance_klines(symbol: str, interval: str = "1h", limit: int = 50) -> Optional[list]:
    """官方 Binance skill: `binance-cli futures-usds kline-candlestick-data`."""
    return futures_klines(symbol, interval=interval, limit=limit)


def gmgn_trending(chain: str = "sol", interval: str = "1h", limit: int = 20) -> list:
    return gmgn_trending_provider(chain=chain, interval=interval, limit=limit)


def gmgn_signal(chain: str = "sol", limit: int = 30) -> list:
    return gmgn_signal_provider(chain=chain, limit=limit)


def gmgn_trenches(chain: str = "sol", token_type: str = "new_creation", limit: int = 20) -> list:
    return gmgn_trenches_provider(chain=chain, token_type=token_type, limit=limit)


def binance_smartmoney_signals(chain: str = "sol", page: int = 1, page_size: int = 50) -> list:
    chain_map = {"sol": "CT_501", "bsc": "56", "solana": "CT_501"}
    chain_id = chain_map.get(chain.lower(), "CT_501")
    try:
        request = urllib.request.Request(
            "https://web3.binance.com/bapi/defi/v1/public/wallet-direct/buw/wallet/web/signal/smart-money/ai",
            data=json.dumps({
                "smartSignalType": "",
                "page": page,
                "pageSize": page_size,
                "chainId": chain_id,
            }).encode(),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "User-Agent": "binance-web3/1.1 (Skill)",
            },
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            data = json.loads(response.read())
        if data.get("success"):
            return data.get("data", [])
    except Exception:
        pass
    return []


def gmgn_security_score(token: dict) -> dict:
    return security_score(token)


def _fetch_one_coin(symbol: str) -> tuple:
    return symbol, {
        "ticker": binance_ticker(symbol),
        "funding": binance_funding(symbol),
        "klines": binance_klines(symbol, interval="1h", limit=50),
    }


def batch_binance(coins: list) -> dict:
    results = {}
    with ThreadPoolExecutor(max_workers=BATCH_WORKERS) as executor:
        futures = {executor.submit(_fetch_one_coin, coin): coin for coin in coins}
        try:
            for future in as_completed(futures, timeout=BATCH_TIMEOUT_SECONDS):
                symbol = futures[future]
                try:
                    resolved_symbol, payload = future.result(timeout=20)
                    results[resolved_symbol] = payload
                except Exception:
                    results[symbol] = {"ticker": None, "funding": None, "klines": None}
        except TimeoutError:
            pass

        for future, symbol in futures.items():
            if symbol in results:
                continue
            future.cancel()
            results[symbol] = {"ticker": None, "funding": None, "klines": None}
    return results


__all__ = [
    "batch_binance",
    "binance_alpha",
    "binance_funding",
    "binance_klines",
    "binance_smartmoney_signals",
    "binance_ticker",
    "gmgn_security_score",
    "gmgn_signal",
    "gmgn_trending",
    "gmgn_trenches",
    "load_gmgn_key",
    "okx_btc_status",
    "okx_funding_rate",
    "okx_swap_tickers",
]
