#!/usr/bin/env python3
"""
妖币雷达 Phase 1.8 - GMGN链上增强版
用法: python3 ~/.hermes/skills/meme-coin-radar/scripts/auto-run.py
数据输出: ~/.hermes/meme-radar/scan_YYYYMMDD_HHMMSS/

Phase 1.8 升级 (GMGN 接入):
  - 新增 GMGN 热门代币扫描（SOL/BSC Chain层 meme coin）
  - Module 1 新增 GMGN 链上安全数据（rug_ratio / is_wash_trading / top_10_holder_rate）
  - Module 4 新增 GMGN 聪明钱信号（smart_degen_count / renowned_count）
  - Module 6 新增 GMGN 聪明钱 K线信号（market signal feed）
  - 新增独立 GMGN 链上机会板块（Layer 0 — 非Binance合约的 meme coin 预警）
  - GMGN API Key 已配置：~/.config/gmgn/.env
"""
import os, subprocess, json, urllib.request, time
from datetime import datetime, timedelta

DATA_DIR = os.path.expanduser("~/.hermes/meme-radar")
os.makedirs(DATA_DIR, exist_ok=True)
TS = datetime.now().strftime("%Y%m%d_%H%M%S")
SCAN_DIR = os.path.join(DATA_DIR, "scan_" + TS)
os.makedirs(SCAN_DIR, exist_ok=True)

def run(cmd, timeout=20):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except Exception as e:
        return "[ERROR] " + str(e)

def save(name, content):
    path = os.path.join(SCAN_DIR, name)
    with open(path, "w") as f:
        f.write(content)
    return path

# ─────────────────────────────────────────────
# GMGN API — Chain层 meme coin 数据
# API Key: ~/.config/gmgn/.env (GMGN_API_KEY=xxx)
# ─────────────────────────────────────────────
GMGN_API_KEY_FILE = os.path.expanduser("~/.config/gmgn/.env")

def load_gmgn_key():
    try:
        with open(GMGN_API_KEY_FILE) as f:
            for line in f:
                if line.startswith("GMGN_API_KEY"):
                    return line.split("=", 1)[1].strip()
    except:
        pass
    return None

def gmgn_api(path, body=None, method="POST"):
    """调用 GMGN API，带 Ed25519 签名（简化版：无签名，直接传 API Key）"""
    import urllib.request, urllib.parse
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
        if body:
            data = json.dumps(body).encode()
        else:
            data = None
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"  [GMGN API Error] {e}")
        return None

def fetch_gmgn_trending(chain="sol", interval="1h", limit=20):
    """获取 GMGN 热门代币（SOL/BSC/Base）"""
    print(f"  [GMGN] 扫描 {chain.upper()} {interval} 热门代币...")
    result = gmgn_api("/v1/market/rank", {
        "chain": chain, "order_by": "volume", "direction": "desc",
        "interval": interval, "limit": limit, "filters": []
    })
    if not result or result.get("code") != 0:
        print(f"  [GMGN] 获取失败，尝试 fallback 方式...")
        return fetch_gmgn_fallback(chain, interval, limit)
    tokens = result.get("data", {}).get("rank", [])
    print(f"  [GMGN] 获取到 {len(tokens)} 个热门代币")
    return tokens

def fetch_gmgn_fallback(chain, interval, limit):
    """Fallback: 使用 gmgn-cli CLI"""
    try:
        r = subprocess.run(
            ["npx", "gmgn-cli", "market", "trending",
             "--chain", chain, "--interval", interval,
             "--order-by", "volume", "--limit", str(limit), "--raw"],
            capture_output=True, text=True, timeout=30,
            env={**os.environ, "GMGN_API_KEY": load_gmgn_key() or ""}
        )
        data = json.loads(r.stdout)
        return data.get("data", {}).get("rank", [])
    except Exception as e:
        print(f"  [GMGN fallback error] {e}")
        return []

def fetch_gmgn_signal(chain="sol", limit=30):
    """获取 GMGN 实时聪明钱信号（Smart Degen Buy / CTO 等）"""
    print(f"  [GMGN] 获取 {chain.upper()} 聪明钱信号...")
    result = gmgn_api("/v1/market/token_signal", {
        "chain": chain, "signal_type": [12, 13],  # Smart Degen Buy + Platform Call
        "limit": limit
    })
    if not result:
        return []
    signals = result.get("data", [])
    print(f"  [GMGN] 获取到 {len(signals)} 个聪明钱信号")
    return signals

def fetch_gmgn_trenches(chain="sol", token_type="new_creation", limit=20):
    """获取 GMGN 新上线 launchpad 代币（Pump.fun 等）"""
    print(f"  [GMGN] 扫描 {chain.upper()} Launchpad 新代币 ({token_type})...")
    result = gmgn_api("/v1/trenches", {
        "chain": chain, "type": [token_type],
        "limit": limit,
        "filters": [{"field": "rug_ratio", "op": "lte", "value": 0.3}]
    })
    if not result:
        return []
    data = result.get("data", {})
    items = data.get(token_type, []) or data.get("new_creation", [])
    print(f"  [GMGN] {token_type}: {len(items)} 个代币")
    return items

