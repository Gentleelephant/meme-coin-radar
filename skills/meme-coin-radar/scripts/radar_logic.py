from __future__ import annotations

from typing import Any

try:
    from .config import Settings
except ImportError:
    from config import Settings


# ────────────────────────────────────────────────
# Helper: EMA / ATR / Trend
# ────────────────────────────────────────────────
def calc_ema(prices: list[float], period: int) -> float | None:
    if not prices or len(prices) < period:
        return None
    k = 2 / (period + 1)
    ema = sum(prices[:period]) / period
    for price in prices[period:]:
        ema = price * k + ema * (1 - k)
    return ema


def calc_atr14(klines) -> float | None:
    if not klines or len(klines) < 15:
        return None
    trs = []
    for i in range(1, len(klines)):
        high, low, prev_close = klines[i][1], klines[i][2], klines[i - 1][3]
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
    return sum(trs[-14:]) / 14 if len(trs) >= 14 else None


def calc_trend_structure(price, ema20, ema50) -> str:
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


def _klines_meta(klines, price: float) -> dict[str, Any]:
    """Compute EMA, ATR, trend from klines."""
    meta = {"ema20": None, "ema50": None, "atr14": None, "atr_pct": None, "trend": None, "closes": []}
    if not klines:
        return meta
    closes = [k[3] for k in klines]
    meta["closes"] = closes
    ema20 = calc_ema(closes, 20)
    ema50 = calc_ema(closes, 50)
    atr14 = calc_atr14(klines)
    meta["ema20"] = ema20
    meta["ema50"] = ema50
    meta["atr14"] = atr14
    if price > 0 and atr14:
        meta["atr_pct"] = atr14 / price
    if ema20 and ema50:
        meta["trend"] = calc_trend_structure(price, ema20, ema50)
    return meta


# ────────────────────────────────────────────────
# Grades aligned with Obsidian tiers
# ────────────────────────────────────────────────
def grade(score: float) -> tuple[str, str]:
    if score >= 85:
        return "🏆极强", "5%总资金/5x杠杆"
    if score >= 75:
        return "⭐强", "3-5%总资金/5x杠杆"
    if score >= 50:
        return "中", "1-2%总资金/3x杠杆"
    if score >= 30:
        return "🔶弱", "不建议开仓"
    return "❌无效", "不交易"


# ────────────────────────────────────────────────
# Obsidian 7 hard-reject rules
# ────────────────────────────────────────────────
CORE_FIELDS = {"atr14", "trend", "oi", "fundingRate", "volume", "alpha_count24h"}


def _classify_missing(
    ticker: dict | None,
    funding: dict | None,
    alpha: dict | None,
    klines: list | None,
    klines_4h: list | None,
    oi: dict | None,
    tradable: bool = True,
) -> dict[str, str]:
    """
    Classify why each field is missing.
    Returns dict: field -> reason_type
    Reason types:
      - fetch_error: provider returned error/None (retryable)
      - not_supported: symbol not on this venue
      - asset_type: this asset type does not have this field
    """
    reasons: dict[str, str] = {}

    if ticker is None or not ticker:
        reasons["volume"] = "fetch_error"
    if funding is None or not funding:
        if tradable:
            reasons["fundingRate"] = "fetch_error"
        else:
            reasons["fundingRate"] = "asset_type"
    if alpha is None or not alpha:
        reasons["alpha_count24h"] = "fetch_error"
    if klines is None or len(klines) < 15:
        if tradable:
            reasons["atr14"] = "fetch_error"
            reasons["trend"] = "fetch_error"
        else:
            reasons["atr14"] = "asset_type"
            reasons["trend"] = "asset_type"
    if oi is None or oi.get("oi") is None:
        if tradable:
            reasons["oi"] = "fetch_error"
        else:
            reasons["oi"] = "asset_type"

    return reasons


