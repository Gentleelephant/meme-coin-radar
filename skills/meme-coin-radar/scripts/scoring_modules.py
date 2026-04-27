from __future__ import annotations

from typing import Any


def to_float(value: Any, default: float = 0.0) -> float:
    if value in (None, "", "N/A"):
        return default
    try:
        return float(str(value).replace(",", "").replace("%", ""))
    except (ValueError, TypeError):
        return default


def normalize_ratio(value: Any) -> float | None:
    if value in (None, "", "N/A"):
        return None
    parsed = to_float(value, default=0.0)
    if parsed == 0 and str(value).strip() not in {"0", "0.0", "0.00", "0%"}:
        return None
    return parsed / 100 if parsed > 1 else parsed


def safe_div(numerator: float, denominator: float) -> float | None:
    if denominator <= 0:
        return None
    return numerator / denominator


def score_turnover_activity(turnover_ratio: float | None, trade_density: float | None, buyer_ratio: float | None) -> int:
    score = 0
    if turnover_ratio is not None:
        if turnover_ratio >= 1.0:
            score = 18
        elif turnover_ratio >= 0.5:
            score = 14
        elif turnover_ratio >= 0.2:
            score = 9
        else:
            score = 4
    if trade_density is not None and trade_density >= 0.5:
        score += 4
    if buyer_ratio is not None and buyer_ratio >= 1.3:
        score += 3
    elif buyer_ratio is not None and buyer_ratio >= 1.05:
        score += 1
    return min(score, 25)


def score_momentum_window(chg24h: float, chg4h: float | None, trend_1h: str | None, trend_4h: str | None) -> int:
    if 3 <= chg24h <= 12:
        score = 20
    elif 12 < chg24h <= 25:
        score = 17
    elif 25 < chg24h <= 35:
        score = 13
    elif 0 <= chg24h < 3:
        score = 10
    elif -8 <= chg24h < 0:
        score = 6
    elif 35 < chg24h <= 60:
        score = 7
    elif chg24h > 60:
        score = 2
    else:
        score = 3
    if chg4h is not None and 0 < chg4h <= 6 and trend_1h in {"bullish", "weak_recovery"}:
        score += 2
    if chg24h > 35 and trend_4h and trend_1h and trend_4h != trend_1h:
        score -= 3
    return max(min(score, 20), 0)


def score_holder_structure(
    top10_ratio: float | None,
    new_wallet_ratio: float | None,
    cluster_concentration: str | None,
    cluster_rug_ratio: float | None,
    smart_money_holder_ratio: float | None,
    whale_holder_ratio: float | None,
) -> int:
    score = 0
    if top10_ratio is not None:
        if top10_ratio <= 0.20:
            score += 8
        elif top10_ratio <= 0.35:
            score += 5
        elif top10_ratio <= 0.50:
            score += 2
    if cluster_concentration:
        level = cluster_concentration.lower()
        if level == "low":
            score += 4
        elif level == "medium":
            score += 2
    if cluster_rug_ratio is not None:
        if cluster_rug_ratio <= 0.20:
            score += 4
        elif cluster_rug_ratio <= 0.35:
            score += 2
    if new_wallet_ratio is not None:
        if 0.10 <= new_wallet_ratio <= 0.35:
            score += 4
        elif 0.35 < new_wallet_ratio <= 0.50:
            score += 2
    if smart_money_holder_ratio is not None and smart_money_holder_ratio >= 0.05:
        score += 2
    if whale_holder_ratio is not None and whale_holder_ratio >= 0.08:
        score += 2
    return min(score, 20)


def score_smart_money_resonance(
    signal_wallet_count: int,
    wallet_type_mix: int,
    repeat_signal_count: int,
    tracked_wallet_overlap: int,
    owned_smart_money_hit_count: int,
) -> int:
    score = 0
    if signal_wallet_count >= 5:
        score += 7
    elif signal_wallet_count >= 3:
        score += 5
    elif signal_wallet_count >= 1:
        score += 2
    if wallet_type_mix >= 2:
        score += 3
    if repeat_signal_count >= 2:
        score += 2
    if tracked_wallet_overlap >= 2:
        score += 2
    if owned_smart_money_hit_count >= 1:
        score += 1
    return min(score, 15)