# ─────────────────────────────────────────────
# GMGN 代币安全评分（填入 Module 1）
# ─────────────────────────────────────────────
def gmgn_security_score(token):
    """
    从 GMGN trending/trenches 结果中提取安全字段。
    token: GMGN rank item dict
    返回: {
        rug_ratio, is_wash_trading, top_10_holder_rate,
        smart_degen_count, renowned_count,
        dev_hold_rate, bundler_rate,
        signal_tag, bonus_score
    }
    """
    try:
        rug = float(token.get("rug_ratio") or 0)
        wash = bool(token.get("is_wash_trading", False))
        top10 = float(token.get("top_10_holder_rate") or 0)
        sm_count = int(token.get("smart_degen_count") or 0)
        kol_count = int(token.get("renowned_count") or 0)
        dev_hold = float(token.get("dev_team_hold_rate") or 0)
        bundler = float(token.get("bundler_rate") or 0)
        creator_close = bool(token.get("creator_close", False))

        bonus = 0
        tag = "⚪ 普通"

        # 硬否决
        if wash:
            tag = "🔴 洗量"
            return {"reject": True, "reason": "is_wash_trading=True 洗量作弊", "bonus": 0, "tag": tag,
                    "rug_ratio": rug, "is_wash_trading": wash, "top_10_holder_rate": top10,
                    "smart_degen_count": sm_count, "renowned_count": kol_count,
                    "dev_hold_rate": dev_hold, "bundler_rate": bundler}

        # 安全否决
        if rug > 0.3:
            tag = f"🔴 Rug风险({rug:.2f})"
            return {"reject": True, "reason": f"rug_ratio={rug:.2f}>0.3 高风险", "bonus": 0, "tag": tag,
                    "rug_ratio": rug, "is_wash_trading": wash, "top_10_holder_rate": top10,
                    "smart_degen_count": sm_count, "renowned_count": kol_count,
                    "dev_hold_rate": dev_hold, "bundler_rate": bundler}

        # 持仓集中度否决
        if top10 > 0.60:
            tag = f"🔴 持仓集中({top10:.0%})"
            return {"reject": True, "reason": f"top_10_holder_rate={top10:.0%}>60% 持仓过度集中", "bonus": 0, "tag": tag,
                    "rug_ratio": rug, "is_wash_trading": wash, "top_10_holder_rate": top10,
                    "smart_degen_count": sm_count, "renowned_count": kol_count,
                    "dev_hold_rate": dev_hold, "bundler_rate": bundler}

        # Dev 未关闭仓位
        if not creator_close and dev_hold > 0.10:
            tag = f"🟡 Dev持仓({dev_hold:.0%})"
            bonus -= 3
        else:
            bonus += 2  # Dev 已离场

        # 机器人bundler率
        if bundler > 0.3:
            bonus -= 3
            tag = f"🟡 机器占{bundler:.0%}"
        else:
            bonus += 2

        # 聪明钱加分
        if sm_count >= 5:
            bonus += 12
            tag = f"🟢 SM{sm_count}+KOL{kol_count}"
        elif sm_count >= 3:
            bonus += 8
            tag = f"🟢 SM{sm_count}"
        elif sm_count >= 1:
            bonus += 4

        # KOL加分
        if kol_count >= 3:
            bonus += 6
        elif kol_count >= 1:
            bonus += 3

        # 安全加分
        if rug < 0.1:
            bonus += 5
        elif rug < 0.2:
            bonus += 3

        if top10 < 0.20:
            bonus += 5
        elif top10 < 0.35:
            bonus += 3

        return {
            "reject": False, "bonus": bonus, "tag": tag,
            "rug_ratio": rug, "is_wash_trading": wash,
            "top_10_holder_rate": top10,
            "smart_degen_count": sm_count, "renowned_count": kol_count,
            "dev_hold_rate": dev_hold, "bundler_rate": bundler,
        }
    except Exception as e:
        return {"reject": False, "bonus": 0, "tag": "⚪ 无GMGN数据",
                "rug_ratio": None, "is_wash_trading": False,
                "top_10_holder_rate": None,
                "smart_degen_count": 0, "renowned_count": 0,
                "dev_hold_rate": None, "bundler_rate": None}

# ─────────────────────────────────────────────
# Binance 基础 API
# ─────────────────────────────────────────────
def binance_ticker(symbol):
    try:
        url = "https://fapi.binance.com/fapi/v1/ticker/24hr?symbol=" + symbol
        d = json.loads(urllib.request.urlopen(url, timeout=5).read())
        return {
            "price": float(d["lastPrice"]),
            "chg24h": float(d["priceChangePercent"]),
            "high24h": float(d["highPrice"]),
            "low24h": float(d["lowPrice"]),
            "volume": float(d["quoteVolume"]) / 1e6,   # M USDT
            "price_vwap": float(d["weightedAvgPrice"]),
        }
    except Exception:
        return None

def binance_funding(symbol):
    try:
        url = "https://fapi.binance.com/fapi/v1/premiumIndex?symbol=" + symbol
        d = json.loads(urllib.request.urlopen(url, timeout=5).read())
        rate = float(d["lastFundingRate"]) * 100
        return {
            "fundingRate": rate,
            "annualRate": rate * 3 * 365,
            "nextFundingTime": d.get("nextFundingTime", 0),
        }
    except Exception:
        return None

def binance_klines(symbol, interval="1h", limit=50):
    """获取K线数据，用于计算 EMA20/50 和 ATR14"""
    try:
        url = (f"https://fapi.binance.com/fapi/v1/klines"
               f"?symbol={symbol}&interval={interval}&limit={limit}")
        d = json.loads(urllib.request.urlopen(url, timeout=5).read())
        # 返回 [(open, high, low, close, vol), ...]
        return [(float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])) for k in d]
    except Exception:
        return None

def calc_ema(prices, period):
    """计算 EMA"""
    if not prices or len(prices) < period:
        return None
    k = 2 / (period + 1)
    ema = sum(prices[:period]) / period
    for p in prices[period:]:
        ema = p * k + ema * (1 - k)
    return ema

def calc_atr14(klines):
    """计算 ATR14（简化版：用 close 波动估算）"""
    if not klines or len(klines) < 15:
        return None
    trs = []
    closes = [k[3] for k in klines]
    for i in range(1, len(klines)):
        high, low, prev_close = klines[i][1], klines[i][2], klines[i-1][3]
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
    if len(trs) < 14:
        return None
    return sum(trs[-14:]) / 14

def calc_trend_structure(price, ema20, ema50):
    """判断趋势结构（对齐 Obsidian）"""
    if ema20 is None or ema50 is None:
        return "unknown"
    if price > ema20 > ema50:
        return "bullish"        # price > ema20 > ema50
    elif price > ema20 and price < ema50:
        return "weak_recovery"  # price > ema20 not above ema50
    elif ema20 > price > ema50:
        return "caution"        # ema20 > price > ema50 (ema20已下穿)
    elif ema20 < price:
        return "below_ema20"    # price below both EMAs
    elif ema50 > price:
        return "bearish"
    return "unknown"

# ─────────────────────────────────────────────
# Binance Alpha 社区活跃度
# ─────────────────────────────────────────────
def fetch_binance_alpha():
    try:
        r = subprocess.run(
            ['npx', '-y', '@binance/binance-cli', 'alpha', 'token-list', '--json'],
            capture_output=True, text=True, timeout=40
        )
        data = json.loads(r.stdout)
        tokens = data.get('data', [])
        print(f"  Alpha: 获取到 {len(tokens)} 个代币的社区数据")
        alpha_dict = {}
        for t in tokens:
            sym = t.get('symbol', '')
            try:
                count24h = int(t.get('count24h') or 0)
                pct = float(t.get('percentChange24h') or 0)
                score = float(t.get('score') or 0)
            except:
                count24h = 0; pct = 0.0; score = 0.0
            alpha_dict[sym] = {'count24h': count24h, 'pct': pct, 'score': score}
        return alpha_dict
    except Exception as e:
        print(f"  Alpha: 获取失败 → {e}")
        return {}

def fetch_binance_batch(coins):
    """批量获取 Binance ticker + funding + klines"""
    results = {}
    for c in coins:
        ticker = binance_ticker(c + "USDT")
        funding = binance_funding(c + "USDT")
        klines = binance_klines(c + "USDT", interval="1h", limit=50)
        results[c] = {"ticker": ticker, "funding": funding, "klines": klines}
        time.sleep(0.06)
    return results

