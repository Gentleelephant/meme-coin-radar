from __future__ import annotations

from .common import json_out


def account_equity() -> float:
    """Fetch OKX account equity (best-effort). Returns 0 if unavailable."""
    # Try balance first
    data = json_out("okx account balance --json", timeout=15)
    if isinstance(data, dict):
        details = data.get("details") or data.get("data") or []
        if isinstance(details, list):
            total = 0.0
            for item in details:
                if isinstance(item, dict):
                    try:
                        eq = float(str(item.get("eq", item.get("equity", 0))).replace(",", ""))
                        total += eq
                    except (ValueError, TypeError):
                        continue
            if total > 0:
                return total

    # Fallback: try swap positions (sum margin)
    data = json_out("okx swap positions --json", timeout=15)
    if isinstance(data, list):
        total = 0.0
        for item in data:
            if isinstance(item, dict):
                try:
                    margin = float(str(item.get("margin", 0)).replace(",", ""))
                    total += margin
                except (ValueError, TypeError):
                    continue
        if total > 0:
            return total

    return 0.0
