#!/usr/bin/env python3
"""
妖币雷达 Phase 1.9 — Skill Orchestrator 版
用法: python3 ~/.hermes/skills/meme-coin-radar/scripts/auto-run.py
数据输出: ~/meme-radar/scan_YYYYMMDD_HHMMSS/

Phase 1.9 核心改动（Skill Orchestrator 重构）:
  - 数据获取全部通过 skill_dispatcher.py，不再直接调 REST/npx
  - Step 0/1  → okx-cex-market (okx market ticker / tickers)
  - Step 0.5   → binance (binance-cli alpha token-list)
  - Step 2     → binance (binance-cli futures-usds kline/funding/ticker)
  - Step G1/G2 → gmgn-market (npx gmgn-cli market trending)
  - Step G3     → gmgn-market + trading-signal (参考 Binance Smart Money)
  - Step G4     → gmgn-market (npx gmgn-cli market trenches)
  - 评分引擎和报告生成保持不变

Skill 映射详见: skill_dispatcher.py 顶部注释
"""

import os, json, time
from datetime import datetime
from skill_dispatcher import (
    okx_btc_status, okx_swap_tickers, okx_funding_rate,
    binance_alpha, binance_ticker, binance_funding, binance_klines,
    gmgn_trending, gmgn_signal, gmgn_trenches, gmgn_security_score,
    binance_smartmoney_signals, batch_binance, load_gmgn_key,
)

# ══════════════════════════════════════════════
# 目录初始化
# ══════════════════════════════════════════════
DATA_DIR = os.path.expanduser("~/meme-radar")
os.makedirs(DATA_DIR, exist_ok=True)
TS = datetime.now().strftime("%Y%m%d_%H%M%S")
SCAN_DIR = os.path.join(DATA_DIR, "scan_" + TS)
os.makedirs(SCAN_DIR, exist_ok=True)

def save(name, content):
    path = os.path.join(SCAN_DIR, name)
    with open(path, "w") as f:
        f.write(content)
    return path

# ══════════════════════════════════════════════
# ATR / EMA 计算（同 Phase 1.8，无变化）
# ══════════════════════════════════════════════
def calc_ema(prices, period):
    if not prices or len(prices) < period:
        return None
    k = 2 / (period + 1)
    ema = sum(prices[:period]) / period
    for p in prices[period:]:
        ema = p * k + ema * (1 - k)
    return ema

def calc_atr14(klines):
    if not klines or len(klines) < 15:
        return None
    trs = []
    for i in range(1, len(klines)):
        high, low, prev_close = klines[i][1], klines[i][2], klines[i-1][3]
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
    return sum(trs[-14:]) / 14 if len(trs) >= 14 else None

def calc_trend_structure(price, ema20, ema50):
    if ema20 is None or ema50 is None:
        return "unknown"
    if price > ema20 > ema50:
        return "bullish"
    elif ema50 > price > ema20:
        return "weak_recovery"
    elif ema20 > price > ema50:
        return "caution"
    elif ema50 > ema20 > price:
        return "bearish"
    elif price >= ema50 and price <= ema20:
        return "below_ema20"
    return "unknown"

# ══════════════════════════════════════════════
# 评分引擎（Phase 1.8 版本，无变化）
# ══════════════════════════════════════════════
def grade(score):
    if   score >= 85: return "🏆极强", "5%总资金/5x杠杆"
    elif score >= 65: return "⭐强",   "3-5%总资金/5x杠杆"
    elif score >= 45: return "中",    "1-2%总资金/3x杠杆"
    else:             return "🔶弱",  "不建议开仓"

medals = ["🥇","🥈","🥉","4.","5.","6.","7.","8."]

def build_trade_plan(result):
    """把评分结果转换成可执行的合约建议。"""
    meta = result.get("meta", {})
    price = float(meta.get("price") or 0)
    atr_pct = meta.get("atr_pct")
    total = int(result.get("total") or 0)
    direction = result.get("direction")

    if price <= 0 or direction not in ("long", "short"):
        return None

    base_risk = atr_pct * 0.8 if atr_pct is not None else 0.05
    risk_pct = min(max(base_risk, 0.035), 0.10)
    entry_buffer = min(max(risk_pct * 0.35, 0.008), 0.025)
    tp1_pct = max(risk_pct * 1.6, 0.05)
    tp2_pct = max(risk_pct * 2.4, 0.08)

    if direction == "long":
        entry_low = price * (1 - entry_buffer)
        entry_high = price * (1 + entry_buffer * 0.35)
        stop_loss = price * (1 - risk_pct)
        take_profit_1 = price * (1 + tp1_pct)
        take_profit_2 = price * (1 + tp2_pct)
    else:
        entry_low = price * (1 - entry_buffer * 0.35)
        entry_high = price * (1 + entry_buffer)
        stop_loss = price * (1 + risk_pct)
        take_profit_1 = price * (1 - tp1_pct)
        take_profit_2 = price * (1 - tp2_pct)

    quality_flags = []
    if meta.get("fr", 0) == 0:
        quality_flags.append("funding_weak")
    if atr_pct is None:
        quality_flags.append("no_atr")
    if meta.get("count24h", 0) <= 0:
        quality_flags.append("no_alpha")

    actionable = total >= 45 and "no_atr" not in quality_flags
    setup_label = "ready" if actionable else "watch"

    return {
        "setup_label": setup_label,
        "entry_low": entry_low,
        "entry_high": entry_high,
        "stop_loss": stop_loss,
        "take_profit_1": take_profit_1,
        "take_profit_2": take_profit_2,
        "risk_pct": risk_pct,
        "quality_flags": quality_flags,
    }