# ─────────────────────────────────────────────
# GMGN 增强评分（与 Binance 合约评分合并）
# ─────────────────────────────────────────────
def score_with_gmgn(symbol, ticker, funding, alpha, klines, btc_dir, gmgn_token):
    """
    Phase 1.8: 在 Binance 合约评分基础上，叠加 GMGN 链上安全/聪明钱数据。
    gmgn_token: GMGN trending/trenches 返回的单个代币 dict（可为空 {}）
    """
    # 先走 Phase 1.7 基础评分
    result = score_phase17(symbol, ticker, funding, alpha, klines, btc_dir, missing_fields=[])

    if gmgn_token:
        sec = gmgn_security_score(gmgn_token)
        gmgn_meta = {
            "rug_ratio": sec.get("rug_ratio"),
            "is_wash_trading": sec.get("is_wash_trading"),
            "top_10_holder_rate": sec.get("top_10_holder_rate"),
            "smart_degen_count": sec.get("smart_degen_count", 0),
            "renowned_count": sec.get("renowned_count", 0),
            "dev_hold_rate": sec.get("dev_hold_rate"),
            "bundler_rate": sec.get("bundler_rate"),
            "gmgn_tag": sec.get("tag", "⚪ 无GMGN数据"),
        }

        if sec.get("reject"):
            # 硬否决：直接降低评分并标记
            result["total"] = min(result["total"], 35)
            result["grade_label"] = "🔶弱"
            result["position_size"] = "不建议开仓"
            result["hit_rules"].append(f"⚠️ GMGN安全否决: {sec.get('reason', '链上安全风险')}")
            result["missing_fields"].append("gmgn_security_reject")
            result["risk_notes"].append(f"🔴 GMGN: {sec.get('tag')}")
        else:
            bonus = sec.get("bonus", 0)
            result["total"] = min(result["total"] + bonus, 100)
            gl, ps = grade(result["total"])
            result["grade_label"] = gl
            result["position_size"] = ps

            # 聪明钱 K线信号加成（Module 6 增强）
            sm = sec.get("smart_degen_count", 0)
            if sm >= 5:
                result["total"] = min(result["total"] + 5, 100)
                result["hit_rules"].append(f"✅ GMGN: {sm}个聪明钱钱包持有（强信号）")
            elif sm >= 1:
                result["hit_rules"].append(f"✅ GMGN: {sm}个聪明钱钱包入场")

            kol = sec.get("renowned_count", 0)
            if kol >= 3:
                result["hit_rules"].append(f"✅ GMGN: {kol}个KOL钱包持有（社交信号）")

            result["hit_rules"].append(f"✅ GMGN安全: rug={sec.get('rug_ratio')}, top10={sec.get('top_10_holder_rate')}")

        # 合并 meta
        result["meta"]["gmgn"] = gmgn_meta

    return result

# ─────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────
def pf(s, default=0.0):
    try: return float(str(s).replace("%","").replace(",","").replace("+",""))
    except: return default

def grade(score):
    if   score >= 85: return "🏆极强", "5%总资金/5x杠杆"
    elif score >= 65: return "⭐强",   "3-5%总资金/5x杠杆"
    elif score >= 45: return "中",    "1-2%总资金/3x杠杆"
    else:             return "🔶弱",  "不建议开仓"

medals = ["🥇","🥈","🥉","4.","5.","6.","7.","8."]

def score_label(score):
    if   score >= 85: return "🏆"
    elif score >= 65: return "⭐"
    elif score >= 45: return "中"
    else:              return "🔶"

