from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.request
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

    def __init__(
        self,
        ok: bool = True,
        error_type: str | None = None,
        message: str = "",
        latency_ms: float = 0.0,
        source: str = "",
    ):
        self.ok = ok
        self.error_type = error_type or (self.OK if ok else "unknown")
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


def run(cmd: str, timeout: int = 20) -> str:
    try:
        completed = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return completed.stdout.strip()
    except Exception as exc:
        return f"[ERROR] {exc}"


def json_out(cmd: str, timeout: int = 25) -> Optional[dict | list]:
    raw = run(cmd, timeout=timeout)
    if not raw or raw.startswith("[ERROR]"):
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def json_out_safe(cmd: str, timeout: int = 25, source: str = "") -> tuple[Optional[dict | list], FetchStatus]:
    """Return (data_or_None, status). Backwards-compatible with json_out."""
    t0 = time.time()
    try:
        raw = run(cmd, timeout=timeout)
        if not raw or raw.startswith("[ERROR]"):
            latency = (time.time() - t0) * 1000
            return None, FetchStatus(
                ok=False,
                error_type=FetchStatus.COMMAND_NOT_FOUND,
                message=raw.replace("[ERROR] ", ""),
                latency_ms=latency,
                source=source,
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
