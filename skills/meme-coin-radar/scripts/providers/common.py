from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.request
from dataclasses import dataclass
from typing import Any, Optional


# ── Structured fetch status (roadmap P0-1) ──────────────────────
class FetchStatus:
    """Structured status for provider fetch operations."""

    OK = "ok"
    TIMEOUT = "timeout"
    NETWORK = "network"
    COMMAND_NOT_FOUND = "command_not_found"
    PARSE_ERROR = "parse_error"
    PERMISSION_DENIED = "permission_denied"
    SOURCE_UNAVAILABLE = "source_unavailable"
    FIELD_NOT_SUPPORTED = "field_not_supported"
    AUTH_ERROR = "auth_error"
    RATE_LIMIT = "rate_limit"
    REGION_RESTRICTED = "region_restricted"
    OPTIONAL_UNAVAILABLE = "optional_unavailable"

    def __init__(
        self,
        ok: bool = True,
        error_type: str | None = None,
        message: str = "",
        latency_ms: float = 0.0,
        source: str = "",
    ):
        self.ok = ok
        self.error_type = None if ok else (error_type or "unknown")
        self.message = message
        self.latency_ms = latency_ms
        self.source = source

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "error_type": self.error_type,
            "message": self.message,
            "latency_ms": round(self.latency_ms, 1),
            "source": self.source,
        }

    @classmethod
    def from_exception(cls, exc: Exception, source: str = "") -> "FetchStatus":
        exc_type = type(exc).__name__.lower()
        if "timeout" in exc_type:
            return cls(ok=False, error_type=cls.TIMEOUT, message=str(exc), source=source)
        elif "not found" in exc_type or "file not found" in str(exc).lower():
            return cls(ok=False, error_type=cls.COMMAND_NOT_FOUND, message=str(exc), source=source)
        elif "permission" in exc_type or "denied" in str(exc).lower():
            return cls(ok=False, error_type=cls.PERMISSION_DENIED, message=str(exc), source=source)
        elif "urlerror" in exc_type or "connection" in str(exc).lower():
            return cls(ok=False, error_type=cls.NETWORK, message=str(exc), source=source)
        else:
            return cls(ok=False, error_type=cls.SOURCE_UNAVAILABLE, message=str(exc), source=source)


@dataclass
class CommandResult:
    returncode: int | None
    stdout: str
    stderr: str
    timed_out: bool = False


def run(cmd: str, timeout: int = 20) -> CommandResult:
    try:
        completed = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return CommandResult(
            returncode=completed.returncode,
            stdout=(completed.stdout or "").strip(),
            stderr=(completed.stderr or "").strip(),
            timed_out=False,
        )
    except subprocess.TimeoutExpired as exc:
        return CommandResult(
            returncode=None,
            stdout=((exc.stdout or "") if isinstance(exc.stdout, str) else "").strip(),
            stderr=((exc.stderr or "") if isinstance(exc.stderr, str) else "").strip(),
            timed_out=True,
        )
    except Exception as exc:
        return CommandResult(returncode=None, stdout="", stderr=str(exc), timed_out=False)


def _status_from_error_message(message: str, source: str = "", latency_ms: float = 0.0) -> FetchStatus:
    normalized = (message or "").strip()
    lowered = normalized.lower()

    if not normalized:
        return FetchStatus(
            ok=False,
            error_type=FetchStatus.SOURCE_UNAVAILABLE,
            message="empty response",
            latency_ms=latency_ms,
            source=source,
        )

    if "timed out" in lowered or "timeout" in lowered:
        error_type = FetchStatus.TIMEOUT
    elif "command not found" in lowered or "no such file or directory" in lowered:
        error_type = FetchStatus.COMMAND_NOT_FOUND
    elif "permission denied" in lowered or "operation not permitted" in lowered:
        error_type = FetchStatus.PERMISSION_DENIED
    elif "50125" in lowered or "80001" in lowered or "not available in your region" in lowered:
        error_type = FetchStatus.REGION_RESTRICTED
    elif "rate limit" in lowered or "too many requests" in lowered or "throttl" in lowered:
        error_type = FetchStatus.RATE_LIMIT
    elif (
        "api key" in lowered
        or "secret key" in lowered
        or "passphrase" in lowered
        or "unauthorized" in lowered
        or "forbidden" in lowered
        or "invalid signature" in lowered
        or "authentication" in lowered
        or "auth" in lowered
    ):
        error_type = FetchStatus.AUTH_ERROR
    elif "connection" in lowered or "urlopen error" in lowered or "name or service not known" in lowered:
        error_type = FetchStatus.NETWORK
    else:
        error_type = FetchStatus.SOURCE_UNAVAILABLE

    return FetchStatus(
        ok=False,
        error_type=error_type,
        message=normalized,
        latency_ms=latency_ms,
        source=source,
    )


