---
name: meme-coin-radar
description: "妖币雷达 Phase 1.8 — GMGN链上增强版，对齐 Obsidian 妖币判断指标五大模块，新增 GMGN SOL/BSC Chain层扫描。触发词：'跑妖币雷达'、'扫描妖币'、'meme radar'。Phase 1.8 新增：GMGN SOL/BSC热门代币、链上安全否决层（rug_ratio/is_wash_trading/top10持仓）、聪明钱追踪（smart_degen_count）、Pump.fun新上线代币。"
tags: ["crypto", "meme-coin", "funding-rate", "open-interest", "perpetual-swap", "okx", "sentiment", "binance", "atr", "ema", "gmgn", "smart-money", "sol", "pumpfun"]
category: crypto-trading
license: MIT
author: hermes
version: "1.8.0"
metadata:
  phase: "1.8"
  data_sources: ["okx-market", "binance-fapi-klines", "binance-alpha", "gmgn-market"]
  obsidian_alignment: "对齐 资料库/妖币判断指标.md 五大模块"
  output: "analysis report + raw data to ~/.hermes/meme-radar/"
  auto_script: "scripts/auto-run.py"
---

# 🦊 妖币雷达 Phase 1.8 — GMGN链上增强版

> **定位**：捕捉合约市场中的极端异动 meme 币，识别被套韭菜，搭便车反向开单。同时扩展到 GMGN Chain层 meme coin 预警。
> **Phase 1.8**：在 Phase 1.7 基础上，接入 GMGN API：
>   - 新增：GMGN SOL/BSC 热门代币扫描（Layer 0 独立板块）
>   - 新增：GMGN 链上安全否决层（`rug_ratio > 0.3` / `is_wash_trading` / `top_10_holder > 60%`）
>   - 新增：GMGN 聪明钱追踪（`smart_degen_count` / `renowned_count`）
>   - 新增：GMGN Pump.fun 新上线代币预警
>   - 新增：GMGN 实时聪明钱信号（Smart Degen Buy / Platform Call）
>   - Binance 合约代币叠加 GMGN 安全增强评分
> **Obsidian 对齐**：评分权重和阈值参考 `妖币判断指标.md` 的五大模块体系

---

## 🔧 数据步骤与 Skill 映射表

> **说明**：运行 `auto-run.py` 脚本时，各步骤数据获取方式一览。
> 脚本直接调用底层命令/API，不需要预先加载任何 skill。
> 以下表格仅供理解数据血缘和维护参考。

| Step | 数据内容 | 获取方式 | 底层命令 / API | 对应 Skill（参考） |
|---:|---|---|---|---|
| 0 | BTC 大盘状态 | `subprocess.run("okx market ticker...")` | OKX REST CLI | `okx-cex-market` |
| 0.5 | Binance Alpha 社区活跃度 | `subprocess.run("npx @binance/binance-cli alpha token-list")` | Binance Alpha API | `binance` |
| 1 | OKX 全量 USDT-M SWAP tickers | `subprocess.run("okx market tickers SWAP")` | OKX REST CLI | `okx-cex-market` |
| 2 | Binance ticker + funding + K线 | `urllib.request` 直接调 REST API | `fapi.binance.com` | `binance` |
| G1 | GMGN SOL 热门代币排行 | `gmgn_api()` → `/v1/market/rank` + npx fallback | GMGN REST API + npx gmgn-cli | `gmgn-market` |
| G2 | GMGN BSC 热门代币排行 | 同上，换 `chain="bsc"` | GMGN REST API + npx gmgn-cli | `gmgn-market` |
| G3 | GMGN 聪明钱实时信号 | `gmgn_api()` → `/v1/market/token_signal` + npx fallback | GMGN REST API + npx gmgn-cli | `trading-signal`（参考） |
| G4 | GMGN Pump.fun 新代币 | `subprocess.run("npx gmgn-cli market trenches...")` | npx gmgn-cli | `okx-dex-trenches`（参考） |
| 3 | 六大模块评分计算 | 本地 Python（无外部调用） | — | 无，纯计算逻辑 |

> **⚠️ 依赖说明**：
> - `npx @binance/binance-cli` — Node.js 环境，npx 自动下载
> - `npx gmgn-cli` — Node.js 环境，GMGN API Key 配置在 `~/.config/gmgn/.env`
> - OKX/Binance REST — 无需认证，直接 HTTP 调用

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

## 📋 报告输出格式（Phase 1.7 — 六大模块视角）

```markdown
# 🦊 妖币雷达 Phase 1.7 扫描报告

## 📊 大盘环境
| 指标 | 数值 | 方向 |
|---|---|---|
| BTC 价格 | $XXX | ↑/↓/横 |
| 市场判断 | 多头/空头/均可 | — |

## 🔥 社区活跃度 TOP10（Binance Alpha — count24h）

## 🏆 机会队列（Phase 1.7 六大模块评分）

| 评级 | 币种 | 方向 | 总分 | 安全 | 量价 | 趋势 | 社交 | 环境 | 费率 |
|---|---|---|---|---:|---:|---:|---:|---:|---:|
| 🏆 | BTC | 🔴做空 | **87** | 20 | 28 | 15 | 12 | 0 | 12 |

### 详细信号（TOP3）
### ❌ 安全否决区
### 📋 评分模型说明（Phase 1.7 — 对齐 Obsidian 五大模块）
```

## 📁 数据存储

```
~/.hermes/meme-radar/scan_[YYYYMMDD_HHMMSS]/
├── 00_btc_status.txt          ← BTC大盘状态
├── 01_all_tickers.txt         ← OKX 全量 USDT-M SWAP tickers
├── 02_binance_batch.txt       ← Binance ticker + funding + K线（JSON）
├── 04_binance_alpha.txt       ← Binance Alpha token-list（JSON）
└── report.md                  ← Phase 1.7 最终报告
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

## 🚀 Phase 2 规划（自动化 + TG推送）

Phase 1.7 已完成核心评分体系对齐。Phase 2 聚焦自动化：

| 功能 | 状态 | 说明 |
|---|---|---|
| 一键自动脚本 | ✅ Phase 1.7 | `scripts/auto-run.py` 六大模块评分 |
| ATR/EMA 趋势结构 | ✅ Phase 1.7 | Binance K线实时计算 |
| 安全否决层 | ✅ Phase 1.7 | Module 1 硬否决土狗 |
| Obsidian 对齐 | ✅ Phase 1.7 | 五大模块评分框架 |
| 定时扫描（cron）| 🔜 待做 | 每6h自动跑，signal >= 65 才推送 |
| TG 推送 | 🔜 待做 | 有强信号时推送到 Home Channel |
| Real 盘小资金测试 | 🔜 待做 | 信号评分 85+ 后才考虑 |

Phase 2 触发词：**"升级妖币雷达"** 或 **"开启定时扫描"** 或 **"妖币 TG 推送"**

---

## 🛠️ 一键自动脚本

```bash
python3 ~/.hermes/skills/meme-coin-radar/scripts/auto-run.py
```

脚本自动完成 Phase 1.7 全流程：
1. BTC 大盘状态检查
2. Binance Alpha count24h 社区活跃度
3. OKX 全量 USDT-M SWAP tickers 解析
4. Binance 批量 ticker + funding + 50根1h K线
5. **六大模块量化评分**（安全/量价/趋势/社交/环境/费率）
6. 输出完整报告到 `~/.hermes/meme-radar/scan_XXX/report.md`

*⚠️ 本报告仅供参考，不构成投资建议。DYOR！*
