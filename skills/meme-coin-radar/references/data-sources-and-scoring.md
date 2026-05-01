# 数据源与评分体系梳理

> 详细评分规格请优先看：
> [scoring-logic-spec.md](/Users/zhangpeng/opt/meme-coin-radar/skills/meme-coin-radar/references/scoring-logic-spec.md)
>
> 当前文件保留为总览；如需做版本级逻辑对比，请以 `scoring-logic-spec.md` 为准。

## 1. 数据源总览

| 层级 | 数据源 | 当前接入方式 | 主要字段/能力 | 作用 |
|---|---|---|---|---|
| 市场基准 | OKX CEX | Python provider | BTC 价格、24h 涨跌、方向 | 定义市场 regime，决定做多/做空容忍度 |
| 候选发现 | OKX OnchainOS | CLI 封装 | hot-tokens、signal list、tracker activities | 提供链上热点、聪明钱、X 热度入口 |
| 链上画像 | OKX OnchainOS | CLI 封装 | price-info、advanced-info、holders、cluster-overview、cluster-top-holders、trades | 补全市值、持仓结构、风险、换手与地址特征 |
| 执行热度 | Binance Alpha | CLI 封装 | count24h、pct、score | 判断交易所社区承接强度 |
| 执行可行性 | Binance Futures | CLI 封装 | ticker、funding、klines、OI、tradable symbols | 判断是否可上模拟盘，以及入场/波动/时机 |
| 社交/新闻 | Surf / PANews | CLI 封装 + 缓存 | mentions、mindshare、growth、news、calendar、editorial hooks | 给 `social_heat` 与 `macro_catalyst` 提供补强 |
| 反馈闭环 | 本地历史数据 | 本地 JSON / JSONL | paper positions、closed trades、metrics、strategy feedback | 支持执行回顾与参数优化 |

## 2. 模式与数据源使用策略

### `scan`

- 目标: 扫描全市场，筛出候选池。
- 数据策略: 保持 OKX OnchainOS 全量发现，优先覆盖广度。
- 建议频率: `15-60` 分钟；高波动窗口 `5-15` 分钟。
- 输出重点: 推荐池、观察池、拒绝原因、多源数据新鲜度。

### `monitor`

- 目标: 只跟踪指定代币。
- 数据策略: 用目标代币过滤候选与 Binance batch，减少无关标的的执行开销。
- 建议频率: `1-5` 分钟，由外部控制循环持续调度。
- 输出重点: 目标代币评分、交易计划、保护策略、持仓上下文。

## 3. 评分框架

### OOS: Onchain Opportunity Score

当前组成:

| 子项 | 满分 | 主要来源 | 说明 |
|---|---:|---|---|
| `turnover_activity` | 25 | OnchainOS price/trades/hot token | 评估换手、交易密度、买卖盘主动性 |
| `momentum_window` | 20 | Binance klines / ticker | 评估 24h 与 4h 动能窗口，防止过度追涨 |
| `holder_structure` | 20 | OnchainOS advanced-info / cluster / holders | 评估筹码分散度、cluster 风险、新钱包参与度 |
| `smart_money_resonance` | 15 | OnchainOS signal / tracker | 评估聪明钱、KOL、追踪地址共振 |
| `market_cap_fit` | 10 | OnchainOS price-info | 偏好中小市值机会；主流币使用 major proxy |
| `intraday_position` | 5 | Binance / OnchainOS 价格 | 评估日内位置是否仍适合介入 |
| `social_heat` | 15 | OKX X rank + Binance Alpha + Surf + PANews | 由 `score_social_heat_v2()` 聚合社交和新闻叙事 |
| `macro_catalyst` | 4 | PANews calendar / events | 高重要事件可做轻量加分 |

说明:

- 当前 `base_oos = 25 + 20 + 20 + 15 + 10 + 5 = 95`
- 最终 `oos = base_oos + social_heat + macro_catalyst`
- 在当前实现中，OOS 不是硬性截断到 100；它是“机会分”而非百分制展示

### ERS: Execution Readiness Score

| 子项 | 满分 | 主要来源 | 说明 |
|---|---:|---|---|
| `execution_mapping` | 35 | 本地映射 + Binance tradable symbols | 是否能可靠映射到可执行合约 |
| `execution_alpha` | 20 | Binance Alpha | 社区热度是否支持交易所承接 |
| `execution_liquidity` | 20 | Binance ticker / ATR | 流动性和波动是否适合做模拟盘 |
| `execution_timing` | 15 | 日内位置 + 24h 涨跌 | 当前是否仍是好的切入时机 |
| `data_quality` | 10 | 缺失字段 + 映射置信度 | 缺数据就降级，不强行给高分 |

### Final Score

- `meme_onchain`: `final_score = OOS * 0.7 + ERS * 0.3`
- `majors_cex`: `final_score = OOS * 0.5 + ERS * 0.5`

原因:

- 妖币核心是先发现链上机会，再验证执行承接，所以更偏 OOS。
- 主流币更依赖交易所流动性和趋势结构，所以 OOS / ERS 权重更接近。

## 4. 决策门槛

### `meme_onchain`

- `recommend_paper_trade`: 一般要求 `oos >= 75` 且 `ers >= 65` 且可交易
- `watch_only`: 链上强但执行不足，或 R:R 不满足
- `manual_review`: 缺字段较多或边界信号不清晰
- `reject`: 命中硬风险或强烈不满足门槛

### `majors_cex`

- 以 `final_score` / `ers` 为主判断，降低纯链上字段缺失对主流币的误伤

## 5. 当前问题与建议

### 数据源侧

- 当前 OKX OnchainOS、Binance、Surf、PANews 仍以 CLI 调用为主，启动和 JSON 解析开销较大。
- `monitor` 模式已通过目标代币过滤降低 batch 成本，但链上发现层仍会跑基础全局发现。

### 评分侧

- `social_heat` 与 `macro_catalyst` 已进入 OOS，但上限与解释文本仍应持续收敛，避免社交噪音过度加分。
- OOS 当前允许超过 100，适合排序，但若后续要做跨版本对比，建议补一层“展示分”和“原始分”分离。

## 6. OnchainOS API 评估

基于外部资料与当前代码现状：

- 当前仓库实际仍通过 `onchainos ...` CLI 命令调用，见 `scripts/providers/onchainos.py`。
- OKX 官方 `onchainos-skills` 仓库明确将其描述为接入 “OKX OnchainOS API” 的技能集合，并要求 API credentials:
  - https://github.com/okx/onchainos-skills
- OKX 官方 `okx-dex-sdk` 仓库显示部分 Onchain Gateway 能力已经通过 SDK / API 暴露，但部分高级能力需要 API access / whitelist:
  - https://github.com/okx/okx-dex-sdk

结论:

- 可以合理判断 OKX 侧已经存在 API 化能力，不再只是本地 CLI 黑盒。
- 但当前是否覆盖 `hot-tokens`、`signal list`、`cluster`、`tracker activities` 全量接口，仍需要按具体 endpoint 再核对。

建议落地顺序:

1. 先给 `providers/onchainos.py` 增加 transport 抽象: `cli` / `api`
2. 优先迁移高频、低争议接口: `wallet status`、`price-info`、`advanced-info`
3. 对 `hot-tokens`、`signals`、`tracker` 做接口可用性验证，若 API 不完整则保留 CLI fallback
4. 在 `monitor` 模式优先走 API，`scan` 模式保留 CLI 兼容，逐步比较时延、稳定性、字段完整度
