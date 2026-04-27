#!/usr/bin/env python3
"""
妖币雷达 Phase 2.0 — Provider + Radar Logic 版 (Obsidian-aligned)
用法: python3 scripts/auto-run.py
数据输出: $XDG_STATE_HOME/meme-coin-radar/scan_YYYYMMDD_HHMMSS/
         或 ~/.local/state/meme-coin-radar/scan_YYYYMMDD_HHMMSS/
         若不可写则回退到系统临时目录

改进点:
  - Obsidian 五大模块评分 (25/30/20/15/10)
  - 7条硬否决规则扩展
  - OI四象限 + 资金费率合并到链上模块
  - 双周期验证 (4H + 1H)
  - R:R >= 1.5 校验
  - 精确仓位计算 (基于账户权益)
  - 标准 JSON 输出
"""

from __future__ import annotations

import json
import os
from datetime import datetime

from history_store import cleanup_old_snapshots, compute_relative_metrics, save_alpha_snapshot, save_ticker_snapshot
from config import ensure_output_dir, load_settings
from asset_mapping import apply_to_candidates
from candidate_discovery import discover_candidates, get_cex_symbols, prioritize_candidates
from radar_logic import build_trade_plan, score_candidate
from skill_dispatcher import (
    batch_binance,
    binance_alpha,
    okx_account_equity,
    okx_btc_status,
    okx_hot_tokens,
    okx_signal_list,
    okx_swap_tickers,
    okx_token_snapshot,
    okx_tracker_activities,
)


SETTINGS = load_settings()
DATA_DIR = ensure_output_dir(SETTINGS.output_dir)
TS = datetime.now().strftime("%Y%m%d_%H%M%S")
SCAN_DIR = DATA_DIR / f"scan_{TS}"
SCAN_DIR.mkdir(parents=True, exist_ok=True)
MEDALS = ["🥇", "🥈", "🥉", "4.", "5.", "6.", "7.", "8."]


def save(name: str, content: str) -> str:
    path = SCAN_DIR / name
    path.write_text(content, encoding="utf-8")
    return str(path)


def _data_freshness_report(fetch_status: dict, scan_ts: int) -> dict:
    """Check data freshness and flag stale entries (>5 min old)."""
    stale_threshold_sec = 300  # 5 minutes
    report = {"scan_ts": scan_ts, "stale_threshold_sec": stale_threshold_sec, "assets": {}}
    for symbol, statuses in fetch_status.items():
        asset_report = {}
        for field, meta in statuses.items():
            if field.startswith("_"):
                continue
            if isinstance(meta, dict):
                fetched_at = meta.get("fetched_at", 0)
                age_sec = scan_ts - fetched_at
                asset_report[field] = {
                    "ok": meta.get("ok", False),
                    "age_sec": age_sec,
                    "stale": age_sec > stale_threshold_sec,
                    "source": meta.get("source", "unknown"),
                }
        report["assets"][symbol] = asset_report
    return report


def _format_freshness_summary(report: dict) -> str:
    """Generate a human-readable freshness summary for the report."""
    stale_count = sum(
        1 for asset in report["assets"].values() for f in asset.values() if f.get("stale")
    )
    total_fields = sum(len(v) for v in report["assets"].values())
    if stale_count == 0:
        return f"✅ 所有 {total_fields} 个数据字段均新鲜（<5分钟）"
    return f"⚠️ {stale_count}/{total_fields} 个数据字段超过 5 分钟阈值，建议复核"


print("=== 妖币雷达 Phase 3.0 扫描（OnchainOS + Alpha + Paper Trade）===")
print(f"时间: {TS}")

# Step 0: BTC 大盘
print("[0] BTC 大盘... (okx-cex-market: okx market ticker)")
btc = okx_btc_status()
save("00_btc_status.json", json.dumps(btc, indent=2, default=str, ensure_ascii=False))
btc_dir = btc.get("direction", "neutral")
btc_price = btc.get("price", 0)
btc_chg = btc.get("chg24h_pct", 0)
btc_source = btc.get("source", "okx-cex-market")
arrow = "↑" if btc_dir == "up" else ("↓" if btc_dir == "down" else "横")
market_bias = "适合做多" if btc_dir == "up" else ("适合做空" if btc_dir == "down" else "多空均可")
print(f"  BTC=${btc_price} chg={btc_chg:+.2f}% [{btc_dir}]")

