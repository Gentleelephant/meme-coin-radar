---
name: meme-coin-radar
description: "妖币雷达 Phase 2.0 — Provider + Radar Logic 融合版，结合当前项目的多数据源/fallback 架构与 crypto-signal-radar 的配置化、纯逻辑评分、执行摘要和交易建议输出。触发词：'跑妖币雷达'、'扫描妖币'、'meme radar'。"
tags: ["crypto", "meme-coin", "funding-rate", "open-interest", "perpetual-swap", "okx", "sentiment", "binance", "atr", "ema", "gmgn", "smart-money", "sol", "pumpfun"]
category: crypto-trading
license: MIT
author: hermes
version: "2.0.0"
metadata:
  phase: "2.0"
  data_sources: ["okx-market", "binance-cli", "binance-alpha", "gmgn-market", "hyperliquid-fallback"]
  obsidian_alignment: "对齐 妖币判断指标.md 六大模块，并增加执行摘要与入场建议"
  output: "analysis report + raw data to ~/meme-radar/"
  auto_script: "scripts/auto-run.py"
---

# 🦊 妖币雷达 Phase 2.0 — Provider + Radar Logic 融合版

> **定位**：从多 provider 数据里筛出值得做合约的妖币，并直接给出方向、入场区间、止盈止损和仓位建议。
> **Phase 2.0 融合点**：
> - 保留当前项目的 provider/fallback 架构：`OKX + Binance + GMGN + fallback`
> - 引入 `crypto-signal-radar` 的配置层：`scripts/config.py`
> - 引入纯逻辑评分层：`scripts/radar_logic.py`
> - 报告新增 `Executive Summary`、`confidence`、`entry_reasons`
> - 合约建议不再只给分数，还会输出可执行交易计划
> **Obsidian 对齐**：评分权重和阈值参考 `妖币判断指标.md` 的六大模块体系

---

## 🔧 数据步骤与 Skill 映射表

> **说明**：运行 `auto-run.py` 脚本时，各步骤数据获取方式一览。
> 当前实现采用 `skill_dispatcher.py + providers/* + radar_logic.py` 三层结构。
> 以下表格用于理解数据血缘和维护入口。

| Step | 数据内容 | 获取方式 | 底层命令 / API | 对应 Skill（参考） |
|---:|---|---|---|---|
| 0 | BTC 大盘状态 | `skill_dispatcher.okx_btc_status()` | `okx market ticker BTC-USDT-SWAP` | `okx-cex-market` |
| 0.5 | Binance Alpha 社区活跃度 | `skill_dispatcher.binance_alpha()` | `binance-cli alpha token-list --json` | `binance` |
| 1 | OKX 全量 USDT-M SWAP tickers | `skill_dispatcher.okx_swap_tickers()` | `okx market tickers SWAP` | `okx-cex-market` |
| 2 | ticker + funding + K线 | `skill_dispatcher.batch_binance()` | `binance-cli futures-usds ...` + fallback | `binance` |
| G1 | GMGN SOL 热门代币排行 | `skill_dispatcher.gmgn_trending()` | GMGN API / `gmgn-cli market trending` | `gmgn-market` |
| G2 | GMGN BSC 热门代币排行 | 同上，换 `chain="bsc"` | GMGN API / `gmgn-cli market trending` | `gmgn-market` |
| G3 | GMGN 聪明钱实时信号 | `skill_dispatcher.gmgn_signal()` | GMGN API | `gmgn-market` |
| G4 | GMGN Pump.fun 新代币 | `skill_dispatcher.gmgn_trenches()` | `gmgn-cli market trenches` | `gmgn-market` |
| 3 | 六大模块评分计算 | `radar_logic.score_candidate()` | 本地 Python | 无，纯计算逻辑 |
| 4 | 交易计划生成 | `radar_logic.build_trade_plan()` | 本地 Python | 无，纯计算逻辑 |

> **⚠️ 依赖说明**：
> - `binance-cli` 命令与官方 Binance skill 保持一致
> - `npx gmgn-cli` — Node.js 环境，GMGN API Key 配置在 `~/.config/gmgn/.env`
> - 当 `OKX CLI` 缺失或 `Binance futures` 不可达时，provider 层会尝试 fallback，而不是让整个流程失败