def score_phase18(c, ticker, funding, alpha, klines, btc_dir, missing_fields, gmgn_token=None):
    """Phase 1.9 六大模块评分 — 数据来自 skill_dispatcher"""
    ticker = ticker or {}
    funding = funding or {}
    alpha   = alpha   or {}

    chg      = ticker.get("chg24h", 0.0)
    price    = ticker.get("price", 0.0)
    vol      = ticker.get("volume", 0.0)   # USDT
    fr       = funding.get("fundingRate_pct", 0.0) if funding else 0.0
    count24h = alpha.get("count24h", 0)

    # ── 趋势指标 ──
    ema20 = ema50 = atr14 = atr_pct = trend_struct = None
    if klines:
        closes = [k[3] for k in klines]
        ema20  = calc_ema(closes, 20)
        ema50  = calc_ema(closes, 50)
        atr14  = calc_atr14(klines)
        if price > 0 and atr14:
            atr_pct = atr14 / price
        if ema20 and ema50:
            trend_struct = calc_trend_structure(price, ema20, ema50)

    # ══════════════════════════════════════════
    # Module 1: 安全与流动性（0-25分 + GMGN安全否决层）
    # ══════════════════════════════════════════
    m1 = 0
    reject = False
    reasons = []

    if vol < 5e6:
        reject = True
        reasons.append("成交额<$5M，疑似土狗")
    elif vol < 20e6:
        m1 += 3
    else:
        m1 += 8

    if funding:
        m1 += 8
    elif ticker:
        m1 += 4

    if vol >= 100e6: m1 += 5
    elif vol >= 50e6: m1 += 3
    if fr > 0 and vol >= 100e6: m1 += 4

    # GMGN 链上安全否决层
    gmgn_meta = {}
    if gmgn_token:
        sec = gmgn_security_score(gmgn_token)
        gmgn_meta = {
            "rug_ratio": sec.get("rug_ratio"),
            "is_wash_trading": sec.get("is_wash_trading"),
            "top_10_holder_rate": sec.get("top_10_holder_rate"),
            "smart_degen_count": sec.get("smart_degen_count", 0),
            "renowned_count": sec.get("renowned_count", 0),
            "gmgn_tag": sec.get("tag", "⚪ 无GMGN数据"),
        }
        if sec.get("reject"):
            reject = True
            reasons.append(f"GMGN安全否决: {sec.get('reason','')}")
        else:
            m1 += min(sec.get("bonus", 0), 12)  # GMGN 安全加成上限 12 分

    if reject:
        return {
            "decision": "reject", "total": 0, "direction": "none",
            "grade_label": "❌拒绝", "position_size": "不交易",
            "module_scores": {"m1_safety": m1, "m2": 0, "m3": 0, "m4": 0, "m5": 0, "m6": 0},
            "hit_rules": [], "miss_rules": ["安全否决: " + "; ".join(reasons)],
            "missing_fields": list(set(missing_fields)),
            "meta": {"gmgn": gmgn_meta},
        }

    # ══════════════════════════════════════════
    # Module 2: 量价与持仓（0-35分）
    # ══════════════════════════════════════════
    m2 = 0
    if atr_pct is not None:
        m2 += 6 if atr_pct >= 0.08 else (3 if atr_pct >= 0.05 else 0)
    if vol >= 500e6: m2 += 10
    elif vol >= 200e6: m2 += 6
    elif vol >= 100e6: m2 += 3
    abs_chg = abs(chg)
    if chg >= 0:
        m2 += 6 if chg >= 30 else (4 if chg >= 15 else (2 if chg >= 5 else 0))
    else:
        m2 += 6 if abs_chg >= 20 else (4 if abs_chg >= 10 else (2 if abs_chg >= 5 else 0))
    if trend_struct == "bullish": m2 += 5
    elif trend_struct == "weak_recovery": m2 += 2
    elif trend_struct == "bearish" and chg < 0: m2 += 3
    if chg > 3 and vol >= 50e6: m2 += 3

    # ══════════════════════════════════════════
    # Module 3: 趋势结构（0-25分）
    # ══════════════════════════════════════════
    m3 = 0
    if trend_struct == "bullish": m3 += 12
    elif trend_struct == "weak_recovery": m3 += 6
    elif trend_struct == "bearish": m3 += 8
    if atr_pct is not None:
        m3 += 8 if atr_pct >= 0.12 else (5 if atr_pct >= 0.08 else (2 if atr_pct >= 0.04 else 0))
    else:
        missing_fields.append("atr14")

    # ══════════════════════════════════════════
    # Module 4: 社交与叙事（0-20分，Binance Alpha）
    # 数据来源: binance-alpha (binance-cli alpha token-list)
    # ══════════════════════════════════════════
    m4 = 0
    if count24h > 0:
        m4 += 10 if count24h >= 100000 else (6 if count24h >= 50000 else (3 if count24h >= 20000 else 1))
        if count24h >= 100000 and abs(chg) >= 5: m4 += 5
        if count24h >= 50000 and abs_chg < 3: m4 += 3   # 酝酿中
    else:
        missing_fields.append("alpha_count24h")

    # ══════════════════════════════════════════
    # Module 5: 市场环境（0-10分）
    # 数据来源: okx-btc-status (okx market ticker BTC-USDT-SWAP)
    # ══════════════════════════════════════════
    m5 = 7 if btc_dir == "up" else (0 if btc_dir == "down" else 4)
    regime = "risk_on" if btc_dir == "up" else ("risk_off" if btc_dir == "down" else "neutral")

    # ══════════════════════════════════════════
    # Module 6: 资金费率（0-20分 + GMGN聪明钱加成）
    # 数据来源: binance-funding (binance-cli futures-usds get-funding-rate-info)
    # ══════════════════════════════════════════
    m6 = 0
    if fr > 0:
        m6 = 15 if fr >= 2 else (10 if fr >= 1 else (6 if fr >= 0.5 else (3 if fr >= 0.2 else 0)))
    elif fr < 0:
        m6 = 15 if fr <= -0.5 else (10 if fr <= -0.2 else (6 if fr <= -0.1 else 2))
    else:
        m6 = 1

    total = m1 + m2 + m3 + m4 + m5 + m6
    total = min(total, 100)

    # 共振加成
    if fr > 0.5 and chg < -5 and count24h > 30000: total += 8
    if chg < -10 and fr < -0.1: total += 10
    total = min(total, 100)

    # GMGN 聪明钱加成
    sm_count = gmgn_meta.get("smart_degen_count", 0)
    kol_count = gmgn_meta.get("renowned_count", 0)
    if sm_count >= 5: total = min(total + 5, 100)
    if sm_count >= 1: missing_fields.append(f"gmgn_smartmoney_sm{sm_count}")

    # 方向判定
    short_s, long_s = 0, 0
    if fr > 0.5: short_s += m6 * 1.5
    elif fr < -0.2: long_s += m6 * 1.5
    if chg < -5: short_s += m2 * 0.8
    elif chg > 5: long_s += m2 * 0.8
    if trend_struct in ("bearish", "below_ema20") and chg < 0: short_s += m3
    elif trend_struct == "bullish" and chg > 0: long_s += m3
    direction = "short" if short_s > long_s else ("long" if long_s > short_s else ("short" if fr > 0 else "long"))

    gl, ps = grade(total)

    # 命中规则
    hit = []
    miss = []
    if fr > 0.5: hit.append(f"资金费率>{0.5}%，利于做空")
    elif fr > 0: miss.append("资金费率<0.5%，做空信号弱")
    if fr < -0.1: hit.append("资金费率<-0.1%，利于做多")
    if abs(chg) >= 10: hit.append(f"价格异动|{chg:.1f}%|显著")
    if count24h >= 50000: hit.append(f"Alpha count24h={count24h:,} 社区活跃")
    elif count24h == 0: miss.append("无Alpha社区数据")
    if trend_struct == "bullish": hit.append("趋势结构: EMA多头排列")
    elif trend_struct == "bearish": hit.append("趋势结构: EMA空头排列")
    if atr_pct and atr_pct >= 0.08: hit.append(f"ATR波动率: {atr_pct*100:.1f}% 有足够空间")
    if vol >= 100e6: hit.append("成交额>$100M 流动性良好")
    elif vol < 20e6: miss.append("成交额<$20M 流动性不足")

    return {
        "decision": "watchlist" if total >= 30 else "reject",
        "total": min(total, 100),
        "direction": direction,
        "grade_label": gl,
        "position_size": ps,
        "module_scores": {"m1_safety": m1, "m2": m2, "m3": m3, "m4": m4, "m5": m5, "m6": m6},
        "hit_rules": hit,
        "miss_rules": miss,
        "missing_fields": list(set(missing_fields)),
        "risk_notes": [],
        "meta": {
            "atr_pct": atr_pct, "trend": trend_struct,
            "ema20": ema20, "ema50": ema50, "price": price,
            "vol": vol, "fr": fr, "chg": chg, "count24h": count24h,
            "regime": regime, "gmgn": gmgn_meta,
            "ticker_source": ticker.get("source", "binance") if ticker else "",
            "funding_source": funding.get("source", "binance") if funding else "",
            "kline_source": (ticker.get("source", "binance") if ticker else "binance") if klines else "",
        },
    }

