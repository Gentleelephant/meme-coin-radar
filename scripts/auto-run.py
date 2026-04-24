#!/usr/bin/env python3
"""
妖币雷达 Phase 2.0 — Provider + Radar Logic 版
用法: python3 scripts/auto-run.py
数据输出: ~/meme-radar/scan_YYYYMMDD_HHMMSS/

本版本融合了 crypto-signal-radar 的优点:
  - 配置从 Settings 统一加载，便于调参和环境切换
  - 评分逻辑下沉到独立模块，方便测试和复用
  - 报告增加执行摘要、置信度和入场理由，便于快速决策
"""

from __future__ import annotations

import json
import os
from datetime import datetime

from config import load_settings
from radar_logic import build_trade_plan, score_candidate
from skill_dispatcher import (
    batch_binance,
    binance_alpha,
    gmgn_security_score,
    gmgn_signal,
    gmgn_trending,
    gmgn_trenches,
    load_gmgn_key,
    okx_btc_status,
    okx_swap_tickers,
)


SETTINGS = load_settings()
DATA_DIR = SETTINGS.output_dir
DATA_DIR.mkdir(parents=True, exist_ok=True)
TS = datetime.now().strftime("%Y%m%d_%H%M%S")
SCAN_DIR = DATA_DIR / f"scan_{TS}"
SCAN_DIR.mkdir(parents=True, exist_ok=True)
MEDALS = ["🥇", "🥈", "🥉", "4.", "5.", "6.", "7.", "8."]


def save(name: str, content: str) -> str:
    path = SCAN_DIR / name
    path.write_text(content, encoding="utf-8")
    return str(path)


print("=== 妖币雷达 Phase 2.0 扫描（Provider + Radar Logic）===")
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
save("04_binance_alpha.json", json.dumps(alpha_dict, indent=2, ensure_ascii=False))
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

# Step 1: OKX 全量 SWAP
print("[1] 全量 SWAP tickers... (okx-cex-market: okx market tickers SWAP)")
all_tickers = okx_swap_tickers()
save("01_all_tickers.json", json.dumps(all_tickers, indent=2, default=str, ensure_ascii=False))
print(f"  解析到 {len(all_tickers)} 个 USDT-M SWAP")

# Step 2: Binance provider batch
all_tickers.sort(key=lambda item: item["chg24h_pct"], reverse=True)
anomaly_syms = [coin["symbol"] for coin in all_tickers[:20] + all_tickers[-20:]]
alpha_top_syms = [symbol for symbol, _ in top_alpha[:15]]
key_coins = list(SETTINGS.key_coins)
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
save(
    "02_binance_batch.json",
    json.dumps(
        {
            key: {
                "ticker": value["ticker"],
                "funding": value["funding"],
                "has_klines": value["klines"] is not None,
            }
            for key, value in bnc_results.items()
        },
        indent=2,
        default=str,
        ensure_ascii=False,
    ),
)

# GMGN -> Symbol 映射
gmgn_addr_to_sym = {}
for token in gmgn_sol_trending + gmgn_bsc_trending:
    address = token.get("address", "")
    symbol = token.get("symbol", "").upper()
    if address and symbol:
        gmgn_addr_to_sym[address] = symbol
        gmgn_addr_to_sym[symbol] = token

# Step 3: 评分
print("[3] 六大模块评分...")
scored = []
for coin in check_coins:
    provider_data = bnc_results.get(coin, {})
    ticker = provider_data.get("ticker")
    funding = provider_data.get("funding")
    klines = provider_data.get("klines")
    alpha = alpha_dict.get(coin.upper(), {})

    if ticker is None and funding is None:
        print(f"  {coin}: Binance无数据，跳过")
        continue

    gmgn_token = gmgn_addr_to_sym.get(coin.upper(), {})
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
    )
    result["name"] = coin
    result["trade_plan"] = build_trade_plan(result)
    scored.append(result)

valid = [item for item in scored if item["decision"] != "reject"]
valid.sort(key=lambda item: item["total"], reverse=True)
top_candidates = valid[: SETTINGS.top_n]
recommendations = [item for item in valid if item.get("can_enter")][: SETTINGS.recommendation_top_n]
all_rejected = [item for item in scored if item["decision"] == "reject"]
print(f"  候选总数={len(scored)}, 有效={len(valid)}, 拒绝={len(all_rejected)}")
for item in top_candidates[:3]:
    modules = item["module_scores"]
    print(
        f"  {item['name']}: 总={item['total']} | 安={modules['m1_safety']} 量={modules['m2']} "
        f"趋={modules['m3']} 社={modules['m4']} 环={modules['m5']} 费={modules['m6']} "
        f"→ {item['direction']} conf={item['confidence']}"
    )