# Step 0.5: Binance Alpha
print("[0.5] Binance Alpha 社区活跃度... (binance: binance-cli alpha token-list)")
alpha_dict = binance_alpha()
save("04_binance_alpha.json", json.dumps(alpha_dict, indent=2, default=str, ensure_ascii=False))
top_alpha = sorted(alpha_dict.items(), key=lambda item: item[1]["count24h"], reverse=True)[:20]
print(f"  Alpha: 获取到 {len(alpha_dict)} 个代币的社区数据")
for sym, data in top_alpha[:5]:
    print(f"    {sym}: tx24h={data['count24h']:,} chg={data['pct']:+.1f}%")

# Step G1/G2: OKX OnchainOS
print("[G1/G2] OKX OnchainOS 链上扫描...")
okx_hot_trending = okx_hot_tokens(ranking_type=4, chain="solana", limit=20, time_frame=4)
okx_hot_x = okx_hot_tokens(ranking_type=5, chain="solana", limit=20, time_frame=4)
okx_signals = okx_signal_list(chain="solana", wallet_type="1,2,3", limit=20)
okx_tracker = okx_tracker_activities(tracker_type="smart_money", chain="solana", trade_type=1, limit=50)
save("05_okx_hot_trending.json", json.dumps(okx_hot_trending, indent=2, default=str, ensure_ascii=False))
save("06_okx_hot_x.json", json.dumps(okx_hot_x, indent=2, default=str, ensure_ascii=False))
save("07_okx_signals.json", json.dumps(okx_signals, indent=2, default=str, ensure_ascii=False))
save("08_okx_tracker.json", json.dumps(okx_tracker, indent=2, default=str, ensure_ascii=False))

print(
    f"  OKX OnchainOS: trending={len(okx_hot_trending)}, "
    f"x_heat={len(okx_hot_x)}, signals={len(okx_signals)}, tracker={len(okx_tracker)}"
)

# Step 0.75: Account equity
print("[0.75] OKX 账户权益...")
account_equity = okx_account_equity()
print(f"  权益=${account_equity:,.2f}" if account_equity > 0 else "  权益: 未获取（Demo环境可能受限）")

# Step 1: OKX 全量 SWAP
print("[1] 全量 SWAP tickers... (okx-cex-market: okx market tickers SWAP)")
all_tickers = okx_swap_tickers()
save("01_all_tickers.json", json.dumps(all_tickers, indent=2, default=str, ensure_ascii=False))
print(f"  解析到 {len(all_tickers)} 个 USDT-M SWAP")

# P1-2: Save daily snapshots
print("[1b] 保存历史快照...")
save_ticker_snapshot(DATA_DIR, all_tickers)
save_alpha_snapshot(DATA_DIR, alpha_dict)
cleanup_old_snapshots(DATA_DIR, keep_days=30)
print("  快照已保存，旧数据已清理")

# Compute alt_rotation: % of tickers with 24h chg > 15%
alt_rotation = False
if all_tickers:
    strong_movers = [t for t in all_tickers if abs(t.get("chg24h_pct", 0)) > 15]
    alt_rotation_ratio = len(strong_movers) / len(all_tickers)
    alt_rotation = alt_rotation_ratio > 0.20 and btc_dir != "up"
    print(f"  市场宽度: {len(strong_movers)}/{len(all_tickers)} 标的24h异动>15% (alt_rotation={alt_rotation})")

# Step 2: Unified candidate discovery (roadmap P0-3)
print("[2] 候选发现层...")
candidates = discover_candidates(
    okx_hot_tokens=okx_hot_trending,
    okx_x_tokens=okx_hot_x,
    okx_signals=okx_signals,
    okx_tracker_activities=okx_tracker,
    alpha_dict=alpha_dict,
    key_coins=list(SETTINGS.key_coins),
    major_coins=list(SETTINGS.major_coins),
)
# P0-5: Asset mapping
cex_symbol_list = [t["symbol"] for t in all_tickers]
enriched_candidates = apply_to_candidates(candidates, cex_symbol_list)