# ══════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════
print("=== 妖币雷达 Phase 1.9 扫描（Skill Orchestrator）===")
print(f"时间: {TS}")

# ─── Step 0: BTC 大盘（okx-cex-market）─────────────
print("[0] BTC 大盘... (okx-cex-market: okx market ticker)")
btc = okx_btc_status()
save("00_btc_status.json", json.dumps(btc, indent=2, default=str))
btc_dir = btc.get("direction", "neutral")
btc_price = btc.get("price", 0)
btc_chg = btc.get("chg24h_pct", 0)
btc_source = btc.get("source", "okx-cex-market")
arrow = "↑" if btc_dir == "up" else ("↓" if btc_dir == "down" else "横")
大盘判断 = "适合做多" if btc_dir == "up" else ("适合做空" if btc_dir == "down" else "多空均可")
print(f"  BTC=${btc_price} chg={btc_chg:+.2f}% [{btc_dir}]")

# ─── Step 0.5: Binance Alpha（binance skill）───────
print("[0.5] Binance Alpha 社区活跃度... (binance: binance-cli alpha token-list)")
alpha_dict = binance_alpha()
save("04_binance_alpha.json", json.dumps(alpha_dict, indent=2))
top_alpha = sorted(alpha_dict.items(), key=lambda x: x[1]["count24h"], reverse=True)[:20]
print(f"  Alpha: 获取到 {len(alpha_dict)} 个代币的社区数据")
for sym, d in top_alpha[:5]:
    print(f"    {sym}: tx24h={d['count24h']:,} chg={d['pct']:+.1f}%")