---

## ⚠️ OKX Demo 模式限制说明（重要！）

OKX Demo 环境（`okx --demo`）不支持以下命令：

| 命令 | 状态 | 替代方案 |
|---|---|---|
| `okx market filter` | ❌ 不可用 | 用 `okx market tickers SWAP` 全量拉 + Python 解析 |
| `okx market oi-change` | ❌ 不可用 | 用 Binance Alpha `count24h` 替代社区情绪指标 |
| `okx news sentiment-rank` | ❌ 不可用 | 用 Binance Alpha `count24h` 替代（更量化，无需认证）|
| `okx futures leverage` | ❌ 对 SWAP 报错 | 直接在 `okx swap place` 里加 `--tdMode cross` |

**Demo 可用命令**：

```bash
# 全量 USDT-M SWAP tickers（获取所有币的价格/24h高低/成交量）
okx market tickers SWAP

# 单币行情 + 资金费率（逐个查）
okx market ticker <instId>
okx market funding-rate <instId>

# 下单（仅限已上线的币种）
okx swap place --instId <instId> --side buy --ordType market --sz N --tdMode cross

# 查仓位
okx swap positions
```

**⚠️ 新币必须先确认可用**：`okx market instruments --instType SWAP | grep KAT`（KAT 等小币在 Demo 可能没有 USDT-M 合约）

---

**Trigger words**: `跑妖币雷达` / `扫描妖币` / `meme radar` / `扫一下妖币`

任选其一即可触发：
- `跑妖币雷达`
- `扫描妖币`
- `meme radar`
- `扫一下妖币`
- `跑一遍雷达`
- `升级版雷达`（强制使用 Phase 1.5 流程）

---

## 🔄 Phase 版本对比

| 对比项 | Phase 1 | Phase 1.5/1.6 | Phase 1.7 | Phase 1.8 ⭐ |
|---|---|---|---|---|
| 大盘过滤 | ❌ 无 | ✅ BTC 状态先行 | ✅ BTC 状态先行 | ✅ BTC 状态先行 |
| 情绪数据 | ❌ 无 | ✅ Binance Alpha (count24h) | ✅ Binance Alpha (count24h) | ✅ Binance Alpha (count24h) |
| ATR/EMA 趋势结构 | ❌ 无 | ❌ 无 | ✅ Module 3 新增 | ✅ Module 3 |
| 安全否决层 | ❌ 无 | ❌ 无 | ✅ Module 1 新增 | ✅ **GMGN 链上安全否决** |
| 六大模块评分 | ❌ 无 | ❌ 无 | ✅ 对齐 Obsidian | ✅ **GMGN 聪明钱加成** |
| GMGN Chain层扫描 | ❌ 无 | ❌ 无 | ❌ 无 | ✅ **SOL/BSC/Base** |
| GMGN 聪明钱信号 | ❌ 无 | ❌ 无 | ❌ 无 | ✅ **smart_degen/trenches** |
| Obsidian 对齐 | ❌ 无 | ⚠️ 部分 | ✅ 五大模块对齐 | ✅ 五大模块对齐 |
| 分析方式 | 人肉判断 | 量化评分 | 六大模块量化评分 | GMGN增强评分 |
| 输出 | TOP3 候选 | TOP6 机会队列 | TOP8 机会队列 | TOP8 + GMGN Layer 0 |

---

## 📡 Phase 1.7 工作流（数据对齐 Obsidian 五大模块）

### Step 0 — 大盘环境检查

**先行过滤**：BTC > $105K → 大盘多头；BTC < $95K → 大盘空头；区间 → 多空均可。

```bash
okx market ticker BTC-USDT-SWAP --json
```

### Step 0.5 — Binance Alpha 社区活跃度

> 同 Phase 1.6，`count24h` 作为社交叙事的代理指标。

```bash
npx -y @binance/binance-cli alpha token-list --json
```

### Step 1 — OKX 全量 USDT-M SWAP Tickers