def _candidate_sort_key(candidate: dict) -> tuple:
    return (
        1 if candidate.get("tradable_on_cex") else 0,
        len(candidate.get("candidate_sources", [])),
        candidate.get("symbol", ""),
    )


enriched_candidates.sort(key=_candidate_sort_key, reverse=True)
multi_source_candidates = [c for c in enriched_candidates if len(c.get("candidate_sources", [])) >= 2]
single_source_candidates = [c for c in enriched_candidates if len(c.get("candidate_sources", [])) < 2]
enriched_candidates = multi_source_candidates + single_source_candidates

# Separate tradable vs onchain
tradable_candidates = [c for c in enriched_candidates if c.get("tradable_on_cex")]
onchain_candidates = [c for c in enriched_candidates if not c.get("tradable_on_cex")]
cex_symbols = get_cex_symbols(candidates)  # native tradable symbols from discovery layer
mapped_cex_symbols = [c.get("symbol") for c in tradable_candidates if c.get("symbol")]
cex_symbols = list(dict.fromkeys(cex_symbols + mapped_cex_symbols))

print(f"  发现候选: CEX可交易={len(tradable_candidates)}, 链上观察={len(onchain_candidates)}")

# Step 2a: Onchain snapshots for candidates with OKX addresses
print("[2a] OKX OnchainOS token snapshots...")
onchain_snapshots: dict[str, dict] = {}
for cand in tradable_candidates + onchain_candidates[:10]:
    meta = cand.get("metadata", {})
    address = meta.get("address") or cand.get("token_address")
    chain = meta.get("chain") or cand.get("chain")
    if not address:
        continue
    snapshot = okx_token_snapshot(address=address, chain=chain)
    snapshot["signals"] = [
        item for item in okx_signals
        if str((item.get("token") or {}).get("tokenAddress") or item.get("tokenAddress") or "") == str(address)
    ]
    snapshot["tracker_items"] = [
        item for item in okx_tracker
        if any(
            str((changed or {}).get("tokenAddress") or "") == str(address)
            for changed in (item.get("changedTokenInfo") or [])
            if isinstance(changed, dict)
        )
    ]
    snapshot["okx_x_rank"] = meta.get("okx_x_rank")
    snapshot["okx_hot_rank"] = meta.get("okx_hot_rank")
    hot_source = (meta.get("onchain_data") or {}).get("hot_token")
    if hot_source:
        snapshot["hot_token"] = hot_source
    x_hot_source = None
    for item in okx_hot_x:
        if str(item.get("tokenContractAddress") or "") == str(address):
            x_hot_source = item
            break
    if x_hot_source:
        snapshot["x_hot_token"] = x_hot_source
    onchain_snapshots[cand.get("symbol", address)] = snapshot
    meta["onchain_data"] = {**(meta.get("onchain_data") or {}), **snapshot}

save("11_onchain_snapshots.json", json.dumps(onchain_snapshots, indent=2, default=str, ensure_ascii=False))

# Step 2b: Binance batch for CEX candidates only
print(f"[2b] Binance batch ({len(cex_symbols)} tradable coins)...")
bnc_batch = batch_binance(cex_symbols)
bnc_results = bnc_batch["results"]
fetch_status = bnc_batch.get("fetch_status", {})
save(
    "02_binance_batch.json",
    json.dumps(
        {
            key: {
                "ticker": value["ticker"],
                "funding": value["funding"],
                "has_klines": value["klines"] is not None,
                "has_klines_4h": value["klines_4h"] is not None,
                "has_klines_1d": value["klines_1d"] is not None,
                "has_oi": value["oi"] is not None,
            }
            for key, value in bnc_results.items()
        },
        indent=2,
        default=str,
        ensure_ascii=False,
    ),
)

# Save fetch_status for monitoring
save(
    "09_fetch_status.json",
    json.dumps(fetch_status, indent=2, default=str, ensure_ascii=False),
)

# P1-1: Data freshness check
scan_ts = int(datetime.now().timestamp())
freshness_report = _data_freshness_report(fetch_status, scan_ts)
save("10_data_freshness.json", json.dumps(freshness_report, indent=2, default=str, ensure_ascii=False))
freshness_summary = _format_freshness_summary(freshness_report)
print(f"  {freshness_summary}")

