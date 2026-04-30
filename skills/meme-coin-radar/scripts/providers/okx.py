from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Optional

from .common import FetchStatus


OKX_BASE_URL = "https://www.okx.com"


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _okx_base_url() -> str:
    return os.environ.get("OKX_API_BASE_URL", OKX_BASE_URL).strip().rstrip("/") or OKX_BASE_URL


def _okx_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _okx_headers(path_with_query: str, method: str, body_bytes: bytes | None) -> dict[str, str] | None:
    api_key = os.environ.get("OKX_API_KEY", "").strip()
    secret_key = os.environ.get("OKX_SECRET_KEY", "").strip()
    passphrase = os.environ.get("OKX_PASSPHRASE", "").strip()
    if not api_key or not secret_key or not passphrase:
        return None

    timestamp = _okx_timestamp()
    payload = f"{timestamp}{method.upper()}{path_with_query}".encode("utf-8")
    if body_bytes:
        payload += body_bytes
    signature = base64.b64encode(hmac.new(secret_key.encode("utf-8"), payload, hashlib.sha256).digest()).decode("utf-8")

    headers = {
        "OK-ACCESS-KEY": api_key,
        "OK-ACCESS-SIGN": signature,
        "OK-ACCESS-TIMESTAMP": timestamp,
        "OK-ACCESS-PASSPHRASE": passphrase,
        "Content-Type": "application/json",
    }
    if _env_bool("OKX_USE_DEMO_TRADING", False):
        headers["x-simulated-trading"] = "1"
    return headers


def _status_from_http_error(status_code: int, reason: str, source: str, latency_ms: float) -> FetchStatus:
    if status_code in {401, 403}:
        error_type = FetchStatus.AUTH_ERROR
    elif status_code == 429:
        error_type = FetchStatus.RATE_LIMIT
    else:
        error_type = FetchStatus.SOURCE_UNAVAILABLE
    return FetchStatus(
        ok=False,
        error_type=error_type,
        message=f"HTTP {status_code}: {reason}",
        latency_ms=latency_ms,
        source=source,
    )


def _okx_request_json(
    path: str,
    *,
    source: str,
    timeout: int = 15,
    method: str = "GET",
    params: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
    auth: bool = False,
) -> tuple[Optional[dict[str, Any]], FetchStatus]:
    query = ""
    if params:
        query = urllib.parse.urlencode(
            [(key, value) for key, value in params.items() if value not in (None, "")]
        )
    path_with_query = f"{path}?{query}" if query else path
    url = f"{_okx_base_url()}{path_with_query}"
    body_bytes = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}

    if auth:
        signed_headers = _okx_headers(path_with_query, method, body_bytes)
        if signed_headers is None:
            return None, FetchStatus(
                ok=False,
                error_type=FetchStatus.AUTH_ERROR,
                message="OKX API credentials not configured",
                source=source,
            )
        headers.update(signed_headers)

    started_at = time.time()
    try:
        request = urllib.request.Request(url, data=body_bytes, headers=headers, method=method.upper())
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read())
        latency_ms = (time.time() - started_at) * 1000
        if not isinstance(payload, dict):
            return None, FetchStatus(
                ok=False,
                error_type=FetchStatus.PARSE_ERROR,
                message="OKX response was not a JSON object",
                latency_ms=latency_ms,
                source=source,
            )
        code = str(payload.get("code", "0") or "0")
        if code not in {"0", ""}:
            message = str(payload.get("msg") or payload.get("message") or "OKX API error")
            error_type = FetchStatus.AUTH_ERROR if code in {"50113", "50114", "50115"} else FetchStatus.SOURCE_UNAVAILABLE
            return payload, FetchStatus(
                ok=False,
                error_type=error_type,
                message=f"OKX API {code}: {message}",
                latency_ms=latency_ms,
                source=source,
            )
        return payload, FetchStatus(ok=True, latency_ms=latency_ms, source=source)
    except urllib.error.HTTPError as exc:
        latency_ms = (time.time() - started_at) * 1000
        return None, _status_from_http_error(
            exc.code if hasattr(exc, "code") else 0,
            exc.reason if hasattr(exc, "reason") else str(exc),
            source,
            latency_ms,
        )
    except Exception as exc:
        latency_ms = (time.time() - started_at) * 1000
        return None, FetchStatus.from_exception(exc, source=source)