def _hard_reject_check(
    symbol: str,
    ticker: dict | None,
    gmgn_token: dict | None,
    gmgn_sec: dict | None,
    atr_pct: float | None,
    atr_vs_30d: float | None,
) -> tuple[bool, list[str], list[str]]:
    """
    Returns: (reject, reject_reasons, risk_notes)
    """
    reject = False
    reasons: list[str] = []
    risk_notes: list[str] = []

    vol = float(ticker.get("volume") or 0) if ticker else 0.0

    # Rule 1: contract_risk_flags (mintable/blacklist/pausable) AND ownership not renounced
    if gmgn_token:
        crf = gmgn_token.get("contract_risk_flags", [])
        if isinstance(crf, str):
            crf = [f.strip() for f in crf.split(",") if f.strip()]
        dangerous = {"mintable", "blacklist", "pausable"}
        if any(flag in dangerous for flag in crf):
            if not bool(gmgn_token.get("ownership_renounced", False)):
                reject = True
                reasons.append(f"合约高危权限未放弃: {crf}")

    # Rule 2: liquidity < $50K
    if gmgn_token:
        liquidity = float(gmgn_token.get("liquidity") or 0)
        if 0 < liquidity < 50000:
            reject = True
            reasons.append(f"流动性=${liquidity:.0f}<$50K")

    # Rule 3: deployer_holder_ratio > 10%
    if gmgn_token:
        dhr = float(gmgn_token.get("deployer_holder_ratio") or 0)
        if dhr > 0.10:
            reject = True
            reasons.append(f"部署者持仓={dhr:.1%}>10%")

    # Rule 4: top10_holder_ratio > 35%
    top10 = gmgn_sec.get("top_10_holder_rate") if gmgn_sec else None
    if top10 is not None and top10 > 0.35:
        reject = True
        reasons.append(f"前十持仓={top10:.1%}>35%")

    # Rule 5: trading unavailable / extreme slippage — not auto-detectable without simulation
    risk_notes.append("未模拟交易检测滑点（需人工确认）")

    # Rule 6: obvious wash trading
    gmgn_reject = gmgn_sec.get("reject") if gmgn_sec else False
    if gmgn_reject and gmgn_sec.get("is_wash_trading"):
        reject = True
        reasons.append("GMGN标记洗量作弊")

    # Additional heuristic: volume very high but few trades / buyers
    if gmgn_token:
        trades = int(gmgn_token.get("trades_24h") or 0)
        buyers = int(gmgn_token.get("buyers_24h") or 0)
        gmgn_vol = float(gmgn_token.get("volume_24h") or gmgn_token.get("volume") or 0)
        if gmgn_vol > 0 and trades > 0:
            avg_trade = gmgn_vol / trades
            if avg_trade > gmgn_vol * 0.3 and trades < 5:
                reject = True
                reasons.append("成交量与交易笔数严重不匹配，疑似刷量")
        if buyers > 0 and trades > 0 and buyers / trades < 0.05:
            reject = True
            reasons.append("买家数/交易笔数过低，疑似刷量")

    # Rule 7: ATR insufficient (<4%) AND below 30-day average (<0.8x)
    if atr_pct is not None:
        if atr_pct < 0.04:
            if atr_vs_30d is not None and atr_vs_30d < 0.8:
                reject = True
                reasons.append(f"ATR={atr_pct*100:.2f}%不足且低于30日均值({atr_vs_30d:.2f}x)")
            else:
                risk_notes.append(f"ATR={atr_pct*100:.2f}%偏低")

    # Note: CEX perp volume hard reject removed per Obsidian spec.
    # Obsidian uses on-chain liquidity_usd, not CEX volume, for liquidity gating.
    # Binance contract tokens do not have on-chain liquidity metrics; rely on exchange listing status instead.

    return reject, reasons, risk_notes


# ────────────────────────────────────────────────
# 5-Module scoring (Obsidian 25/30/20/15/10)
# ────────────────────────────────────────────────
def _score_safety_liquidity(
    ticker: dict | None,
    funding: dict | None,
    gmgn_sec: dict | None,
) -> int:
    m = 0
    vol = float(ticker.get("volume") or 0) if ticker else 0.0

    # Volume tier (max 8)
    if vol >= 500e6:
        m += 8
    elif vol >= 100e6:
        m += 5
    elif vol >= 20e6:
        m += 3
    elif vol >= 5e6:
        m += 1

    # Exchange listing / funding availability (max 5)
    if funding:
        m += 5
    elif ticker:
        m += 2

    # GMGN on-chain security bonus (max 12, capped by module limit)
    if gmgn_sec and not gmgn_sec.get("reject"):
        tag = gmgn_sec.get("tag", "")
        if "🟢" in tag:
            m += 5
        elif "🟡" in tag:
            m += 2

        rug = gmgn_sec.get("rug_ratio", 1)
        if rug is not None:
            if rug < 0.1:
                m += 4
            elif rug < 0.2:
                m += 2

        top10 = gmgn_sec.get("top_10_holder_rate", 1)
        if top10 is not None:
            if top10 < 0.20:
                m += 4
            elif top10 < 0.35:
                m += 2

        if gmgn_sec.get("dev_hold_rate", 1) is not None and gmgn_sec.get("dev_hold_rate", 1) < 0.10:
            m += 2

    return min(m, 25)