# ─────────────────────────────────────────────
# Phase 1.7 五大模块评分引擎
# ─────────────────────────────────────────────
def score_phase17(c, ticker, funding, alpha, klines, btc_dir, missing_fields):
    """
    对齐 Obsidian 妖币判断指标 五大模块评分。
    每个模块可独立计算，缺失数据自动跳过并记录。

    Returns: {
        total, direction, grade_label, position_size,
        module_scores: dict,
        hit_rules: list,
        miss_rules: list,
        missing_fields: list,
        risk_notes: list,
        meta: {atr_pct, trend, ema20, ema50, price}
    }
    """
    chg = ticker["chg24h"] if ticker else 0.0
    price = ticker["price"] if ticker else 0.0
    vol = (ticker["volume"] * 1e6) if ticker else 0.0  # 转为 USD
    fr = funding["fundingRate"] if funding else 0.0
    count24h = alpha.get('count24h', 0) if alpha else 0

    # ── 计算趋势指标 ──
    ema20 = ema50 = atr14 = atr_pct = trend_struct = None
    if klines:
        closes = [k[3] for k in klines]
        ema20 = calc_ema(closes, 20)
        ema50 = calc_ema(closes, 50)
        atr14 = calc_atr14(klines)
        if price > 0 and atr14:
            atr_pct = atr14 / price  # ATR / price 波动率
        if ema20 and ema50:
            trend_struct = calc_trend_structure(price, ema20, ema50)

    # ─────────────────────────────────────────
    # Module 1: 安全与流动性（硬否决层，0-25分）
    # 注意：链上数据（LP锁定/前十持仓/合约权限）通过免费API无法获取
    # 替代：用 Binance 上市状态 + 成交额 间接判断
    # ─────────────────────────────────────────
    m1_safety = 0
    safety_reject = False
    safety_reasons = []

    # 硬否决：成交额过低（土狗信号）
    if vol < 5e6:   # < 5M USDT
        safety_reject = True
        safety_reasons.append("成交额 < $5M，疑似土狗")
    elif vol < 20e6:
        m1_safety += 3
        safety_reasons.append("成交额偏低 ($%sM)" % round(vol/1e6,1))
    else:
        m1_safety += 8

    # Binance 合约可用（隐性安全确认）
    if funding is not None:
        m1_safety += 8  # Binance 已上线 = 经过一定审核
    elif ticker is not None:
        m1_safety += 4  # 只有ticker没有funding = 降权通过

    # 持仓集中度：通过免费API无法获取，标记为缺失
    if funding is None and ticker is None:
        safety_reject = True
        safety_reasons.append("Binance无数据，无法验证")

    if safety_reject:
        return {
            "decision": "reject",
            "total": 0,
            "direction": "none",
            "grade_label": "❌拒绝",
            "position_size": "不交易",
            "module_scores": {"m1_safety": 0, "m2_price_vol": 0, "m3_trend": 0, "m4_alpha": 0, "m5_regime": 0, "m6_fr": 0},
            "hit_rules": [],
            "miss_rules": ["安全否决: " + "; ".join(safety_reasons)],
            "missing_fields": ["funding_rate", "volume_usd"] if funding is None or ticker is None else [],
            "risk_notes": safety_reasons,
            "meta": {"atr_pct": None, "trend": trend_struct, "ema20": ema20, "ema50": ema50, "price": price},
        }

    # 软评分（可加分）
    if vol >= 100e6: m1_safety += 5
    elif vol >= 50e6: m1_safety += 3
    if fr > 0 and vol >= 100e6: m1_safety += 4  # 高费率 + 高成交 = 多头接盘明显

    # ─────────────────────────────────────────
    # Module 2: 量价与持仓（0-35分）
    # ─────────────────────────────────────────
    m2_pv = 0

    # ATR 波动过滤（>= 8% 才算有足够交易空间）
    if atr_pct is not None:
        if atr_pct >= 0.08: m2_pv += 6
        elif atr_pct >= 0.05: m2_pv += 3

    # 成交额扩张（用24h成交额替代volume_vs_7d_avg）
    if vol >= 500e6: m2_pv += 10
    elif vol >= 200e6: m2_pv += 6
    elif vol >= 100e6: m2_pv += 3

    # 价格强度
    abs_chg = abs(chg)
    if chg >= 0:
        if chg >= 30: m2_pv += 6
        elif chg >= 15: m2_pv += 4
        elif chg >= 5: m2_pv += 2
    else:
        if abs_chg >= 20: m2_pv += 6
        elif abs_chg >= 10: m2_pv += 4
        elif abs_chg >= 5: m2_pv += 2

    # EMA 趋势过滤（做多方向加成更多）
    if trend_struct == "bullish":
        m2_pv += 5
    elif trend_struct == "weak_recovery":
        m2_pv += 2
    elif trend_struct == "bearish" and chg < 0:
        m2_pv += 3  # 顺势做空有加成

    # 买盘主导（只对上涨币有意义）
    if chg > 3 and vol >= 50e6:
        m2_pv += 3

    # ─────────────────────────────────────────
    # Module 3: 趋势结构（0-25分，新增）
    # ─────────────────────────────────────────
    m3_trend = 0

    if trend_struct == "bullish":
        m3_trend += 12  # 趋势完整，多空都顺
    elif trend_struct == "weak_recovery":
        m3_trend += 6
    elif trend_struct == "bearish":
        m3_trend += 8   # 下跌趋势中做空顺

    # ATR 波动空间（必须有波动才有机会）
    if atr_pct is not None:
        if atr_pct >= 0.12: m3_trend += 8
        elif atr_pct >= 0.08: m3_trend += 5
        elif atr_pct >= 0.04: m3_trend += 2
    else:
        # ATR 缺失，不加分但不扣分
        missing_fields.append("atr14")

    # EMA20/50 计算
    if ema20 is None: missing_fields.append("ema20")
    if ema50 is None: missing_fields.append("ema50")

    # ─────────────────────────────────────────
    # Module 4: 社交与叙事（0-20分，Alpha count24h）
    # ─────────────────────────────────────────
    m4_alpha = 0

    if count24h > 0:
        if count24h >= 100000:
            m4_alpha += 10
            if chg > 5: m4_alpha += 5   # 追涨 + 高活跃
            elif chg < -5: m4_alpha += 5  # 抄底 + 高活跃
        elif count24h >= 50000:
            m4_alpha += 6
            if abs(chg) >= 10: m4_alpha += 3
        elif count24h >= 20000:
            m4_alpha += 3
            if abs(chg) >= 15: m4_alpha += 2
        else:
            m4_alpha += 1  # 有活跃度记录就算1分
    else:
        missing_fields.append("alpha_count24h")

    # Alpha 单独出现但无价格异动 = 酝酿中（观察分）
    if count24h >= 50000 and abs(chg) < 3:
        m4_alpha += 3  # 酝酿中，观察区信号

    # ─────────────────────────────────────────
    # Module 5: 市场环境（0-10分）
    # ─────────────────────────────────────────
    m5_regime = 0
    regime_label = "neutral"

    if btc_dir == "up":
        regime_label = "risk_on"
        m5_regime = 7
    elif btc_dir == "down":
        regime_label = "risk_off"
        m5_regime = 0
    else:
        regime_label = "neutral"
        m5_regime = 4

    # ─────────────────────────────────────────
    # Module 6: 资金费率（0-20分，对齐 Obsidian OI 四象限）
    # ─────────────────────────────────────────
    m6_fr = 0

    if fr > 0:
        # 做空信号
        if fr >= 2.0: m6_fr += 15
        elif fr >= 1.0: m6_fr += 10
        elif fr >= 0.5: m6_fr += 6
        elif fr >= 0.2: m6_fr += 3
    elif fr < 0:
        # 做多信号
        if fr <= -0.5: m6_fr += 15
        elif fr <= -0.2: m6_fr += 10
        elif fr <= -0.1: m6_fr += 6
        elif fr < 0: m6_fr += 2
    else:
        m6_fr += 1  # 0费率给1分（中性）

    # ─────────────────────────────────────────
    # 综合评分与方向判定
    # ─────────────────────────────────────────
    total = m1_safety + m2_pv + m3_trend + m4_alpha + m5_regime + m6_fr
    total = min(total, 100)

    # 方向判定：综合各模块得分
    short_score = 0
    long_score = 0

    # 资金费率方向权重最高
    if fr > 0.5:
        short_score += m6_fr * 1.5  # 资金费率加权
    elif fr < -0.2:
        long_score += m6_fr * 1.5

    # 价格变动方向
    if chg < -5: short_score += m2_pv * 0.8
    elif chg > 5: long_score += m2_pv * 0.8

    # 趋势方向
    if trend_struct in ("bearish", "below_ema20") and chg < 0:
        short_score += m3_trend
    elif trend_struct == "bullish" and chg > 0:
        long_score += m3_trend

    # 大盘方向
    if btc_dir == "up" and chg > 0: long_score += m5_regime
    elif btc_dir == "down" and chg < 0: short_score += m5_regime

    if short_score > long_score:
        direction = "short"
    elif long_score > short_score:
        direction = "long"
    else:
        # 平局时按资金费率决定
        direction = "short" if fr > 0 else "long"

    # 满足条件的做空加成
    if fr > 0.5 and chg < -5 and count24h > 30000:
        total += 8  # 费率+暴跌+高活跃 = 做空共振

    # 满足条件的做多加成（暴跌反弹）
    if chg < -10 and fr < -0.1:
        total += 10  # 暴跌+负费率 = 最佳做多窗口

    total = min(total, 100)
    gl, ps = grade(total)

    # ── 命中/未命中规则 ──
    hit = []; miss = []
    if fr > 0.5: hit.append("资金费率>0.5%，利于做空")
    elif fr > 0: miss.append("资金费率<0.5%，做空信号弱")
    if fr < -0.1: hit.append("资金费率<0.1%，利于做多")
    elif fr >= 0: miss.append("资金费率>=0，做多信号弱")
    if abs(chg) >= 10: hit.append("价格异动|%s%%|显著" % round(chg,1))
    if count24h >= 50000: hit.append("Alpha count24h=%s 社区活跃" % f"{count24h:,}")
    elif count24h == 0: miss.append("无Alpha社区数据")
    if trend_struct == "bullish": hit.append("趋势结构: EMA多头排列")
    elif trend_struct == "bearish": hit.append("趋势结构: EMA空头排列")
    if atr_pct and atr_pct >= 0.08: hit.append("ATR波动率: %.1f%% 有足够空间" % (atr_pct*100))
    elif atr_pct is None: miss.append("无ATR数据")
    if vol >= 100e6: hit.append("成交额>$100M 流动性良好")
    elif vol < 20e6: miss.append("成交额<$20M 流动性不足")

    # 缺失数据记录
    all_missing = list(set(missing_fields))

    return {
        "decision": "watchlist" if total >= 30 else "reject",
        "total": total,
        "direction": direction,
        "grade_label": gl,
        "position_size": ps,
        "module_scores": {
            "m1_safety": m1_safety,
            "m2_price_vol": m2_pv,
            "m3_trend": m3_trend,
            "m4_alpha": m4_alpha,
            "m5_regime": m5_regime,
            "m6_fr": m6_fr,
        },
        "hit_rules": hit,
        "miss_rules": miss,
        "missing_fields": all_missing,
        "risk_notes": [],
        "meta": {
            "atr_pct": atr_pct,
            "trend": trend_struct,
            "ema20": ema20,
            "ema50": ema50,
            "price": price,
            "vol": vol,
            "fr": fr,
            "chg": chg,
            "count24h": count24h,
            "regime": regime_label,
        },
    }

