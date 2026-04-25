# 信号判断规则 & 量化评分模型 Phase 2.0 (Obsidian 对齐版)

> 对齐 Obsidian 知识库「妖币判断指标」五大模块评分体系。
> Phase 2.0 五大模块：安全与流动性(25) / 量价与趋势(30) / 链上与聪明钱(20) / 社交与叙事(15) / 市场环境(10)

## 核心逻辑

资金费率 = 零和博弈的镜子
- 正费率：多头付钱给空头 → 做空信号
- 负费率：空头付钱给多头 → 做多信号

Phase 2.0 改进：
- 五大模块权重对齐 Obsidian（25/30/20/15/10）
- 7 条硬否决规则（新增合约风险、流动性、部署者持仓等）
- OI 四象限接入 Binance open-interest 历史数据
- 双周期验证（4H + 1H）
- R:R >= 1.5 校验
- 精确仓位计算（基于账户权益 × 止损幅度）

---

## 一、Obsidian 五大模块评分体系（总分100）

| 模块 | 满分 | 对齐 Obsidian | 核心指标 | 文件函数 |
|---|---|---|---|---|
| M1: 安全与流动性 | 25 | 安全与流动性 | 成交额 / 交易所状态 / GMGN安全 | `_score_safety_liquidity()` |
| M2: 量价与趋势 | 30 | 量价与持仓 | ATR / 成交额 / 价格变化 / EMA趋势 / 4H共振 | `_score_price_volume_trend()` |
| M3: 链上与聪明钱 | 20 | 链上与聪明钱 | 聪明钱 / Holder增长 / OI四象限 / 资金费率 / 买/卖比 | `_score_onchain_smart_money()` |
| M4: 社交与叙事 | 15 | 社交与叙事 | Alpha count24h / 社交提及(预留) | `_score_social_narrative()` |
| M5: 市场环境 | 10 | 市场环境 | BTC 方向 | `_score_market_regime()` |

---

## 二、7 条硬否决规则（直接 reject）

| # | 规则 | 条件 | 代码位置 |
|---|------|------|----------|
| 1 | 合约高危权限 | `contract_risk_flags` 包含 `mintable`/`blacklist`/`pausable` 且权限未放弃 | `_hard_reject_check()` |
| 2 | 流动性过低 | `liquidity_usd < 50000` | `_hard_reject_check()` |
| 3 | 部署者持仓过高 | `deployer_holder_ratio > 0.1` | `_hard_reject_check()` |
| 4 | 持仓过度集中 | `top10_holder_ratio > 0.35` | `_hard_reject_check()` |
| 5 | 交易不可用 | 买卖滑点极高或明显无法正常卖出 | 当前仅记录风险笔记，未自动检测 |
| 6 | 明显刷量 | `is_wash_trading=True` 或 volume/trades/buyers 严重不匹配 | `_hard_reject_check()` |
| 7 | 波动空间不足 | `atr_pct_14 < 0.04` 且 `atr_pct_14_vs_30d_avg < 0.8` | `_hard_reject_check()`（30d均值为Phase 3预留） |
| — | 成交额极低（原有） | `volume < $5M` | `_hard_reject_check()` |

---

## 三、方向信号与决策门槛

### 三档输出标准

| 总分 | 决策 | 说明 |
|------|------|------|
| < 50 | `reject` | 直接排除 |
| 50–74 | `watchlist` | 进入观察池 |
| >= 75 | `monster_candidate` | 升级为重点预警 |

### `can_enter` 条件（可执行交易）
- `total >= 75`
- `dominant_score >= min_direction_bias` (默认 18)
- `bias_gap >= min_direction_gap` (默认 6)
- `R:R >= 1.5`（交易计划中校验）

---

## 四、各模块评分细则

### M1: 安全与流动性（0–25分）

| 子项 | 条件 | 分数 |
|---|---|---:|
| Volume >= $500M | 顶级流动性 | +8 |
| Volume $100M–$500M | 良好流动性 | +5 |
| Volume $20M–$100M | 中等流动性 | +3 |
| Volume $5M–$20M | 勉强可交易 | +1 |
| Funding API可用 | Binance已上线合约 | +5 |
| 仅Ticker可用 | 降权 | +2 |
| GMGN tag 绿色 | 链上安全良好 | +5 |
| GMGN tag 黄色 | 轻微风险 | +2 |
| rug_ratio < 0.1 | 极低Rug风险 | +4 |
| top10 < 0.20 | 持仓分散 | +4 |
| dev_hold < 0.10 | 开发团队控盘低 | +2 |

### M2: 量价与趋势（0–30分）