top_ready = recommendations[:3]
top_watch = [item for item in valid if not item.get("can_enter")][:3]
summary_lines = [
    f"- 扫描候选 {len(scored)} 个，进入观察池 {len(valid)} 个，可执行建议 {len(recommendations)} 个。",
    f"- 市场环境判断为 `{btc_dir}`，BTC 24h 涨跌 `{btc_chg:+.2f}%`，当前偏向 `{market_bias}`。",
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
    "# 🦊 妖币雷达 Phase 2.0 扫描报告",
    f"> 扫描时间：{TS}",
    "> **融合思路**：保留当前项目的多 provider 数据获取能力，并引入 crypto-signal-radar 的配置化、纯逻辑评分和执行摘要结构。",
    "",
    "## Executive Summary",
    "",
    *summary_lines,
    "",
    "## 📊 大盘环境",
    "",
    "| 指标 | 数值 | 方向 | 数据来源 |",
    "|---|---:|---|---|",
    f"| BTC 价格 | ${btc_price:.2f} | {arrow} | {btc_source} |",
    f"| BTC 24h涨跌 | {btc_chg:+.2f}% | — | {btc_source} |",
    f"| 市场判断 | {market_bias} | — | {btc_source} |",
    "",
    "## 🎯 合约建议",
    "",
]

