from __future__ import annotations

from typing import Any

try:
    from .config import Settings
except ImportError:
    from config import Settings


def calc_ema(prices, period):
    if not prices or len(prices) < period:
        return None
    k = 2 / (period + 1)
    ema = sum(prices[:period]) / period
    for price in prices[period:]:
        ema = price * k + ema * (1 - k)
    return ema


def calc_atr14(klines):
    if not klines or len(klines) < 15:
        return None
    trs = []
    for i in range(1, len(klines)):
        high, low, prev_close = klines[i][1], klines[i][2], klines[i - 1][3]
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
    return sum(trs[-14:]) / 14 if len(trs) >= 14 else None


def calc_trend_structure(price, ema20, ema50):
    if ema20 is None or ema50 is None:
        return "unknown"
    if price > ema20 > ema50:
        return "bullish"
    if ema50 > price > ema20:
        return "weak_recovery"
    if ema20 > price > ema50:
        return "caution"
    if ema50 > ema20 > price:
        return "bearish"
    if price >= ema50 and price <= ema20:
        return "below_ema20"
    return "unknown"


def grade(score):
    if score >= 85:
        return "🏆极强", "5%总资金/5x杠杆"
    if score >= 65:
        return "⭐强", "3-5%总资金/5x杠杆"
    if score >= 45:
        return "中", "1-2%总资金/3x杠杆"
    return "🔶弱", "不建议开仓"


def build_trade_plan(result: dict[str, Any]) -> dict[str, Any] | None:
    meta = result.get("meta", {})
    price = float(meta.get("price") or 0)
    atr_pct = meta.get("atr_pct")
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

    setup_label = "ready" if result.get("can_enter") else "watch"
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


def _direction_signal(chg, fr, trend_struct, count24h, sm_count, total, settings: Settings):
    long_bias = 0.0
    short_bias = 0.0
    reasons = []

    if chg >= 5:
        long_bias += 16.0
        reasons.append("24h趋势偏多")
    elif chg <= -5:
        short_bias += 16.0
        reasons.append("24h趋势偏空")

    if fr < -0.2:
        long_bias += 14.0
        reasons.append("负费率支持做多")
    elif fr > 0.5:
        short_bias += 14.0
        reasons.append("正费率支持做空")
    elif fr > 0:
        short_bias += 5.0
    elif fr < 0:
        long_bias += 5.0

    if trend_struct == "bullish":
        long_bias += 14.0
        reasons.append("EMA多头排列")
    elif trend_struct == "bearish":
        short_bias += 14.0
        reasons.append("EMA空头排列")
    elif trend_struct == "weak_recovery":
        long_bias += 8.0
        reasons.append("弱修复结构")
    elif trend_struct == "below_ema20":
        short_bias += 8.0

    if count24h >= 100000:
        if chg >= 0:
            long_bias += 6.0
        else:
            short_bias += 6.0
        reasons.append("社区活跃度很高")
    elif count24h >= 50000:
        if abs(chg) >= 5:
            reasons.append("社区活跃度确认异动")
        if chg >= 0:
            long_bias += 4.0
        else:
            short_bias += 4.0

    if sm_count >= 3:
        long_bias += 6.0
        reasons.append("链上聪明钱参与")
    elif sm_count >= 1:
        long_bias += 3.0

    dominant = "long" if long_bias > short_bias else "short"
    dominant_score = max(long_bias, short_bias)
    bias_gap = abs(long_bias - short_bias)
    confidence = min(100.0, total * 0.65 + dominant_score * 0.35)
    can_enter = (
        total >= settings.min_recommend_score
        and dominant_score >= settings.min_direction_bias
        and bias_gap >= settings.min_direction_gap
    )
    if not can_enter:
        return False, dominant, round(confidence, 2), reasons or ["方向优势不足"]
    return True, dominant, round(confidence, 2), reasons


