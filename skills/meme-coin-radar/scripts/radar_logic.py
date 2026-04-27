from __future__ import annotations

from typing import Any

try:
    from .config import Settings
    from .scoring_modules import (
        direction_signal,
        normalize_ratio,
        safe_div,
        score_data_quality,
        score_execution_alpha,
        score_execution_liquidity,
        score_execution_mapping,
        score_execution_timing,
        score_holder_structure,
        score_intraday_position,
        score_major_holder_structure_proxy,
        score_major_market_cap_fit,
        score_major_participation_proxy,
        score_market_regime,
        score_market_cap_fit,
        score_momentum_window,
        score_smart_money_resonance,
        score_social_heat,
        score_turnover_activity,
        to_float,
    )
except ImportError:
    from config import Settings
    from scoring_modules import (
        direction_signal,
        normalize_ratio,
        safe_div,
        score_data_quality,
        score_execution_alpha,
        score_execution_liquidity,
        score_execution_mapping,
        score_execution_timing,
        score_holder_structure,
        score_intraday_position,
        score_major_holder_structure_proxy,
        score_major_market_cap_fit,
        score_major_participation_proxy,
        score_market_regime,
        score_market_cap_fit,
        score_momentum_window,
        score_smart_money_resonance,
        score_social_heat,
        score_turnover_activity,
        to_float,
    )


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

    # Rule 5: trading unavailable / extreme slippage — not auto-detectable without simulation
    risk_notes.append("未模拟交易检测滑点（需人工确认）")

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
        total_score = result.get("final_score", result.get("total", 0))
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
    klines_4h: list | None = None,
    klines_1d: list | None = None,
    oi: dict | None = None,
    equity: float = 0.0,
    alt_rotation: bool = False,
    volume_vs_7d: float | None = None,
    tradable: bool = True,
    market_type: str = "cex_perp",
    mapping_confidence: str = "native",
    strategy_mode: str = "meme_onchain",
    onchain_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ticker = ticker or {}
    funding = funding or {}
    alpha = alpha or {}
    onchain_data = onchain_data or {}
    mf = list(missing_fields)

    chg = float(ticker.get("chg24h", 0.0))
    price = float(ticker.get("price", 0.0))
    vol = float(ticker.get("volume", 0.0))
    fr = float(funding.get("fundingRate_pct", 0.0)) if funding else 0.0
    count24h = alpha.get("count24h", 0) if alpha else 0
    alpha_pct = float(alpha.get("pct", 0.0) or 0.0) if alpha else 0.0

    k1h = _klines_meta(klines, price)
    if k1h["atr_pct"] is None:
        mf.append("atr14")
    if k1h["trend"] is None:
        mf.append("trend")

    k4h = _klines_meta(klines_4h, price) if klines_4h else None
    if klines_4h and k4h and k4h["trend"] is None:
        mf.append("trend_4h")

    price_info = onchain_data.get("price_info", {})
    advanced_info = onchain_data.get("advanced_info", {})
    cluster_overview = onchain_data.get("cluster_overview", {})
    cluster_top_holders = onchain_data.get("cluster_top_holders", {})
    hot_token = onchain_data.get("hot_token", {})
    x_hot_token = onchain_data.get("x_hot_token", {})
    holders_list = onchain_data.get("holders", []) or []
    trades_list = onchain_data.get("trades", []) or []
    signal_items = onchain_data.get("signals", []) or []
    tracker_items = onchain_data.get("tracker_items", []) or []

    market_cap = max(
        to_float(price_info.get("marketCap")),
        to_float(hot_token.get("marketCap")),
        to_float(x_hot_token.get("marketCap")),
    )
    onchain_volume_24h = max(
        to_float(price_info.get("volume24H")),
        to_float(hot_token.get("volume")),
    )
    holder_count = max(
        int(to_float(price_info.get("holders"))),
        int(to_float(hot_token.get("holders"))),
    )
    txs_24h = max(
        int(to_float(price_info.get("txs24H"))),
        int(to_float(hot_token.get("txs"))),
        len(trades_list),
    )
    buyers_24h = int(to_float(hot_token.get("txsBuy")))
    sellers_24h = int(to_float(hot_token.get("txsSell")))
    turnover_ratio = safe_div(onchain_volume_24h, market_cap)
    trade_density = safe_div(float(txs_24h), float(max(holder_count, 1)))
    buyer_ratio = safe_div(float(buyers_24h), float(max(sellers_24h, 1)))
    chg4h = to_float(price_info.get("priceChange4H"), default=None) if price_info else None
    if chg4h is None and klines_4h and len(klines_4h) >= 2:
        try:
            prev_close = float(klines_4h[-2][3])
            last_close = float(klines_4h[-1][3])
            chg4h = (last_close - prev_close) / prev_close * 100 if prev_close > 0 else None
        except (IndexError, ValueError, TypeError):
            chg4h = None

    intraday_high = max(to_float(price_info.get("maxPrice")), to_float(ticker.get("high24h")))
    intraday_low = max(to_float(price_info.get("minPrice")), 0.0)
    day_pos = safe_div(price - intraday_low, max(intraday_high - intraday_low, 0.0)) if intraday_high > intraday_low and price > 0 else None

    top10_ratio = normalize_ratio(advanced_info.get("top10HoldPercent"))
    if top10_ratio is None:
        top10_ratio = normalize_ratio(hot_token.get("top10HoldPercent"))
    new_wallet_ratio = normalize_ratio(cluster_overview.get("holderNewAddressPercent"))
    cluster_rug_ratio = normalize_ratio(cluster_overview.get("rugPullPercent"))
    cluster_concentration = str(cluster_overview.get("clusterConcentration") or "")
    smart_money_holder_ratio = normalize_ratio(onchain_data.get("smart_money_holder_percent"))
    whale_holder_ratio = normalize_ratio(onchain_data.get("whale_holder_percent"))
    okx_x_rank = onchain_data.get("okx_x_rank")

    signal_wallet_count = 0
    wallet_types: set[str] = set()
    repeat_signal_count = 0
    tracked_wallets: set[str] = set()
    for item in signal_items:
        signal_wallet_count = max(signal_wallet_count, int(to_float(item.get("triggerWalletCount"))))
        wallet_type = str(item.get("walletType") or "")
        if wallet_type:
            wallet_types.add(wallet_type)
        sold_ratio = normalize_ratio(item.get("soldRatioPercent"))
        if sold_ratio is not None and sold_ratio < 0.50:
            repeat_signal_count += 1
    for item in tracker_items:
        addr = str(item.get("userAddress") or item.get("walletAddress") or "")
        if addr:
            tracked_wallets.add(addr)
    tracked_wallet_overlap = len(tracked_wallets)
    owned_smart_money_hit_count = 0

    reject = False
    reject_reasons: list[str] = []
    risk_notes: list[str] = []
    if top10_ratio is not None and top10_ratio > 0.35:
        reject = True
        reject_reasons.append(f"前十持仓={top10_ratio:.1%}>35%")
    if cluster_rug_ratio is not None and cluster_rug_ratio >= 0.60:
        reject = True
        reject_reasons.append(f"cluster_rug_risk={cluster_rug_ratio:.0%}过高")
    liquidity = to_float(price_info.get("liquidity"))
    if 0 < liquidity < 50000:
        reject = True
        reject_reasons.append(f"流动性=${liquidity:.0f}<$50K")
    suspicious_ratio = normalize_ratio(advanced_info.get("suspiciousHoldingPercent"))
    if suspicious_ratio is not None and suspicious_ratio >= 0.20:
        reject = True
        reject_reasons.append(f"可疑持仓占比={suspicious_ratio:.0%}过高")
    dev_ratio = normalize_ratio(advanced_info.get("devHoldingPercent"))
    if dev_ratio is not None and dev_ratio >= 0.15:
        reject = True
        reject_reasons.append(f"开发者持仓={dev_ratio:.0%}过高")
    if mapping_confidence == "low" and tradable:
        reject = True
        reject_reasons.append("Binance映射置信度过低")
    if chg > 60 and day_pos is not None and day_pos > 0.95 and (k4h and k4h.get("trend") not in {"bullish", "weak_recovery"}):
        reject = True
        reject_reasons.append("已暴涨且结构衰竭")

    if reject:
        return {
            "symbol": symbol,
            "decision": "reject",
            "total": 0,
            "total_score": 0,
            "final_score": 0,
            "oos": 0,
            "ers": 0,
            "direction": "none",
            "can_enter": False,
            "confidence": 0.0,
            "entry_reasons": [],
            "grade_label": "❌拒绝",
            "position_size": "不交易",
            "module_scores": {
                "turnover_activity": 0,
                "momentum_window": 0,
                "holder_structure": 0,
                "smart_money_resonance": 0,
                "market_cap_fit": 0,
                "intraday_position": 0,
                "social_heat": 0,
                "execution_mapping": 0,
                "execution_alpha": 0,
                "execution_liquidity": 0,
                "execution_timing": 0,
                "data_quality": 0,
                "safety_liquidity": 0,
                "price_volume": 0,
                "onchain_smart_money": 0,
                "social_narrative": 0,
                "market_regime": 0,
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
                "day_pos": day_pos,
                "market_cap": market_cap,
                "strategy_mode": strategy_mode,
            },
        }

    if volume_vs_7d is None and klines_1d and len(klines_1d) >= 8:
        try:
            vols = [float(k[5]) for k in klines_1d[-8:]]
            if len(vols) >= 8 and vols[-1] > 0:
                avg_7d = sum(vols[:-1]) / 7
                if avg_7d > 0:
                    volume_vs_7d = vols[-1] / avg_7d
        except (IndexError, ValueError, TypeError):
            pass

    oi_data: dict[str, Any] | None = None
    if oi:
        oi_data = {"oi": oi.get("oi"), "oi_change_pct": oi.get("oi_change_pct", 0), "price_change_pct": chg}

    turnover_activity = score_turnover_activity(turnover_ratio, trade_density, buyer_ratio)
    momentum_window = score_momentum_window(chg, chg4h, k1h.get("trend"), k4h.get("trend") if k4h else None)
    holder_structure = score_holder_structure(
        top10_ratio,
        new_wallet_ratio,
        cluster_concentration,
        cluster_rug_ratio,
        smart_money_holder_ratio,
        whale_holder_ratio,
    )
    smart_money_resonance = score_smart_money_resonance(
        signal_wallet_count=signal_wallet_count,
        wallet_type_mix=len(wallet_types),
        repeat_signal_count=repeat_signal_count,
        tracked_wallet_overlap=tracked_wallet_overlap,
        owned_smart_money_hit_count=owned_smart_money_hit_count,
    )
    if strategy_mode == "majors_cex":
        holder_structure = score_major_holder_structure_proxy(
            holder_structure,
            vol,
            k1h.get("trend"),
            k4h.get("trend") if k4h else None,
            count24h,
        )
    market_cap_fit = score_major_market_cap_fit(market_cap) if strategy_mode == "majors_cex" else score_market_cap_fit(market_cap)
    intraday_position = score_intraday_position(day_pos)
    social_heat = score_social_heat(okx_x_rank, count24h)
    if strategy_mode == "majors_cex":
        smart_money_resonance = score_major_participation_proxy(
            smart_money_resonance,
            count24h,
            to_float(oi.get("oi_change_pct"), default=None) if oi else None,
        )
    oos = turnover_activity + momentum_window + holder_structure + smart_money_resonance + market_cap_fit + intraday_position + social_heat

    execution_mapping = score_execution_mapping(mapping_confidence, tradable)
    execution_alpha = score_execution_alpha(count24h, alpha_pct)
    execution_liquidity = score_execution_liquidity(k1h.get("atr_pct"), vol, chg)
    execution_timing = score_execution_timing(day_pos, chg)

    missing_reasons = _classify_missing(ticker, funding, alpha, klines, klines_4h, oi, tradable=tradable)
    if market_cap <= 0:
        missing_reasons["marketCap"] = "fetch_error"
        mf.append("marketCap")
    if onchain_volume_24h <= 0:
        missing_reasons["volume24H"] = "fetch_error"
        mf.append("volume24H")
    if top10_ratio is None:
        missing_reasons["top10_holder_ratio"] = "fetch_error"
        mf.append("top10_holder_ratio")
    data_quality = score_data_quality(len(set(mf)), mapping_confidence)
    ers = execution_mapping + execution_alpha + execution_liquidity + execution_timing + data_quality

    final_score = round(oos * 0.5 + ers * 0.5) if strategy_mode == "majors_cex" else round(oos * 0.7 + ers * 0.3)

    sm_count = signal_wallet_count
    can_enter, direction, confidence, entry_reasons = direction_signal(
        chg,
        fr,
        k1h.get("trend"),
        count24h,
        sm_count,
        final_score,
        k4h.get("trend") if k4h else None,
        settings.min_recommend_score,
        settings.min_direction_bias,
        settings.min_direction_gap,
    )

    if strategy_mode == "majors_cex":
        if final_score >= 68 and ers >= 68 and tradable:
            decision = "recommend_paper_trade"
        elif final_score >= 58:
            decision = "watch_only" if tradable else "manual_review"
        elif len(set(mf)) >= 3:
            decision = "manual_review"
        else:
            decision = "reject"
    elif oos >= 70 and ers >= 65 and tradable:
        decision = "recommend_paper_trade"
    elif oos >= 70:
        decision = "watch_only"
    elif oos >= 55 or len(set(mf)) >= 3:
        decision = "manual_review"
    else:
        decision = "reject"
    if decision != "recommend_paper_trade":
        can_enter = False
    if not tradable:
        risk_notes.append(f"不可交易标的({market_type})，仅观察")

    gl, ps = grade(final_score)

    hit: list[str] = []
    miss: list[str] = []
    if turnover_ratio is not None and turnover_ratio >= 0.5:
        hit.append(f"换手率={turnover_ratio:.2f} 投机活跃")
    else:
        miss.append("换手率不足")
    if 3 <= chg <= 30:
        hit.append(f"24h动能处于启动区间({chg:+.1f}%)")
    elif chg > 60:
        miss.append("24h涨幅过大，疑似后排追高")
    if top10_ratio is not None and top10_ratio <= 0.35:
        hit.append(f"前十持仓={top10_ratio:.1%} 相对健康")
    elif top10_ratio is not None:
        miss.append(f"前十持仓={top10_ratio:.1%} 偏集中")
    if cluster_rug_ratio is not None and cluster_rug_ratio <= 0.35:
        hit.append(f"Cluster rug risk={cluster_rug_ratio:.0%} 可接受")
    elif cluster_rug_ratio is not None:
        miss.append(f"Cluster rug risk={cluster_rug_ratio:.0%} 偏高")
    if signal_wallet_count >= 3:
        hit.append(f"OKX 聚合信号钱包数={signal_wallet_count}")
    elif signal_wallet_count == 0:
        miss.append("缺少 OKX 聪明钱共振")
    if market_cap > 0:
        hit.append(f"市值=${market_cap/1e6:.1f}M")
    if okx_x_rank is not None and okx_x_rank <= 15:
        hit.append(f"OKX X热度排名 #{okx_x_rank}")
    elif count24h == 0:
        miss.append("无 Binance Alpha 热度确认")

    fetch_error_count = sum(1 for reason in missing_reasons.values() if reason == "fetch_error")
    needs_manual_review = decision == "manual_review" or fetch_error_count >= 2
    if fetch_error_count >= 2:
        risk_notes.append(f"关键字段拉取失败 {fetch_error_count} 项，建议重试复核")
    if not tradable and decision == "watch_only":
        risk_notes.append("链上强度达标，但当前无法承接 Binance 模拟交易")

    regime = "risk_on" if btc_dir == "up" else ("risk_off" if btc_dir == "down" else "neutral")

    return {
        "symbol": symbol,
        "decision": decision,
        "total": final_score,
        "total_score": final_score,
        "final_score": final_score,
        "oos": oos,
        "ers": ers,
        "direction": direction,
        "can_enter": can_enter,
        "confidence": confidence,
        "entry_reasons": entry_reasons,
        "grade_label": gl,
        "position_size": ps,
        "tradable": tradable,
        "market_type": market_type,
        "strategy_mode": strategy_mode,
        "mapping_confidence": mapping_confidence,
        "venue": "binance/okx" if tradable and market_type == "cex_perp" else ("okx/onchain" if not tradable else "unknown"),
        "module_scores": {
            "turnover_activity": turnover_activity,
            "momentum_window": momentum_window,
            "holder_structure": holder_structure,
            "smart_money_resonance": smart_money_resonance,
            "market_cap_fit": market_cap_fit,
            "intraday_position": intraday_position,
            "social_heat": social_heat,
            "execution_mapping": execution_mapping,
            "execution_alpha": execution_alpha,
            "execution_liquidity": execution_liquidity,
            "execution_timing": execution_timing,
            "data_quality": data_quality,
            # compatibility aliases for the existing report/test surface
            "safety_liquidity": holder_structure,
            "price_volume": momentum_window,
            "onchain_smart_money": smart_money_resonance,
            "social_narrative": social_heat,
            "market_regime": score_market_regime(btc_dir, alt_rotation=alt_rotation),
            "m1_safety": holder_structure,
            "m2": momentum_window,
            "m3": smart_money_resonance,
            "m4": social_heat,
            "m5": score_market_regime(btc_dir, alt_rotation=alt_rotation),
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
            "day_pos": day_pos,
            "market_cap": market_cap,
            "turnover_ratio": turnover_ratio,
            "buyer_ratio": buyer_ratio,
            "okx_x_rank": okx_x_rank,
            "strategy_mode": strategy_mode,
            "onchain": onchain_data,
            "ticker_source": ticker.get("source", "binance") if ticker else "",
            "funding_source": funding.get("source", "binance") if funding else "",
            "kline_source": ticker.get("source", "binance") if (ticker and klines) else "",
        },
    }