# Step 3: 评分
print("[3] Obsidian 五大模块评分...")
scored = []

# Score tradable CEX candidates
for cand in tradable_candidates:
    coin = cand.get("symbol", "")
    provider_data = bnc_results.get(coin, {})
    ticker = provider_data.get("ticker")
    funding = provider_data.get("funding")
    klines = provider_data.get("klines")
    klines_4h = provider_data.get("klines_4h")
    oi = provider_data.get("oi")
    alpha = alpha_dict.get(coin.upper(), {})

    if ticker is None and funding is None:
        print(f"  {coin}: Binance无数据，跳过")
        continue

    klines_1d = provider_data.get("klines_1d")
    cand_metadata = cand.get("metadata", {})
    onchain_data = cand_metadata.get("onchain_data", {})
    # P1-2: Compute relative metrics from history
    rel_metrics = compute_relative_metrics(
        output_dir=DATA_DIR,
        symbol=coin,
        current_volume=ticker.get("volume") if ticker else None,
        current_atr_pct=None,  # computed inside score_candidate from klines
        current_alpha_count=alpha.get("count24h") if alpha else None,
    )

    result = score_candidate(
        symbol=coin,
        ticker=ticker,
        funding=funding,
        alpha=alpha,
        klines=klines,
        btc_dir=btc_dir,
        missing_fields=[],
        settings=SETTINGS,
        klines_4h=klines_4h,
        klines_1d=klines_1d,
        oi=oi,
        equity=account_equity,
        alt_rotation=alt_rotation,
        tradable=cand.get("tradable_on_cex", True),
        market_type=cand.get("market_type", "cex_perp"),
        mapping_confidence=cand.get("mapping_confidence", "native"),
        strategy_mode=cand.get("strategy_mode", "meme_onchain"),
        onchain_data=onchain_data,
    )
    result["name"] = coin
    result["candidate_sources"] = cand.get("candidate_sources", [])
    result["relative_metrics"] = rel_metrics
    plan = build_trade_plan(result, equity=account_equity)
    result["trade_plan"] = plan
    if plan and plan.get("rr", 0) < 1.5:
        result["can_enter"] = False
        result.setdefault("risk_notes", []).append(f"R:R={plan['rr']:.2f}<1.5，不满足最低风险回报比")
    scored.append(result)

# Score onchain-only candidates (watch only, no trade)
for cand in onchain_candidates[:10]:  # Limit to top 10 onchain
    coin = cand.get("symbol", "")
    cand_metadata = cand.get("metadata", {})
    onchain_data = cand_metadata.get("onchain_data", {})
    result = score_candidate(
        symbol=coin,
        ticker=None,
        funding=None,
        alpha={},
        klines=None,
        btc_dir=btc_dir,
        missing_fields=["atr14", "trend", "oi", "fundingRate", "volume"],
        settings=SETTINGS,
        tradable=False,
        market_type=cand.get("market_type", "layer0_watch"),
        mapping_confidence=cand.get("mapping_confidence", "none"),
        strategy_mode=cand.get("strategy_mode", "meme_onchain"),
        onchain_data=onchain_data,
    )
    result["name"] = coin
    result["candidate_sources"] = cand.get("candidate_sources", [])
    result["watch_only"] = True
    scored.append(result)

valid = [item for item in scored if item["decision"] != "reject"]
valid.sort(key=lambda item: item["total"], reverse=True)
top_candidates = valid[: SETTINGS.top_n]
recommendations = [item for item in valid if item.get("can_enter")][: SETTINGS.recommendation_top_n]
all_rejected = [item for item in scored if item["decision"] == "reject"]
print(f"  候选总数={len(scored)}, 有效={len(valid)}, 拒绝={len(all_rejected)}, 可执行={len(recommendations)}")
for item in top_candidates[:3]:
    modules = item["module_scores"]
    print(
        f"  {item['name']}: 总={item['total']} | "
        f"安={modules['safety_liquidity']} 量={modules['price_volume']} "
        f"链={modules['onchain_smart_money']} 社={modules['social_narrative']} 环={modules['market_regime']} "
        f"→ {item['direction']} conf={item['confidence']}"
    )