def score_market_cap_fit(market_cap: float) -> int:
    if 5e6 <= market_cap <= 50e6:
        return 10
    if 50e6 < market_cap <= 150e6:
        return 8
    if 150e6 < market_cap <= 300e6:
        return 6
    if market_cap < 5e6:
        return 4
    if 300e6 < market_cap <= 1e9:
        return 2
    return 0


def score_intraday_position(day_pos: float | None) -> int:
    if day_pos is None:
        return 0
    if 0.75 <= day_pos <= 0.95:
        return 5
    if 0.60 <= day_pos < 0.75:
        return 3
    if day_pos > 0.95:
        return 2
    if day_pos >= 0.40:
        return 1
    return 0


def score_social_heat(okx_x_rank: int | None, alpha_count24h: int) -> int:
    okx_score = 0
    if okx_x_rank is not None:
        if okx_x_rank <= 5:
            okx_score = 3
        elif okx_x_rank <= 15:
            okx_score = 2
        elif okx_x_rank <= 30:
            okx_score = 1
    alpha_score = 0
    if alpha_count24h >= 100000:
        alpha_score = 2
    elif alpha_count24h >= 50000:
        alpha_score = 1
    return min(okx_score + alpha_score, 5)


def score_execution_mapping(mapping_confidence: str, tradable: bool) -> int:
    if not tradable:
        return 0
    if mapping_confidence in {"native", "exact", "high"}:
        return 35
    if mapping_confidence in {"medium", "probable"}:
        return 20
    return 0


def score_execution_alpha(alpha_count24h: int, alpha_pct: float) -> int:
    if alpha_count24h >= 100000 and alpha_pct >= 0:
        return 20
    if alpha_count24h >= 50000 and alpha_pct >= 0:
        return 15
    if alpha_count24h >= 20000:
        return 8
    if alpha_count24h > 0:
        return 4
    return 0


def score_execution_liquidity(atr_pct: float | None, volume: float, chg24h: float) -> int:
    score = 0
    if volume >= 100e6:
        score += 10
    elif volume >= 20e6:
        score += 7
    elif volume >= 5e6:
        score += 4
    if atr_pct is not None:
        if 0.04 <= atr_pct <= 0.12:
            score += 10
        elif 0.02 <= atr_pct <= 0.18:
            score += 6
        elif atr_pct > 0.18 or abs(chg24h) > 60:
            score += 2
    return min(score, 20)


def score_execution_timing(day_pos: float | None, chg24h: float) -> int:
    if day_pos is None:
        return 0
    if 0.70 <= day_pos <= 0.92 and chg24h <= 30:
        return 15
    if 0.60 <= day_pos <= 0.95 and chg24h <= 45:
        return 10
    if day_pos > 0.95 or chg24h > 60:
        return 3
    return 6


def score_data_quality(missing_count: int, mapping_confidence: str) -> int:
    score = 10
    if mapping_confidence in {"low", "none"}:
        score -= 4
    score -= min(missing_count, 6)
    return max(score, 0)


def score_market_regime(btc_dir: str, alt_rotation: bool = False) -> int:
    if alt_rotation:
        return 10
    return 7 if btc_dir == "up" else (0 if btc_dir == "down" else 3)


def direction_signal(
    chg: float,
    fr: float,
    trend_struct: str | None,
    count24h: int,
    sm_count: int,
    total: float,
    trend_4h: str | None,
    min_recommend_score: float,
    min_direction_bias: float,
    min_direction_gap: float,
) -> tuple[bool, str, float, list[str]]:
    long_bias = 0.0
    short_bias = 0.0
    reasons: list[str] = []

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

    if trend_4h == "bullish":
        long_bias += 6.0
        reasons.append("4H趋势偏多")
    elif trend_4h == "bearish":
        short_bias += 6.0
        reasons.append("4H趋势偏空")

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
        total >= min_recommend_score
        and dominant_score >= min_direction_bias
        and bias_gap >= min_direction_gap
    )
    if not can_enter:
        return False, dominant, round(confidence, 2), reasons or ["方向优势不足"]
    return True, dominant, round(confidence, 2), reasons