def _score_price_volume_trend(
    ticker: dict | None,
    k1h: dict[str, Any],
    k4h: dict[str, Any] | None,
    chg4h: float | None = None,
    volume_vs_7d: float | None = None,
    risk_notes: list[str] | None = None,
) -> int:
    m = 0
    atr_pct = k1h.get("atr_pct")
    trend_1h = k1h.get("trend")
    vol = float(ticker.get("volume") or 0) if ticker else 0.0
    chg = float(ticker.get("chg24h") or 0) if ticker else 0.0
    abs_chg = abs(chg)
    rn = risk_notes if risk_notes is not None else []

    # Volatility / ATR (max 6)
    if atr_pct is not None:
        if atr_pct >= 0.08:
            m += 6
        elif atr_pct >= 0.05:
            m += 3

    # Volume expansion vs 7d avg (max 10) – preferred metric
    if volume_vs_7d is not None:
        if volume_vs_7d >= 5:
            m += 10
        elif volume_vs_7d >= 3:
            m += 6
        elif volume_vs_7d >= 2:
            m += 3
    else:
        # Fallback to absolute volume tiers when 7d avg unavailable
        if vol >= 500e6:
            m += 8
        elif vol >= 200e6:
            m += 5
        elif vol >= 100e6:
            m += 3
        elif vol >= 50e6:
            m += 1

    # Price strength: combines 24h + 4h momentum (max 6)
    if chg >= 50 and chg4h is not None and chg4h >= 12:
        m += 6
    elif chg >= 25 and chg4h is not None and chg4h >= 5:
        m += 4
    elif abs_chg >= 5:
        m += 2

    # Trend structure (max 6) – bearish gets 0 per Obsidian spec
    if trend_1h == "bullish":
        m += 6
    elif trend_1h == "weak_recovery":
        m += 2
    elif trend_1h in ("caution", "below_ema20"):
        m += 1
    elif trend_1h == "bearish":
        rn.append("逆趋势异动: price_below_ema20_below_ema50")

    # 4H dual timeframe alignment bonus (max 4)
    if k4h:
        trend_4h = k4h.get("trend")
        if trend_4h and trend_1h and trend_4h == trend_1h:
            m += 4

    # Buy pressure confirmation (max 3)
    if chg > 3 and vol >= 50e6:
        m += 3

    return min(m, 30)


def _score_onchain_smart_money(
    funding: dict | None,
    gmgn_sec: dict | None,
    oi_data: dict | None,
    holder_growth: float | None,
) -> int:
    m = 0

    # 1. Smart money inflow (max 8)
    sm_count = int(gmgn_sec.get("smart_degen_count", 0)) if gmgn_sec else 0
    if sm_count >= 5:
        m += 8
    elif sm_count >= 3:
        m += 5
    elif sm_count >= 1:
        m += 2

    # 2. Holder growth (max 6)
    if holder_growth is not None:
        if holder_growth >= 0.25:
            m += 6
        elif holder_growth >= 0.10:
            m += 3
        elif holder_growth >= 0:
            m += 1
    else:
        # Weak fallback using absolute holder count
        holders = int(gmgn_sec.get("holders", 0)) if gmgn_sec else 0
        if holders >= 5000:
            m += 1

    # 3. OI quadrant (max 4, can be negative)
    if oi_data:
        oi_chg = oi_data.get("oi_change_pct", 0)
        price_chg = oi_data.get("price_change_pct", 0)
        oi_up = oi_chg > 0
        price_up = price_chg > 0
        if oi_up and price_up:
            m += 4
        elif oi_up and not price_up:
            m -= 2
        elif not oi_up and price_up:
            m += 2
        elif not oi_up and not price_up:
            m -= 4

    # 4. Funding rate (max 2)
    fr = funding.get("fundingRate_pct", 0.0) if funding else 0.0
    if fr > 0:
        if fr >= 2.0:
            m += 2
        elif fr >= 0.5:
            m += 1
    elif fr < 0:
        if fr <= -0.5:
            m += 2
        elif fr <= -0.2:
            m += 1

    # 5. Buyer/seller dominance (max 2)
    if gmgn_sec:
        buyers = int(gmgn_sec.get("buyers_24h", 0))
        sellers = int(gmgn_sec.get("sellers_24h", 0))
        if sellers > 0 and buyers / sellers >= 1.2:
            m += 2
        elif buyers > sellers:
            m += 1

    return max(min(m, 20), 0)