def _okx_public_json(
    path: str,
    *,
    source: str,
    timeout: int = 15,
    params: dict[str, Any] | None = None,
) -> tuple[Optional[dict[str, Any]], FetchStatus]:
    return _okx_request_json(path, source=source, timeout=timeout, params=params, auth=False)


def _okx_private_json(
    path: str,
    *,
    source: str,
    timeout: int = 15,
    params: dict[str, Any] | None = None,
) -> tuple[Optional[dict[str, Any]], FetchStatus]:
    return _okx_request_json(path, source=source, timeout=timeout, params=params, auth=True)


def _payload_items(payload: Optional[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def btc_status() -> dict[str, Any]:
    payload, status = _okx_public_json(
        "/api/v5/market/ticker",
        params={"instId": "BTC-USDT-SWAP"},
        timeout=15,
        source="okx-market-ticker",
    )
    items = _payload_items(payload)
    if not status.ok or not items:
        return {}

    item = items[0]
    try:
        last = float(str(item.get("last", "0")).replace(",", ""))
        open24h = float(str(item.get("open24h", "0")).replace(",", ""))
    except (ValueError, TypeError):
        return {}

    chg = (last - open24h) / open24h * 100 if open24h > 0 else 0.0
    return {
        "price": last,
        "open24h": open24h,
        "chg24h_pct": chg,
        "direction": "up" if chg > 2 else ("down" if chg < -2 else "neutral"),
        "raw": item,
        "source": "okx",
    }


def swap_tickers() -> list[dict[str, Any]]:
    payload, status = _okx_public_json(
        "/api/v5/market/tickers",
        params={"instType": "SWAP"},
        timeout=20,
        source="okx-market-tickers",
    )
    items = _payload_items(payload)
    if not status.ok or not items:
        return []

    result = []
    for item in items:
        inst_id = str(item.get("instId", ""))
        if "-USDT-SWAP" not in inst_id:
            continue
        try:
            last = float(str(item.get("last", 0) or 0).replace(",", ""))
            high = float(str(item.get("high24h", 0) or 0).replace(",", ""))
            low = float(str(item.get("low24h", 0) or 0).replace(",", ""))
            vol = float(str(item.get("volCcy24h", 0) or 0).replace(",", ""))
            open24h = float(str(item.get("open24h", 0) or 0).replace(",", ""))
        except (ValueError, TypeError):
            continue
        chg = (last - open24h) / open24h * 100 if open24h > 0 else 0.0
        result.append(
            {
                "instId": inst_id,
                "symbol": inst_id.replace("-USDT-SWAP", ""),
                "last": last,
                "high24h": high,
                "low24h": low,
                "vol24h": vol,
                "open24h": open24h,
                "chg24h_pct": chg,
                "source": "okx",
            }
        )
    return result


def funding_rate(inst_id: str) -> Optional[dict[str, Any]]:
    payload, status = _okx_public_json(
        "/api/v5/public/funding-rate",
        params={"instId": inst_id},
        timeout=10,
        source="okx-funding-rate",
    )
    items = _payload_items(payload)
    if not status.ok or not items:
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


def account_equity() -> float:
    """Fetch OKX account equity (best-effort). Returns 0 if unavailable."""
    payload, status = _okx_private_json(
        "/api/v5/account/balance",
        timeout=15,
        source="okx-account-balance",
    )
    if status.ok:
        total = 0.0
        for item in _payload_items(payload):
            for detail in item.get("details", []):
                if not isinstance(detail, dict):
                    continue
                try:
                    total += float(str(detail.get("eq", detail.get("equity", 0))).replace(",", ""))
                except (ValueError, TypeError):
                    continue
        if total > 0:
            return total

    payload, status = _okx_private_json(
        "/api/v5/account/positions",
        params={"instType": "SWAP"},
        timeout=15,
        source="okx-account-positions",
    )
    if not status.ok:
        return 0.0

    total = 0.0
    for item in _payload_items(payload):
        try:
            total += float(str(item.get("margin", 0)).replace(",", ""))
        except (ValueError, TypeError):
            continue
    return total