# ─────────────────────────────────────────────
# 主流程
# ─────────────────────────────────────────────
print("=== 妖币雷达 Phase 1.7 扫描 ===")
print("时间: " + TS)

# Step 0: BTC 大盘
print("[0] BTC 大盘...")
btc_raw = run("okx market ticker BTC-USDT-SWAP --json", timeout=15)
save("00_btc_status.txt", btc_raw)
btc_dir = "neutral"
btc_price = "N/A"
btc_chg = "N/A"
if btc_raw.startswith("["):
    try:
        d = json.loads(btc_raw)[0]
        btc_price = d.get("last", "N/A")
        open24h = float(d.get("open24h", btc_price))
        last = float(btc_price)
        btc_chg = "%.2f" % ((last - open24h) / open24h * 100)
        chg_v = float(btc_chg)
        btc_dir = "up" if chg_v > 2 else ("down" if chg_v < -2 else "neutral")
    except: pass
arrow = "↑" if btc_dir=="up" else ("↓" if btc_dir=="down" else "横")
大盘判断 = "适合做多" if btc_dir=="up" else ("适合做空" if btc_dir=="down" else "多空均可")
print("  BTC=$" + str(btc_price) + " chg=" + str(btc_chg) + "% [" + btc_dir + "]")

# Step 0.5: Binance Alpha
print("[0.5] Binance Alpha 社区活跃度...")
alpha_dict = fetch_binance_alpha()
save("04_binance_alpha.txt", json.dumps(alpha_dict, indent=2))
top_alpha = sorted(alpha_dict.items(), key=lambda x: x[1]['count24h'], reverse=True)[:20]
print("  Alpha TOP5 活跃度:")
for sym, d in top_alpha[:5]:
    print(f"    {sym}: tx24h={d['count24h']:,} chg={d['pct']:+.1f}%")

# ── Phase 1.8 新增：GMGN Chain层扫描 ──
gmgn_key = load_gmgn_key()
gmgn_sol_trending = []
gmgn_bsc_trending = []
gmgn_signals = []
gmgn_trenches_sol = []

if gmgn_key:
    print("[G1] GMGN SOL 热门代币扫描...")
    gmgn_sol_trending = fetch_gmgn_trending(chain="sol", interval="1h", limit=20)
    save("05_gmgn_sol_trending.json", json.dumps(gmgn_sol_trending, indent=2, default=str, ensure_ascii=False))

    print("[G2] GMGN BSC 热门代币扫描...")
    gmgn_bsc_trending = fetch_gmgn_trending(chain="bsc", interval="1h", limit=20)
    save("06_gmgn_bsc_trending.json", json.dumps(gmgn_bsc_trending, indent=2, default=str, ensure_ascii=False))

    print("[G3] GMGN SOL 聪明钱信号...")
    gmgn_signals = fetch_gmgn_signal(chain="sol", limit=30)
    if gmgn_signals:
        save("07_gmgn_signals.json", json.dumps(gmgn_signals, indent=2, default=str, ensure_ascii=False))
        signal_addresses = [s.get("token_address", "") for s in gmgn_signals[:10]]
        print(f"  聪明钱信号地址: {signal_addresses[:3]}")
    else:
        # CLI fallback
        try:
            r = subprocess.run(
                ["npx", "gmgn-cli", "market", "signal", "--chain", "sol",
                 "--signal-type", "12", "--raw"],
                capture_output=True, text=True, timeout=30,
                env={**os.environ, "GMGN_API_KEY": gmgn_key}
            )
            data = json.loads(r.stdout)
            gmgn_signals = data if isinstance(data, list) else data.get("data", [])
            save("07_gmgn_signals.json", json.dumps(gmgn_signals, indent=2, default=str))
        except:
            pass

    print("[G4] GMGN SOL Pump.fun 新上线代币...")
    try:
        r = subprocess.run(
            ["npx", "gmgn-cli", "market", "trenches", "--chain", "sol",
             "--type", "new_creation", "--limit", "20", "--filter-preset", "safe", "--raw"],
            capture_output=True, text=True, timeout=30,
            env={**os.environ, "GMGN_API_KEY": gmgn_key}
        )
        raw = r.stdout.strip()
        if raw:
            data = json.loads(raw)
            gmgn_trenches_sol = data.get("data", {}).get("new_creation", []) or []
            save("08_gmgn_trenches_sol.json", json.dumps(gmgn_trenches_sol, indent=2, default=str, ensure_ascii=False))
    except Exception as e:
        print(f"  GMGN trenches fallback error: {e}")

    # GMGN SOL trending 安全过滤
    gmgn_sol_pass = []
    gmgn_sol_reject = []
    for t in gmgn_sol_trending:
        sec = gmgn_security_score(t)
        symbol = t.get("symbol", "")
        price = float(t.get("price") or 0)
        chg = float(t.get("price_change_percent1h") or 0)
        vol = float(t.get("volume") or 0)
        sm = sec.get("smart_degen_count", 0)
        if not sec.get("reject"):
            gmgn_sol_pass.append({
                "symbol": symbol,
                "name": t.get("name", ""),
                "address": t.get("address", ""),
                "chain": "sol",
                "price": price,
                "chg1h": chg,
                "vol": vol,
                "liquidity": float(t.get("liquidity") or 0),
                "mcap": float(t.get("market_cap") or 0),
                "holders": int(t.get("holder_count") or 0),
                "rug_ratio": sec.get("rug_ratio"),
                "wash": sec.get("is_wash_trading"),
                "top10": sec.get("top_10_holder_rate"),
                "smart_degen_count": sm,
                "renowned_count": sec.get("renowned_count", 0),
                "gmgn_tag": sec.get("tag"),
                "bonus": sec.get("bonus", 0),
                "sec": sec,
            })
        else:
            gmgn_sol_reject.append({"symbol": symbol, "reason": sec.get("reason", "")})

    # GMGN SOL 聪明钱共振：smart_degen_count >= 3 且有涨幅
    gmgn_sm共振 = [t for t in gmgn_sol_pass if t["smart_degen_count"] >= 3]
    gmgn_sm共振.sort(key=lambda x: (x["smart_degen_count"], x["chg1h"]), reverse=True)

    print(f"  GMGN SOL 安全通过: {len(gmgn_sol_pass)}, 拒绝: {len(gmgn_sol_reject)}, 聪明钱共振: {len(gmgn_sm共振)}")