def _score_social_narrative(alpha: dict | None, chg: float) -> int:
    m = 0
    count24h = alpha.get("count24h", 0) if alpha else 0
    abs_chg = abs(chg)

    if count24h >= 100000:
        m += 6
        if abs_chg >= 5:
            m += 2
    elif count24h >= 50000:
        m += 4
        if abs_chg >= 3:
            m += 2
    elif count24h >= 20000:
        m += 2
    elif count24h > 0:
        m += 1

    # Reserved for Phase 3: social_mentions, kol_count, narrative_tags (max 5)
    # if social_mentions_4h_vs_7d_avg >= 2: m += 3
    # if kol_unique_count_24h >= 3: m += 2

    return min(m, 15)


def _score_market_regime(btc_dir: str, alt_rotation: bool = False) -> int:
    if alt_rotation:
        return 10
    return 7 if btc_dir == "up" else (0 if btc_dir == "down" else 3)


# ────────────────────────────────────────────────
# Direction signal (long/short bias)
# ────────────────────────────────────────────────
def _direction_signal(
    chg: float,
    fr: float,
    trend_struct: str | None,
    count24h: int,
    sm_count: int,
    total: float,
    trend_4h: str | None,
    settings: Settings,
) -> tuple[bool, str, float, list[str]]:
    long_bias = 0.0
    short_bias = 0.0
    reasons: list[str] = []

    # Price momentum
    if chg >= 5:
        long_bias += 16.0
        reasons.append("24h趋势偏多")
    elif chg <= -5:
        short_bias += 16.0
        reasons.append("24h趋势偏空")

    # Funding rate
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

    # Trend structure (1H)
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

    # Dual timeframe check
    if trend_4h:
        if trend_4h == "bullish":
            long_bias += 6.0
            reasons.append("4H趋势偏多")
        elif trend_4h == "bearish":
            short_bias += 6.0
            reasons.append("4H趋势偏空")
        if trend_struct and ((trend_4h == "bullish" and trend_struct not in ("bullish", "weak_recovery"))
                            or (trend_4h == "bearish" and trend_struct not in ("bearish",))):
            # Mild contradiction: reduce the weaker side
            pass

    # Social activity
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

    # Smart money
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