top_ready = recommendations[:3]
top_watch = [item for item in valid if not item.get("can_enter")][:3]
summary_lines = [
    f"- 扫描候选 {len(scored)} 个，进入观察池 {len(valid)} 个，可执行建议 {len(recommendations)} 个。",
    f"- 市场环境判断为 `{btc_dir}`，BTC 24h 涨跌 `{btc_chg:+.2f}%`，当前偏向 `{market_bias}`。",
    f"- {freshness_summary}。",
]
if top_ready:
    summary_lines.append(
        "- 当前优先关注: "
        + "，".join(f"`{item['name']}`({item['direction']}, conf={item['confidence']:.0f})" for item in top_ready)
        + "。"
    )
elif top_watch:
    summary_lines.append(
        "- 暂无强执行信号，观察名单靠前的是: "
        + "，".join(f"`{item['name']}`({item['direction']}, score={item['total']})" for item in top_watch)
        + "。"
    )

watch_only_items = [item for item in valid if item["decision"] == "watch_only"][:5]
manual_review_items = [item for item in valid if item["decision"] == "manual_review"][:5]


def _decision_label(item: dict) -> str:
    return {
        "recommend_paper_trade": "Paper Trade",
        "watch_only": "Watch Only",
        "manual_review": "Manual Review",
        "reject": "Reject",
    }.get(item.get("decision", ""), item.get("decision", "unknown"))


def _direction_label(item: dict) -> str:
    return "🟢 做多" if item.get("direction") == "long" else ("🔴 做空" if item.get("direction") == "short" else "—")


report_lines = [
    "# 🦊 妖币雷达 Phase 3.0 扫描报告",
    f"> 扫描时间：{TS}",
    "> **评分主轴**：`Onchain Opportunity Score (OOS)` + `Execution Readiness Score (ERS)`，以 `OKX OnchainOS` 为主，`Binance Alpha` 为补强，`Binance 模拟盘` 为执行承接。",
    "",
    "## Executive Summary",
    "",
    *summary_lines,
    "",
    "## 📊 市场上下文",
    "",
    "| 指标 | 数值 | 方向 | 数据来源 |",
    "|---|---|---:|---|",
    f"| BTC 价格 | ${btc_price:.2f} | {arrow} | {btc_source} |",
    f"| BTC 24h涨跌 | {btc_chg:+.2f}% | — | {btc_source} |",
    f"| 市场判断 | {market_bias} | — | {btc_source} |",
    f"| 账户权益 | ${account_equity:,.2f} | — | okx |" if account_equity > 0 else "| 账户权益 | N/A | — | okx |",
    "",
    "## 🎯 Paper Trade 候选",
    "",
]

if recommendations:
    report_lines += [
        "| 排名 | 币种 | 方向 | OOS | ERS | 置信度 | 入场区间 | 止损 | 止盈1 | 止盈2 | 仓位建议 |",
        "|---|---|---|---:|---:|---:|---|---|---|---|---|",
    ]
    for index, item in enumerate(recommendations, 1):
        plan = item.get("trade_plan") or {}
        ps_text = f"${plan['position_size_usd']:,.0f} USDT" if plan.get("position_size_usd") else item.get("position_size", "N/A")
        report_lines.append(
            f"| {index} | **{item['name']}** | {_direction_label(item)} | {item.get('oos', 0)} | {item.get('ers', 0)} | "
            f"{item['confidence']:.0f} | ${plan.get('entry_low', 0):.6g} - ${plan.get('entry_high', 0):.6g} | "
            f"${plan.get('stop_loss', 0):.6g} | ${plan.get('take_profit_1', 0):.6g} | ${plan.get('take_profit_2', 0):.6g} | {ps_text} |"
        )
    report_lines.append("")
else:
    report_lines += [
        "> ⚠️ 本次没有满足 `recommend_paper_trade` 门槛的标的。",
        "",
    ]

if watch_only_items:
    report_lines += [
        "## 👀 Watch Only",
        "",
        "| 币种 | OOS | ERS | 方向 | 原因 |",
        "|---|---:|---:|---|---|",
    ]
    for item in watch_only_items:
        reason = item["miss_rules"][0] if item.get("miss_rules") else "链上强度达标，但当前执行承接不足"
        report_lines.append(
            f"| **{item['name']}** | {item.get('oos', 0)} | {item.get('ers', 0)} | {_direction_label(item)} | {reason} |"
        )
    report_lines.append("")

