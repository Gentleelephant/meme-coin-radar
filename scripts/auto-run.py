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
    gmgn_security_score,
    gmgn_signal,
    gmgn_trending,
    gmgn_trenches,
    load_gmgn_key,
    okx_account_equity,
    okx_btc_status,
    okx_swap_tickers,
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


print("=== 妖币雷达 Phase 2.0 扫描（Obsidian 对齐版）===")
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

# Step G1/G2: GMGN
print("[G1/G2] GMGN Chain层扫描... (gmgn-market: npx gmgn-cli)")
gmgn_key_present = bool(load_gmgn_key())
gmgn_sol_trending = gmgn_trending(chain="sol", interval="1h", limit=20)
gmgn_bsc_trending = gmgn_trending(chain="bsc", interval="1h", limit=20)
gmgn_signals = gmgn_signal(chain="sol", limit=30)
gmgn_trenches_sol = gmgn_trenches(chain="sol", token_type="new_creation", limit=20)

save("05_gmgn_sol_trending.json", json.dumps(gmgn_sol_trending, indent=2, default=str, ensure_ascii=False))
save("06_gmgn_bsc_trending.json", json.dumps(gmgn_bsc_trending, indent=2, default=str, ensure_ascii=False))
save("07_gmgn_signals.json", json.dumps(gmgn_signals, indent=2, default=str, ensure_ascii=False))
save("08_gmgn_trenches_sol.json", json.dumps(gmgn_trenches_sol, indent=2, default=str, ensure_ascii=False))

gmgn_sol_pass = []
gmgn_sol_reject = []
for token in gmgn_sol_trending:
    sec = gmgn_security_score(token)
    symbol = token.get("symbol", "")
    if not sec.get("reject"):
        gmgn_sol_pass.append(
            {
                "symbol": symbol,
                "name": token.get("name", ""),
                "chain": "sol",
                "address": token.get("address", ""),
                "price": float(token.get("price") or 0),
                "chg1h": float(token.get("price_change_percent1h") or 0),
                "vol": float(token.get("volume") or 0),
                "liquidity": float(token.get("liquidity") or 0),
                "holders": int(token.get("holder_count") or 0),
                "smart_degen_count": sec.get("smart_degen_count", 0),
                "renowned_count": sec.get("renowned_count", 0),
                "rug_ratio": sec.get("rug_ratio"),
                "top10": sec.get("top_10_holder_rate"),
                "gmgn_tag": sec.get("tag"),
                "bonus": sec.get("bonus", 0),
            }
        )
    else:
        gmgn_sol_reject.append({"symbol": symbol, "reason": sec.get("reason", "")})

gmgn_sm_resonance = sorted(
    [token for token in gmgn_sol_pass if token["smart_degen_count"] >= 3],
    key=lambda item: (item["smart_degen_count"], item["chg1h"]),
    reverse=True,
)
print(
    f"  GMGN SOL: 安全通过={len(gmgn_sol_pass)}, "
    f"拒绝={len(gmgn_sol_reject)}, 聪明钱共振={len(gmgn_sm_resonance)}"
)

if not gmgn_key_present:
    gmgn_status = "missing_key"
elif gmgn_sol_trending:
    gmgn_status = "ok"
elif gmgn_sol_reject:
    gmgn_status = "all_rejected"
else:
    gmgn_status = "fetch_failed"

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
    all_tickers=all_tickers,
    alpha_dict=alpha_dict,
    gmgn_sol_trending=gmgn_sol_trending,
    gmgn_bsc_trending=gmgn_bsc_trending,
    gmgn_signals=gmgn_signals,
    gmgn_trenches=gmgn_trenches_sol,
    key_coins=list(SETTINGS.key_coins),
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