if recommendations:
    report_lines += [
        "| 排名 | 币种 | 方向 | 置信度 | 入场区间 | 止损 | 止盈1 | 止盈2 | 仓位建议 |",
        "|---|---|---|---:|---|---|---|---|---|",
    ]
    for index, item in enumerate(recommendations, 1):
        plan = item["trade_plan"]
        direction_label = "🟢 做多" if item["direction"] == "long" else "🔴 做空"
        report_lines.append(
            f"| {index} | **{item['name']}** | {direction_label} | {item['confidence']:.0f} | "
            f"${plan['entry_low']:.6g} - ${plan['entry_high']:.6g} | "
            f"${plan['stop_loss']:.6g} | ${plan['take_profit_1']:.6g} | "
            f"${plan['take_profit_2']:.6g} | {item['position_size']} |"
        )
    report_lines.append("")
    for item in recommendations:
        report_lines.append(f"### {item['name']} {('做多' if item['direction'] == 'long' else '做空')}")
        report_lines.append("")
        report_lines.append(f"- 置信度: `{item['confidence']:.0f}`")
        for reason in item.get("entry_reasons", [])[:3]:
            report_lines.append(f"- 入场理由: {reason}")
        for rule in item["hit_rules"][:3]:
            report_lines.append(f"- ✅ {rule}")
        if item["miss_rules"]:
            report_lines.append(f"- ⚠️ 风险: {item['miss_rules'][0]}")
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
        "|---|---|---|---:|---:|---:|---:|---:|",
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
            "|---|---|---|---:|---:|---:|",
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
            "|---|---:|---:|---:|---|",
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
    "## 🏆 机会队列（Provider + Radar Logic）",
    "",
    "| 评级 | 币种 | 方向 | 总分 | 置信度 | 可执行 | 安全 | 量价 | 趋势 | 社交 | 环境 | 费率 | 数据来源 |",
    "|---|---|---|---:|---:|---|---:|---:|---:|---:|---:|---:|---|",
]
for item in top_candidates:
    modules = item["module_scores"]
    direction_emoji = "🟢" if item["direction"] == "long" else "🔴"
    base_source = item.get("meta", {}).get("ticker_source") or item.get("meta", {}).get("funding_source") or "binance"
    source = f"{base_source} + gmgn" if item.get("meta", {}).get("gmgn", {}).get("smart_degen_count", 0) else base_source
    report_lines.append(
        f"| {item['grade_label']} | **{item['name']}** | {direction_emoji}{item['direction']} | "
        f"**{item['total']}** | {item['confidence']:.0f} | "
        f"{'是' if item.get('can_enter') else '否'} | {modules['m1_safety']} | {modules['m2']} | "
        f"{modules['m3']} | {modules['m4']} | {modules['m5']} | {modules['m6']} | {source} |"
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
    for reason in item.get("entry_reasons", [])[:3]:
        report_lines.append(f"- 入场理由: {reason}")
    report_lines += [
        "",
        "| 指标 | 数值 | 得分 | 数据来源 |",
        "|---|---|---:|---|",
        f"| 当前价格 | ${price:.4g} | — | {ticker_source}-ticker |",
        f"| 24h涨跌 | {chg:+.2f}% | — | {ticker_source}-ticker |",
        f"| 资金费率 | {fr:+.4f}% | {item['module_scores']['m6']} | {funding_source}-funding |",
        f"| ATR14 | {f'{atr * 100:.2f}%' if atr is not None else 'N/A'} | {item['module_scores']['m3'] // 2} | {kline_source}-klines |",
        f"| Alpha count24h | {meta['count24h']:,} | {item['module_scores']['m4']} | binance-alpha |",
        f"| 市场环境 | {meta['regime']} | {item['module_scores']['m5']} | okx-btc-status |",
    ]
    if gmgn_meta.get("gmgn_tag"):
        report_lines.append(
            f"| **GMGN安全** | rug={gmgn_meta.get('rug_ratio')}, top10={gmgn_meta.get('top_10_holder_rate')}, "
            f"SM={gmgn_meta.get('smart_degen_count', 0)} | +GMGN | gmgn-market |"
        )

    report_lines.append("")
    for rule in item["hit_rules"][:5]:
        report_lines.append(f"- ✅ {rule}")
    for rule in item["miss_rules"][:3]:
        report_lines.append(f"- ❌ {rule}")
    if item["missing_fields"]:
        report_lines.append(f"- ⚠️ 缺失: {', '.join(item['missing_fields'])}")

    report_lines += [
        "",
        f"**入场** {entry_text}",
        f"**止损** {stop_text}",
        f"**止盈1** {tp1_text}",
    ]
    if tp2_text:
        report_lines.append(f"**止盈2** {tp2_text}")
    report_lines += [
        f"**仓位** {item['position_size']}",
        "",
    ]

if all_rejected:
    report_lines += [
        "## ❌ 安全否决区",
        "",
        "| 币种 | 拒绝原因 |",
        "|---|---|",
    ]
    for item in all_rejected[:5]:
        report_lines.append(f"| {item['name']} | {'; '.join(item['miss_rules']) or 'Binance无数据'} |")

report_lines += [
    "",
    "## 🧩 融合后的项目优势",
    "",
    "- 当前项目保留了 `provider/fallback` 架构，能在 Binance 不可用时自动降级。",
    "- `crypto-signal-radar` 的配置化和纯逻辑评分已经接入，阈值不再散落在主脚本里。",
    "- 报告增加了执行摘要、置信度和入场理由，更接近实际交易决策流。",
    "- 新增基础单元测试，后续改评分逻辑时更不容易回归。",
    "",
    "## 📋 Provider 架构说明",
    "",
    "| Step | 数据内容 | Skill | CLI/API |",
    "|---:|---|---|---|",
    "| 0 | BTC 大盘状态 | okx-cex-market | okx market ticker BTC-USDT-SWAP |",
    "| 0.5 | 社区活跃度 | binance | binance-cli alpha token-list |",
    "| 1 | 全量 SWAP tickers | okx-cex-market | okx market tickers SWAP |",
    "| 2 | ticker / funding / klines | binance + fallback | binance-cli futures-usds / public fallback |",
    "| G1 | GMGN SOL 热门代币 | gmgn-market | npx gmgn-cli market trending |",
    "| G2 | GMGN BSC 热门代币 | gmgn-market | npx gmgn-cli market trending |",
    "| G3 | GMGN 聪明钱信号 | gmgn-market | GMGN API |",
    "| G4 | GMGN Pump.fun 新代币 | gmgn-market | npx gmgn-cli market trenches |",
    "| 3 | 六大模块评分 | 本地逻辑 | Python radar_logic.py |",
    "",
    "*⚠️ 本报告仅供参考，不构成投资建议。DYOR！*",
    f"*数据路径：{SCAN_DIR}/*",
    f"*Phase 2.0 — {datetime.now().strftime('%Y-%m-%d')}*",
]

report_path = SCAN_DIR / "report.md"
report_path.write_text("\n".join(report_lines), encoding="utf-8")

print("=== 妖币雷达 Phase 2.0 扫描完成 ===")
print(f"目录: {SCAN_DIR}")
print(f"报告: {report_path}")
print("")
print("🏆 机会队列 TOP" + str(len(top_candidates)) + ":")
for index, item in enumerate(top_candidates[: SETTINGS.top_n]):
    direction_emoji = "🟢" if item["direction"] == "long" else "🔴"
    gmgn_tag = (item["meta"].get("gmgn") or {}).get("gmgn_tag", "")
    tag_suffix = f" [{gmgn_tag}]" if gmgn_tag and gmgn_tag != "⚪ 无GMGN数据" else ""
    print(
        f"  {MEDALS[index]} {item['name']} {direction_emoji}{item['direction']} "
        f"评分:{item['total']} conf:{item['confidence']:.0f} {item['grade_label']}{tag_suffix}"
    )
if gmgn_sm_resonance:
    print(f"🚀 GMGN 聪明钱共振: {', '.join(token['symbol'] for token in gmgn_sm_resonance[:5])}")
