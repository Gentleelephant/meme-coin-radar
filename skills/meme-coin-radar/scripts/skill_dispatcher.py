#!/usr/bin/env python3
"""
妖币雷达 Phase 3.0 — Skill Dispatcher
改进点:
  - OKX OnchainOS 作为链上主发现层
  - Binance Alpha / Futures 作为执行承接层
  - batch_binance() 返回结构化 fetch_status
"""
from __future__ import annotations

import json
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from typing import Any, Optional

try:
    from .providers.binance import (
        alpha_token_list,
        futures_exchange_info,
        futures_funding,
        futures_klines,
        futures_new_algo_order,
        futures_new_order,
        futures_test_order,
        futures_ticker,
        open_interest as binance_open_interest,
    )
    from .providers.common import FetchStatus, json_out, json_out_safe
    from .providers.hyperliquid import btc_status as hyperliquid_btc_status, swap_tickers as hyperliquid_swap_tickers
    from .providers.onchainos import (
        hot_tokens as onchainos_hot_tokens_provider,
        signal_list as onchainos_signal_list_provider,
        token_snapshot as onchainos_token_snapshot_provider,
        tracker_activities as onchainos_tracker_activities_provider,
    )
    from .providers.okx import account_equity as okx_account_equity_impl
except ImportError:
    from providers.binance import (
        alpha_token_list,
        futures_exchange_info,
        futures_funding,
        futures_klines,
        futures_new_algo_order,
        futures_new_order,
        futures_test_order,
        futures_ticker,
        open_interest as binance_open_interest,
    )
    from providers.common import FetchStatus, json_out, json_out_safe
    from providers.hyperliquid import btc_status as hyperliquid_btc_status, swap_tickers as hyperliquid_swap_tickers
    from providers.onchainos import (
        hot_tokens as onchainos_hot_tokens_provider,
        signal_list as onchainos_signal_list_provider,
        token_snapshot as onchainos_token_snapshot_provider,
        tracker_activities as onchainos_tracker_activities_provider,
    )
    from providers.okx import account_equity as okx_account_equity_impl

BATCH_WORKERS = 12
BATCH_TIMEOUT_SECONDS = 60


def okx_btc_status() -> dict:
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


def okx_account_equity() -> float:
    return okx_account_equity_impl()


def binance_alpha() -> dict:
    return alpha_token_list()


def binance_ticker(symbol: str) -> Optional[dict]:
    return futures_ticker(symbol)


def binance_funding(symbol: str) -> Optional[dict]:
    return futures_funding(symbol)


def binance_klines(symbol: str, interval: str = "1h", limit: int = 50) -> Optional[list]:
    return futures_klines(symbol, interval=interval, limit=limit)


def binance_exchange_info(symbol: str) -> Optional[dict]:
    return futures_exchange_info(symbol)


def binance_test_order(**params: Any) -> dict[str, Any]:
    return futures_test_order(**params)


def binance_new_order(**params: Any) -> dict[str, Any]:
    return futures_new_order(**params)


def binance_new_algo_order(**params: Any) -> dict[str, Any]:
    return futures_new_algo_order(**params)


def _status_payload(status: FetchStatus) -> dict[str, Any]:
    return {**status.to_dict(), "fetched_at": int(time.time())}


def okx_hot_tokens(
    ranking_type: int = 4,
    chain: str | None = None,
    limit: int = 20,
    time_frame: int = 4,
    include_status: bool = False,
) -> list | tuple[list, dict[str, Any]]:
    items, _status = onchainos_hot_tokens_provider(
        ranking_type=ranking_type,
        chain=chain,
        limit=limit,
        time_frame=time_frame,
    )
    if include_status:
        return items, _status_payload(_status)
    return items


def okx_signal_list(
    chain: str,
    wallet_type: str = "1,2,3",
    limit: int = 20,
    include_status: bool = False,
) -> list | tuple[list, dict[str, Any]]:
    items, _status = onchainos_signal_list_provider(chain=chain, wallet_type=wallet_type, limit=limit)
    if include_status:
        return items, _status_payload(_status)
    return items