def _status_from_command_result(result: CommandResult, source: str = "", latency_ms: float = 0.0) -> FetchStatus:
    if result.timed_out:
        message = result.stderr or result.stdout or "command timed out"
        return FetchStatus(
            ok=False,
            error_type=FetchStatus.TIMEOUT,
            message=message,
            latency_ms=latency_ms,
            source=source,
        )
    if result.returncode == 127:
        message = result.stderr or result.stdout or "command not found"
        return FetchStatus(
            ok=False,
            error_type=FetchStatus.COMMAND_NOT_FOUND,
            message=message,
            latency_ms=latency_ms,
            source=source,
        )
    if result.returncode == 126:
        message = result.stderr or result.stdout or "permission denied"
        return FetchStatus(
            ok=False,
            error_type=FetchStatus.PERMISSION_DENIED,
            message=message,
            latency_ms=latency_ms,
            source=source,
        )
    diagnostic = result.stderr or result.stdout
    return _status_from_error_message(diagnostic, source=source, latency_ms=latency_ms)


def json_out(cmd: str, timeout: int = 25) -> Optional[dict | list]:
    result = run(cmd, timeout=timeout)
    raw = result.stdout
    if result.returncode not in (0, None) or result.timed_out or not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def json_out_safe(cmd: str, timeout: int = 25, source: str = "") -> tuple[Optional[dict | list], FetchStatus]:
    """Return (data_or_None, status). Backwards-compatible with json_out."""
    t0 = time.time()
    try:
        result = run(cmd, timeout=timeout)
        raw = result.stdout
        if result.returncode not in (0,) or result.timed_out or not raw:
            latency = (time.time() - t0) * 1000
            return None, _status_from_command_result(
                result,
                source=source,
                latency_ms=latency,
            )
        data = json.loads(raw)
        latency = (time.time() - t0) * 1000
        return data, FetchStatus(ok=True, latency_ms=latency, source=source)
    except json.JSONDecodeError as exc:
        latency = (time.time() - t0) * 1000
        return None, FetchStatus(
            ok=False,
            error_type=FetchStatus.PARSE_ERROR,
            message=f"JSON parse error: {exc}",
            latency_ms=latency,
            source=source,
        )
    except Exception as exc:
        latency = (time.time() - t0) * 1000
        return None, FetchStatus.from_exception(exc, source=source)


def http_json(
    url: str,
    timeout: int = 15,
    method: str = "GET",
    body: dict | None = None,
) -> Optional[dict | list]:
    try:
        req_body = json.dumps(body).encode() if body is not None else None
        headers = {"Content-Type": "application/json"} if body is not None else {}
        request = urllib.request.Request(url, data=req_body, headers=headers, method=method)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())
    except Exception:
        return None


def http_json_safe(
    url: str,
    timeout: int = 15,
    method: str = "GET",
    body: dict | None = None,
    source: str = "",
) -> tuple[Optional[dict | list], FetchStatus]:
    t0 = time.time()
    try:
        req_body = json.dumps(body).encode() if body is not None else None
        headers = {"Content-Type": "application/json"} if body is not None else {}
        request = urllib.request.Request(url, data=req_body, headers=headers, method=method)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read())
        latency = (time.time() - t0) * 1000
        return data, FetchStatus(ok=True, latency_ms=latency, source=source)
    except urllib.error.HTTPError as exc:
        latency = (time.time() - t0) * 1000
        status = exc.code if hasattr(exc, "code") else 0
        return None, FetchStatus(
            ok=False,
            error_type=FetchStatus.SOURCE_UNAVAILABLE,
            message=f"HTTP {status}: {exc.reason if hasattr(exc, 'reason') else str(exc)}",
            latency_ms=latency,
            source=source,
        )
    except Exception as exc:
        latency = (time.time() - t0) * 1000
        return None, FetchStatus.from_exception(exc, source=source)