```bash
okx market tickers SWAP > /tmp/tickers.txt
# Python 解析：提取涨幅TOP20 + 跌幅TOP20
```

### Step 2 — Binance 批量数据（含 K线计算 ATR/EMA）

> **Phase 1.7 新增**：同时拉取 ticker + funding + 50根1h K线，用于计算 ATR14 + EMA20/50。

```python
# Binance K线计算 ATR/EMA（见 auto-run.py）
# GET /fapi/v1/klines?symbol=XXX&interval=1h&limit=50
# ATR14: 平均真实波幅（用K线高/低/收盘估算）
# EMA20/50: 指数移动平均线，判断趋势结构
# 趋势结构: bullish(=price>ema20>ema50) / weak_recovery / bearish
```

### Step 3 — 六大模块量化评分

> 对齐 Obsidian `妖币判断指标.md` 的五大模块。链上数据不可用时自动跳过。

| 模块 | 对齐 Obsidian | 数据来源 | 可用性 |
|---|---|---|---|
| Module 1: 安全 | 安全与流动性 | Binance ticker vol + 上市状态 | ✅ 可获取 |
| Module 2: 量价 | 量价与持仓 | Binance ticker + K线 ATR | ✅ 可获取 |
| Module 3: 趋势结构 | ATR/EMA趋势 | Binance K线 EMA20/50/ATR | ✅ 可获取 |
| Module 4: 社交叙事 | 社交与叙事 | Binance Alpha count24h | ✅ 可获取 |
| Module 5: 市场环境 | 市场环境 | BTC 方向 | ✅ 可获取 |
| Module 6: 资金费率 | OI/聪明钱 | Binance premiumIndex | ✅ 可获取 |
| LP锁定比例 | 安全层 | 免费API不可用 | ⚠️ 跳过 |
| 持仓集中度 | 安全层 | 免费API不可用 | ⚠️ 跳过 |
| 聪明钱净流入 | 链上层 | 免费API不可用 | ⚠️ 跳过 |
| 持有人增长率 | 链上层 | 免费API不可用 | ⚠️ 跳过 |
| KOL独立提及数 | 社交层 | 免费API不可用 | ⚠️ 跳过 |

### Step 4 — 综合评分 & 输出报告

---

## 🧠 Phase 1.7 六大模块评分体系（对齐 Obsidian 五大模块）

> 本评分体系对齐 Obsidian `资料库/妖币判断指标.md`，但 **数据获取限制**：
> - Obsidian 评分体系中有大量链上数据（`holders_growth`、`smart_money_inflow`、`LP锁定`、`持仓集中度`）免费 API 无法获取
> - Phase 1.7 用 Binance 可获取数据替代或跳过，保持评分框架完整

### Module 1: 安全与流动性（0-25分，硬否决层）

| 子项 | 条件 | 分数 | 说明 |
|---|---|---:|---|
| 硬否决 | 成交额 < $5M | **reject** | 疑似土狗 |
| 成交额 | ≥ $100M | +8 | Binance流动性确认 |
| 成交额 | $20M-$100M | +3 | 软通过 |
| Binance合约 | funding API可用 | +8 | Binance已上线 = 经过一定审核 |
| Binance合约 | 仅ticker可用 | +4 | 降权通过 |
| 高费率+高成交 | fr > 0.5% 且 vol > $100M | +4 | 做空多头接盘明显 |

### Module 2: 量价与持仓（0-35分）

| 子项 | 条件 | 分数 | 说明 |
|---|---|---:|---|
| ATR波动 | atr_pct ≥ 8% | +6 | 有足够交易空间 |
| ATR波动 | 5% ≤ atr_pct < 8% | +3 | |
| 成交额 | ≥ $500M | +10 | |
| 成交额 | $200M-$500M | +6 | |
| 成交额 | $100M-$200M | +3 | |
| 价格涨幅 | ≥ 30% | +6 | |
| 价格涨幅 | ≥ 15% | +4 | |
| 价格涨幅 | ≥ 5% | +2 | |
| 价格跌幅 | ≥ 20% | +6 | |
| 价格跌幅 | ≥ 10% | +4 | |
| 价格跌幅 | ≥ 5% | +2 | |
| EMA趋势 | bullish（price>ema20>ema50）| +5 | 趋势完整 |
| EMA趋势 | weak_recovery | +2 | |
| EMA趋势 | bearish + 下跌 | +3 | 顺势做空 |
| 买盘主导 | 涨>3% 且 vol>$50M | +3 | |