def okx_tracker_activities(
    tracker_type: str = "smart_money",
    chain: str | None = None,
    trade_type: int = 1,
    limit: int = 50,
    include_status: bool = False,
) -> list | tuple[list, dict[str, Any]]:
    items, _status = onchainos_tracker_activities_provider(
        tracker_type=tracker_type,
        chain=chain,
        trade_type=trade_type,
        limit=limit,
    )
    if include_status:
        return items, _status_payload(_status)
    return items


def okx_token_snapshot(address: str, chain: str | None = None) -> dict[str, Any]:
    return onchainos_token_snapshot_provider(address=address, chain=chain)


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


def _fetch_one_coin(symbol: str) -> tuple:
    """Fetch all data for a single coin with status tracking and timestamps."""
    status_map: dict[str, Any] = {}
    now = int(time.time())

    ticker = binance_ticker(symbol)
    status_map["ticker"] = {"ok": ticker is not None, "source": "binance", "fetched_at": now}

    funding = binance_funding(symbol)
    status_map["funding"] = {"ok": funding is not None, "source": "binance", "fetched_at": now}

    klines = binance_klines(symbol, interval="1h", limit=50)
    status_map["klines"] = {"ok": klines is not None, "source": "binance", "fetched_at": now}

    klines_4h = binance_klines(symbol, interval="4h", limit=50)
    status_map["klines_4h"] = {"ok": klines_4h is not None, "source": "binance", "fetched_at": now}

    klines_1d = binance_klines(symbol, interval="1d", limit=8)
    status_map["klines_1d"] = {"ok": klines_1d is not None, "source": "binance", "fetched_at": now}

    oi = binance_open_interest(symbol)
    status_map["oi"] = oi.get("status", {"ok": oi.get("error_type") is None, "source": "binance", "fetched_at": now})

    return symbol, {
        "ticker": ticker,
        "funding": funding,
        "klines": klines,
        "klines_4h": klines_4h,
        "klines_1d": klines_1d,
        "oi": oi,
        "_fetched_at": now,
        "_status": status_map,
    }


def batch_binance(coins: list) -> dict:
    results: dict[str, Any] = {}
    fetch_status: dict[str, Any] = {}

    with ThreadPoolExecutor(max_workers=BATCH_WORKERS) as executor:
        futures = {executor.submit(_fetch_one_coin, coin): coin for coin in coins}
        try:
            for future in as_completed(futures, timeout=BATCH_TIMEOUT_SECONDS):
                symbol = futures[future]
                try:
                    resolved_symbol, payload = future.result(timeout=25)
                    results[resolved_symbol] = payload
                    fetch_status[resolved_symbol] = payload.get("_status", {})
                except Exception as exc:
                    results[symbol] = {
                        "ticker": None, "funding": None, "klines": None,
                        "klines_4h": None, "klines_1d": None, "oi": None,
                        "_status": {"_batch_error": str(exc)},
                    }
                    fetch_status[symbol] = {"_batch_error": str(exc)}
        except TimeoutError:
            pass

        for future, symbol in futures.items():
            if symbol in results:
                continue
            future.cancel()
            results[symbol] = {
                "ticker": None, "funding": None, "klines": None,
                "klines_4h": None, "klines_1d": None, "oi": None,
                "_status": {"_batch_error": "timeout"},
            }
            fetch_status[symbol] = {"_batch_error": "timeout"}

    return {"results": results, "fetch_status": fetch_status}


__all__ = [
    "batch_binance",
    "binance_alpha",
    "binance_exchange_info",
    "binance_funding",
    "binance_klines",
    "binance_new_algo_order",
    "binance_new_order",
    "binance_smartmoney_signals",
    "binance_test_order",
    "binance_ticker",
    "okx_account_equity",
    "okx_btc_status",
    "okx_funding_rate",
    "okx_hot_tokens",
    "okx_signal_list",
    "okx_swap_tickers",
    "okx_token_snapshot",
    "okx_tracker_activities",
]
