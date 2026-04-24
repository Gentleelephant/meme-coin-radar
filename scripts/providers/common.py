from __future__ import annotations

import json
import os
import subprocess
import urllib.request
from typing import Optional

GMGN_API_KEY_FILE = os.path.expanduser("~/.config/gmgn/.env")


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


def http_json(
    url: str,
    timeout: int = 15,
    method: str = "GET",
    body: dict | None = None,
) -> Optional[dict | list]:
    try:
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Content-Type": "application/json"} if body is not None else {}
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())
    except Exception:
        return None


def load_gmgn_key() -> Optional[str]:
    try:
        with open(GMGN_API_KEY_FILE) as handle:
            for line in handle:
                if line.startswith("GMGN_API_KEY"):
                    return line.split("=", 1)[1].strip()
    except Exception:
        pass
    return None