### Module 3: 趋势结构（0-25分，新增 ⭐）

| 子项 | 条件 | 分数 | 说明 |
|---|---|---:|---|
| 趋势结构 | bullish（EMA多头排列）| +12 | 做多做空都顺 |
| 趋势结构 | bearish（EMA空头排列）| +8 | 顺势做空 |
| 趋势结构 | weak_recovery | +6 | |
| ATR波动空间 | atr_pct ≥ 12% | +8 | 极端波动机会 |
| ATR波动空间 | 8% ≤ atr_pct < 12% | +5 | |
| ATR波动空间 | 4% ≤ atr_pct < 8% | +2 | |
| ATR缺失 | — | 跳过不扣分 | |

> ATR14 计算：`sum(TR[-14:]) / 14`，TR = max(H-L, |H-Pclose|, |L-Pclose|)
> EMA20/50：Binance 1h K线 Close 价格计算

### Module 4: 社交与叙事（0-20分，Alpha count24h）

| 子项 | 条件 | 分数 | 说明 |
|---|---|---:|---|
| count24h | ≥ 100,000 且有价格异动 | +10~15 | 极高活跃度 + 信号确认 |
| count24h | 50,000–100,000 | +6~9 | 高活跃 |
| count24h | 20,000–50,000 | +3~5 | 中等活跃 |
| 酝酿信号 | count24h ≥ 50k 但无价格异动 | +3 | 观察区，可能酝酿中 |
| count24h缺失 | — | 跳过不扣分 | 报告记录 |

### Module 5: 市场环境（0-10分）

| 子项 | 条件 | 分数 |
|---|---|---:|
| BTC上涨 > 2% | 大盘多头 | +7 |
| BTC横盘 | 中性 | +4 |
| BTC下跌 | 大盘空头 | +0 |

### Module 6: 资金费率（0-20分）

| 子项 | 条件 | 分数 |
|---|---|---:|
| 正费率 | fr > 2% | +15 |
| 正费率 | fr > 1% | +10 |
| 正费率 | fr > 0.5% | +6 |
| 正费率 | fr > 0.2% | +3 |
| 负费率 | fr < -0.5% | +15 |
| 负费率 | fr < -0.2% | +10 |
| 负费率 | fr < -0.1% | +6 |
| 零费率 | fr == 0 | +1 |

### 共振加成（额外加分）

| 条件 | 额外加分 |
|---|---:|
| fr > 0.5% + 下跌 >5% + count24h > 30k | +8（做空共振）|
| 下跌 >10% + fr < -0.1% | +10（最佳做多窗口）|

### 信号等级

| 等级 | 总分 | 操作 |
|---|---|---|
| 🏆 极强 | 85+ | 优先入场，5%资金/5x杠杆 |
| ⭐ 强 | 65-84 | 入场，3-5%资金/5x杠杆 |
| 中 | 45-64 | 轻仓观察，1-2%资金/3x杠杆 |
| 🔶 弱 | 30-44 | 观望，仅供参考 |
| ❌ 无效 | <30 | 过滤不输出 |

---

## 📋 报告输出格式（Phase 2.0）

```markdown
# 🦊 妖币雷达 Phase 2.0 扫描报告

## Executive Summary
- 扫描候选数
- 可执行建议数
- 当前市场偏向
- 优先关注币种

## 📊 大盘环境
| 指标 | 数值 | 方向 |
|---|---|---|
| BTC 价格 | $XXX | ↑/↓/横 |
| 市场判断 | 多头/空头/均可 | — |

## 🎯 合约建议
| 币种 | 方向 | 置信度 | 入场区间 | 止损 | 止盈1 | 止盈2 |

## 🏆 机会队列（Provider + Radar Logic）

| 评级 | 币种 | 方向 | 总分 | 置信度 | 可执行 | 安全 | 量价 | 趋势 | 社交 | 环境 | 费率 |

### 详细信号（TOP3，含 entry_reasons）
### ❌ 安全否决区
### 🚀 GMGN Chain层机会板块
```