# ─── Step G1/G2: GMGN Chain层扫描（gmgn-market）───
print("[G1/G2] GMGN Chain层扫描... (gmgn-market: npx gmgn-cli)")
gmgn_key_present = bool(load_gmgn_key())
gmgn_sol_trending = gmgn_trending(chain="sol", interval="1h", limit=20)
gmgn_bsc_trending = gmgn_trending(chain="bsc", interval="1h", limit=20)
gmgn_signals = gmgn_signal(chain="sol", limit=30)
gmgn_trenches_sol = gmgn_trenches(chain="sol", token_type="new_creation", limit=20)

save("05_gmgn_sol_trending.json",  json.dumps(gmgn_sol_trending, indent=2, default=str, ensure_ascii=False))
save("06_gmgn_bsc_trending.json",  json.dumps(gmgn_bsc_trending, indent=2, default=str, ensure_ascii=False))
save("07_gmgn_signals.json",       json.dumps(gmgn_signals,      indent=2, default=str, ensure_ascii=False))
save("08_gmgn_trenches_sol.json",  json.dumps(gmgn_trenches_sol, indent=2, default=str, ensure_ascii=False))

gmgn_sol_pass, gmgn_sol_reject = [], []
for t in gmgn_sol_trending:
    sec = gmgn_security_score(t)
    sym = t.get("symbol", "")
    if not sec.get("reject"):
        gmgn_sol_pass.append({
            "symbol": sym, "name": t.get("name", ""), "chain": "sol",
            "address": t.get("address", ""),
            "price": float(t.get("price") or 0),
            "chg1h": float(t.get("price_change_percent1h") or 0),
            "vol": float(t.get("volume") or 0),
            "liquidity": float(t.get("liquidity") or 0),
            "holders": int(t.get("holder_count") or 0),
            "smart_degen_count": sec.get("smart_degen_count", 0),
            "renowned_count": sec.get("renowned_count", 0),
            "rug_ratio": sec.get("rug_ratio"),
            "top10": sec.get("top_10_holder_rate"),
            "gmgn_tag": sec.get("tag"),
            "bonus": sec.get("bonus", 0),
        })
    else:
        gmgn_sol_reject.append({"symbol": sym, "reason": sec.get("reason", "")})