else:
    print("[G*] GMGN API Key 未配置，跳过 Chain层扫描（可配置 ~/.config/gmgn/.env）")

# Step 1: 全量 OKX SWAP tickers
print("[1] 全量 SWAP tickers...")
tickers_raw = run("okx market tickers SWAP", timeout=20)
save("01_all_tickers.txt", tickers_raw)

def parse_tickers(text):
    coins = []
    for line in text.strip().splitlines():
        line = line.strip()
        if not line or "----" in line or "instId" in line or "Environment" in line:
            continue
        parts = line.split()
        if len(parts) >= 5 and "-USDT-SWAP" in parts[0]:
            try:
                last = float(parts[1]); high = float(parts[2]); low = float(parts[3]); vol = float(parts[4])
                mid = (high + low) / 2
                chg = (last - mid) / mid * 100 if mid > 0 else 0
                coins.append({"instId": parts[0], "last": last, "high24h": high, "low24h": low, "vol": vol, "chg": chg})
            except: pass
    return coins

all_tickers = parse_tickers(tickers_raw)
print("  解析到 " + str(len(all_tickers)) + " 个 USDT-M SWAP")

# Step 2: 构建候选币列表（涨幅+跌幅+Alpha+主流）
all_tickers.sort(key=lambda x: x["chg"], reverse=True)
anomaly = [c["instId"].replace("-USDT-SWAP","") for c in all_tickers[:20] + all_tickers[-20:]]
alpha_top = [sym for sym, _ in top_alpha[:15]]
key_coins = ["BTC","ETH","SOL","ZEC","HYPE","BNB","DOGE","PEPE","WIF","SHIB","AAVE","AVAX","LINK","UNI","ARB","OP","INJ","SEI","TIA","SUI","APT","NEAR","FTM","MATIC","ENS","RENDER","GALA","AXS","SNX","YGG"]
check_coins = list(dict.fromkeys(key_coins + anomaly + alpha_top))[:30]

print("[2] Binance batch (" + str(len(check_coins)) + " coins) 含K线+费率...")
bnc_results = fetch_binance_batch(check_coins)
save("02_binance_batch.txt", json.dumps({k: {
    "ticker": v["ticker"],
    "funding": v["funding"],
    "has_klines": v["klines"] is not None,
} for k, v in bnc_results.items()}, indent=2, default=str))

# ── Step 3: Phase 1.8 GMGN增强六大模块评分 ──
print("[3] Phase 1.8 GMGN增强六大模块评分...")
scored = []

# 构建 GMGN → Binance 符号映射（SOL meme币常有 Binance 合约对）
gmgn_addr_to_symbol = {}
for t in gmgn_sol_trending + gmgn_bsc_trending:
    addr = t.get("address", "")
    sym = t.get("symbol", "").upper()
    if addr and sym:
        gmgn_addr_to_symbol[addr] = sym
        gmgn_addr_to_symbol[sym] = t  # 也按符号索引

for c in check_coins:
    r = bnc_results.get(c, {})
    ticker = r.get("ticker")
    funding = r.get("funding")
    klines = r.get("klines")
    alpha = alpha_dict.get(c, {})

    if ticker is None and funding is None:
        print(f"  {c}: Binance无数据，跳过")
        continue

    # 查找 GMGN 数据
    gmgn_token = gmgn_addr_to_symbol.get(c.upper(), {})

    # Phase 1.8: 用 GMGN 增强评分
    result = score_with_gmgn(c, ticker, funding, alpha, klines, btc_dir, gmgn_token)
    result["name"] = c
    scored.append(result)

# 过滤拒绝项
valid = [s for s in scored if s["decision"] != "reject"]
valid.sort(key=lambda x: x["total"], reverse=True)
top8 = valid[:8]
all_rejected = [s for s in scored if s["decision"] == "reject"]

print(f"  候选总数={len(scored)}, 有效={len(valid)}, 拒绝={len(all_rejected)}")
for s in top8[:3]:
    m = s["module_scores"]
    print(f"  {s['name']}: 总={s['total']} | 安={m['m1_safety']} 量={m['m2_price_vol']} 趋={m['m3_trend']} 社={m['m4_alpha']} 环={m['m5_regime']} 费={m['m6_fr']} → {s['direction']}")

# ── Step 4: 生成 Phase 1.7 报告 ──
report_lines = [
    "# 🦊 妖币雷达 Phase 1.8 扫描报告",
    "> 扫描时间：" + TS,
    "> 数据来源：OKX Demo + Binance Alpha + Binance USDT-M K线 + **GMGN Chain层数据**",
    "> Phase 1.8 新增：GMGN SOL/BSC热门代币扫描、链上安全否决层（rug_ratio/wash_trading）、聪明钱追踪",
    "> 对齐 Obsidian 妖币判断指标 五大模块评分",
    "",
    "## 📊 大盘环境",
    "",
    "| 指标 | 数值 | 方向 |",
    "|---|---:|---|",
    f"| BTC 价格 | ${btc_price} | {arrow} |",
    f"| BTC 24h涨跌 | {btc_chg}% | — |",
    f"| 市场判断 | {大盘判断} | — |",
    "",
]

