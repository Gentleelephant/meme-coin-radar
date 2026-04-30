---
name: meme-coin-radar
description: "妖币雷达 v3.3.0 — 基于 OKX OnchainOS + Binance Alpha + Binance 模拟盘承接的候选发现与评分 skill。触发词：'跑妖币雷达'、'扫描妖币'、'meme radar'。"
tags: ["crypto", "meme-coin", "okx", "onchainos", "binance", "alpha", "paper-trade", "smart-money", "sol", "bnb"]
category: crypto-trading
license: MIT
author: hermes
version: "3.3.0"
metadata:
  phase: "3.2"
  data_sources: ["okx-onchainos", "binance-cli", "binance-alpha"]
  scoring_model: "OOS + ERS + final decision"
  output: "analysis report + raw data to $XDG_STATE_HOME/meme-coin-radar/ or ~/.local/state/meme-coin-radar/ (fallback: system temp dir)"
  auto_script: "skills/meme-coin-radar/scripts/auto-run.py"
---

# 妖币雷达 v3.2.0

> 单一版本源：`skills/meme-coin-radar/VERSION`

> 定位：先用 `OKX OnchainOS` 找链上热点和结构信号，再用 `Binance Alpha + Futures` 判断能否承接到模拟交易。

## 核心模型

- `Onchain Opportunity Score (OOS)`：判断这个标的是不是值得关注的链上机会。
- `Execution Readiness Score (ERS)`：判断当前是否适合承接到 Binance 模拟盘。
- `Final Decision`：
  - `recommend_paper_trade`
  - `watch_only`
  - `manual_review`
  - `reject`

## 数据流水线

| Step | 数据内容 | 获取方式 | 底层来源 |
|---:|---|---|---|
| -1 | OnchainOS 登录态预检 | `skill_dispatcher.okx_wallet_status()` | OKX OnchainOS CLI |
| 0 | BTC 大盘状态 | `skill_dispatcher.okx_btc_status()` | OKX CEX |
| 0.5 | Binance Alpha 热度 | `skill_dispatcher.binance_alpha()` | Binance Alpha |
| 1 | 链上候选发现 | `skill_dispatcher.okx_hot_tokens()` / `okx_signal_list()` / `okx_tracker_activities()` | OKX OnchainOS |
| 2a | 链上快照（lite+deep 分层）| 所有 candidate 先 `depth="lite"`；所有 tradable candidate 再补 `depth="deep"`（onchain-only 保持 lite） | OKX OnchainOS |
| 3 | 执行承接数据 | `skill_dispatcher.batch_binance()` | Binance Futures |
| 4 | 评分与交易计划 | `radar_logic.score_candidate()` / `build_trade_plan()` | 本地 Python |

## 候选模式

### `meme_onchain`

适合妖币、热点链上标的，优先看：

- 换手率 / 活跃度
- 动能窗口
- 持有人结构
- 聪明钱共振
- X 热度

### `majors_cex`

适合 `BTC / ETH / SOL / BNB / ZEC / HYPE` 这类主流或半主流标的，优先看：

- Binance 成交额 / 波动 / OI / funding
- Alpha 热度确认
- 4H / 1H 趋势结构
- 执行承接与入场时机

> `majors_cex` 不强依赖完整链上筹码字段，避免主流币因 OKX 链上覆盖不足被误伤。

## 评分结构

### OOS（满分 100）

- 换手率 / 活跃度：25
- 动能窗口：20
- 持有人结构 / 筹码健康度：20
- 聪明钱与地址共振：15
- 市值区间：10
- 日内位置：5
- 社交 / X 热度：5

### ERS（满分 100）

- Binance 映射可执行性：35
- Binance Alpha 热度确认：20
- 波动 / 流动性适合模拟盘：20
- 入场时机：15
- 数据完整度与映射置信度：10

## 运行入口

触发词：

- `跑妖币雷达`
- `扫描妖币`
- `meme radar`
- `跑一遍雷达`

脚本入口：

```bash
python3 skills/meme-coin-radar/scripts/auto-run.py
```

## 输出结果

扫描目录会生成：

- `report.md`
- `result.json`
- `00_scan_meta.json`
- `00_btc_status.json`
- `01_all_tickers.json`
- `02_binance_batch.json`
- `04_binance_alpha.json`
- `05_okx_hot_trending.json`
- `06_okx_hot_x.json`
- `07_okx_signals.json`
- `08_okx_tracker.json`
- `09_fetch_status.json`
- `10_data_freshness.json`
- `11_onchain_snapshots.json`
- `12_execution_results.json`（启用自动模拟下单时）

## 模拟交易执行

当前支持把 `recommend_paper_trade` 候选直接转成 Binance 风格的 bracket 订单计划：

- 主单
- 止损单
- 分批止盈单

默认是安全模式：

- `RADAR_EXECUTION_MODE=paper`
- `RADAR_AUTO_EXECUTE_PAPER_TRADES=false`

可选开关：

- `RADAR_AUTO_EXECUTE_PAPER_TRADES=true`
  启用后，会把推荐标的写入本地 `paper_positions.json`，作为模拟持仓簿。
- `RADAR_VALIDATE_ORDERS_WITH_BINANCE=true`
  启用后，会用 Binance skill 的 `futures-usds test-order` 规则对主单、止损、止盈做预校验。

当前约定：

- 主单优先使用 `MARKET` 或 `LIMIT`
- 止损使用 `STOP_MARKET`
- 止盈使用 `TAKE_PROFIT_MARKET`
- 保护单默认带 `reduce_only=true`
- 触发价格默认使用 `MARK_PRICE`

## 代码结构

- `scripts/auto-run.py`：主编排入口
- `scripts/skill_dispatcher.py`：数据抓取分发层
- `scripts/providers/onchainos.py`：OKX OnchainOS provider
- `scripts/providers/binance.py`：Binance provider
- `scripts/candidate_discovery.py`：候选发现
- `scripts/asset_mapping.py`：链上标的到 Binance 执行标的映射
- `scripts/scoring_modules.py`：分项评分函数
- `scripts/radar_logic.py`：总评分与交易计划

## 注意事项

- 当前执行层只服务 `Binance 模拟盘`，不默认做自动实盘。
- skill 可以组合使用多个外部 skill 的底层能力，但工程实现应沉到 `providers/`，不要写成 skill 互相调用。
- 如果项目代码更新，`SKILL.md` 需要同步维护，否则使用者看到的工作流和真实代码会脱节。

*仅用于研究与模拟验证，不构成投资建议。*