gmgn_sm共振 = sorted([t for t in gmgn_sol_pass if t["smart_degen_count"] >= 3],
                     key=lambda x: (x["smart_degen_count"], x["chg1h"]), reverse=True)
print(f"  GMGN SOL: 安全通过={len(gmgn_sol_pass)}, 拒绝={len(gmgn_sol_reject)}, 聪明钱共振={len(gmgn_sm共振)}")

if not gmgn_key_present:
    gmgn_status = "missing_key"
elif gmgn_sol_trending:
    gmgn_status = "ok"
elif gmgn_sol_reject:
    gmgn_status = "all_rejected"
else:
    gmgn_status = "fetch_failed"

# ─── Step 1: OKX 全量 SWAP Tickers（okx-cex-market）─────
print("[1] 全量 SWAP tickers... (okx-cex-market: okx market tickers SWAP)")
all_tickers = okx_swap_tickers()
save("01_all_tickers.json", json.dumps(all_tickers, indent=2, default=str))
print(f"  解析到 {len(all_tickers)} 个 USDT-M SWAP")

# ─── Step 2: Binance 批量数据（binance skill）─────
all_tickers.sort(key=lambda x: x["chg24h_pct"], reverse=True)
anomaly_syms = [c["symbol"] for c in all_tickers[:20] + all_tickers[-20:]]
alpha_top_syms = [sym for sym, _ in top_alpha[:15]]
key_coins = ["BTC","ETH","SOL","ZEC","HYPE","BNB","DOGE","PEPE","WIF","SHIB","AAVE",
             "AVAX","LINK","UNI","ARB","OP","INJ","SEI","TIA","SUI","APT","NEAR","FTM"]
priority_groups = [
    key_coins[:12],
    anomaly_syms,
    alpha_top_syms,
    key_coins[12:],
]
check_coins = []
seen_coins = set()
for group in priority_groups:
    for symbol in group:
        if symbol in seen_coins:
            continue
        seen_coins.add(symbol)
        check_coins.append(symbol)

print(f"[2] Binance batch ({len(check_coins)} coins)... (binance: binance-cli futures-usds)")
bnc_results = batch_binance(check_coins)
save("02_binance_batch.json", json.dumps({
    k: {"ticker": v["ticker"], "funding": v["funding"], "has_klines": v["klines"] is not None}
    for k, v in bnc_results.items()
}, indent=2, default=str))

# ─── GMGN → Binance 符号映射 ────────────────────
gmgn_addr_to_sym = {}
for t in gmgn_sol_trending + gmgn_bsc_trending:
    addr, sym = t.get("address", ""), t.get("symbol", "").upper()
    if addr and sym:
        gmgn_addr_to_sym[addr] = sym
        gmgn_addr_to_sym[sym] = t

# ─── Step 3: 六大模块评分 ──────────────────────────
print("[3] 六大模块评分...")
scored = []
for c in check_coins:
    r = bnc_results.get(c, {})
    ticker   = r.get("ticker")
    funding  = r.get("funding")
    klines   = r.get("klines")
    alpha    = alpha_dict.get(c.upper(), {})

    if ticker is None and funding is None:
        print(f"  {c}: Binance无数据，跳过")
        continue

    gmgn_t = gmgn_addr_to_sym.get(c.upper(), {})
    result = score_phase18(c, ticker, funding, alpha, klines, btc_dir, [], gmgn_token=gmgn_t)
    result["name"] = c
    result["trade_plan"] = build_trade_plan(result)
    scored.append(result)

valid = [s for s in scored if s["decision"] != "reject"]
valid.sort(key=lambda x: x["total"], reverse=True)
top8 = valid[:8]
recommendations = [
    s for s in valid
    if s.get("trade_plan", {}).get("setup_label") == "ready"
][:3]
all_rejected = [s for s in scored if s["decision"] == "reject"]
print(f"  候选总数={len(scored)}, 有效={len(valid)}, 拒绝={len(all_rejected)}")
for s in top8[:3]:
    m = s["module_scores"]
    print(f"  {s['name']}: 总={s['total']} | 安={m['m1_safety']} 量={m['m2']} 趋={m['m3']} 社={m['m4']} 环={m['m5']} 费={m['m6']} → {s['direction']}")