# ────────────────────────────────────────────────
# Trade plan builder (with Obsidian R:R + sizing)
# ────────────────────────────────────────────────
def build_trade_plan(
    result: dict[str, Any],
    equity: float = 0.0,
) -> dict[str, Any] | None:
    meta = result.get("meta", {})
    price = float(meta.get("price") or 0)
    atr_pct = meta.get("atr_pct")
    direction = result.get("direction")

    if price <= 0 or direction not in ("long", "short"):
        return None

    base_risk = atr_pct * 0.8 if atr_pct else 0.05
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

    # Obsidian R:R validation (use entry range midpoint as expected fill)
    mid_entry = (entry_low + entry_high) / 2
    risk_distance = abs(mid_entry - stop_loss)
    reward_distance = abs(take_profit_1 - mid_entry)
    rr = reward_distance / risk_distance if risk_distance > 0 else 0.0

    setup_label = "ready" if result.get("can_enter") else "watch"
    if rr < 1.5:
        setup_label = "watch"
        result["can_enter_rr_blocked"] = True
        result.setdefault("risk_notes", []).append(f"R:R={rr:.2f}<1.5，降级观察")

    # Position sizing per Obsidian formula
    position_size_usd: float | None = None
    position_text = result.get("position_size", "不建议开仓")
    if equity > 0 and risk_distance > 0:
        total_score = result.get("total", 0)
        risk_ratio = 0.03 if total_score >= 85 else (0.02 if total_score >= 75 else 0.01)
        stop_pct = risk_distance / mid_entry if mid_entry > 0 else risk_pct
        position_size_usd = equity * risk_ratio / stop_pct
        leverage = 5 if total_score >= 80 else (3 if total_score >= 65 else 1)
        # Round to clean numbers
        if position_size_usd >= 1000:
            position_size_usd = round(position_size_usd, -2)
        else:
            position_size_usd = round(position_size_usd, 1)
        coins = position_size_usd / price if price > 0 else 0
        position_text = f"建议开仓 ${position_size_usd:,.0f} USDT（约 {coins:.2f} 个币）@ {leverage}x 杠杆"

    quality_flags = []
    if meta.get("fr", 0) == 0:
        quality_flags.append("funding_weak")
    if atr_pct is None:
        quality_flags.append("no_atr")
    if meta.get("count24h", 0) <= 0:
        quality_flags.append("no_alpha")
    if result.get("needs_manual_review"):
        quality_flags.append("needs_review")

    return {
        "setup_label": setup_label,
        "entry_low": entry_low,
        "entry_high": entry_high,
        "stop_loss": stop_loss,
        "take_profit_1": take_profit_1,
        "take_profit_2": take_profit_2,
        "risk_pct": risk_pct,
        "rr": round(rr, 2),
        "position_size_usd": position_size_usd,
        "quality_flags": quality_flags,
    }