| 子项 | 条件 | 分数 |
|---|---|---:|
| ATR >= 12% | 极端波动 | +6 |
| ATR 8–12% | 良好波动 | +4 |
| ATR 4–8% | 一般波动 | +2 |
| Volume >= $500M | 顶级成交 | +8 |
| Volume $200M–$500M | 高成交 | +5 |
| Volume $100M–$200M | 中等 | +3 |
| Volume $50M–$100M | 一般 | +1 |
| 价格变动 abs(chg) >= 30% | — | +6 |
| 价格变动 abs(chg) >= 15% | — | +4 |
| 价格变动 abs(chg) >= 5% | — | +2 |
| 1H趋势 bullish | 多头排列 | +6 |
| 1H趋势 bearish | 空头排列 | +4 |
| 1H趋势 weak_recovery | 弱修复 | +2 |
| 4H趋势与1H一致 | 双周期共振 | +4 |
| 买盘主导 chg>3% 且 vol>$50M | — | +3 |

### M3: 链上与聪明钱（0–20分，允许降到0）

| 子项 | 条件 | 分数 |
|---|---|---:|
| smart_degen >= 5 | 强聪明钱 | +8 |
| smart_degen >= 3 | 中等聪明钱 | +5 |
| smart_degen >= 1 | 轻微聪明钱 | +2 |
| holders_growth >= 25% | 快速扩散 | +6 |
| holders_growth >= 10% | 中等增长 | +3 |
| holders_growth >= 0% | 正增长 | +1 |
| OI上升 + 价格上升 | 新多头建仓 | +4 |
| OI上升 + 价格下跌 | 空头加仓压盘 | -2 |
| OI下降 + 价格上升 | 多头止盈离场 | +2 |
| OI下降 + 价格下跌 | 多空同时撤退 | -4 |
| 资金费率 abs(fr) >= 2% | 极端费率 | +2 |
| 资金费率 abs(fr) >= 1% | 显著费率 | +1 |
| buyers/sellers >= 1.2 | 买盘主导 | +2 |

### M4: 社交与叙事（0–15分）

| 子项 | 条件 | 分数 |
|---|---|---:|
| count24h >= 100k + 异动 | 全网热点 | +8 |
| count24h 50k–100k | 高活跃 | +4~6 |
| count24h 20k–50k | 中等活跃 | +2 |
| count24h > 0 | 低活跃 | +1 |

### M5: 市场环境（0–10分）

| BTC 状态 | 得分 |
|---|---:|
| 上涨 > +2% | +7 |
| 横盘（-2%~+2%） | +4 |
| 下跌 < -2% | +0 |

---

## 五、缺失字段降级规则

| 条件 | 处理 |
|------|------|
| 核心字段缺失 >= 1 项 | `needs_manual_review = True` |
| 核心字段缺失 >= 3 项 | `total_score` 强制上限 74，`decision = watchlist`，`can_enter = False` |

核心字段白名单：`atr14`, `trend`, `oi`, `fundingRate`, `volume`, `alpha_count24h`

---

## 六、交易计划（build_trade_plan）

### 参数计算
- `risk_pct = ATR14% * 0.8`，clamped `[3.5%, 10%]`
- `entry_buffer = risk_pct * 0.35`，clamped `[0.8%, 2.5%]`
- `TP1 = risk_pct * 1.6`，min 5%
- `TP2 = risk_pct * 2.4`，min 8%

### R:R 校验
- 以入场区间中点作为预期成交价
- 若 `R:R < 1.5`，强制 `setup_label = "watch"`，并记录 `risk_notes`

### 精确仓位
- 从 OKX 拉取账户权益 `equity`
- 风险系数：极强信号 3%，强信号 2%，中等信号 1%
- `position_size_usd = equity * risk_ratio / stop_loss_pct`
- 输出格式：`建议开仓 $XXX USDT（约 Y 个币）@ Zx 杠杆`

---

## 七、数据结构变更

### score_candidate 新增参数
- `klines_4h`: 4H K线（双周期验证）
- `oi`: Open Interest 数据（OI四象限）
- `equity`: 账户权益（仓位计算）

### score_candidate 返回值新增字段
- `symbol`, `total_score`, `hard_reject`, `reject_reasons`, `risk_notes`, `needs_manual_review`
- `module_scores`: 使用 Obsidian 模块名（保留旧别名）

### 输出文件
- `report.md`: Markdown 报告
- `result.json`: 标准 JSON 数组，便于接入数据库/监控

---

## 八、Phase 3 预留（后续迭代）

| 功能 | 说明 | 依赖 |
|------|------|------|
| ATR 30日均值 | atr_pct_14_vs_30d_avg | 本地数据库 / historical klines |
| Volume 7日均值 | volume_24h_vs_7d_avg | 本地数据库 |
| Holder 增长率 | holders_growth_24h | GMGN 历史数据存储 |
| Buy/Seller 比率 | buyers_24h / sellers_24h | GMGN API 字段确认 |
| 社交多维度 | social_mentions, kol_unique_count | X API / tweetscout |
| 叙事标签匹配 | narrative_tags | 热点词库定义 |