def score_candidate(
    symbol,
    ticker,
    funding,
    alpha,
    klines,
    btc_dir,
    missing_fields,
    settings: Settings,
    gmgn_token=None,
    gmgn_security_score_fn=None,
):
    ticker = ticker or {}
    funding = funding or {}
    alpha = alpha or {}

    chg = ticker.get("chg24h", 0.0)
    price = ticker.get("price", 0.0)
    vol = ticker.get("volume", 0.0)
    fr = funding.get("fundingRate_pct", 0.0) if funding else 0.0
    count24h = alpha.get("count24h", 0)

    ema20 = ema50 = atr14 = atr_pct = trend_struct = None
    if klines:
        closes = [k[3] for k in klines]
        ema20 = calc_ema(closes, 20)
        ema50 = calc_ema(closes, 50)
        atr14 = calc_atr14(klines)
        if price > 0 and atr14:
            atr_pct = atr14 / price
        if ema20 and ema50:
            trend_struct = calc_trend_structure(price, ema20, ema50)

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

    if vol >= 100e6:
        m1 += 5
    elif vol >= 50e6:
        m1 += 3
    if fr > 0 and vol >= 100e6:
        m1 += 4

    gmgn_meta = {}
    if gmgn_token and gmgn_security_score_fn:
        sec = gmgn_security_score_fn(gmgn_token)
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
            reasons.append(f"GMGN安全否决: {sec.get('reason', '')}")
        else:
            m1 += min(sec.get("bonus", 0), 12)

    if reject:
        return {
            "decision": "reject",
            "total": 0,
            "direction": "none",
            "can_enter": False,
            "confidence": 0.0,
            "entry_reasons": [],
            "grade_label": "❌拒绝",
            "position_size": "不交易",
            "module_scores": {"m1_safety": m1, "m2": 0, "m3": 0, "m4": 0, "m5": 0, "m6": 0},
            "hit_rules": [],
            "miss_rules": ["安全否决: " + "; ".join(reasons)],
            "missing_fields": list(set(missing_fields)),
            "meta": {"gmgn": gmgn_meta},
        }

    m2 = 0
    if atr_pct is not None:
        m2 += 6 if atr_pct >= 0.08 else (3 if atr_pct >= 0.05 else 0)
    if vol >= 500e6:
        m2 += 10
    elif vol >= 200e6:
        m2 += 6
    elif vol >= 100e6:
        m2 += 3
    abs_chg = abs(chg)
    if chg >= 0:
        m2 += 6 if chg >= 30 else (4 if chg >= 15 else (2 if chg >= 5 else 0))
    else:
        m2 += 6 if abs_chg >= 20 else (4 if abs_chg >= 10 else (2 if abs_chg >= 5 else 0))
    if trend_struct == "bullish":
        m2 += 5
    elif trend_struct == "weak_recovery":
        m2 += 2
    elif trend_struct == "bearish" and chg < 0:
        m2 += 3
    if chg > 3 and vol >= 50e6:
        m2 += 3

    m3 = 0
    if trend_struct == "bullish":
        m3 += 12
    elif trend_struct == "weak_recovery":
        m3 += 6
    elif trend_struct == "bearish":
        m3 += 8
    if atr_pct is not None:
        m3 += 8 if atr_pct >= 0.12 else (5 if atr_pct >= 0.08 else (2 if atr_pct >= 0.04 else 0))
    else:
        missing_fields.append("atr14")

    m4 = 0
    if count24h > 0:
        m4 += 10 if count24h >= 100000 else (6 if count24h >= 50000 else (3 if count24h >= 20000 else 1))
        if count24h >= 100000 and abs(chg) >= 5:
            m4 += 5
        if count24h >= 50000 and abs_chg < 3:
            m4 += 3
    else:
        missing_fields.append("alpha_count24h")

    m5 = 7 if btc_dir == "up" else (0 if btc_dir == "down" else 4)
    regime = "risk_on" if btc_dir == "up" else ("risk_off" if btc_dir == "down" else "neutral")

    if fr > 0:
        m6 = 15 if fr >= 2 else (10 if fr >= 1 else (6 if fr >= 0.5 else (3 if fr >= 0.2 else 0)))
    elif fr < 0:
        m6 = 15 if fr <= -0.5 else (10 if fr <= -0.2 else (6 if fr <= -0.1 else 2))
    else:
        m6 = 1

    total = min(m1 + m2 + m3 + m4 + m5 + m6, 100)
    if fr > 0.5 and chg < -5 and count24h > 30000:
        total += 8
    if chg < -10 and fr < -0.1:
        total += 10
    total = min(total, 100)

    sm_count = gmgn_meta.get("smart_degen_count", 0)
    if sm_count >= 5:
        total = min(total + 5, 100)
    if sm_count >= 1:
        missing_fields.append(f"gmgn_smartmoney_sm{sm_count}")

    can_enter, direction, confidence, entry_reasons = _direction_signal(
        chg, fr, trend_struct, count24h, sm_count, total, settings
    )
    gl, ps = grade(total)

    hit = []
    miss = []
    if fr > 0.5:
        hit.append("资金费率>0.5%，利于做空")
    elif fr > 0:
        miss.append("资金费率<0.5%，做空信号弱")
    if fr < -0.1:
        hit.append("资金费率<-0.1%，利于做多")
    if abs(chg) >= 10:
        hit.append(f"价格异动|{chg:.1f}%|显著")
    if count24h >= 50000:
        hit.append(f"Alpha count24h={count24h:,} 社区活跃")
    elif count24h == 0:
        miss.append("无Alpha社区数据")
    if trend_struct == "bullish":
        hit.append("趋势结构: EMA多头排列")
    elif trend_struct == "bearish":
        hit.append("趋势结构: EMA空头排列")
    if atr_pct and atr_pct >= 0.08:
        hit.append(f"ATR波动率: {atr_pct*100:.1f}% 有足够空间")
    if vol >= 100e6:
        hit.append("成交额>$100M 流动性良好")
    elif vol < 20e6:
        miss.append("成交额<$20M 流动性不足")

    return {
        "decision": "watchlist" if total >= settings.min_watch_score else "reject",
        "total": total,
        "direction": direction,
        "can_enter": can_enter,
        "confidence": confidence,
        "entry_reasons": entry_reasons,
        "grade_label": gl,
        "position_size": ps,
        "module_scores": {"m1_safety": m1, "m2": m2, "m3": m3, "m4": m4, "m5": m5, "m6": m6},
        "hit_rules": hit,
        "miss_rules": miss,
        "missing_fields": list(set(missing_fields)),
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
            "regime": regime,
            "gmgn": gmgn_meta,
            "ticker_source": ticker.get("source", "binance") if ticker else "",
            "funding_source": funding.get("source", "binance") if funding else "",
            "kline_source": (ticker.get("source", "binance") if ticker else "binance") if klines else "",
        },
    }
