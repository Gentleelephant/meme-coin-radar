# 信号判断规则与评分模型 Phase 3.x

> 适用范围：当前 `meme-coin-radar` 实现。
> 当前评分主轴：`OOS + ERS + Final Decision`
> 如与历史 `Phase 2.0 / Obsidian 五模块` 资料冲突，以 [radar_logic.py](/Users/zhangpeng/opt/meme-coin-radar/skills/meme-coin-radar/scripts/radar_logic.py) 和 [scoring_modules.py](/Users/zhangpeng/opt/meme-coin-radar/skills/meme-coin-radar/scripts/scoring_modules.py) 为准。

## 一、当前评分结构

### 1. Onchain Opportunity Score（OOS）

用于判断“这个标的是不是值得关注的机会”。

当前主要维度：

| 模块 | 满分 | 说明 |
|---|---:|---|
| 换手率 / 活跃度 | 25 | `volume24h / market_cap`、trade density、buyers vs sellers |
| 动能窗口 | 20 | 优先奖励 `0% ~ 30%` 启动区，暴涨后降权 |
| 持有人结构 / 筹码健康度 | 20 | top holder concentration、new wallet ratio、cluster 风险 |
| 聪明钱与地址共振 | 15 | OKX signal / tracker / owned smart money hits |
| 市值区间 | 10 | 优先 `5M ~ 300M`，过大降权 |
| 日内位置 | 5 | 接近突破但未明显冲顶更优 |
| 社交 / 新闻热度 | 5 或 15 | 取决于是否启用 `social heat v2` |

### 2. Execution Readiness Score（ERS）

用于判断“现在能不能承接到 Binance 模拟盘”。

| 模块 | 满分 | 说明 |
|---|---:|---|
| Binance 映射可执行性 | 35 | exact / probable / none |
| Binance Alpha 热度确认 | 20 | `count24h`、热度同步情况 |
| 波动 / 流动性 | 20 | 是否适合 paper 执行 |
| 入场时机 | 15 | 是否仍在可参与窗口 |
| 数据完整度与映射置信度 | 10 | 缺字段越多越降权 |

### 3. Final Decision

| 结果 | 含义 |
|---|---|
| `recommend_paper_trade` | 可以进入 Paper 执行候选 |
| `watch_only` | 机会存在，但暂不适合执行 |
| `manual_review` | 中等机会或数据不完整，需要人工复核 |
| `reject` | 直接排除 |

## 二、现行决策门槛

### `meme_onchain`

- 默认要求 `OOS >= 75`
- 且 `ERS >= 65`
- 且未命中硬否决

### `majors_cex`

- 仍然使用 `OOS + ERS`
- 但对链上筹码字段依赖更低
- 更看重成交额、波动、结构、Alpha 热度与执行承接

## 三、硬否决规则

当前应优先关注的硬风险：

- 持仓极度集中
- cluster rug risk 高
- deployer / suspicious 持仓异常
- 流动性过低
- 数据映射不可信
- 已暴涨且结构衰竭
- 缺失关键执行保护参数

命中这些条件时，即使分数不低，也应直接降到 `reject` 或禁止执行。

## 四、社交与新闻热度

当前项目已经不再把社交项只理解为 `Alpha count24h`。

可用来源包括：

- OKX `hot-tokens` 的 X 热度榜
- Binance Alpha 热度
- Surf 社交 / mindshare / sentiment
- PANews 新闻、活动日历、编辑热点、board/highlights

当前推荐理解为两层：

| 层级 | 说明 |
|---|---|
| `social momentum` | mentions、growth、mindshare、X 排名 |
| `news narrative` | 新闻覆盖、热点关键词、叙事标签、事件/日历 |

## 五、交易计划口径

当前交易计划已经不是旧版固定公式说明，而是配置化生成：

- `entry_low`
- `entry_high`
- `stop_loss`
- `take_profit_1`
- `take_profit_2`
- `position_size_usd`
- `execution`

其中 `execution` 会进一步约束：

- 主单类型
- 固定止损
- 固定双止盈
- `break_even` 或 `callback` trailing stop

## 六、胜率与 Paper 复盘

当前项目会跟踪：

- `raw_win_rate`
- `tp1_hit_rate`
- `full_tp_rate`
- `stop_loss_rate`
- `profit_factor`
- `max_drawdown`

并支持按以下维度拆分：

- `strategy_mode`
- `candidate_sources`
- `direction`
- `score_bucket`
- `data_quality_tier`
- `narrative_label`

## 七、历史说明

以下内容已经不再是当前实现主模型：

- `Phase 2.0` 的 Obsidian 五大模块
- `GMGN` 主导的链上安全 / 社交口径
- 以 `monster_candidate / watchlist / can_enter` 为主的旧决策语言

如果需要研究历史模型，请将旧版文档视为归档资料，而不是现行规则。