## 📁 数据存储

```
~/meme-radar/scan_[YYYYMMDD_HHMMSS]/
├── 00_btc_status.json         ← BTC大盘状态
├── 01_all_tickers.json        ← OKX 全量 USDT-M SWAP tickers
├── 02_binance_batch.json      ← provider ticker + funding + K线可用性
├── 04_binance_alpha.json      ← Binance Alpha token-list
├── 05_gmgn_sol_trending.json  ← GMGN SOL 热门币
├── 06_gmgn_bsc_trending.json  ← GMGN BSC 热门币
├── 07_gmgn_signals.json       ← GMGN 聪明钱信号
├── 08_gmgn_trenches_sol.json  ← GMGN 新币数据
└── report.md                  ← Phase 2.0 最终报告
```

---

## ⚠️ 数据可用性说明（重要！）

Phase 1.7 对齐 Obsidian `妖币判断指标.md` 的评分框架，但以下数据免费 API **无法获取**：

| 数据 | 替代/处理 |
|---|---|
| LP锁定比例 | ⚠️ 跳过，报告记录 `missing_fields: ["lp_locked_ratio"]` |
| 前十持仓集中度 | ⚠️ 跳过，用 Binance 上市状态间接替代 |
| 合约高危权限 | ⚠️ 跳过，无法检测 mintable/blacklist/pausable |
| 部署者持仓占比 | ⚠️ 跳过，无法检测初始分配 |
| 持有人增长率 | ⚠️ 跳过，OKX Demo 不支持链上数据 |
| 聪明钱净流入 | ⚠️ 跳过，OKX Demo 不支持 |
| 独立 KOL 提及数 | ⚠️ 用 Binance Alpha count24h 替代 |
| 叙事标签匹配 | ⚠️ 跳过，无法判断叙事热点 |
| ATR 相对30日均值 | ⚠️ 跳过，只用当前 ATR14 |

> **设计原则**：缺失数据不影响评分进程，报告记录缺失字段供人工复核。

---

## 🚀 后续规划（自动化 + 推送）

Phase 2.0 已完成 provider + logic 融合。下一步聚焦自动化：

| 功能 | 状态 | 说明 |
|---|---|---|
| 一键自动脚本 | ✅ Phase 2.0 | provider + 评分 + 交易计划 |
| 配置化阈值 | ✅ Phase 2.0 | `scripts/config.py` |
| 纯逻辑评分测试 | ✅ Phase 2.0 | `tests/test_radar_logic.py` |
| 执行摘要与置信度 | ✅ Phase 2.0 | 报告层已接入 |
| 定时扫描（cron）| 🔜 待做 | 每6h自动跑，signal >= 65 才推送 |
| TG 推送 | 🔜 待做 | 有强信号时推送到 Home Channel |
| Real 盘小资金测试 | 🔜 待做 | 信号评分 85+ 后才考虑 |

后续触发词：**"升级妖币雷达"** 或 **"开启定时扫描"** 或 **"妖币 TG 推送"**

---

## 🛠️ 一键自动脚本

```bash
python3 scripts/auto-run.py
```

脚本自动完成 Phase 2.0 全流程：
1. BTC 大盘状态检查
2. Binance Alpha count24h 社区活跃度
3. GMGN 热门币 / 聪明钱 / 新币扫描
4. OKX 全量 USDT-M SWAP tickers 解析
5. Binance 官方 skill 命令风格的批量 ticker + funding + K线
6. **六大模块量化评分**（安全/量价/趋势/社交/环境/费率）
7. 生成 `Executive Summary + 合约建议 + 详细信号` 报告到 `~/meme-radar/scan_XXX/report.md`

*⚠️ 本报告仅供参考，不构成投资建议。DYOR！*