# GMGN -> Symbol 映射
gmgn_addr_to_sym = {}
for token in gmgn_sol_trending + gmgn_bsc_trending:
    address = token.get("address", "")
    symbol = token.get("symbol", "").upper()
    if address and symbol:
        gmgn_addr_to_sym[address] = symbol
        gmgn_addr_to_sym[symbol] = token

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
    gmgn_token = cand_metadata.get("gmgn_data", {})
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
        gmgn_token=gmgn_token,
        gmgn_security_score_fn=gmgn_security_score,
        klines_4h=klines_4h,
        klines_1d=klines_1d,
        oi=oi,
        equity=account_equity,
        alt_rotation=alt_rotation,
        tradable=cand.get("tradable_on_cex", True),
        market_type=cand.get("market_type", "cex_perp"),
        mapping_confidence=cand.get("mapping_confidence", "native"),
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
    gmgn_token = cand_metadata.get("gmgn_data", {})
    result = score_candidate(
        symbol=coin,
        ticker=None,
        funding=None,
        alpha={},
        klines=None,
        btc_dir=btc_dir,
        missing_fields=["atr14", "trend", "oi", "fundingRate", "volume"],
        settings=SETTINGS,
        gmgn_token=gmgn_token,
        gmgn_security_score_fn=gmgn_security_score,
        tradable=False,
        market_type=cand.get("market_type", "layer0_watch"),
        mapping_confidence=cand.get("mapping_confidence", "none"),
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

report_lines = [
    "# 🦊 妖币雷达 Phase 2.0 扫描报告（Obsidian 对齐版）",
    f"> 扫描时间：{TS}",
    "> **融合思路**：对齐 Obsidian 知识库五大模块（25/30/20/15/10），扩展 7 条硬否决，接入 OI 四象限与双周期验证。",
    "",
    "## Executive Summary",
    "",
    *summary_lines,
    "",
    "## 📊 大盘环境",
    "",
    "| 指标 | 数值 | 方向 | 数据来源 |",
    "|---|---|---:|---|",
    f"| BTC 价格 | ${btc_price:.2f} | {arrow} | {btc_source} |",
    f"| BTC 24h涨跌 | {btc_chg:+.2f}% | — | {btc_source} |",
    f"| 市场判断 | {market_bias} | — | {btc_source} |",
    f"| 账户权益 | ${account_equity:,.2f} | — | okx |" if account_equity > 0 else "| 账户权益 | N/A | — | okx |",
    "",
    "## 🎯 合约建议",
    "",
]

if recommendations:
    report_lines += [
        "| 排名 | 币种 | 方向 | 置信度 | 入场区间 | 止损 | 止盈1 | 止盈2 | 仓位建议 |",
        "|---|---|---|---|---:|---|---|---|---|",
    ]
    for index, item in enumerate(recommendations, 1):
        plan = item["trade_plan"]
        direction_label = "🟢 做多" if item["direction"] == "long" else "🔴 做空"
        ps_text = item.get("position_size", "")
        if plan and plan.get("position_size_usd"):
            ps_text = f"${plan['position_size_usd']:,.0f} USDT"
        report_lines.append(
            f"| {index} | **{item['name']}** | {direction_label} | {item['confidence']:.0f} | "
            f"${plan['entry_low']:.6g} - ${plan['entry_high']:.6g} | "
            f"${plan['stop_loss']:.6g} | ${plan['take_profit_1']:.6g} | "
            f"${plan['take_profit_2']:.6g} | {ps_text} |"
        )
    report_lines.append("")
    for item in recommendations:
        report_lines.append(f"### {item['name']} {('做多' if item['direction'] == 'long' else '做空')}")
        report_lines.append("")
        report_lines.append(f"- 置信度: `{item['confidence']:.0f}`")
        if item.get("trade_plan"):
            report_lines.append(f"- R:R: `{item['trade_plan']['rr']:.2f}`")
        for reason in item.get("entry_reasons", [])[:3]:
            report_lines.append(f"- 入场理由: {reason}")
        for rule in item["hit_rules"][:3]:
            report_lines.append(f"- ✅ {rule}")
        if item["miss_rules"]:
            report_lines.append(f"- ⚠️ 风险: {item['miss_rules'][0]}")
        if item.get("needs_manual_review"):
            report_lines.append(f"- 🔶 需人工复核: 缺失字段 {', '.join(item['missing_fields'])}")
        report_lines.append("")
else:
    report_lines += [
        "> ⚠️ 本次没有满足“合约可执行建议”门槛的币种。",
        f"> 当前门槛：总分 >= {SETTINGS.min_recommend_score:.0f}，方向偏置 >= {SETTINGS.min_direction_bias:.0f}，方向差值 >= {SETTINGS.min_direction_gap:.0f}。",
        "",
    ]

if gmgn_sol_pass:
    report_lines += [
        "## 🚀 GMGN Chain层机会板块（Layer 0 — 非Binance合约）",
        "",
        "> ⚠️ **Layer 0 声明**：以下代币为链上代币，未在 OKX/Binance 上线合约，仅供情绪/聪明钱跟踪观察，**不能直接做合约交易**。",
        "",
        "### 🟢 聪明钱共振代币（GMGN smart_degen_count ≥ 3）",
        "",
        "| 评级 | 代币 | Chain | 价格 | 1h涨跌 | 聪明钱 | KOL | Rug | GMGN信号 |",
        "|---|---|---|---|---:|---:|---:|---:|---|",
    ]
    for token in gmgn_sm_resonance[:5]:
        rug = f"{token['rug_ratio']:.2f}" if token.get("rug_ratio") is not None else "N/A"
        tag = token["gmgn_tag"] or "⚪"
        report_lines.append(
            f"| ⭐ | **{token['symbol']}** | SOL | ${token['price']:.6g} | **{token['chg1h']:+.1f}%** | "
            f"{token['smart_degen_count']} | {token['renowned_count']} | {rug} | {tag} |"
        )

    report_lines += [
        "",
        "### 📈 GMGN SOL 热门代币 TOP10（安全过滤后）",
        "",
        "| 代币 | 名称 | 价格 | 1h涨跌 | 成交量 | Rug | 聪明钱 | KOL |",
        "|---|---|---|---|---:|---:|---:|---:|",
    ]
    for token in gmgn_sol_pass[:10]:
        rug = f"{token['rug_ratio']:.2f}" if token.get("rug_ratio") is not None else "—"
        report_lines.append(
            f"| **{token['symbol']}** | {token['name'][:15]} | ${token['price']:.6g} | {token['chg1h']:+.1f}% | "
            f"${token['vol'] / 1e6:.1f}M | {rug} | {token['smart_degen_count']} | {token['renowned_count']} |"
        )

    if gmgn_trenches_sol:
        report_lines += [
            "",
            "### 🆕 GMGN SOL Pump.fun 新上线代币",
            "",
            "| 代币 | 流动性 | 成交量 | Rug | 聪明钱 | KOL |",
            "|---|---|---:|---:|---:|---:|",
        ]
        for token in gmgn_trenches_sol[:8]:
            report_lines.append(
                f"| **{token.get('symbol', '')}** | "
                f"${float(token.get('liquidity', 0)) / 1000:.0f}K | "
                f"${float(token.get('volume_1h', 0)) / 1000:.0f}K | "
                f"{float(token.get('rug_ratio', 0)):.2f} | "
                f"{int(token.get('smart_degen_count', 0))} | "
                f"{int(token.get('renowned_count', 0))} |"
            )

    if gmgn_signals:
        report_lines += [
            "",
            "### 💰 GMGN 实时聪明钱信号（Smart Degen Buy）",
            "",
            "| 时间 | 代币地址 | 触发时市值 | 当前市值 | 信号类型 |",
            "|---|---|---:|---:|---|",
        ]
        for signal in gmgn_signals[:8]:
            ts = signal.get("trigger_at", 0)
            try:
                time_label = datetime.fromtimestamp(ts).strftime("%H:%M") if ts else "N/A"
            except Exception:
                time_label = str(ts)[:8]
            address = signal.get("token_address", "")[:8] + "..."
            trigger_mc = signal.get("trigger_mc", 0)
            market_cap = signal.get("market_cap", 0)
            signal_type = signal.get("signal_type", "")
            signal_name = {12: "SmartDegenBuy", 13: "PlatformCall"}.get(int(signal_type), signal_type)
            report_lines.append(
                f"| {time_label} | `{address}` | ${trigger_mc / 1000:.0f}K | ${market_cap / 1000:.0f}K | {signal_name} |"
            )
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
for index, (symbol, data) in enumerate(top_alpha[:10], 1):
    report_lines.append(
        f"| {index} | **{symbol}** | {data['count24h']:,} | {data['pct']:+.1f}% | binance-alpha |"
    )

report_lines += [
    "",
    "## 🏆 机会队列（Obsidian 五大模块）",
    "",
    "| 评级 | 币种 | 方向 | 总分 | 置信度 | 可执行 | 安全 | 量价 | 链上 | 社交 | 环境 | 数据来源 |",
    "|---|---|---|---|---:|---|---:|---:|---:|---:|---:|---|",
]
for item in top_candidates:
    modules = item["module_scores"]
    direction_emoji = "🟢" if item["direction"] == "long" else "🔴"
    base_source = item.get("meta", {}).get("ticker_source") or item.get("meta", {}).get("funding_source") or "binance"
    source = f"{base_source} + gmgn" if item.get("meta", {}).get("gmgn", {}).get("smart_degen_count", 0) else base_source
    decision_label = "妖币" if item["decision"] == "monster_candidate" else "观察"
    report_lines.append(
        f"| {item['grade_label']} | **{item['name']}** | {direction_emoji}{item['direction']} | "
        f"**{item['total']}** | {item['confidence']:.0f} | "
        f"{'是' if item.get('can_enter') else '否'}({decision_label}) | "
        f"{modules['safety_liquidity']} | {modules['price_volume']} | "
        f"{modules['onchain_smart_money']} | {modules['social_narrative']} | "
        f"{modules['market_regime']} | {source} |"
    )

report_lines.append("")
for index, item in enumerate(top_candidates[:3]):
    meta = item["meta"]
    direction_label = "🟢做多" if item["direction"] == "long" else "🔴做空"
    price = meta["price"]
    chg = meta["chg"]
    fr = meta["fr"]
    atr = meta["atr_pct"]
    gmgn_meta = meta.get("gmgn", {})
    plan = item.get("trade_plan") or {}
    ticker_source = meta.get("ticker_source", "binance")
    funding_source = meta.get("funding_source", "binance")
    kline_source = meta.get("kline_source", "binance")
    trend_4h = meta.get("trend_4h")

    if price > 0:
        if item["direction"] == "long":
            fallback_stop = f"{price * 0.95:.6g}"
            fallback_target = f"{price * 1.15:.6g}"
        else:
            fallback_stop = f"{price * 1.08:.6g}"
            fallback_target = f"{price * 0.85:.6g}"
    else:
        fallback_stop = "N/A"
        fallback_target = "N/A"

    if plan:
        entry_text = f"${plan['entry_low']:.6g} - ${plan['entry_high']:.6g}"
        stop_text = f"${plan['stop_loss']:.6g}"
        tp1_text = f"${plan['take_profit_1']:.6g}"
        tp2_text = f"${plan['take_profit_2']:.6g}"
    else:
        entry_text = str(price)
        stop_text = fallback_stop
        tp1_text = fallback_target
        tp2_text = None

    report_lines += [
        f"#### {MEDALS[index]} **{item['name']}** — {direction_label} — 评分：**{item['total']}** {item['grade_label']}",
        "",
        f"- 置信度: `{item['confidence']:.0f}`",
    ]
    if plan.get("rr"):
        report_lines.append(f"- R:R: `{plan['rr']:.2f}`")
    for reason in item.get("entry_reasons", [])[:3]:
        report_lines.append(f"- 入场理由: {reason}")
    report_lines += [
        "",
        "| 指标 | 数值 | 得分 | 数据来源 |",
        "|---|---|---:|---|",
        f"| 当前价格 | ${price:.4g} | — | {ticker_source}-ticker |",
        f"| 24h涨跌 | {chg:+.2f}% | — | {ticker_source}-ticker |",
        f"| 资金费率 | {fr:+.4f}% | {item['module_scores']['onchain_smart_money']//2} | {funding_source}-funding |",
        f"| ATR14 | {f'{atr * 100:.2f}%' if atr is not None else 'N/A'} | {item['module_scores']['price_volume']//2} | {kline_source}-klines |",
        f"| 1H趋势 | {meta.get('trend', 'N/A')} | — | {kline_source}-klines |",
        f"| 4H趋势 | {trend_4h or 'N/A'} | — | {kline_source}-klines |",
        f"| Alpha count24h | {meta['count24h']:,} | {item['module_scores']['social_narrative']} | binance-alpha |",
        f"| 市场环境 | {meta['regime']} | {item['module_scores']['market_regime']} | okx-btc-status |",
    ]
    if meta.get("oi"):
        oi_info = meta["oi"]
        report_lines.append(
            f"| **OI变化** | {oi_info.get('oi_change_pct', 0):+.1f}% | — | binance-oi |"
        )
    if gmgn_meta.get("gmgn_tag"):
        report_lines.append(
            f"| **GMGN安全** | rug={gmgn_meta.get('rug_ratio')}, top10={gmgn_meta.get('top_10_holder_rate')}, "
            f"SM={gmgn_meta.get('smart_degen_count', 0)} | +GMGN | gmgn-market |"
        )
    if item.get("needs_manual_review"):
        report_lines.append(f"| **⚠️ 需复核** | 缺失: {', '.join(item['missing_fields'])} | — | — |")

    report_lines.append("")
    for rule in item["hit_rules"][:5]:
        report_lines.append(f"- ✅ {rule}")
    for rule in item["miss_rules"][:3]:
        report_lines.append(f"- ❌ {rule}")
    if item["missing_fields"]:
        report_lines.append(f"- ⚠️ 缺失: {', '.join(item['missing_fields'])}")
    if item.get("risk_notes"):
        for note in item["risk_notes"][:3]:
            report_lines.append(f"- 🔶 {note}")

    report_lines += [
        "",
        f"**入场** {entry_text}",
        f"**止损** {stop_text}",
        f"**止盈1** {tp1_text}",
    ]
    if tp2_text:
        report_lines.append(f"**止盈2** {tp2_text}")
    if plan and plan.get("position_size_usd"):
        report_lines.append(f"**仓位** ${plan['position_size_usd']:,.0f} USDT @ 杠杆")
    else:
        report_lines.append(f"**仓位** {item['position_size']}")
    report_lines += [
        "",
    ]

if all_rejected:
    report_lines += [
        "## ❌ 安全否决区",
        "",
        "| 币种 | 拒绝原因 |",
        "|---|---|",
    ]
    for item in all_rejected[:10]:
        report_lines.append(f"| {item['name']} | {'; '.join(item.get('reject_reasons', item.get('miss_rules', []))) or 'Binance无数据'} |")

report_lines += [
    "",
    "## 🧩 项目改进说明",
    "",
    "- **Obsidian 五大模块对齐**：安全25 / 量价趋势30 / 链上聪明钱20 / 社交15 / 环境10",
    "- **7条硬否决扩展**：新增合约高危权限、流动性<$50K、部署者>10%、前十>35%、刷量检测",
    "- **OI 四象限**：接入 Binance open-interest 历史数据，计算 OI 变化方向",
    "- **双周期验证**：同时拉取 4H K 线，共振加分 / 矛盾扣分",
    "- **R:R 校验**：交易计划默认校验 >= 1.5，否则降级为观察",
    "- **精确仓位**：基于 OKX 账户权益 × 止损幅度计算建议开仓量",
    "- **缺失字段降级**：核心字段缺失 >3 项强制上限 74 分，任意缺失标记人工复核",
    "- **标准 JSON 输出**：同时生成 `result.json`，便于数据库/监控接入",
    "",
    "## 📋 Provider 架构说明",
    "",
    "| Step | 数据内容 | Skill | CLI/API |",
    "|---:|---|---|---|",
    "| 0 | BTC 大盘状态 | okx-cex-market | okx market ticker BTC-USDT-SWAP |",
    "| 0.5 | 社区活跃度 | binance | binance-cli alpha token-list |",
    "| 0.75 | 账户权益 | okx-cex-market | okx account balance |",
    "| 1 | 全量 SWAP tickers | okx-cex-market | okx market tickers SWAP |",
    "| 2 | ticker + funding + 1H/4H K线 + OI | binance + fallback | binance-cli futures-usds / public fallback |",
    "| G1 | GMGN SOL 热门代币 | gmgn-market | npx gmgn-cli market trending |",
    "| G2 | GMGN BSC 热门代币 | gmgn-market | npx gmgn-cli market trending |",
    "| G3 | GMGN 聪明钱信号 | gmgn-market | GMGN API |",
    "| G4 | GMGN Pump.fun 新代币 | gmgn-market | npx gmgn-cli market trenches |",
    "| 3 | 五大模块评分 | 本地逻辑 | Python radar_logic.py |",
    "",
    "*⚠️ 本报告仅供参考，不构成投资建议。DYOR！*",
    f"*数据路径：{SCAN_DIR}/*",
    f"*Phase 2.0 (Obsidian aligned) — {datetime.now().strftime('%Y-%m-%d')}*",
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
        "total_score": item.get("total_score", item.get("total", 0)),
        "module_scores": {
            k: v for k, v in item.get("module_scores", {}).items()
            if not k.startswith("m") or k in ["m1_safety", "m2", "m3", "m4", "m5", "m6"]
        },
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
        "relative_metrics": item.get("relative_metrics", {}),
        "trade_plan": {
            k: v for k, v in (plan or {}).items()
            if k not in ("entry_low", "entry_high", "stop_loss", "take_profit_1", "take_profit_2")
        } if plan else None,
    })

