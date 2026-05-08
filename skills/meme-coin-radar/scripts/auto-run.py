#!/usr/bin/env python3
"""
妖币雷达 Phase 3.0 — OnchainOS + Alpha + Paper Trade 执行版
用法:
  python3 scripts/auto-run.py --mode scan
  python3 scripts/auto-run.py --mode monitor --symbols PEPE,WIF
数据输出: $XDG_STATE_HOME/meme-coin-radar/scan_YYYYMMDD_HHMMSS/
         或 ~/.local/state/meme-coin-radar/scan_YYYYMMDD_HHMMSS/
         若不可写则回退到系统临时目录

改进点:
  - OKX OnchainOS 主发现 + Binance Alpha/Execution 承接
  - OOS + ERS 双轴评分
  - 主流币 majors_cex 模式
  - Paper bracket orders（主单 + TP + SL）
  - 可选 Binance test-order 预校验
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime

from history_store import cleanup_old_snapshots, compute_relative_metrics, load_paper_positions, save_alpha_snapshot, save_social_snapshot, save_ticker_snapshot
from config import ensure_output_dir, load_settings
from asset_mapping import apply_to_candidates
from candidate_discovery import discover_candidates, get_cex_symbols
from execution_binance import execute_paper_bracket
from paper_analytics import compute_metrics
from paper_reconciler import reconcile_all_positions, ticks_from_klines
from paper_strategy_feedback import save_strategy_feedback
from providers.intel import build_shared_intel_context, fetch_social_intel
from radar_logic import build_trade_plan, score_candidate
from skill_dispatcher import (
    batch_binance,
    binance_alpha,
    binance_tradable_symbols,
    okx_account_equity,
    okx_btc_status,
    okx_hot_tokens,
    okx_signal_list,
    okx_swap_tickers,
    okx_token_snapshot,
    okx_tracker_activities,
    okx_wallet_status,
)
from versioning import load_project_version

OUTPUT_CONTRACT_VERSION = "1.0"
SUPPORTED_CONTRACT_VERSIONS = {"1.0"}


MODE_PROFILES = {
    "scan": {
        "label": "妖币扫描模式",
        "trigger": "触发词包含“跑妖币雷达 / 扫描妖币 / meme radar”，且未指定目标代币。",
        "cadence": "建议 15-60 分钟运行一次；高波动窗口可缩短到 5-15 分钟。",
        "result_focus": "输出全市场候选池、推荐池、观察池和拒绝原因，适合发现潜在妖币。",
    },
    "monitor": {
        "label": "指定代币监控模式",
        "trigger": "用户显式给出监控代币列表，或外部调度器用 `--mode monitor --symbols ...` 调用。",
        "cadence": "建议 1-5 分钟运行一次；做 T 时由外部循环持续调用。",
        "result_focus": "输出目标代币的跟踪评分、执行计划和持仓相关上下文，适合已有标的的节奏跟踪。",
    },
}


def _parse_symbol_csv(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    seen: list[str] = []
    for part in raw.split(","):
        symbol = part.strip().upper()
        if symbol and symbol not in seen:
            seen.append(symbol)
    return tuple(seen)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run meme-coin-radar in scan or target-monitor mode.")
    parser.add_argument("--mode", choices=sorted(MODE_PROFILES), default=None, help="Run mode. Defaults to RADAR_RUN_MODE or scan.")
    parser.add_argument("--symbols", default=None, help="Comma-separated target symbols for monitor mode.")
    parser.add_argument("--top-n", type=int, default=None, help="Override RADAR_TOP_N for this run.")
    parser.add_argument("--recommendation-top-n", type=int, default=None, help="Override RADAR_RECOMMENDATION_TOP_N for this run.")
    return parser.parse_args()


CLI_ARGS = _parse_args()
SETTINGS = load_settings()
if CLI_ARGS.top_n is not None:
    SETTINGS.top_n = CLI_ARGS.top_n
if CLI_ARGS.recommendation_top_n is not None:
    SETTINGS.recommendation_top_n = CLI_ARGS.recommendation_top_n
PROJECT_VERSION = load_project_version()
DATA_DIR = ensure_output_dir(SETTINGS.output_dir)
TS = datetime.now().strftime("%Y%m%d_%H%M%S")
SCAN_DIR = DATA_DIR / f"scan_{TS}"
SCAN_DIR.mkdir(parents=True, exist_ok=True)
MEDALS = ["🥇", "🥈", "🥉", "4.", "5.", "6.", "7.", "8."]
RUN_MODE = (CLI_ARGS.mode or SETTINGS.run_mode or "scan").strip().lower()
if RUN_MODE not in MODE_PROFILES:
    raise SystemExit(f"Unsupported run mode: {RUN_MODE}")
TARGET_SYMBOLS = _parse_symbol_csv(CLI_ARGS.symbols) or tuple(SETTINGS.target_symbols)
if RUN_MODE == "monitor" and not TARGET_SYMBOLS:
    raise SystemExit("monitor mode requires target symbols via --symbols or RADAR_TARGET_SYMBOLS")
MODE_PROFILE = MODE_PROFILES[RUN_MODE]


def save(name: str, content: str) -> str:
    path = SCAN_DIR / name
    path.write_text(content, encoding="utf-8")
    return str(path)


REQUIRED_CANDIDATE_FIELDS = ["symbol", "final_score", "oos", "ers", "decision", "direction"]


def validate_candidate(item: dict, path: str) -> list[str]:
    """Validate a single candidate has all required fields."""
    errors: list[str] = []
    for field in REQUIRED_CANDIDATE_FIELDS:
        if field not in item or item[field] is None:
            errors.append(f"{path}: missing required field '{field}'")
    return errors


def validate_output(data: list[dict]) -> tuple[bool, list[str]]:
    """Validate the output data has required field integrity."""
    errors: list[str] = []
    if not isinstance(data, list):
        errors.append("root: expected list of candidates")
        return False, errors

    for i, item in enumerate(data):
        item_errors = validate_candidate(item, f"candidates[{i}]")
        errors.extend(item_errors)

    return len(errors) == 0, errors


def check_contract_compatibility(version: str | None) -> bool:
    """Check if a contract version is compatible with the current output contract."""
    if version is None or version == "0.9":
        return False  # Pre-contract versions
    return version in SUPPORTED_CONTRACT_VERSIONS


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


def _prefix_status_fields(status_map: dict[str, dict], prefix: str) -> dict[str, dict]:
    return {f"{prefix}{key}": value for key, value in (status_map or {}).items()}


def _status_label(status: dict) -> str:
    if not isinstance(status, dict):
        return "unknown"
    if status.get("ok"):
        return "ok"
    error_type = status.get("error_type") or "unknown"
    message = str(status.get("message") or "").strip()
    return f"{error_type}{f' ({message})' if message else ''}"


def _print_onchain_diagnostics(status_map: dict[str, dict]) -> None:
    issues = []
    for name in ("hot_trending", "hot_x", "signals", "tracker"):
        status = status_map.get(name) or {}
        if not status.get("ok"):
            issues.append(f"{name}={_status_label(status)}")
    if issues:
        print(f"  ⚠️ OnchainOS诊断: {'; '.join(issues)}")


def _print_binance_batch_diagnostics(fetch_status: dict[str, dict], results: dict[str, dict]) -> None:
    timed_out: list[str] = []
    empty_assets: list[str] = []
    partial_assets: list[str] = []

    for symbol, status_map in fetch_status.items():
        if symbol.startswith("__"):
            continue
        if isinstance(status_map, dict) and status_map.get("_batch_error") == "timeout":
            timed_out.append(symbol)
            continue
        payload = results.get(symbol) or {}
        available_count = sum(
            1
            for field in ("ticker", "funding", "klines", "klines_4h", "klines_1d")
            if payload.get(field) is not None
        )
        if payload.get("oi") and isinstance(payload.get("oi"), dict) and payload["oi"].get("oi") is not None:
            available_count += 1
        if available_count == 0:
            empty_assets.append(symbol)
        elif available_count < 6:
            partial_assets.append(symbol)

    if timed_out:
        preview = ", ".join(timed_out[:6])
        suffix = "..." if len(timed_out) > 6 else ""
        print(f"  ⚠️ Binance batch超时: {len(timed_out)} 个标的未在60秒内完成，例如 {preview}{suffix}")
    if empty_assets:
        preview = ", ".join(empty_assets[:6])
        suffix = "..." if len(empty_assets) > 6 else ""
        print(f"  ⚠️ Binance无返回数据: {len(empty_assets)} 个标的全部字段为空，例如 {preview}{suffix}")
    if partial_assets:
        preview = ", ".join(partial_assets[:6])
        suffix = "..." if len(partial_assets) > 6 else ""
        print(f"  ℹ️ Binance部分缺数: {len(partial_assets)} 个标的只有部分字段成功，例如 {preview}{suffix}")


def _okx_attention_context(snapshot: dict) -> dict:
    signal_items = snapshot.get("signals", []) or []
    tracker_items = snapshot.get("tracker_items", []) or []
    return {
        "okx_x_rank": snapshot.get("okx_x_rank"),
        "kol_onchain_activity_count": sum(1 for item in signal_items if str(item.get("walletType") or "") == "2"),
        "smart_money_onchain_activity_count": len(tracker_items),
    }


print(f"=== 妖币雷达 v{PROJECT_VERSION} 扫描（OnchainOS + Alpha + Paper Trade）===")
print(f"时间: {TS}")
print(f"模式: {MODE_PROFILE['label']} ({RUN_MODE})")
if TARGET_SYMBOLS:
    print(f"目标: {', '.join(TARGET_SYMBOLS)}")

# Step -1: OnchainOS auth preflight
print("[-1] OnchainOS 登录态检查...")
okx_wallet = okx_wallet_status()
okx_wallet_ok = (okx_wallet.get("status") or {}).get("ok", False)
if not okx_wallet_ok:
    _preflight_err = (okx_wallet.get("status") or {}).get("error_type", "unknown")
    _preflight_msg = (okx_wallet.get("status") or {}).get("message", "")
    print(f"  ⚠️ OnchainOS 登录态检查失败 ({_preflight_err}): {_preflight_msg}")
    okx_logged_in = False
    okx_account_count = 0
else:
    okx_logged_in = (okx_wallet.get("data") or {}).get("loggedIn", False)
    okx_account_count = (okx_wallet.get("data") or {}).get("accountCount", 0)
    if not okx_logged_in:
        print("  ⚠️ OnchainOS 未登录，部分数据可能不可用")
    else:
        print(f"  ✅ OnchainOS 已登录 ({okx_account_count} 个账户)")

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
okx_hot_trending, okx_hot_trending_status = okx_hot_tokens(ranking_type=4, chain="solana", limit=20, time_frame=4, include_status=True)
okx_hot_x, okx_hot_x_status = okx_hot_tokens(ranking_type=5, chain="solana", limit=20, time_frame=4, include_status=True)
okx_signals, okx_signals_status = okx_signal_list(chain="solana", wallet_type="1,2,3", limit=20, include_status=True)
okx_tracker, okx_tracker_status = okx_tracker_activities(tracker_type="smart_money", chain="solana", trade_type=1, limit=50, include_status=True)
save("05_okx_hot_trending.json", json.dumps(okx_hot_trending, indent=2, default=str, ensure_ascii=False))
save("06_okx_hot_x.json", json.dumps(okx_hot_x, indent=2, default=str, ensure_ascii=False))
save("07_okx_signals.json", json.dumps(okx_signals, indent=2, default=str, ensure_ascii=False))
save("08_okx_tracker.json", json.dumps(okx_tracker, indent=2, default=str, ensure_ascii=False))

print(
    f"  OKX OnchainOS: trending={len(okx_hot_trending)}, "
    f"x_heat={len(okx_hot_x)}, signals={len(okx_signals)}, tracker={len(okx_tracker)}"
)
_print_onchain_diagnostics(
    {
        "hot_trending": okx_hot_trending_status,
        "hot_x": okx_hot_x_status,
        "signals": okx_signals_status,
        "tracker": okx_tracker_status,
    }
)
if okx_tracker_status.get("ok") and not okx_tracker:
    print("  ℹ️ tracker=0: 当前筛选条件为 solana + smart_money + buy-only，可能是该时间窗内无匹配交易")

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

print("[1c] Binance USDT 永续白名单...")
binance_symbol_whitelist, binance_symbol_whitelist_status = binance_tradable_symbols()
print(
    f"  Binance whitelist: {len(binance_symbol_whitelist)} symbols "
    f"[{'ok' if binance_symbol_whitelist_status.get('ok') else binance_symbol_whitelist_status.get('error_type', 'unknown')}]"
)

# Step 2: Unified candidate discovery (roadmap P0-3)
print("[2] 候选发现层...")
existing_positions = load_paper_positions(DATA_DIR)
existing_position_symbols = list(existing_positions.keys())
discovery_key_coins = list(dict.fromkeys(list(SETTINGS.key_coins) + list(TARGET_SYMBOLS)))
candidates = discover_candidates(
    okx_hot_tokens=okx_hot_trending,
    okx_x_tokens=okx_hot_x,
    okx_signals=okx_signals,
    okx_tracker_activities=okx_tracker,
    alpha_dict=alpha_dict,
    key_coins=discovery_key_coins,
    major_coins=list(SETTINGS.major_coins),
)
# P0-5: Asset mapping
cex_symbol_list = sorted(binance_symbol_whitelist) if binance_symbol_whitelist else [t["symbol"] for t in all_tickers]
enriched_candidates = apply_to_candidates(candidates, cex_symbol_list)
for cand in enriched_candidates:
    symbol = cand.get("symbol", "").upper()
    has_binance_execution = symbol in binance_symbol_whitelist if binance_symbol_whitelist else cand.get("tradable_on_cex", False)
    cand["has_binance_execution"] = has_binance_execution
    if not has_binance_execution:
        cand["tradable_on_cex"] = False
        if cand.get("market_type") == "cex_perp":
            cand["market_type"] = "watchlist"


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

if TARGET_SYMBOLS:
    target_symbol_set = set(TARGET_SYMBOLS)
    if RUN_MODE == "monitor":
        enriched_candidates = [c for c in enriched_candidates if c.get("symbol") in target_symbol_set]
    else:
        target_first = [c for c in enriched_candidates if c.get("symbol") in target_symbol_set]
        rest = [c for c in enriched_candidates if c.get("symbol") not in target_symbol_set]
        enriched_candidates = target_first + rest

# Separate tradable vs onchain
tradable_candidates = [c for c in enriched_candidates if c.get("tradable_on_cex")]
onchain_candidates = [c for c in enriched_candidates if not c.get("tradable_on_cex")]
cex_symbols = get_cex_symbols(candidates)  # native tradable symbols from discovery layer
mapped_cex_symbols = [c.get("symbol") for c in tradable_candidates if c.get("symbol")]
cex_symbols = list(dict.fromkeys(cex_symbols + mapped_cex_symbols + existing_position_symbols))
if binance_symbol_whitelist:
    cex_symbols = [symbol for symbol in cex_symbols if symbol in binance_symbol_whitelist]
if RUN_MODE == "monitor":
    target_symbol_set = set(TARGET_SYMBOLS)
    cex_symbols = [symbol for symbol in cex_symbols if symbol in target_symbol_set]

print(f"  发现候选: CEX可交易={len(tradable_candidates)}, 链上观察={len(onchain_candidates)}")

# Step 2a: Onchain snapshots for candidates with OKX addresses
print("[2a] OKX OnchainOS token snapshots...")
onchain_snapshots: dict[str, dict] = {}
# Lite snapshots for all candidates with addresses (price-info + advanced-info only)
lite_candidates = tradable_candidates + onchain_candidates[:10]
for cand in lite_candidates:
    meta = cand.get("metadata", {})
    address = meta.get("address") or cand.get("token_address")
    chain = meta.get("chain") or cand.get("chain")
    if not address:
        continue
    snapshot = okx_token_snapshot(address=address, chain=chain, depth="lite")
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

# Deep snapshots for all tradable candidates (risk gates require cluster/holders/trades)
# onchain-only candidates stay lite to reduce CLI churn
deep_candidates = tradable_candidates
for cand in deep_candidates:
    meta = cand.get("metadata", {})
    address = meta.get("address") or cand.get("token_address")
    chain = meta.get("chain") or cand.get("chain")
    if not address:
        continue
    sym = cand.get("symbol", address)
    deep = okx_token_snapshot(address=address, chain=chain, depth="deep")
    existing = onchain_snapshots.get(sym) or {}
    # Merge deep data into existing snapshot
    for key in ("cluster_overview", "cluster_top_holders", "holders", "trades"):
        existing[key] = deep.get(key)
        existing["status"] = existing.get("status") or {}
        existing["status"][key] = (deep.get("status") or {}).get(key)
    onchain_snapshots[sym] = existing
    meta["onchain_data"] = {**(meta.get("onchain_data") or {}), **existing}

save("11_onchain_snapshots.json", json.dumps(onchain_snapshots, indent=2, default=str, ensure_ascii=False))

# Step 2b: Binance batch for CEX candidates only
print(f"[2b] Binance batch ({len(cex_symbols)} tradable coins)...")
bnc_batch = batch_binance(cex_symbols)
bnc_results = bnc_batch["results"]
fetch_status = bnc_batch.get("fetch_status", {})
shared_intel_context = build_shared_intel_context(DATA_DIR, lang="en")
fetch_status["__onchain_discovery__"] = {
    "binance_tradable_symbols": binance_symbol_whitelist_status,
    "hot_trending": okx_hot_trending_status,
    "hot_x": okx_hot_x_status,
    "signals": okx_signals_status,
    "tracker": okx_tracker_status,
    "panews_rankings": {
        "ok": (shared_intel_context.get("panews_rankings") or {}).get("ok", False),
        "source": (shared_intel_context.get("panews_rankings") or {}).get("source", "panews-rankings"),
        "fetched_at": (shared_intel_context.get("panews_rankings") or {}).get("fetched_at", 0),
        "error_type": (shared_intel_context.get("panews_rankings") or {}).get("error_type"),
    },
    "panews_hooks": {
        "ok": (shared_intel_context.get("panews_hooks") or {}).get("ok", False),
        "source": (shared_intel_context.get("panews_hooks") or {}).get("source", "panews-hooks"),
        "fetched_at": (shared_intel_context.get("panews_hooks") or {}).get("fetched_at", 0),
        "error_type": (shared_intel_context.get("panews_hooks") or {}).get("error_type"),
    },
    "panews_polymarket": {
        "ok": (shared_intel_context.get("panews_polymarket") or {}).get("ok", False),
        "source": (shared_intel_context.get("panews_polymarket") or {}).get("source", "panews-polymarket-highlights"),
        "fetched_at": (shared_intel_context.get("panews_polymarket") or {}).get("fetched_at", 0),
        "error_type": (shared_intel_context.get("panews_polymarket") or {}).get("error_type"),
    },
    "macro_calendar": {
        "ok": (shared_intel_context.get("macro_calendar") or {}).get("ok", False),
        "source": (shared_intel_context.get("macro_calendar") or {}).get("source", "panews-calendar-macro"),
        "fetched_at": (shared_intel_context.get("macro_calendar") or {}).get("fetched_at", 0),
        "error_type": (shared_intel_context.get("macro_calendar") or {}).get("error_type"),
    },
}
for symbol, snapshot in onchain_snapshots.items():
    status_map = snapshot.get("status") or {}
    if not status_map:
        continue
    fetch_status.setdefault(symbol, {})
    fetch_status[symbol].update(_prefix_status_fields(status_map, "onchain_"))
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
                "ticker_ok": bool((value.get("_status", {}).get("ticker") or {}).get("ok")),
                "funding_ok": bool((value.get("_status", {}).get("funding") or {}).get("ok")),
                "klines_ok": bool((value.get("_status", {}).get("klines") or {}).get("ok")),
                "klines_4h_ok": bool((value.get("_status", {}).get("klines_4h") or {}).get("ok")),
                "klines_1d_ok": bool((value.get("_status", {}).get("klines_1d") or {}).get("ok")),
                "oi_ok": bool((value.get("_status", {}).get("oi") or {}).get("ok")),
                "oi_value": (value.get("oi") or {}).get("oi"),
                "oi_error_type": (value.get("_status", {}).get("oi") or {}).get("error_type"),
            }
            for key, value in bnc_results.items()
        },
        indent=2,
        default=str,
        ensure_ascii=False,
    ),
)

# P1-1: Data freshness check
scan_ts = int(datetime.now().timestamp())
freshness_report = _data_freshness_report(fetch_status, scan_ts)
freshness_summary = _format_freshness_summary(freshness_report)
print(f"  {freshness_summary}")
_print_binance_batch_diagnostics(fetch_status, bnc_results)

# Step 2c: Reconcile existing paper positions
reconcile_result = None
paper_metrics = None
if existing_position_symbols:
    print(f"[2c] Reconcile 模拟持仓 ({len(existing_position_symbols)} symbols)...")
    tick_map = {
        symbol: ticks_from_klines((bnc_results.get(symbol) or {}).get("klines"))
        for symbol in existing_position_symbols
    }
    reconcile_result = reconcile_all_positions(DATA_DIR, tick_map=tick_map)
    paper_metrics = reconcile_result.get("metrics")
    save("13_reconcile_result.json", json.dumps(reconcile_result, indent=2, default=str, ensure_ascii=False))
    print(
        f"  reconcile: updated={reconcile_result.get('updated_positions', 0)}, "
        f"closed={reconcile_result.get('closed_positions', 0)}"
    )

# Step 3: 评分
print("[3] Obsidian 五大模块评分...")
scored = []
social_intel_map: dict[str, dict] = {}

tradable_base_results: list[tuple[dict, dict, dict, dict]] = []
for cand in tradable_candidates:
    coin = cand.get("symbol", "")
    provider_data = bnc_results.get(coin, {})
    ticker = provider_data.get("ticker")
    funding = provider_data.get("funding")
    klines = provider_data.get("klines")
    klines_4h = provider_data.get("klines_4h")
    oi = provider_data.get("oi")
    alpha = alpha_dict.get(coin.upper(), {})
    klines_1d = provider_data.get("klines_1d")
    cand_metadata = cand.get("metadata", {})
    onchain_data = cand_metadata.get("onchain_data", {})
    if ticker is None and funding is None:
        print(f"  {coin}: Binance无数据，跳过")
        continue
    base_result = score_candidate(
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
        social_intel={},
        kline_source=((provider_data.get("_status") or {}).get("klines") or {}).get("source"),
    )
    tradable_base_results.append((cand, provider_data, alpha, base_result))

tradable_base_results.sort(key=lambda item: item[3].get("meta", {}).get("base_oos", 0), reverse=True)
intel_limit = max(1, len(tradable_base_results) // 2) if tradable_base_results else 0
intel_candidates = {
    item[0].get("symbol", "")
    for index, item in enumerate(tradable_base_results)
    if index < intel_limit or item[3].get("meta", {}).get("base_oos", 0) >= 45
}

for cand, _provider_data, _alpha, _base_result in tradable_base_results:
    coin = cand.get("symbol", "")
    if not coin or coin not in intel_candidates:
        continue
    cand_metadata = cand.get("metadata", {})
    onchain_data = cand_metadata.get("onchain_data", {})
    social_intel = fetch_social_intel(
        symbol=coin,
        output_dir=DATA_DIR,
        chain=cand.get("chain"),
        token_address=cand.get("token_address"),
        okx_context=_okx_attention_context(onchain_data),
        panews_context=shared_intel_context,
        lang="en",
    )
    social_intel_map[coin] = social_intel
    fetch_status.setdefault(coin, {})
    for source_name, source_status in (social_intel.get("status") or {}).items():
        fetch_status[coin][f"intel_{source_name}"] = source_status

if social_intel_map:
    save("15_social_intel.json", json.dumps(social_intel_map, indent=2, default=str, ensure_ascii=False))
    save_social_snapshot(DATA_DIR, social_intel_map)

save("09_fetch_status.json", json.dumps(fetch_status, indent=2, default=str, ensure_ascii=False))
scan_ts = int(datetime.now().timestamp())
freshness_report = _data_freshness_report(fetch_status, scan_ts)
save("10_data_freshness.json", json.dumps(freshness_report, indent=2, default=str, ensure_ascii=False))
freshness_summary = _format_freshness_summary(freshness_report)

# Score tradable CEX candidates
for cand, provider_data, alpha, _base_result in tradable_base_results:
    coin = cand.get("symbol", "")
    ticker = provider_data.get("ticker")
    funding = provider_data.get("funding")
    klines = provider_data.get("klines")
    klines_4h = provider_data.get("klines_4h")
    oi = provider_data.get("oi")

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
        social_intel=social_intel_map.get(coin, {}),
        kline_source=((provider_data.get("_status") or {}).get("klines") or {}).get("source"),
    )
    result["name"] = coin
    result["candidate_sources"] = cand.get("candidate_sources", [])
    result["relative_metrics"] = rel_metrics
    plan = build_trade_plan(result, equity=account_equity, settings=SETTINGS)
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
    f"- 当前版本 `v{PROJECT_VERSION}`。",
    f"- 运行模式 `{RUN_MODE}`（{MODE_PROFILE['label']}）。",
    f"- 扫描候选 {len(scored)} 个，进入观察池 {len(valid)} 个，可执行建议 {len(recommendations)} 个。",
    f"- 市场环境判断为 `{btc_dir}`，BTC 24h 涨跌 `{btc_chg:+.2f}%`，当前偏向 `{market_bias}`。",
    f"- {freshness_summary}。",
]
if TARGET_SYMBOLS:
    summary_lines.append("- 当前目标列表: " + "，".join(f"`{symbol}`" for symbol in TARGET_SYMBOLS) + "。")
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

execution_results = []
execution_mode = SETTINGS.execution_mode
if SETTINGS.auto_execute_paper_trades and recommendations:
    print(f"[4] 创建模拟交易订单... mode={execution_mode}")
    for item in recommendations:
        execution_result = execute_paper_bracket(
            item,
            output_dir=DATA_DIR,
            execution_mode=execution_mode,
            validate_with_binance=SETTINGS.validate_orders_with_binance,
        )
        item["execution_result"] = execution_result
        execution_results.append(execution_result)
        print(f"  {item['name']}: {execution_result.get('status')}")
    save("12_execution_results.json", json.dumps(execution_results, indent=2, default=str, ensure_ascii=False))
elif recommendations:
    for item in recommendations:
        item["execution_result"] = {
            "status": "not_executed",
            "mode": execution_mode,
            "reason": "RADAR_AUTO_EXECUTE_PAPER_TRADES disabled",
        }

if paper_metrics is None:
    paper_metrics = compute_metrics(DATA_DIR, reconcile_result.get("account", {}) if reconcile_result else {}, load_paper_positions(DATA_DIR))
save("14_paper_metrics.json", json.dumps(paper_metrics, indent=2, default=str, ensure_ascii=False))
strategy_feedback = save_strategy_feedback(DATA_DIR)
save("16_strategy_feedback.json", json.dumps(strategy_feedback, indent=2, default=str, ensure_ascii=False))

if paper_metrics and paper_metrics.get("total_trades", 0) > 0:
    summary_lines.append(
        f"- 模拟盘累计 `{paper_metrics['total_trades']}` 笔，胜率 `{paper_metrics['raw_win_rate']*100:.1f}%`，"
        f" TP1 命中率 `{paper_metrics['tp1_hit_rate']*100:.1f}%`。"
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
    f"# 🦊 妖币雷达 v{PROJECT_VERSION} {MODE_PROFILE['label']}报告",
    f"> 扫描时间：{TS}",
    f"> 版本：`v{PROJECT_VERSION}`",
    f"> 运行模式：`{RUN_MODE}` / {MODE_PROFILE['label']}",
    f"> 推荐频率：{MODE_PROFILE['cadence']}",
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
    "## 📅 宏观/事件日历",
    "",
]

# Macro calendar section
macro_calendar_data = (shared_intel_context.get("macro_calendar") or {}).get("data") or {}
macro_items_all = macro_calendar_data.get("macro_items") or []
if macro_items_all:
    report_lines += [
        "| 日期 | 类别 | 事件 |",
        "|---|---|---|",
    ]
    for item in macro_items_all[:10]:
        date = item.get("date", "—")
        category = item.get("category", "—")
        title = item.get("title", "—")
        report_lines.append(f"| {date} | {category} | {title} |")
    report_lines.append("")
else:
    report_lines += ["> 近期无高重要性宏观/事件数据", ""]

report_lines += [
    "## 🎯 Paper Trade 候选",
    "",
]

if recommendations:
    report_lines += [
        "| 排名 | 币种 | 模式 | 方向 | OOS | ERS | 入场区间 | 止损 | 止盈1 | 止盈2 | TP1分批 | 保护策略 | 仓位建议 |",
        "|---|---|---|---|---:|---:|---|---|---|---|---:|---|---|",
    ]
    for index, item in enumerate(recommendations, 1):
        plan = item.get("trade_plan") or {}
        ps_text = f"${plan['position_size_usd']:,.0f} USDT" if plan.get("position_size_usd") else item.get("position_size", "N/A")
        report_lines.append(
            f"| {index} | **{item['name']}** | `{plan.get('plan_profile', item.get('strategy_mode', 'n/a'))}` | {_direction_label(item)} | {item.get('oos', 0)} | {item.get('ers', 0)} | "
            f"${plan.get('entry_low', 0):.6g} - ${plan.get('entry_high', 0):.6g} | "
            f"${plan.get('stop_loss', 0):.6g} | ${plan.get('take_profit_1', 0):.6g} | ${plan.get('take_profit_2', 0):.6g} | {plan.get('tp1_fraction', 0) * 100:.0f}% | `{plan.get('protection_strategy', plan.get('trailing_mode', 'fixed'))}` | {ps_text} |"
        )
    report_lines.append("")
else:
    report_lines += [
        "> ⚠️ 本次没有满足 `recommend_paper_trade` 门槛的标的。",
        "",
    ]

if recommendations:
    report_lines += [
        "## 🧾 Paper Orders",
        "",
        "| 币种 | 模式 | 状态 | 主单 | 止损 | 止盈 | TP1分批 | 保护策略 |",
        "|---|---|---|---|---|---|---:|---|",
    ]
    for item in recommendations:
        execution = item.get("execution_result") or {}
        plan = item.get("trade_plan") or {}
        intent = (plan.get("execution") or {})
        entry_type = ((intent.get("entry_order") or {}).get("type")) or "N/A"
        tp_orders = execution.get("take_profit_orders") or (intent.get("take_profit_orders") or [])
        tp_summary = ", ".join(f"${order.get('stop_price', 0):.6g}" for order in tp_orders[:2]) if tp_orders else "—"
        report_lines.append(
            f"| **{item['name']}** | {execution.get('mode', execution_mode)} | {execution.get('status', 'pending')} | "
            f"{entry_type} | ${((execution.get('stop_loss_order') or (intent.get('stop_loss_order') or {})).get('stop_price', 0)):.6g} | {tp_summary} | "
            f"{plan.get('tp1_fraction', 0) * 100:.0f}% | `{plan.get('protection_strategy', plan.get('trailing_mode', 'fixed'))}` |"
        )
    report_lines.append("")

if paper_metrics:
    report_lines += [
        "## 📈 Paper Metrics",
        "",
        "| 指标 | 数值 |",
        "|---|---:|",
        f"| Closed Trades | {paper_metrics.get('total_trades', 0)} |",
        f"| Raw Win Rate | {paper_metrics.get('raw_win_rate', 0.0) * 100:.1f}% |",
        f"| TP1 Hit Rate | {paper_metrics.get('tp1_hit_rate', 0.0) * 100:.1f}% |",
        f"| Full TP Rate | {paper_metrics.get('full_tp_rate', 0.0) * 100:.1f}% |",
        f"| Stop Loss Rate | {paper_metrics.get('stop_loss_rate', 0.0) * 100:.1f}% |",
        f"| Profit Factor | {paper_metrics.get('profit_factor') if paper_metrics.get('profit_factor') is not None else 'N/A'} |",
        f"| Net PnL | {paper_metrics.get('net_pnl', 0.0):.2f} |",
        f"| Open Positions | {paper_metrics.get('open_positions', 0)} |",
        "",
    ]

if strategy_feedback:
    report_lines += [
        "## 🧠 Strategy Feedback",
        "",
        f"- Closed trades: `{strategy_feedback.get('total_closed_trades', 0)}`",
    ]
    for suggestion in (strategy_feedback.get("suggestions") or [])[:3]:
        report_lines.append(f"- {suggestion.get('message')}")
    report_lines.append("")

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
    if plan.get("plan_profile"):
        report_lines.append(f"- 计划模板: `{plan['plan_profile']}`")
    if plan.get("why_this_plan"):
        report_lines.append(f"- 计划原因: {plan['why_this_plan']}")
    for reason in item.get("hit_rules", [])[:4]:
        report_lines.append(f"- ✅ {reason}")
    for note in item.get("risk_notes", [])[:3]:
        report_lines.append(f"- 🔶 {note}")
    if item.get("miss_rules"):
        report_lines.append(f"- ⚠️ {item['miss_rules'][0]}")
    if plan:
        report_lines.append(f"- 入场区间: `${plan.get('entry_low', 0):.6g} - ${plan.get('entry_high', 0):.6g}`")
        report_lines.append(f"- 止损: `${plan.get('stop_loss', 0):.6g}`")
        report_lines.append(f"- 止盈1: `${plan.get('take_profit_1', 0):.6g}`（平仓 `{plan.get('tp1_fraction', 0) * 100:.0f}%`）")
        report_lines.append(f"- 止盈2: `${plan.get('take_profit_2', 0):.6g}`（剩余仓位）")
        report_lines.append(f"- 保护策略: `{plan.get('protection_strategy', plan.get('trailing_mode', 'fixed'))}`")
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
    "## 🧭 Mode Contract",
    "",
    f"- 触发条件: {MODE_PROFILE['trigger']}",
    f"- 推荐频率: {MODE_PROFILE['cadence']}",
    f"- 输出重点: {MODE_PROFILE['result_focus']}",
]
if TARGET_SYMBOLS:
    report_lines.append("- 目标代币: " + "，".join(f"`{symbol}`" for symbol in TARGET_SYMBOLS))
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
] + (  # preflight warning branch
    [f"*⚠️ OnchainOS 登录态检查失败 ({_preflight_err}): {_preflight_msg}。*", ""]
    if not okx_wallet_ok
    else (["*⚠️ OnchainOS 未登录，部分链上数据可能不可用。*", ""] if not okx_logged_in else [])
) + [
    "*⚠️ 本报告仅供研究与模拟验证，不构成投资建议。*",
    f"*数据路径：{SCAN_DIR}/*",
    f"*Version {PROJECT_VERSION} — {datetime.now().strftime('%Y-%m-%d')}*",
]

report_path = SCAN_DIR / "report.md"
report_path.write_text("\n".join(report_lines), encoding="utf-8")

# Standard JSON output (Obsidian aligned)
json_results = []
for item in scored:
    plan = item.get("trade_plan")
    json_results.append({
        "output_contract_version": OUTPUT_CONTRACT_VERSION,
        "radar_version": PROJECT_VERSION,
        "run_mode": RUN_MODE,
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
        "execution_result": item.get("execution_result"),
    })

# Validate output contract before saving
valid, errors = validate_output(json_results)
if not valid:
    print(f" ⚠️ 输出格式校验发现 {len(errors)} 个问题：")
    for e in errors[:5]:
        print(f"    - {e}")
    if len(errors) > 5:
        print(f"    - ... 还有 {len(errors) - 5} 个问题")

save("result.json", json.dumps(json_results, indent=2, ensure_ascii=False, default=str))
save(
    "00_scan_meta.json",
    json.dumps(
        {
            "output_contract_version": OUTPUT_CONTRACT_VERSION,
            "radar_version": PROJECT_VERSION,
            "scan_timestamp": TS,
            "scan_dir": str(SCAN_DIR),
            "run_mode": RUN_MODE,
            "mode_profile": MODE_PROFILE,
            "target_symbols": list(TARGET_SYMBOLS),
            "output_contract": {
                "report": "report.md",
                "result": "result.json",
                "meta": "00_scan_meta.json",
                "fetch_status": "09_fetch_status.json",
                "freshness": "10_data_freshness.json",
                "onchain_snapshots": "11_onchain_snapshots.json",
                "execution_results": "12_execution_results.json",
                "paper_metrics": "14_paper_metrics.json",
                "social_intel": "15_social_intel.json",
                "strategy_feedback": "16_strategy_feedback.json",
            },
            "onchainos_auth_preflight": {
                "loggedIn": okx_logged_in,
                "accountCount": okx_account_count,
                **okx_wallet.get("status", {}),
            },
        },
        indent=2,
        ensure_ascii=False,
        default=str,
    ),
)

print(f"=== 妖币雷达 v{PROJECT_VERSION} 扫描完成 ===")
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
