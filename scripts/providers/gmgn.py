from __future__ import annotations

import json
import os
import subprocess
import urllib.request
from typing import Optional

from .common import load_gmgn_key


def api(path: str, body: dict | None = None, method: str = "POST") -> Optional[dict]:
    key = load_gmgn_key()
    if not key:
        return None
    try:
        url = "https://api.gmgn.ai" + path
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
            "User-Agent": "gmgn-cli/1.0",
        }
        data = json.dumps(body).encode() if body else None
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def trending(chain: str = "sol", interval: str = "1h", limit: int = 20) -> list:
    result = api("/v1/market/rank", {
        "chain": chain,
        "order_by": "volume",
        "direction": "desc",
        "interval": interval,
        "limit": limit,
        "filters": [],
    })
    if result and result.get("code") == 0:
        tokens = result.get("data", {}).get("rank", [])
        if tokens:
            return tokens

    try:
        completed = subprocess.run(
            [
                "npx", "-y", "gmgn-cli", "market", "trending",
                "--chain", chain,
                "--interval", interval,
                "--order-by", "volume",
                "--limit", str(limit),
                "--raw",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            env={**os.environ, "GMGN_API_KEY": load_gmgn_key() or ""},
        )
        data = json.loads(completed.stdout)
        return (data.get("data", {}) or {}).get("rank", []) or []
    except Exception:
        return []


def signal(chain: str = "sol", limit: int = 30) -> list:
    result = api("/v1/market/token_signal", {
        "chain": chain,
        "signal_type": [12, 13],
        "limit": limit,
    })
    if result:
        signals = result.get("data", [])
        if signals:
            return signals

    try:
        completed = subprocess.run(
            [
                "npx", "-y", "gmgn-cli", "market", "signal",
                "--chain", chain,
                "--signal-type", "12",
                "--limit", str(limit),
                "--raw",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            env={**os.environ, "GMGN_API_KEY": load_gmgn_key() or ""},
        )
        data = json.loads(completed.stdout)
        return data if isinstance(data, list) else data.get("data", [])
    except Exception:
        return []


def trenches(chain: str = "sol", token_type: str = "new_creation", limit: int = 20) -> list:
    try:
        completed = subprocess.run(
            [
                "npx", "-y", "gmgn-cli", "market", "trenches",
                "--chain", chain,
                "--type", token_type,
                "--limit", str(limit),
                "--filter-preset", "safe",
                "--raw",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            env={**os.environ, "GMGN_API_KEY": load_gmgn_key() or ""},
        )
        raw = completed.stdout.strip()
        if raw:
            data = json.loads(raw)
            return (
                (data.get("data", {}) or {}).get(token_type, [])
                or (data.get("data", {}) or {}).get("new_creation", [])
                or []
            )
    except Exception:
        pass
    return []


def _is_wash_trading_heuristic(volume: float, trades: int, buyers: int) -> bool:
    if volume <= 0 or trades <= 0:
        return False
    avg_trade = volume / trades
    if avg_trade > volume * 0.3 and trades < 5:
        return True
    if buyers > 0 and buyers / trades < 0.05:
        return True
    return False


def security_score(token: dict) -> dict:
    try:
        rug = float(token.get("rug_ratio") or 0)
        wash = bool(token.get("is_wash_trading", False))
        top10 = float(token.get("top_10_holder_rate") or 0)
        sm_count = int(token.get("smart_degen_count") or 0)
        kol_count = int(token.get("renowned_count") or 0)
        dev_hold = float(token.get("dev_team_hold_rate") or 0)
        bundler = float(token.get("bundler_rate") or 0)
        creator_close = bool(token.get("creator_close", False))
        deployer_ratio = float(token.get("deployer_holder_ratio") or 0)
        liquidity = float(token.get("liquidity") or 0)
        trades_24h = int(token.get("trades_24h") or 0)
        buyers_24h = int(token.get("buyers_24h") or 0)
        volume_24h = float(token.get("volume_24h") or token.get("volume") or 0)
        holder_count = int(token.get("holder_count") or 0)
        holders_growth_24h = float(token.get("holders_growth_24h") or 0)
        sellers_24h = int(token.get("sellers_24h") or 0)

        # Contract risk flags
        crf = token.get("contract_risk_flags", [])
        if isinstance(crf, str):
            crf = [f.strip() for f in crf.split(",") if f.strip()]
        dangerous = {"mintable", "blacklist", "pausable"}
        has_dangerous = any(flag in dangerous for flag in crf)
        ownership_renounced = bool(token.get("ownership_renounced", False))

        bonus = 0
        tag = "⚪ 普通"
        reject = False
        reason = ""

        # Obsidian hard rejects (expanded from Phase 1.0)
        if wash:
            reject = True
            reason = "is_wash_trading=True 洗量作弊"
            tag = "🔴 洗量"
        elif has_dangerous and not ownership_renounced:
            reject = True
            reason = f"合约高危权限未放弃: {crf}"
            tag = "🔴 合约高危"
        elif liquidity > 0 and liquidity < 50000:
            reject = True
            reason = f"流动性=${liquidity:.0f}<$50K"
            tag = "🔴 流动性不足"
        elif deployer_ratio > 0.10:
            reject = True
            reason = f"部署者持仓={deployer_ratio:.1%}>10%"
            tag = "🔴 部署者控盘"
        elif top10 > 0.35:
            reject = True
            reason = f"top10={top10:.1%}>35% 持仓过度集中"
            tag = "🔴 持仓集中"
        elif _is_wash_trading_heuristic(volume_24h, trades_24h, buyers_24h):
            reject = True
            reason = "成交量与交易笔数/买家数严重不匹配，疑似刷量"
            tag = "🔴 刷量"

        if not reject:
            if not creator_close and dev_hold > 0.10:
                tag = f"🟡 Dev({dev_hold:.0%})"
                bonus -= 3
            else:
                bonus += 2
            if bundler > 0.3:
                bonus -= 3
                tag = f"🟡 机器占{bundler:.0%}"
            else:
                bonus += 2

            if sm_count >= 5:
                bonus += 12
                tag = f"🟢 SM{sm_count}+KOL{kol_count}"
            elif sm_count >= 3:
                bonus += 8
                tag = f"🟢 SM{sm_count}"
            elif sm_count >= 1:
                bonus += 4
            if kol_count >= 3:
                bonus += 6
            elif kol_count >= 1:
                bonus += 3
            if rug < 0.1:
                bonus += 5
            elif rug < 0.2:
                bonus += 3
            if top10 < 0.20:
                bonus += 5
            elif top10 < 0.35:
                bonus += 3

        return {
            "reject": reject,
            "reason": reason,
            "bonus": bonus,
            "tag": tag,
            "rug_ratio": rug,
            "is_wash_trading": wash,
            "top_10_holder_rate": top10,
            "smart_degen_count": sm_count,
            "renowned_count": kol_count,
            "dev_hold_rate": dev_hold,
            "bundler_rate": bundler,
            "deployer_holder_ratio": deployer_ratio,
            "liquidity": liquidity,
            "contract_risk_flags": crf,
            "ownership_renounced": ownership_renounced,
            "holders": holder_count,
            "holders_growth_24h": holders_growth_24h,
            "buyers_24h": buyers_24h,
            "sellers_24h": sellers_24h,
        }
    except Exception:
        return {
            "reject": False,
            "bonus": 0,
            "tag": "⚪ 无GMGN数据",
            "rug_ratio": None,
            "is_wash_trading": False,
            "top_10_holder_rate": None,
            "smart_degen_count": 0,
            "renowned_count": 0,
            "dev_hold_rate": None,
            "bundler_rate": None,
            "deployer_holder_ratio": None,
            "liquidity": None,
            "contract_risk_flags": [],
            "ownership_renounced": None,
            "holders": 0,
            "holders_growth_24h": None,
            "buyers_24h": 0,
            "sellers_24h": 0,
        }