# ── GMGN Chain层机会板块（Phase 1.8 独立 Layer 0）──
if gmgn_key and gmgn_sol_pass:
    report_lines += [
        "",
        "## 🚀 GMGN Chain层机会板块（Layer 0 — 非Binance合约）",
        "",
        "### 🟢 聪明钱共振代币（GMGN smart_degen_count ≥ 3）",
        "",
        "| 评级 | 代币 | 名称 | Chain | 价格 | 1h涨跌 | 成交量 | 流动性 | 持币人数 | Rug | Top10持 | 聪明钱 | KOL | GMGN信号 |",
        "|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for t in gmgn_sm共振[:5]:
        tag = t["gmgn_tag"] or "⚪"
        rug = f"{t['rug_ratio']:.2f}" if t.get("rug_ratio") is not None else "N/A"
        top10 = f"{t['top10']:.0%}" if t.get("top10") is not None else "N/A"
        liq = f"${t['liquidity']/1000:.0f}K" if t["liquidity"] else "N/A"
        report_lines.append(
            f"| ⭐ | **{t['symbol']}** | {t['name'][:20]} | SOL | "
            f"${t['price']:.6g} | **{t['chg1h']:+.1f}%** | ${t['vol']/1e6:.1f}M | {liq} | "
            f"{t['holders']:,} | {rug} | {top10} | {t['smart_degen_count']} | {t['renowned_count']} | {tag} |"
        )

    report_lines += [
        "",
        "### 📈 GMGN SOL 热门代币 TOP10（安全过滤后）",
        "",
        "| 代币 | 名称 | 价格 | 1h涨跌 | 成交量 | 流动性 | Rug | 聪明钱 | KOL | 信号 |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for t in gmgn_sol_pass[:10]:
        rug = f"{t['rug_ratio']:.2f}" if t.get("rug_ratio") is not None else "—"
        liq = f"${t['liquidity']/1000:.0f}K" if t["liquidity"] else "—"
        tag = t.get("gmgn_tag", "⚪")
        report_lines.append(
            f"| **{t['symbol']}** | {t['name'][:15]} | ${t['price']:.6g} | {t['chg1h']:+.1f}% | "
            f"${t['vol']/1e6:.1f}M | {liq} | {rug} | {t['smart_degen_count']} | {t['renowned_count']} | {tag} |"
        )

    if gmgn_trenches_sol:
        report_lines += [
            "",
            "### 🆕 GMGN SOL Pump.fun 新上线代币（safe preset）",
            "",
            "| 代币 | 名称 | 流动性 | 成交量 | Rug | 聪明钱 | KOL |",
            "|---|---|---|---:|---:|---:|---:|---:|",
        ]
        for t in gmgn_trenches_sol[:8]:
            report_lines.append(
                f"| **{t.get('symbol','')}** | {t.get('name','')[:15]} | "
                f"${float(t.get('liquidity',0))/1000:.0f}K | "
                f"${float(t.get('volume_1h',0))/1000:.0f}K | "
                f"{float(t.get('rug_ratio',0)):.2f} | "
                f"{int(t.get('smart_degen_count',0))} | "
                f"{int(t.get('renowned_count',0))} |"
            )

    if gmgn_signals:
        report_lines += [
            "",
            "### 💰 GMGN 实时聪明钱信号（Smart Degen Buy）",
            "",
            "| 时间 | 代币地址 | 触发时市值 | 当前市值 | ATH市值 | 信号类型 |",
            "|---|---:|---:|---:|---:|---|",
        ]
        from datetime import datetime as dt
        for s in gmgn_signals[:8]:
            ts = s.get("trigger_at", 0)
            try:
                t_str = dt.fromtimestamp(ts).strftime("%H:%M") if ts else "N/A"
            except:
                t_str = str(ts)
            addr = s.get("token_address", "")[:8] + "..."
            mc = s.get("trigger_mc", 0)
            cur = s.get("market_cap", 0)
            ath = s.get("ath", 0)
            stype = s.get("signal_type", "")
            sig_name = {12: "SmartDegenBuy", 13: "PlatformCall"}.get(int(stype), stype)
            report_lines.append(
                f"| {t_str} | `{addr}` | ${mc/1000:.0f}K | ${cur/1000:.0f}K | ${ath/1000:.0f}K | {sig_name} |"
            )
else:
    report_lines += [
        "",
        "## 🚀 GMGN Chain层机会板块",
        "",
        "> ⚠️ GMGN API Key 未配置。配置后可解锁：",
        "> - SOL/BSC 热门 meme 币实时扫描",
        "> - 链上安全否决（rug_ratio / wash_trading）",
        "> - 聪明钱钱包追踪（smart_degen_count）",
        "> - Pump.fun 新上线代币预警",
        "",
        "```bash",
        "# GMGN API Key 配置（参考 ~/.config/gmgn/.env）",
        "# 访问 https://gmgn.ai/ai 获取 API Key",
        "```",
    ]

report_lines += [
    "",
    "## 🔥 社区活跃度 TOP10（Binance Alpha — count24h）",
    "",
    "| 排名 | 币种 | count24h（链上交易） | 24h 涨跌 |",
    "|---|---|---:|---:|",
]
for i, (sym, d) in enumerate(top_alpha[:10], 1):
    report_lines.append(f"| {i} | **{sym}** | {d['count24h']:,} | {d['pct']:+.1f}% |")

report_lines += [
    "",
    "## 🏆 机会队列（Phase 1.8 GMGN增强六大模块评分）",
    "",
    "| 评级 | 币种 | 方向 | 总分 | 安全 | 量价 | 趋势 | 社交 | 环境 | 费率 |",
    "|---|---|---|---|---:|---:|---:|---:|---:|---:|",
]

for c in top8:
    m = c["module_scores"]
    dir_em = "🟢" if c["direction"] == "long" else "🔴"
    report_lines.append(f"| {c['grade_label']} | **{c['name']}** | {dir_em}{c['direction']} | **{c['total']}** | {m['m1_safety']} | {m['m2_price_vol']} | {m['m3_trend']} | {m['m4_alpha']} | {m['m5_regime']} | {m['m6_fr']} |")

report_lines.append("")
report_lines.append("### 详细信号（TOP3）")
report_lines.append("")

for i, c in enumerate(top8[:3]):
    meta = c["meta"]
    dir_em = "🟢做多" if c["direction"] == "long" else "🔴做空"
    dir_ch = "做多" if c["direction"] == "long" else "做空"
    price = meta["price"]
    chg = meta["chg"]
    fr = meta["fr"]
    atr = meta["atr_pct"]
    trend = meta["trend"]
    ema20 = meta["ema20"]
    ema50 = meta["ema50"]
    count24h = meta["count24h"]
    vol = meta["vol"]

    if price > 0:
        if c["direction"] == "long":
            stop_loss = "%.4f" % (price * 0.95)
            target = "%.4f" % (price * 1.15)
        else:
            stop_loss = "%.4f" % (price * 1.08)
            target = "%.4f" % (price * 0.85)
    else:
        stop_loss = target = "N/A"

    atr_str = "%.2f%%" % (atr * 100) if atr else "N/A"
    ema20_str = "%.4f" % ema20 if ema20 else "N/A"
    ema50_str = "%.4f" % ema50 if ema50 else "N/A"

    # GMGN 额外数据
    gmgn_sec = c.get("meta", {}).get("gmgn") or {}
    gmgn_tag = gmgn_sec.get("gmgn_tag", "—")
    rug = gmgn_sec.get("rug_ratio")
    top10 = gmgn_sec.get("top_10_holder_rate")
    sm_count = gmgn_sec.get("smart_degen_count", 0)
    kol_count = gmgn_sec.get("renowned_count", 0)
    dev_hold = gmgn_sec.get("dev_hold_rate")

    gmgn_extra = ""
    if gmgn_tag and gmgn_tag != "—":
        rug_str = f"{rug:.3f}" if rug is not None else "—"
        top10_str = f"{top10:.1%}" if top10 is not None else "—"
        dev_str = f"{dev_hold:.1%}" if dev_hold is not None else "—"
        gmgn_extra = f"| **GMGN安全** | rug={rug_str}, top10={top10_str}, dev={dev_str} | — | {gmgn_tag} |"

    report_lines += [
        f"#### {medals[i]} **{c['name']}** — {dir_em} — 评分：**{c['total']}** {c['grade_label']}",
        "",
        "| 指标 | 数值 | 得分 | 说明 |",
        "|---|---|---:|---|",
        f"| 当前价格 | ${price} | — | — |",
        f"| 24h涨跌 | {chg:+.2f}% | — | — |",
        f"| 资金费率 | {fr:+.4f}%/8h（年化 {fr*3*365:+.1f}%） | {c['module_scores']['m6_fr']} | Module 6 |",
        f"| 成交额 | ${vol/1e6:.1f}M | {c['module_scores']['m2_price_vol']} | Module 2 |",
        f"| **ATR14** | {atr_str} | {c['module_scores']['m3_trend']//2} | Module 3（趋势） |",
        f"| **EMA20/50** | {ema20_str} / {ema50_str} | — | 趋势结构: {trend} |",
        f"| **趋势结构** | {trend} | {c['module_scores']['m3_trend']} | Module 3 |",
        f"| **Alpha count24h** | {count24h:,} | {c['module_scores']['m4_alpha']} | Module 4（社区） |",
        f"| **市场环境** | {meta['regime']} | {c['module_scores']['m5_regime']} | Module 5 |",
        f"| **安全评分** | — | {c['module_scores']['m1_safety']} | Module 1（Binance） |",
    ]
    if gmgn_extra:
        report_lines.append(gmgn_extra)

    report_lines += [
        "",
        "**命中规则**：",
    ]
    for rule in c["hit_rules"][:5]:
        report_lines.append(f"- ✅ {rule}")
    for rule in c["miss_rules"][:3]:
        report_lines.append(f"- ❌ {rule}")

    if c["missing_fields"]:
        report_lines.append(f"- ⚠️ 缺失数据: {', '.join(c['missing_fields'])}（已跳过，不阻断评分）")

    report_lines += [
        "",
        f"**入场参考**：{price} | **止损**：{stop_loss} | **目标**：{target}",
        f"**仓位建议**：{c['position_size']}",
        "",
    ]

# 拒绝区
if all_rejected:
    report_lines += [
        "## ❌ 安全否决区",
        "",
        "| 币种 | 拒绝原因 |",
        "|---|---|",
    ]
    for s in all_rejected[:5]:
        reason = "; ".join(s["miss_rules"]) if s["miss_rules"] else "Binance无数据"
        report_lines.append(f"| {s['name']} | {reason} |")

report_lines += [
    "",
    "## 📋 评分模型说明（Phase 1.8 — GMGN增强版）",
    "",
    "### 六大模块评分体系（含 GMGN 增强）",
    "",
    "| 模块 | 满分 | 核心指标 | 说明 |",
    "|---|---|---:|---|",
    "| Module 1: 安全 | 25+GMGN | 成交额/Binance可用/rug_ratio | Phase 1.8 新增 GMGN 链上安全否决（rug>0.3/wash_trading/top10>60%）|",
    "| Module 2: 量价 | 35 | 价格变动/成交额/ATR | 对齐 Obsidian 量价持仓模块 |",
    "| Module 3: 趋势结构 | 25 | EMA20/50/AATR | 对齐 Obsidian ATR+EMA 趋势判断 |",
    "| Module 4: 社交叙事 | 20 | Binance Alpha count24h | 对齐 Obsidian 社交叙事模块 |",
    "| Module 5: 市场环境 | 10 | BTC方向 | 对齐 Obsidian 市场环境模块 |",
    "| Module 6: 资金费率 | 20+GMGN | 费率正负/smart_degen_count | Phase 1.8 新增 GMGN 聪明钱计数加成 |",
    "| GMGN 聪明钱加成 | +23 | smart_degen≥5/≥3/≥1, renowned≥3/≥1 | Phase 1.8 GMGN Chain层信号 |",
    "",
    "### 数据可用性说明（Phase 1.8）",
    "",
    "| 数据 | 状态 | 解决方案 |",
    "||:---:|---|",
    "| ATR14 | ✅ 可获取 | Binance K线计算 |",
    "| EMA20/50 | ✅ 可获取 | Binance K线计算 |",
    "| 资金费率 | ✅ 可获取 | Binance premiumIndex |",
    "| Alpha count24h | ✅ 可获取 | binance-cli alpha token-list |",
    "| GMGN trending (SOL/BSC) | ✅ 可获取 | gmgn-cli market trending |",
    "| GMGN 链上安全数据 | ✅ 可获取 | gmgn-cli (rug_ratio/wash_trading/top10) |",
    "| GMGN 聪明钱计数 | ✅ 可获取 | gmgn-cli (smart_degen_count/renowned_count) |",
    "| GMGN Pump.fun 新代币 | ✅ 可获取 | gmgn-cli market trenches |",
    "| GMGN 实时聪明钱信号 | ✅ 可获取 | gmgn-cli market signal |",
    "| LP锁定比例 | ⚠️ GMGN提供 | 用 GMGN 安全数据间接判断 |",
    "| 前十持仓集中度 | ✅ GMGN提供 | top_10_holder_rate |",
    "| 持有人增长率 | ⚠️ GMGN提供部分 | holder_count |",
    "| 聪明钱净流入明细 | ⚠️ GMGN提供 | gmgn-track wallet |",
    "| 合约高危权限 | ⚠️ GMGN提供部分 | rug_ratio 替代 |",
    "",
    "### 信号等级",
    "",
    "| 等级 | 评分 | 操作 |",
    "|---|---|---|",
    "| 🏆极强 | 85+ | 优先入场，5%资金/5x |",
    "| ⭐强 | 65-84 | 入场，3-5%资金/5x |",
    "| 中 | 45-64 | 轻仓观察，1-2%资金/3x |",
    "| 🔶弱 | 30-44 | 观望，仅供参考 |",
    "| ❌无效 | <30 | 过滤不输出 |",
    "",
    "*⚠️ 本报告仅供参考，不构成投资建议。DYOR！*",
    "",
    "---",
    f"*数据路径：{SCAN_DIR}/*",
    f"*Phase 1.8 — GMGN Chain层增强版 {datetime.now().strftime('%Y-%m-%d')}*",
]

report_path = os.path.join(SCAN_DIR, "report.md")
with open(report_path, "w") as f:
    f.write("\n".join(report_lines))

print("=== 妖币雷达 Phase 1.8 扫描完成 ===")
print("目录: " + SCAN_DIR)
print("报告: " + report_path)
print("")
print("🏆 机会队列 TOP" + str(len(top8)) + ":")
for i, c in enumerate(top8[:8]):
    dir_em = "🟢" if c["direction"]=="long" else "🔴"
    m = c["meta"]
    gmgn_tag = (c["meta"].get("gmgn") or {}).get("gmgn_tag", "")
    tag_str = f" [{gmgn_tag}]" if gmgn_tag and gmgn_tag != "⚪ 无GMGN数据" else ""
    print(f"  {medals[i]} {c['name']} {dir_em}{c['direction']} 评分:{c['total']} {c['grade_label']}{tag_str}")
    print(f"     price=${m['price']:.4g} chg={m['chg']:+.1f}% FR={m['fr']:+.4f}% ATR={m['atr_pct']*100:.2f}% trend={m['trend']} count24h={m['count24h']:,}")
if gmgn_key and gmgn_sol_pass:
    print(f"")
    print("🚀 GMGN Chain层 聪明钱共振代币:")
    for i, t in enumerate(gmgn_sm共振[:5]):
        print(f"  {medals[i]} {t['symbol']} SM{t['smart_degen_count']}KOL{t['renowned_count']} chg={t['chg1h']:+.1f}% {t['gmgn_tag']}")