if manual_review_items:
    report_lines += [
        "## 🔶 Manual Review",
        "",
        "| 币种 | OOS | ERS | 需复核项 |",
        "|---|---:|---:|---|",
    ]
    for item in manual_review_items:
        missing = ", ".join(item.get("missing_fields", [])[:4]) or "结构化复核"
        report_lines.append(f"| **{item['name']}** | {item.get('oos', 0)} | {item.get('ers', 0)} | {missing} |")
    report_lines.append("")

report_lines += [
    "## 🏆 Scoreboard",
    "",
    "| 币种 | 决策 | 方向 | Final | OOS | ERS | 换手/活跃 | 动能 | 持仓结构 | 聪明钱 | 社交 | 映射 |",
    "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
]
for item in top_candidates:
    modules = item["module_scores"]
    report_lines.append(
        f"| **{item['name']}** | {_decision_label(item)} | {_direction_label(item)} | {item.get('final_score', item['total'])} | "
        f"{item.get('oos', 0)} | {item.get('ers', 0)} | {modules.get('turnover_activity', 0)} | "
        f"{modules.get('momentum_window', 0)} | {modules.get('holder_structure', 0)} | "
        f"{modules.get('smart_money_resonance', 0)} | {modules.get('social_heat', 0)} | {modules.get('execution_mapping', 0)} |"
    )

report_lines.append("")
for index, item in enumerate(top_candidates[:3]):
    meta = item["meta"]
    plan = item.get("trade_plan") or {}
    report_lines += [
        f"### {MEDALS[index]} {item['name']} — {_decision_label(item)}",
        "",
        f"- Final Score: `{item.get('final_score', item['total'])}`",
        f"- OOS: `{item.get('oos', 0)}`",
        f"- ERS: `{item.get('ers', 0)}`",
        f"- 方向: `{item.get('direction')}` / 置信度 `{item['confidence']:.0f}`",
        f"- 市值: `${meta.get('market_cap', 0) / 1e6:.1f}M`" if meta.get("market_cap") else "- 市值: `N/A`",
        f"- 换手率: `{meta.get('turnover_ratio'):.2f}`" if meta.get("turnover_ratio") is not None else "- 换手率: `N/A`",
        f"- 日内位置: `{meta.get('day_pos'):.2f}`" if meta.get("day_pos") is not None else "- 日内位置: `N/A`",
        f"- Binance Alpha count24h: `{meta.get('count24h', 0):,}`",
    ]
    if plan.get("rr") is not None:
        report_lines.append(f"- R:R: `{plan['rr']:.2f}`")
    for reason in item.get("hit_rules", [])[:4]:
        report_lines.append(f"- ✅ {reason}")
    for note in item.get("risk_notes", [])[:3]:
        report_lines.append(f"- 🔶 {note}")
    if item.get("miss_rules"):
        report_lines.append(f"- ⚠️ {item['miss_rules'][0]}")
    if plan:
        report_lines.append(f"- 入场区间: `${plan.get('entry_low', 0):.6g} - ${plan.get('entry_high', 0):.6g}`")
        report_lines.append(f"- 止损: `${plan.get('stop_loss', 0):.6g}`")
        report_lines.append(f"- 止盈1: `${plan.get('take_profit_1', 0):.6g}`")
        report_lines.append(f"- 止盈2: `${plan.get('take_profit_2', 0):.6g}`")
    report_lines.append("")

report_lines += [
    "## 🔥 Binance Alpha 热度 TOP10",
    "",
    "| 排名 | 币种 | count24h | 24h涨跌 | score |",
    "|---|---|---:|---:|---:|",
]
for index, (symbol, data) in enumerate(top_alpha[:10], 1):
    report_lines.append(
        f"| {index} | **{symbol}** | {data['count24h']:,} | {data['pct']:+.1f}% | {data.get('score', 0):.0f} |"
    )