save("result.json", json.dumps(json_results, indent=2, ensure_ascii=False, default=str))

print("=== 妖币雷达 Phase 2.0 扫描完成 ===")
print(f"目录: {SCAN_DIR}")
print(f"报告: {report_path}")
print(f"JSON: {SCAN_DIR / 'result.json'}")
print("")
print("🏆 机会队列 TOP" + str(len(top_candidates)) + ":")
for index, item in enumerate(top_candidates[: SETTINGS.top_n]):
    direction_emoji = "🟢" if item["direction"] == "long" else "🔴"
    gmgn_tag = (item["meta"].get("gmgn") or {}).get("gmgn_tag", "")
    tag_suffix = f" [{gmgn_tag}]" if gmgn_tag and gmgn_tag != "⚪ 无GMGN数据" else ""
    decision_label = "妖币" if item["decision"] == "monster_candidate" else "观察"
    print(
        f"  {MEDALS[index]} {item['name']} {direction_emoji}{item['direction']} "
        f"评分:{item['total']} conf:{item['confidence']:.0f} {item['grade_label']} [{decision_label}]{tag_suffix}"
    )
if gmgn_sm_resonance:
    print(f"🚀 GMGN 聪明钱共振: {', '.join(token['symbol'] for token in gmgn_sm_resonance[:5])}")