# ══════════════════════════════════════════════
# 报告生成（Phase 1.9 版本）
# ══════════════════════════════════════════════
report_lines = [
    "# 🦊 妖币雷达 Phase 1.9 扫描报告（Skill Orchestrator）",
    f"> 扫描时间：{TS}",
    "> **Skill Orchestrator 架构**：所有数据通过 Hermes Skill 接口获取",
    "> - Step 0/1: **okx-cex-market** (okx market ticker / tickers)",
    "> - Step 0.5: **binance** (binance-cli alpha token-list)",
    "> - Step 2: **binance** (binance-cli futures-usds kline/funding/ticker)",
    "> - Step G1/G2: **gmgn-market** (npx gmgn-cli market trending)",
    "> - Step G3: **gmgn-market** + **trading-signal** (参考 Binance Smart Money)",
    "> - Step G4: **gmgn-market** (npx gmgn-cli market trenches)",
    "",
    "## 📊 大盘环境",
    "",
    "| 指标 | 数值 | 方向 | 数据来源 |",
    "|---|---:|---|---|",
    f"| BTC 价格 | ${btc_price:.2f} | {arrow} | {btc_source} |",
    f"| BTC 24h涨跌 | {btc_chg:+.2f}% | — | {btc_source} |",
    f"| 市场判断 | {大盘判断} | — | {btc_source} |",
    "",
]