if all_rejected:
    report_lines += [
        "",
        "## ❌ Rejects",
        "",
        "| 币种 | 原因 |",
        "|---|---|",
    ]
    for item in all_rejected[:10]:
        report_lines.append(f"| **{item['name']}** | {'; '.join(item.get('reject_reasons', item.get('miss_rules', []))) or '不满足最小门槛'} |")

report_lines += [
    "",
    "## 🧩 Data Pipeline",
    "",
    "| Step | 数据内容 | 来源 |",
    "|---:|---|---|",
    "| 0 | BTC 大盘状态 | OKX CEX ticker |",
    "| 0.5 | 交易所热度补强 | Binance Alpha token-list |",
    "| 1 | 链上发现候选 | OKX OnchainOS hot-tokens / signal list / tracker activities |",
    "| 2 | 链上特征快照 | OKX OnchainOS price-info / advanced-info / holders / cluster / trades |",
    "| 3 | 执行承接数据 | Binance ticker / funding / klines / OI |",
    "| 4 | 评分与计划 | 本地 radar_logic.py (`OOS + ERS`) |",
    "",
    "## Notes",
    "",
    "- `OOS` 决定链上机会强弱，`ERS` 决定是否适合承接到 Binance 模拟盘。",
    "- `recommend_paper_trade` 需要同时满足链上强度、执行承接和硬风险过滤。",
    "- `watch_only` 常见于链上强、但当前映射或执行条件不足的标的。",
    "- `manual_review` 代表数据缺口较多或信号边界不清晰，需要人工复核。",
    "",
    "*⚠️ 本报告仅供研究与模拟验证，不构成投资建议。*",
    f"*数据路径：{SCAN_DIR}/*",
    f"*Phase 3.0 — {datetime.now().strftime('%Y-%m-%d')}*",
]

report_path = SCAN_DIR / "report.md"
report_path.write_text("\n".join(report_lines), encoding="utf-8")

# Standard JSON output (Obsidian aligned)
json_results = []
for item in scored:
    plan = item.get("trade_plan")
    json_results.append({
        "symbol": item.get("symbol", item.get("name", "")),
        "decision": item["decision"],
        "final_score": item.get("final_score", item.get("total", 0)),
        "oos": item.get("oos", 0),
        "ers": item.get("ers", 0),
        "total_score": item.get("total_score", item.get("total", 0)),
        "module_scores": item.get("module_scores", {}),
        "hard_reject": item.get("hard_reject", False),
        "reject_reasons": item.get("reject_reasons", []),
        "hit_rules": item.get("hit_rules", []),
        "miss_rules": item.get("miss_rules", []),
        "risk_notes": item.get("risk_notes", []),
        "missing_fields": item.get("missing_fields", []),
        "needs_manual_review": item.get("needs_manual_review", False),
        "direction": item.get("direction"),
        "can_enter": item.get("can_enter"),
        "confidence": item.get("confidence"),
        "entry_reasons": item.get("entry_reasons", []),
        "candidate_sources": item.get("candidate_sources", []),
        "mapping_confidence": item.get("mapping_confidence"),
        "market_type": item.get("market_type"),
        "relative_metrics": item.get("relative_metrics", {}),
        "meta": item.get("meta", {}),
        "trade_plan": {
            k: v for k, v in (plan or {}).items()
            if k not in ("entry_low", "entry_high", "stop_loss", "take_profit_1", "take_profit_2")
        } if plan else None,
    })

save("result.json", json.dumps(json_results, indent=2, ensure_ascii=False, default=str))

print("=== 妖币雷达 Phase 3.0 扫描完成 ===")
print(f"目录: {SCAN_DIR}")
print(f"报告: {report_path}")
print(f"JSON: {SCAN_DIR / 'result.json'}")
print("")
print("🏆 机会队列 TOP" + str(len(top_candidates)) + ":")
for index, item in enumerate(top_candidates[: SETTINGS.top_n]):
    direction_emoji = "🟢" if item["direction"] == "long" else "🔴"
    decision_label = "纸面交易" if item["decision"] == "recommend_paper_trade" else ("观察" if item["decision"] == "watch_only" else "复核")
    print(
        f"  {MEDALS[index]} {item['name']} {direction_emoji}{item['direction']} "
        f"评分:{item['total']} conf:{item['confidence']:.0f} {item['grade_label']} [{decision_label}]"
    )
