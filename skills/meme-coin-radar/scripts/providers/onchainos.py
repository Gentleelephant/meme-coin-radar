from __future__ import annotations

import json
import shutil
import time
from typing import Any

from .common import FetchStatus, _status_from_command_result, run


def _quote(value: str) -> str:
    return value.replace('"', '\\"')


def _cmd(command: str) -> str:
    return command


def _legacy_json_cmd(command: str) -> str:
    return f"{command} --format json"


def _json_command(command: str, timeout: int, source: str) -> tuple[Any, FetchStatus]:
    max_attempts = 2  # retry once specifically for auth errors

    for attempt in range(max_attempts):
        candidates = (_cmd(command), _legacy_json_cmd(command))
        last_status = FetchStatus(ok=False, error_type=FetchStatus.SOURCE_UNAVAILABLE, message="empty response", source=source)

        for index, candidate in enumerate(candidates):
            started_at = time.time()
            result = run(candidate, timeout=timeout)
            latency_ms = (time.time() - started_at) * 1000
            raw = result.stdout

            if result.returncode not in (0,) or result.timed_out or not raw:
                message = result.stderr or result.stdout or ("command timed out" if result.timed_out else "empty response")
                if index == 1 and "unexpected argument '--format' found" in message:
                    continue
                last_status = _status_from_command_result(
                    result,
                    source=source,
                    latency_ms=latency_ms,
                )
                continue

            try:
                return json.loads(raw), FetchStatus(ok=True, latency_ms=latency_ms, source=source)
            except json.JSONDecodeError as exc:
                last_status = FetchStatus(
                    ok=False,
                    error_type=FetchStatus.PARSE_ERROR,
                    message=f"JSON parse error: {exc}",
                    latency_ms=latency_ms,
                    source=source,
                )

        if last_status.error_type == FetchStatus.AUTH_ERROR and attempt == 0:
            time.sleep(2.0)
            continue

        break

    return None, last_status


def _preflight_status(source: str) -> FetchStatus | None:
    if shutil.which("onchainos") is None:
        return FetchStatus(
            ok=False,
            error_type=FetchStatus.COMMAND_NOT_FOUND,
            message="onchainos CLI not installed or not in PATH",
            source=source,
        )
    return None