report_lines += [
    "## 🎯 合约建议",
    "",
]
if recommendations:
    report_lines += [
        "| 排名 | 币种 | 方向 | 入场区间 | 止损 | 止盈1 | 止盈2 | 仓位建议 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for i, item in enumerate(recommendations, 1):
        plan = item["trade_plan"]
        direction_label = "🟢 做多" if item["direction"] == "long" else "🔴 做空"
        report_lines.append(
            f"| {i} | **{item['name']}** | {direction_label} | "
            f"${plan['entry_low']:.6g} - ${plan['entry_high']:.6g} | "
            f"${plan['stop_loss']:.6g} | ${plan['take_profit_1']:.6g} | "
            f"${plan['take_profit_2']:.6g} | {item['position_size']} |"
        )

    report_lines.append("")
    for item in recommendations:
        report_lines.append(f"### {item['name']} {('做多' if item['direction'] == 'long' else '做空')}")
        report_lines.append("")
        for rule in item["hit_rules"][:4]:
            report_lines.append(f"- ✅ {rule}")
        if item["miss_rules"]:
            report_lines.append(f"- ⚠️ 风险: {item['miss_rules'][0]}")
        report_lines.append("")
else:
    report_lines += [
        "> ⚠️ 本次没有满足“合约可执行建议”门槛的币种。",
        "> 进入建议区至少需要：总分 >= 45，且价格、funding、ATR 数据可用。",
        "",
    ]

# GMGN Chain层
if gmgn_sol_pass:
    report_lines += [
        "## 🚀 GMGN Chain层机会板块（Layer 0 — 非Binance合约）",
        "",
        "### 🟢 聪明钱共振代币（GMGN smart_degen_count ≥ 3）",
        "",
        "| 评级 | 代币 | Chain | 价格 | 1h涨跌 | 聪明钱 | KOL | Rug | GMGN信号 |",
        "|---|---|---|---|---:|---:|---:|---:|---|",
    ]
    for t in gmgn_sm共振[:5]:
        rug = f"{t['rug_ratio']:.2f}" if t.get("rug_ratio") is not None else "N/A"
        tag = t["gmgn_tag"] or "⚪"
        report_lines.append(
            f"| ⭐ | **{t['symbol']}** | SOL | ${t['price']:.6g} | **{t['chg1h']:+.1f}%** | "
            f"{t['smart_degen_count']} | {t['renowned_count']} | {rug} | {tag} |"
        )

    report_lines += ["", "### 📈 GMGN SOL 热门代币 TOP10（安全过滤后）", "",
                     "| 代币 | 名称 | 价格 | 1h涨跌 | 成交量 | Rug | 聪明钱 | KOL |",
                     "|---|---|---|---:|---:|---:|---:|---:|"]
    for t in gmgn_sol_pass[:10]:
        rug = f"{t['rug_ratio']:.2f}" if t.get("rug_ratio") is not None else "—"
        report_lines.append(
            f"| **{t['symbol']}** | {t['name'][:15]} | ${t['price']:.6g} | {t['chg1h']:+.1f}% | "
            f"${t['vol']/1e6:.1f}M | {rug} | {t['smart_degen_count']} | {t['renowned_count']} |"
        )

    if gmgn_trenches_sol:
        report_lines += ["", "### 🆕 GMGN SOL Pump.fun 新上线代币", "",
                         "| 代币 | 流动性 | 成交量 | Rug | 聪明钱 | KOL |",
                         "|---|---|---|---:|---:|---:|"]
        for t in gmgn_trenches_sol[:8]:
            report_lines.append(
                f"| **{t.get('symbol','')}** | "
                f"${float(t.get('liquidity',0))/1000:.0f}K | "
                f"${float(t.get('volume_1h',0))/1000:.0f}K | "
                f"{float(t.get('rug_ratio',0)):.2f} | "
                f"{int(t.get('smart_degen_count',0))} | "
                f"{int(t.get('renowned_count',0))} |"
            )

    if gmgn_signals:
        report_lines += ["", "### 💰 GMGN 实时聪明钱信号（Smart Degen Buy）", "",
                         "| 时间 | 代币地址 | 触发时市值 | 当前市值 | 信号类型 |",
                         "|---|---:|---:|---:|---|"]
        from datetime import datetime as dt
        for s in gmgn_signals[:8]:
            ts = s.get("trigger_at", 0)
            try:
                t_str = dt.fromtimestamp(ts).strftime("%H:%M") if ts else "N/A"
            except:
                t_str = str(ts)[:8]
            addr = s.get("token_address", "")[:8] + "..."
            mc = s.get("trigger_mc", 0)
            cur = s.get("market_cap", 0)
            stype = s.get("signal_type", "")
            sig_name = {12: "SmartDegenBuy", 13: "PlatformCall"}.get(int(stype), stype)
            report_lines.append(f"| {t_str} | `{addr}` | ${mc/1000:.0f}K | ${cur/1000:.0f}K | {sig_name} |")
elif gmgn_status == "missing_key":
    report_lines += [
        "## 🚀 GMGN Chain层机会板块",
        "> ⚠️ GMGN API Key 未配置（~/.config/gmgn/.env），跳过 Chain层扫描",
    ]
elif gmgn_status == "all_rejected":
    report_lines += [
        "## 🚀 GMGN Chain层机会板块",
        f"> ⚠️ GMGN 数据已获取，但 SOL 热门代币在安全过滤后全部被拒绝。拒绝数：{len(gmgn_sol_reject)}",
    ]
else:
    report_lines += [
        "## 🚀 GMGN Chain层机会板块",
        "> ⚠️ GMGN 已配置，但本次未获取到可用 SOL 热门代币数据；请排查接口返回或 CLI fallback。",
    ]

report_lines += [
    "",
    "## 🔥 社区活跃度 TOP10（Binance Alpha）",
    "",
    "| 排名 | 币种 | count24h（链上交易） | 24h 涨跌 | 数据来源 |",
    "|---|---|---:|---:|---|",
]
for i, (sym, d) in enumerate(top_alpha[:10], 1):
    report_lines.append(f"| {i} | **{sym}** | {d['count24h']:,} | {d['pct']:+.1f}% | binance-alpha |")

report_lines += [
    "",
    "## 🏆 机会队列（Phase 1.9 六大模块评分）",
    "",
    "| 评级 | 币种 | 方向 | 总分 | 安全 | 量价 | 趋势 | 社交 | 环境 | 费率 | 数据来源 |",
    "|---|---|---|---|---:|---:|---:|---:|---:|---:|---|",
]
for c in top8:
    m = c["module_scores"]
    dir_em = "🟢" if c["direction"] == "long" else "🔴"
    base_src = c.get("meta", {}).get("ticker_source") or c.get("meta", {}).get("funding_source") or "binance"
    src = f"{base_src} + gmgn" if c.get("meta", {}).get("gmgn", {}).get("smart_degen_count", 0) else base_src
    report_lines.append(
        f"| {c['grade_label']} | **{c['name']}** | {dir_em}{c['direction']} | **{c['total']}** | "
        f"{m['m1_safety']} | {m['m2']} | {m['m3']} | {m['m4']} | {m['m5']} | {m['m6']} | {src} |"
    )

# 详细信号
report_lines.append("")
for i, c in enumerate(top8[:3]):
    meta = c["meta"]
    dir_em = "🟢做多" if c["direction"] == "long" else "🔴做空"
    price = meta["price"]
    chg = meta["chg"]
    fr = meta["fr"]
    atr = meta["atr_pct"]
    gmgn_meta = meta.get("gmgn", {})
    plan = c.get("trade_plan") or {}
    ticker_source = meta.get("ticker_source", "binance")
    funding_source = meta.get("funding_source", "binance")
    kline_source = meta.get("kline_source", "binance")

    if price > 0:
        if c["direction"] == "long":
            stop_loss, target = f"{price*0.95:.6g}", f"{price*1.15:.6g}"
        else:
            stop_loss, target = f"{price*1.08:.6g}", f"{price*0.85:.6g}"
    else:
        stop_loss = target = "N/A"

    if plan:
        entry_text = f"${plan['entry_low']:.6g} - ${plan['entry_high']:.6g}"
        stop_text = f"${plan['stop_loss']:.6g}"
        tp1_text = f"${plan['take_profit_1']:.6g}"
        tp2_text = f"${plan['take_profit_2']:.6g}"
    else:
        entry_text = str(price)
        stop_text = stop_loss
        tp1_text = target
        tp2_text = None

    report_lines += [
        f"#### {medals[i]} **{c['name']}** — {dir_em} — 评分：**{c['total']}** {c['grade_label']}",
        "",
        "| 指标 | 数值 | 得分 | 数据来源 |",
        "|---|---|---:|---|",
        f"| 当前价格 | ${price:.4g} | — | {ticker_source}-ticker |",
        f"| 24h涨跌 | {chg:+.2f}% | — | {ticker_source}-ticker |",
        f"| 资金费率 | {fr:+.4f}% | {c['module_scores']['m6']} | {funding_source}-funding |",
        f"| ATR14 | {f'{atr*100:.2f}%' if atr is not None else 'N/A'} | {c['module_scores']['m3']//2} | {kline_source}-klines |",
        f"| Alpha count24h | {meta['count24h']:,} | {c['module_scores']['m4']} | binance-alpha |",
        f"| 市场环境 | {meta['regime']} | {c['module_scores']['m5']} | okx-btc-status |",
    ]
    if gmgn_meta.get("gmgn_tag"):
        rug = gmgn_meta.get("rug_ratio")
        top10 = gmgn_meta.get("top_10_holder_rate")
        sm = gmgn_meta.get("smart_degen_count", 0)
        report_lines.append(
            f"| **GMGN安全** | rug={rug}, top10={top10}, SM={sm} | +GMGN | gmgn-market |"
        )

    report_lines.append("")
    for rule in c["hit_rules"][:5]:
        report_lines.append(f"- ✅ {rule}")
    for rule in c["miss_rules"][:3]:
        report_lines.append(f"- ❌ {rule}")
    if c["missing_fields"]:
        report_lines.append(f"- ⚠️ 缺失: {', '.join(c['missing_fields'])}")

    report_lines += [
        "",
        f"**入场** {entry_text}",
        f"**止损** {stop_text}",
        f"**止盈1** {tp1_text}",
        f"**仓位** {c['position_size']}",
        "",
    ]
    if tp2_text:
        report_lines.insert(len(report_lines) - 2, f"**止盈2** {tp2_text}")

if all_rejected:
    report_lines += [
        "## ❌ 安全否决区",
        "",
        "| 币种 | 拒绝原因 |",
        "|---|---|",
    ]
    for s in all_rejected[:5]:
        report_lines.append(f"| {s['name']} | {'; '.join(s['miss_rules']) or 'Binance无数据'} |")

report_lines += [
    "",
    "## 📋 Skill Orchestrator 架构说明",
    "",
    "| Step | 数据内容 | Skill | CLI/API |",
    "|---:|---|---|---|",
    "| 0 | BTC 大盘状态 | okx-cex-market | okx market ticker BTC-USDT-SWAP |",
    "| 0.5 | 社区活跃度 | binance | binance-cli alpha token-list |",
    "| 1 | 全量 SWAP tickers | okx-cex-market | okx market tickers SWAP |",
    "| 2 | Binance ticker/funding/klines | binance | binance-cli futures-usds |",
    "| G1 | GMGN SOL 热门代币 | gmgn-market | npx gmgn-cli market trending |",
    "| G2 | GMGN BSC 热门代币 | gmgn-market | npx gmgn-cli market trending |",
    "| G3 | GMGN 聪明钱信号 | gmgn-market + trading-signal | GMGN API + Binance Web3 REST |",
    "| G4 | GMGN Pump.fun 新代币 | gmgn-market | npx gmgn-cli market trenches |",
    "| 3 | 六大模块评分 | 本地（无外部） | Python 评分引擎 |",
    "",
    "*⚠️ 本报告仅供参考，不构成投资建议。DYOR！*",
    f"*数据路径：{SCAN_DIR}/*",
    f"*Phase 1.9 — Skill Orchestrator {datetime.now().strftime('%Y-%m-%d')}*",
]

report_path = os.path.join(SCAN_DIR, "report.md")
with open(report_path, "w") as f:
    f.write("\n".join(report_lines))

print("=== 妖币雷达 Phase 1.9 扫描完成 ===")
print(f"目录: {SCAN_DIR}")
print(f"报告: {report_path}")
print("")
print("🏆 机会队列 TOP" + str(len(top8)) + ":")
for i, c in enumerate(top8[:8]):
    dir_em = "🟢" if c["direction"] == "long" else "🔴"
    gmgn_tag = (c["meta"].get("gmgn") or {}).get("gmgn_tag", "")
    tag_str = f" [{gmgn_tag}]" if gmgn_tag and gmgn_tag != "⚪ 无GMGN数据" else ""
    print(f"  {medals[i]} {c['name']} {dir_em}{c['direction']} 评分:{c['total']} {c['grade_label']}{tag_str}")
if gmgn_sm共振:
    print(f"🚀 GMGN 聪明钱共振: {', '.join(t['symbol'] for t in gmgn_sm共振[:5])}")
