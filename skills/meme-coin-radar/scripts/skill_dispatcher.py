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
        futures_tradable_symbols,
        futures_test_order,
        futures_ticker,
        open_interest as binance_open_interest,
    )
    from .providers.common import FetchStatus
    from .providers.hyperliquid import btc_status as hyperliquid_btc_status, swap_tickers as hyperliquid_swap_tickers
    from .providers.onchainos import (
        hot_tokens as onchainos_hot_tokens_provider,
        signal_list as onchainos_signal_list_provider,
        token_snapshot as onchainos_token_snapshot_provider,
        tracker_activities as onchainos_tracker_activities_provider,
        wallet_status as onchainos_wallet_status_provider,
    )
    from .providers.okx import (
        account_equity as okx_account_equity_impl,
        btc_status as okx_btc_status_impl,
        funding_rate as okx_funding_rate_impl,
        swap_tickers as okx_swap_tickers_impl,
    )
except ImportError:
    from providers.binance import (
        alpha_token_list,
        futures_exchange_info,
        futures_funding,
        futures_klines,
        futures_new_algo_order,
        futures_new_order,
        futures_tradable_symbols,
        futures_test_order,
        futures_ticker,
        open_interest as binance_open_interest,
    )
    from providers.common import FetchStatus
    from providers.hyperliquid import btc_status as hyperliquid_btc_status, swap_tickers as hyperliquid_swap_tickers
    from providers.onchainos import (
        hot_tokens as onchainos_hot_tokens_provider,
        signal_list as onchainos_signal_list_provider,
        token_snapshot as onchainos_token_snapshot_provider,
        tracker_activities as onchainos_tracker_activities_provider,
        wallet_status as onchainos_wallet_status_provider,
    )
    from providers.okx import (
        account_equity as okx_account_equity_impl,
        btc_status as okx_btc_status_impl,
        funding_rate as okx_funding_rate_impl,
        swap_tickers as okx_swap_tickers_impl,
    )

BATCH_WORKERS = 12
BATCH_TIMEOUT_SECONDS = 60


def okx_btc_status() -> dict:
    data = okx_btc_status_impl()
    return data if data else hyperliquid_btc_status()


def okx_swap_tickers() -> list:
    data = okx_swap_tickers_impl()
    return data if data else hyperliquid_swap_tickers()


def okx_funding_rate(inst_id: str) -> Optional[dict]:
    return okx_funding_rate_impl(inst_id)


def okx_account_equity() -> float:
    return okx_account_equity_impl()


def binance_alpha() -> dict:
    return alpha_token_list()


def binance_ticker(symbol: str) -> tuple[Optional[dict], FetchStatus]:
    return futures_ticker(symbol)


def binance_funding(symbol: str) -> tuple[Optional[dict], FetchStatus]:
    return futures_funding(symbol)


def binance_klines(symbol: str, interval: str = "1h", limit: int = 50) -> tuple[Optional[list], FetchStatus]:
    return futures_klines(symbol, interval=interval, limit=limit)


def binance_tradable_symbols() -> tuple[set[str], dict[str, Any]]:
    symbols, status = futures_tradable_symbols()
    return symbols, _status_payload(status)


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


def okx_wallet_status() -> dict[str, Any]:
    data, status = onchainos_wallet_status_provider()
    return {
        "data": data,
        "status": _status_payload(status),
    }


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


def okx_token_snapshot(address: str, chain: str | None = None, depth: str = "full") -> dict[str, Any]:
    """Fetch on-chain snapshot. depth = "lite" | "deep" | "full"."""
    return onchainos_token_snapshot_provider(address=address, chain=chain, depth=depth)


def _fetch_one_coin(symbol: str) -> tuple:
    """Fetch all data for a single coin with status tracking and timestamps."""
    status_map: dict[str, Any] = {}
    now = int(time.time())

    ticker, ticker_status = binance_ticker(symbol)
    status_map["ticker"] = {**ticker_status.to_dict(), "fetched_at": now}

    funding, funding_status = binance_funding(symbol)
    status_map["funding"] = {**funding_status.to_dict(), "fetched_at": now}

    klines, klines_status = binance_klines(symbol, interval="1h", limit=50)
    status_map["klines"] = {**klines_status.to_dict(), "fetched_at": now}

    klines_4h, klines_4h_status = binance_klines(symbol, interval="4h", limit=50)
    status_map["klines_4h"] = {**klines_4h_status.to_dict(), "fetched_at": now}

    klines_1d, klines_1d_status = binance_klines(symbol, interval="1d", limit=8)
    status_map["klines_1d"] = {**klines_1d_status.to_dict(), "fetched_at": now}

    oi, oi_status = binance_open_interest(symbol)
    status_map["oi"] = {**oi_status.to_dict(), "fetched_at": now}

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
    "binance_test_order",
    "binance_ticker",
    "binance_tradable_symbols",
    "okx_account_equity",
    "okx_btc_status",
    "okx_funding_rate",
    "okx_hot_tokens",
    "okx_signal_list",
    "okx_swap_tickers",
    "okx_token_snapshot",
    "okx_tracker_activities",
]