def _unwrap_items(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        for key in ("data", "items", "list", "rows", "result"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return [data]
    return []


def _unwrap_object(data: Any) -> dict[str, Any]:
    if isinstance(data, dict):
        for key in ("data", "result", "item"):
            value = data.get(key)
            if isinstance(value, dict):
                return value
        return data
    items = _unwrap_items(data)
    return items[0] if items else {}


def hot_tokens(
    ranking_type: int,
    chain: str | None = None,
    limit: int = 20,
    time_frame: int = 4,
    rank_by: int | None = None,
) -> tuple[list[dict[str, Any]], FetchStatus]:
    preflight = _preflight_status("okx-onchainos-hot-tokens")
    if preflight is not None:
        return [], preflight
    parts = [f"onchainos token hot-tokens --ranking-type {ranking_type}", f"--limit {limit}", f"--time-frame {time_frame}"]
    if chain:
        parts.append(f'--chain "{_quote(chain)}"')
    if rank_by is not None:
        parts.append(f"--rank-by {rank_by}")
    data, status = _json_command(" ".join(parts), timeout=25, source="okx-onchainos-hot-tokens")
    return _unwrap_items(data), status


def signal_list(
    chain: str,
    wallet_type: str = "1,2,3",
    limit: int = 20,
    min_address_count: int | None = None,
) -> tuple[list[dict[str, Any]], FetchStatus]:
    preflight = _preflight_status("okx-onchainos-signal-list")
    if preflight is not None:
        return [], preflight
    parts = [f'onchainos signal list --chain "{_quote(chain)}"', f'--wallet-type "{_quote(wallet_type)}"', f"--limit {limit}"]
    if min_address_count is not None:
        parts.append(f"--min-address-count {min_address_count}")
    data, status = _json_command(" ".join(parts), timeout=25, source="okx-onchainos-signal-list")
    return _unwrap_items(data), status


def tracker_activities(
    tracker_type: str = "smart_money",
    chain: str | None = None,
    trade_type: int = 1,
    limit: int | None = None,
) -> tuple[list[dict[str, Any]], FetchStatus]:
    """Get latest DEX activities for tracked addresses.

    Note: --limit is no longer supported by onchainos >=2.5.0. The parameter
    is kept for backwards compatibility but is ignored.
    """
    preflight = _preflight_status("okx-onchainos-tracker-activities")
    if preflight is not None:
        return [], preflight
    parts = [f"onchainos tracker activities --tracker-type {tracker_type}", f"--trade-type {trade_type}"]
    if chain:
        parts.append(f'--chain "{_quote(chain)}"')
    data, status = _json_command(" ".join(parts), timeout=25, source="okx-onchainos-tracker-activities")
    return _unwrap_items(data), status


def wallet_status(chain: str | None = None) -> tuple[dict[str, Any], FetchStatus]:
    preflight = _preflight_status("okx-onchainos-wallet-status")
    if preflight is not None:
        return {}, preflight
    parts = ["onchainos wallet status"]
    if chain:
        parts.append(f'--chain "{_quote(chain)}"')
    data, status = _json_command(" ".join(parts), timeout=10, source="okx-onchainos-wallet-status")
    return _unwrap_object(data), status


def token_price_info(address: str, chain: str | None = None) -> tuple[dict[str, Any], FetchStatus]:
    preflight = _preflight_status("okx-onchainos-token-price-info")
    if preflight is not None:
        return {}, preflight
    parts = [f'onchainos token price-info --address "{_quote(address)}"']
    if chain:
        parts.append(f'--chain "{_quote(chain)}"')
    data, status = _json_command(" ".join(parts), timeout=20, source="okx-onchainos-token-price-info")
    return _unwrap_object(data), status


def token_holders(address: str, chain: str | None = None, tag_filter: int | None = None, limit: int = 100) -> tuple[list[dict[str, Any]], FetchStatus]:
    preflight = _preflight_status("okx-onchainos-token-holders")
    if preflight is not None:
        return [], preflight
    parts = [f'onchainos token holders --address "{_quote(address)}"', f"--limit {limit}"]
    if chain:
        parts.append(f'--chain "{_quote(chain)}"')
    if tag_filter is not None:
        parts.append(f"--tag-filter {tag_filter}")
    data, status = _json_command(" ".join(parts), timeout=25, source="okx-onchainos-token-holders")
    return _unwrap_items(data), status


def token_advanced_info(address: str, chain: str | None = None) -> tuple[dict[str, Any], FetchStatus]:
    preflight = _preflight_status("okx-onchainos-token-advanced-info")
    if preflight is not None:
        return {}, preflight
    parts = [f'onchainos token advanced-info --address "{_quote(address)}"']
    if chain:
        parts.append(f'--chain "{_quote(chain)}"')
    data, status = _json_command(" ".join(parts), timeout=20, source="okx-onchainos-token-advanced-info")
    return _unwrap_object(data), status


def token_cluster_overview(address: str, chain: str | None = None) -> tuple[dict[str, Any], FetchStatus]:
    preflight = _preflight_status("okx-onchainos-token-cluster-overview")
    if preflight is not None:
        return {}, preflight
    parts = [f'onchainos token cluster-overview --address "{_quote(address)}"']
    if chain:
        parts.append(f'--chain "{_quote(chain)}"')
    data, status = _json_command(" ".join(parts), timeout=20, source="okx-onchainos-token-cluster-overview")
    return _unwrap_object(data), status


def token_cluster_top_holders(address: str, chain: str | None = None, range_filter: int = 1) -> tuple[dict[str, Any], FetchStatus]:
    preflight = _preflight_status("okx-onchainos-token-cluster-top-holders")
    if preflight is not None:
        return {}, preflight
    parts = [f'onchainos token cluster-top-holders --address "{_quote(address)}"', f"--range-filter {range_filter}"]
    if chain:
        parts.append(f'--chain "{_quote(chain)}"')
    data, status = _json_command(" ".join(parts), timeout=20, source="okx-onchainos-token-cluster-top-holders")
    return _unwrap_object(data), status


def token_trades(address: str, chain: str | None = None, limit: int = 100) -> tuple[list[dict[str, Any]], FetchStatus]:
    preflight = _preflight_status("okx-onchainos-token-trades")
    if preflight is not None:
        return [], preflight
    parts = [f'onchainos token trades --address "{_quote(address)}"', f"--limit {limit}"]
    if chain:
        parts.append(f'--chain "{_quote(chain)}"')
    data, status = _json_command(" ".join(parts), timeout=25, source="okx-onchainos-token-trades")
    return _unwrap_items(data), status


def token_snapshot(address: str, chain: str | None = None, depth: str = "full") -> dict[str, Any]:
    """Fetch on-chain snapshot. depth = "lite" | "deep" | "full".

    - lite: price_info + advanced_info (2 calls)
    - deep: holders + trades + cluster_overview + cluster_top_holders (4 calls)
    - full: all 6 calls (default, backwards compatible)
    """
    _depth = depth if depth in ("lite", "deep", "full") else "full"
    fetched_at = int(time.time())

    price_info: dict[str, Any] = {}
    price_status = FetchStatus(ok=False, error_type=FetchStatus.OPTIONAL_UNAVAILABLE, message=f"skipped in {_depth} mode", source="okx-onchainos-token-price-info")
    advanced_info: dict[str, Any] = {}
    advanced_status = FetchStatus(ok=False, error_type=FetchStatus.OPTIONAL_UNAVAILABLE, message=f"skipped in {_depth} mode", source="okx-onchainos-token-advanced-info")
    cluster_overview: dict[str, Any] = {}
    cluster_status = FetchStatus(ok=False, error_type=FetchStatus.OPTIONAL_UNAVAILABLE, message=f"skipped in {_depth} mode", source="okx-onchainos-token-cluster-overview")
    cluster_top: dict[str, Any] = {}
    cluster_top_status = FetchStatus(ok=False, error_type=FetchStatus.OPTIONAL_UNAVAILABLE, message=f"skipped in {_depth} mode", source="okx-onchainos-token-cluster-top-holders")
    holders: list[dict[str, Any]] = []
    holders_status = FetchStatus(ok=False, error_type=FetchStatus.OPTIONAL_UNAVAILABLE, message=f"skipped in {_depth} mode", source="okx-onchainos-token-holders")
    trades: list[dict[str, Any]] = []
    trades_status = FetchStatus(ok=False, error_type=FetchStatus.OPTIONAL_UNAVAILABLE, message=f"skipped in {_depth} mode", source="okx-onchainos-token-trades")

    if _depth in ("lite", "full"):
        price_info, price_status = token_price_info(address, chain=chain)
        advanced_info, advanced_status = token_advanced_info(address, chain=chain)

    if _depth in ("deep", "full"):
        cluster_overview, cluster_status = token_cluster_overview(address, chain=chain)
        cluster_top, cluster_top_status = token_cluster_top_holders(address, chain=chain, range_filter=1)
        holders, holders_status = token_holders(address, chain=chain, limit=100)
        trades, trades_status = token_trades(address, chain=chain, limit=100)

    return {
        "price_info": price_info,
        "advanced_info": advanced_info,
        "cluster_overview": cluster_overview,
        "cluster_top_holders": cluster_top,
        "holders": holders,
        "trades": trades,
        "status": {
            "price_info": {**price_status.to_dict(), "fetched_at": fetched_at},
            "advanced_info": {**advanced_status.to_dict(), "fetched_at": fetched_at},
            "cluster_overview": {**cluster_status.to_dict(), "fetched_at": fetched_at},
            "cluster_top_holders": {**cluster_top_status.to_dict(), "fetched_at": fetched_at},
            "holders": {**holders_status.to_dict(), "fetched_at": fetched_at},
            "trades": {**trades_status.to_dict(), "fetched_at": fetched_at},
        },
    }