# ────────────────────────────────────────────────
# Main scoring entry-point (Obsidian aligned)
# ────────────────────────────────────────────────
def score_candidate(
    symbol: str,
    ticker: dict | None,
    funding: dict | None,
    alpha: dict | None,
    klines: list | None,
    btc_dir: str,
    missing_fields: list[str],
    settings: Settings,
    gmgn_token: dict | None = None,
    gmgn_security_score_fn=None,
    klines_4h: list | None = None,
    klines_1d: list | None = None,
    oi: dict | None = None,
    equity: float = 0.0,
    alt_rotation: bool = False,
    volume_vs_7d: float | None = None,
    tradable: bool = True,
    market_type: str = "cex_perp",
    mapping_confidence: str = "native",
) -> dict[str, Any]:
    ticker = ticker or {}
    funding = funding or {}
    alpha = alpha or {}
    mf = list(missing_fields)  # copy

    chg = float(ticker.get("chg24h", 0.0))
    price = float(ticker.get("price", 0.0))
    vol = float(ticker.get("volume", 0.0))
    fr = float(funding.get("fundingRate_pct", 0.0)) if funding else 0.0
    count24h = alpha.get("count24h", 0) if alpha else 0

    # K-line metadata (1H)
    k1h = _klines_meta(klines, price)
    if k1h["atr_pct"] is None:
        mf.append("atr14")
    if k1h["trend"] is None:
        mf.append("trend")

    # K-line metadata (4H)
    k4h = _klines_meta(klines_4h, price) if klines_4h else None
    if klines_4h and k4h and k4h["trend"] is None:
        mf.append("trend_4h")

    # GMGN security
    gmgn_sec: dict[str, Any] | None = None
    if gmgn_token and gmgn_security_score_fn:
        gmgn_sec = gmgn_security_score_fn(gmgn_token)
    if gmgn_token and not gmgn_sec:
        mf.append("gmgn_security")

    # ATR vs 30d average (placeholder until Phase 3 historical DB)
    atr_vs_30d = None

    # Hard rejects
    reject, reject_reasons, risk_notes = _hard_reject_check(
        symbol, ticker, gmgn_token, gmgn_sec, k1h.get("atr_pct"), atr_vs_30d
    )

    if reject:
        return {
            "symbol": symbol,
            "decision": "reject",
            "total": 0,
            "total_score": 0,
            "direction": "none",
            "can_enter": False,
            "confidence": 0.0,
            "entry_reasons": [],
            "grade_label": "❌拒绝",
            "position_size": "不交易",
            "module_scores": {
                "safety_liquidity": 0,
                "price_volume": 0,
                "onchain_smart_money": 0,
                "social_narrative": 0,
                "market_regime": 0,
                "m1_safety": 0,
                "m2": 0,
                "m3": 0,
                "m4": 0,
                "m5": 0,
                "m6": 0,
            },
            "hard_reject": True,
            "reject_reasons": reject_reasons,
            "hit_rules": [],
            "miss_rules": ["硬否决: " + "; ".join(reject_reasons)],
            "risk_notes": risk_notes,
            "missing_fields": list(set(mf)),
            "needs_manual_review": True,
            "meta": {
                "price": price,
                "vol": vol,
                "atr_pct": k1h.get("atr_pct"),
                "trend": k1h.get("trend"),
                "gmgn": gmgn_sec or {},
            },
        }

    # Compute chg4h from last two 4H closes if available
    chg4h = None
    if klines_4h and len(klines_4h) >= 2:
        try:
            prev_close = float(klines_4h[-2][3])
            last_close = float(klines_4h[-1][3])
            if prev_close > 0:
                chg4h = (last_close - prev_close) / prev_close * 100
        except (IndexError, ValueError, TypeError):
            pass

    # Compute volume_vs_7d from 1d klines if available
    if volume_vs_7d is None and klines_1d and len(klines_1d) >= 8:
        try:
            vols = [float(k[5]) for k in klines_1d[-8:]]  # last 8 days
            if len(vols) >= 8 and vols[-1] > 0:
                avg_7d = sum(vols[:-1]) / 7
                if avg_7d > 0:
                    volume_vs_7d = vols[-1] / avg_7d
        except (IndexError, ValueError, TypeError):
            pass

    # Module scoring
    m1 = _score_safety_liquidity(ticker, funding, gmgn_sec)
    m2 = _score_price_volume_trend(ticker, k1h, k4h, chg4h=chg4h, volume_vs_7d=volume_vs_7d, risk_notes=risk_notes)

    # Holder growth (from GMGN if available)
    holder_growth = None
    if gmgn_sec:
        holder_growth = gmgn_sec.get("holders_growth_24h")
    if holder_growth is None and gmgn_token:
        holder_growth = float(gmgn_token.get("holders_growth_24h") or 0) or None

    # OI data enrichment
    oi_data: dict[str, Any] | None = None
    if oi:
        oi_data = {
            "oi": oi.get("oi"),
            "oi_change_pct": oi.get("oi_change_pct", 0),
            "price_change_pct": chg,
        }
    else:
        mf.append("oi")

    m3 = _score_onchain_smart_money(funding, gmgn_sec, oi_data, holder_growth)
    m4 = _score_social_narrative(alpha, chg)
    m5 = _score_market_regime(btc_dir, alt_rotation=alt_rotation)

    total = m1 + m2 + m3 + m4 + m5

    # Obsidian decision tiers
    if total >= 75:
        decision = "monster_candidate"
    elif total >= 50:
        decision = "watchlist"
    else:
        decision = "reject"

    # Direction signal
    sm_count = int(gmgn_sec.get("smart_degen_count", 0)) if gmgn_sec else 0
    can_enter, direction, confidence, entry_reasons = _direction_signal(
        chg, fr, k1h.get("trend"), count24h, sm_count, total,
        k4h.get("trend") if k4h else None, settings,
    )

    # Downgrade decision if below 75 (Obsidian: only monster_candidate can enter)
    if total < 75:
        can_enter = False

    # P0-4: Tradability enforcement
    if not tradable:
        can_enter = False
        risk_notes.append(f"不可交易标的({market_type})，仅观察")

    # Grade & position sizing text (legacy)
    gl, ps = grade(total)

    hit: list[str] = []
    miss: list[str] = []

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
        mf.append("alpha_count24h")
    if k1h.get("trend") == "bullish":
        hit.append("趋势结构: EMA多头排列")
    elif k1h.get("trend") == "bearish":
        hit.append("趋势结构: EMA空头排列")
    if k4h and k4h.get("trend"):
        if k4h["trend"] == k1h.get("trend"):
            hit.append(f"双周期共振: 4H+1H均{k4h['trend']}")
        else:
            miss.append(f"双周期矛盾: 4H={k4h['trend']} vs 1H={k1h.get('trend')}")
    if k1h.get("atr_pct") and k1h["atr_pct"] >= 0.08:
        hit.append(f"ATR波动率: {k1h['atr_pct']*100:.1f}% 有足够空间")
    if vol >= 100e6:
        hit.append("成交额>$100M 流动性良好")
    elif vol < 20e6:
        miss.append("成交额<$20M 流动性不足")
    if oi_data and oi_data.get("oi_change_pct", 0) != 0:
        oi_chg = oi_data["oi_change_pct"]
        hit.append(f"OI变化: {oi_chg:+.1f}%")

    # P1-3: Classified missing field downgrade
    missing_reasons = _classify_missing(ticker, funding, alpha, klines, klines_4h, oi, tradable=tradable)
    missing_core = set(mf) & CORE_FIELDS

    # Count fetch_errors vs asset_type
    fetch_error_count = sum(1 for k, v in missing_reasons.items() if v == "fetch_error")
    asset_type_count = sum(1 for k, v in missing_reasons.items() if v == "asset_type")

    needs_manual_review = False
    if missing_core:
        needs_manual_review = True
        # P1-3: More specific risk notes
        if fetch_error_count > 0:
            risk_notes.append(f"核心字段缺失({fetch_error_count}项): 数据拉取失败，建议重试")
        if asset_type_count > 0:
            risk_notes.append(f"核心字段缺失({asset_type_count}项): 资产类型不支持该字段")

    # P1-3: Tiered downgrade based on cause
    if fetch_error_count >= 3:
        # Data quality issue — force watchlist but allow retry
        total = min(total, 74)
        decision = "watchlist"
        can_enter = False
        risk_notes.append("多项核心字段拉取失败，降级为观察池，建议重试后复核")
    elif asset_type_count >= 3 and not tradable:
        # Onchain asset with many missing fields — expected, do not harshly penalize
        total = min(total, 60)  # Softer cap for onchain
        if total < 50:
            decision = "reject"
        else:
            decision = "watchlist"
        can_enter = False
        risk_notes.append("链上资产数据维度有限，仅供观察参考")

    regime = "risk_on" if btc_dir == "up" else ("risk_off" if btc_dir == "down" else "neutral")

    return {
        "symbol": symbol,
        "decision": decision,
        "total": total,
        "total_score": total,
        "direction": direction,
        "can_enter": can_enter,
        "confidence": confidence,
        "entry_reasons": entry_reasons,
        "grade_label": gl,
        "position_size": ps,
        "tradable": tradable,
        "market_type": market_type,
        "mapping_confidence": mapping_confidence,
        "venue": "binance/okx" if tradable and market_type == "cex_perp" else ("gmgn/onchain" if not tradable else "unknown"),
        "module_scores": {
            "safety_liquidity": m1,
            "price_volume": m2,
            "onchain_smart_money": m3,
            "social_narrative": m4,
            "market_regime": m5,
            # backward-compat aliases
            "m1_safety": m1,
            "m2": m2,
            "m3": m3,
            "m4": m4,
            "m5": m5,
            "m6": 0,
        },
        "hard_reject": False,
        "reject_reasons": [],
        "hit_rules": hit,
        "miss_rules": miss,
        "risk_notes": list(set(risk_notes)),
        "missing_fields": list(set(mf)),
        "needs_manual_review": needs_manual_review,
        "missing_reasons": missing_reasons,
        "meta": {
            "atr_pct": k1h.get("atr_pct"),
            "trend": k1h.get("trend"),
            "trend_4h": k4h.get("trend") if k4h else None,
            "ema20": k1h.get("ema20"),
            "ema50": k1h.get("ema50"),
            "price": price,
            "vol": vol,
            "fr": fr,
            "chg": chg,
            "count24h": count24h,
            "regime": regime,
            "oi": oi_data,
            "gmgn": gmgn_sec or {},
            "ticker_source": ticker.get("source", "binance") if ticker else "",
            "funding_source": funding.get("source", "binance") if funding else "",
            "kline_source": ticker.get("source", "binance") if (ticker and klines) else "",
        },
    }
