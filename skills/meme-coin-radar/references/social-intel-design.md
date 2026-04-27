# 社交情报与新闻叙事层设计

> 版本：v1
> 日期：2026-04-27
> 适用项目：`meme-coin-radar Phase 3.0`
> 目标：将 `surf + PANews + OKX OnchainOS + Binance` 统一接入为可评分、可复盘的社交情报与新闻叙事层

---

## 一、背景与目标

当前项目在以下能力上已经比较完整：

- `OKX OnchainOS`：链上候选发现、持仓结构、聪明钱/KOL/Whale 交易行为
- `Binance Alpha + Futures`：交易所热度、价格反应、执行承接
- `Paper Trading`：订单管理、撮合、胜率与账户统计

但对 meme coin 最核心的驱动力之一，即：

- 社交传播
- 新闻事件
- 热点叙事
- KOL 与公开榜单引导

当前覆盖仍然偏弱，主要依赖：

- `okx_x_rank`
- `Binance Alpha count24h`

这导致系统能回答“链上结构是否健康”“是否具备执行条件”，但还不能充分回答：

- 这个币最近 6h / 24h 是否正在被讨论？
- 是谁在带节奏，社交热度是在加速还是衰减？
- 是否有新闻、活动、上市、合作、监管、政治事件在催化？
- 它属于哪类叙事，当前叙事是否处于热点区？

### 本设计目标

新增一个统一的 `Social / News Intelligence Layer`，实现：

1. 接入 `surf` 的全球新闻、社交、mindshare、sentiment 能力
2. 接入 `PANews` 的中文新闻、专题、活动、日历、热点配置、Polymarket board 快照
3. 与 `OKX OnchainOS` 的链上 KOL / smart money 行为形成互补
4. 将结构化情报沉淀为统一字段，供：
   - 候选发现增强
   - 评分引擎 `social_heat v2`
   - 复盘分析 `paper_analytics`
   - 报告解释层

---

## 二、设计原则

### 2.1 数据源职责分离

- `surf`：
  - 全球/英文/跨站新闻搜索
  - 社交用户、帖子、mindshare、sentiment
  - 跨域搜索和补充市场背景
- `PANews`：
  - 中文新闻、专题、系列、栏目、热榜
  - 活动/日历/编辑推荐/热点关键词
  - Polymarket smart money board 公开快照
- `OKX OnchainOS`：
  - 链上聪明钱/KOL/Whale 实时行为
  - X 热度榜代理
- `Binance Alpha + Futures`：
  - 交易所热度确认
  - 价格反应与执行承接

### 2.2 不直接依赖单一黑盒总分

外部来源即使提供了现成评分，也不直接当项目总分使用。所有情报应先落成结构化字段，再由本项目自行计算：

- `social_momentum_score`
- `news_narrative_score`
- `kol_attention_score`
- `public_board_snapshot_score`

### 2.3 快照优先

实时情报会快速变化。所有用于评分和复盘的情报都应以“扫描当时快照”为准，避免复盘时重新查询导致数据漂移。

### 2.4 中文与全球视角并存

- `surf` 提供全球视角
- `PANews` 提供中文编辑视角

两者不是互斥关系，应并存并在字段层面区分来源。

### 2.5 渐进式获取，避免情报层放大扫描成本

社交情报与新闻叙事层不应对所有候选一视同仁地深查。V1 采用“分层获取”策略：

1. 先用现有基础因子计算 `base_oos`
   - `turnover_activity`
   - `momentum_window`
   - `holder_structure`
   - `smart_money_resonance`
   - `market_cap_fit`
   - `intraday_position`
2. 仅对基础排名前 50% 或 `base_oos >= 45` 的候选触发 `surf / PANews` 情报查询
3. 全量接口只拉一次并缓存
   - `PANews get-rankings`
   - `PANews get-hooks`
4. 热点关键词与热榜缓存 30 分钟，扫描间复用

这样可以把情报层从“全候选深查”改为“有潜力候选深查”，控制扫描耗时和免费额度压力。

---

## 三、能力映射

### 3.1 Surf 可承接的能力

依据 `surf` skill 可确认的域能力：

- `news-*`, `search-news`
- `social-*`
- `market-*`
- `project-*`
- `search-*`

适合接入的字段：

- `social_mentions_6h`
- `social_mentions_24h`
- `social_growth_6h`
- `social_growth_24h`
- `mindshare_score`
- `sentiment_score`
- `global_news_count_24h`
- `global_news_headlines`
- `global_news_event_tags`
- `global_project_mentions`

### 3.2 PANews 可承接的能力

依据 `PANews` skill 可确认命令：

- `list-articles`
- `get-daily-must-reads`
- `get-rankings`
- `search-articles`
- `list-topics`
- `get-topic`
- `list-columns`
- `list-series`
- `list-events`
- `list-calendar-events`
- `get-hooks`
- `list-polymarket-boards`
- `get-polymarket-board`
- `get-polymarket-highlights`
- `compare-polymarket-boards`

适合接入的字段：

- `panews_article_count_24h`
- `panews_latest_headlines`
- `panews_hot_rank`
- `panews_topic_tags`
- `panews_editorial_keywords`
- `panews_event_count_7d`
- `panews_calendar_flags`
- `panews_polymarket_board_score`
- `panews_polymarket_board_labels`

### 3.3 OKX OnchainOS 可承接的能力

适合继续复用的字段：

- `okx_x_rank`
- `okx_hot_rank`
- `kol_onchain_activity_count`
- `smart_money_onchain_activity_count`
- `wallet_type_mix`
- `signal_wallet_count`
- `tracker_overlap_score`

### 3.4 Binance 可承接的能力

适合继续复用的字段：

- `alpha_count24h`
- `alpha_pct`
- `price_reaction_1h`
- `price_reaction_6h`
- `price_reaction_24h`

---

## 四、统一 Provider 设计

新增：

- `scripts/providers/intel.py`

职责：

- 编排 `surf / PANews / OKX / Binance`
- 统一返回标准化情报结构
- 统一健康状态、抓取时间、来源置信度

### 4.1 ProviderResult

```python
class ProviderResult(TypedDict):
    ok: bool
    source: str
    fetched_at: int
    latency_ms: float
    confidence: float
    error_type: str | None
    message: str | None
    data: dict[str, Any]
```

### 4.2 UnifiedSocialIntel

```python
class UnifiedSocialIntel(TypedDict):
    symbol: str
    chain: str | None
    token_address: str | None
    snapshot_timestamp: int

    social_mentions_6h: int | None
    social_mentions_24h: int | None
    social_growth_6h: float | None
    social_growth_24h: float | None
    social_heat_direction: str | None
    mindshare_score: float | None
    sentiment_score: float | None

    global_news_count_24h: int | None
    global_news_headlines: list[str]
    global_news_event_tags: list[str]

    panews_article_count_24h: int | None
    panews_latest_headlines: list[str]
    panews_hot_rank: int | None
    panews_topic_tags: list[str]
    panews_editorial_keywords: list[str]
    panews_event_count_7d: int | None
    panews_calendar_flags: list[str]

    kol_social_mentions: int | None
    kol_onchain_activity_count: int | None
    smart_money_onchain_activity_count: int | None

    public_board_snapshot_score: float | None
    public_board_snapshot_labels: list[str]

    narrative_labels: list[str]
    source_confidence: dict[str, float]
    status: dict[str, dict[str, Any]]
    source_degraded: list[str]
```

### 4.3 核心方法

建议实现：

- `fetch_social_intel(symbol, chain=None, token_address=None) -> UnifiedSocialIntel`
- `fetch_surf_social(symbol) -> ProviderResult`
- `fetch_surf_news(symbol) -> ProviderResult`
- `fetch_panews_news(symbol) -> ProviderResult`
- `fetch_panews_topics(symbol) -> ProviderResult`
- `fetch_panews_events(symbol) -> ProviderResult`
- `fetch_panews_polymarket_snapshot(symbol) -> ProviderResult`
- `fetch_okx_attention(symbol, token_address, chain) -> ProviderResult`
- `merge_intel_results(...) -> UnifiedSocialIntel`

### 4.4 降级与 Circuit Breaker 规则

新增：

- `SocialIntelDegradeStrategy`

规则：

1. 单源失败
   - `surf` 连续失败时：静默降级到 `PANews + OKX + Binance`
   - `PANews` 返回空列表时：标记 `source_degraded=["panews"]`，但不阻断评分
   - `OKX x_rank` 缺失时：`social_momentum_score` 去掉该输入，按剩余输入归一化
2. 多源失败
   - 可用来源数 / 计划来源数 `< 0.5` 时，触发整体降级
   - `social_heat_v2` 降为保守模式，只使用：
     - `okx_x_rank`
     - `alpha_count24h`
     - `kol_onchain_activity_count`
3. 全部社交源不可用
   - `social_heat_v2 = 0`
   - 结果中写明：
     - `source_degraded=["surf", "panews", "okx_social"]`
     - `social_heat_unavailable=true`
4. 熔断
   - 任一外部源连续 3 次出现 `503 / timeout / rate_limit`
   - 30 分钟内不再主动调用该源，仅使用缓存

---

## 五、字段定义与解释

### 5.1 社交热度字段

- `social_mentions_6h`
  - 最近 6 小时提及总量
- `social_mentions_24h`
  - 最近 24 小时提及总量
- `social_growth_6h`
  - 与前一 6h 窗口相比的变化率
- `social_growth_24h`
  - 与前一 24h 窗口相比的变化率
- `social_heat_direction`
  - `accelerating | stable | cooling | unknown`
- `mindshare_score`
  - surf 社交注意力代理分
- `sentiment_score`
  - surf 情绪代理分

说明：

- Provider 层优先返回原始 counts / score
- `growth` 由情报聚合层结合历史快照计算
- 第一次扫描或窗口不足时：
  - `social_growth_6h = 0.0`
  - `social_growth_24h = 0.0`
  - 不因缺历史窗口而直接降级

### 5.2 新闻与活动字段

- `global_news_count_24h`
  - surf 全球新闻命中数
- `panews_article_count_24h`
  - PANews 近 24h 命中数
- `panews_latest_headlines`
  - 最新标题摘要
- `panews_editorial_keywords`
  - 来自 `get-hooks` 的热点词
- `panews_event_count_7d`
  - 近 7 天活动/事件命中数
- `panews_calendar_flags`
  - 日历事件标签，如 `listing`, `unlock`, `governance`, `conference`

### 5.3 KOL 与公开榜单字段

- `kol_social_mentions`
  - surf 侧 KOL/社交大号提及量代理
- `kol_onchain_activity_count`
  - OKX KOL 链上行为次数
- `smart_money_onchain_activity_count`
  - OKX smart money 行为次数
- `public_board_snapshot_score`
  - 来自 PANews Polymarket board 的公开情绪强度代理
- `public_board_snapshot_labels`
  - 如 `top_board`, `hot_highlights`, `consensus_bullish`

### 5.4 叙事分类字段

- `narrative_labels`
  - 项目当前叙事标签，枚举建议：
    - `meme`
    - `ai`
    - `politics`
    - `celebrity`
    - `infra`
    - `exchange`
    - `regulation`
    - `defi`
    - `gaming`
    - `prediction_market`

叙事来源：

- PANews 标题/主题/栏目/系列
- surf 新闻标题/项目搜索结果
- OKX 热点描述（如可用）

### 5.5 V1 叙事分类基线

V1 不依赖 LLM 分类。先实现一个低成本关键词分类器：

```python
NARRATIVE_KEYWORDS = {
    "ai": ["ai", "agent", "gpt", "llm", "intelligence"],
    "politics": ["trump", "election", "sec", "regulation", "congress"],
    "meme": ["meme", "pepe", "dog", "cat", "woof"],
    "defi": ["defi", "swap", "yield", "lending", "liquidity"],
    "gaming": ["game", "gaming", "metaverse", "play"],
    "exchange": ["listing", "binance", "coinbase", "okx", "bybit"],
}
```

输入：

- `symbol`
- `global_news_headlines`
- `panews_latest_headlines`
- `panews_topic_tags`
- `panews_editorial_keywords`

输出：

- 命中的标签并入 `narrative_labels`

V2 再升级到 LLM 分类与更精细的主题归因。

---

## 六、评分设计：Social Heat v2

当前 `score_social_heat()` 过于简化，仅使用：

- `okx_x_rank`
- `alpha_count24h`

建议升级为两个子模块：

1. `social_momentum_score`（满分 8）
2. `news_narrative_score`（满分 7）

总计：

- `social_heat_v2` 满分 15

### 6.1 social_momentum_score（8）

建议输入：

- `okx_x_rank`
- `social_mentions_24h`
- `social_growth_6h`
- `mindshare_score`
- `alpha_count24h`

建议逻辑：

- `okx_x_rank <= 5`：+2
- `social_mentions_24h` 高：+2
- `social_growth_6h > 0.5`：+2
- `mindshare_score` 高：+1
- `alpha_count24h` 与社交升温共振：+1

### 6.2 news_narrative_score（7）

建议输入：

- `global_news_count_24h`
- `panews_article_count_24h`
- `panews_editorial_keywords`
- `panews_event_count_7d`
- `public_board_snapshot_score`
- `narrative_labels`

建议逻辑：

- 24h 新闻覆盖显著：+2
- PANews 热榜 / 热点关键词命中：+2
- 活动 / 日历催化明确：+1
- Polymarket board 高亮：+1
- 处于热点叙事标签：+1

### 6.3 权重建议

将当前 OOS 的社交热度由 `5` 分提升为 `15` 分。

当前代码里的 OOS 满分为 `100`：

- `25 + 20 + 20 + 15 + 10 + 5 + 5`

升级后 OOS 满分变为 `110`：

- `25 + 20 + 20 + 15 + 10 + 5 + 15`

因此阈值需要同步调整，避免无意放宽通过率。

V1 设计选择：

- `meme_onchain` 的 OOS 阈值从 `70` 提高到 `75`
- `majors_cex` 继续以执行承接为主，不单独因为社交层抬升阈值

这是一种“轻度收紧”而非精确等比迁移，目的是：

- 保持 meme 策略的选择性
- 避免社交层抬权后让更多低质量币误入交易
- 后续通过 `paper_analytics` 复盘再校准

形成新的 OOS：

- `turnover_activity`
- `momentum_window`
- `holder_structure`
- `smart_money_resonance`
- `market_cap_fit`
- `intraday_position`
- `social_heat_v2`

注意：

- 不建议让社交层超过链上结构和聪明钱的总权重
- 目标是“增强 meme 场景识别”，而不是把系统变成新闻追涨器

---

## 七、候选发现增强

情报层除了用于评分，也可用于增强候选发现。

### 7.1 新增发现入口

- `surf search-news`
- `PANews get-rankings`
- `PANews get-daily-must-reads`
- `PANews get-hooks`

### 7.2 新增来源标签

候选资产新增：

- `candidate_sources += ["surf_news_hot"]`
- `candidate_sources += ["panews_hot_rank"]`
- `candidate_sources += ["panews_daily_reads"]`
- `candidate_sources += ["panews_editorial_hook"]`

### 7.3 候选用途

- `surf_news_hot`
  - 全球热点候选
- `panews_hot_rank`
  - 中文内容热点候选
- `panews_editorial_hook`
  - 编辑热点/搜索热点候选

注意：

- 这些来源应作为“加候选池”的补充
- 不应直接绕过 `OKX + Binance` 的评分与执行约束
- 新闻来源候选进入正式评分前，至少需满足：
  - OKX OnchainOS 可查到该资产
  - 至少有 `LOW` 置信度的 CEX 映射
  - 24h 链上交易量 > `$10K`
- 不满足上述条件时：
  - 允许进入 `watch_only`
  - 不进入正式 `recommend_paper_trade` 流程

---

## 八、快照与持久化设计

### 8.1 扫描快照

新增输出：

- `15_social_intel.json`

内容：

- 每个候选的统一社交情报快照
- 各子来源的 status
- 叙事标签与事件标签
- `snapshot_timestamp`
- `source_degraded`

### 8.2 历史快照

建议新增：

- `history/social_YYYYMMDDHH.json`
- `history/news_YYYYMMDDHH.json`

用途：

- 计算 6h / 24h 变化
- 支持回溯“当时为什么给高分”

说明：

- `growth` 计算不在单一 provider 内完成
- 由情报聚合层读取历史快照后统一计算
- 如果扫描间隔不规则，则使用“最近不晚于目标窗口的快照”做近似比较

### 8.3 Paper Trading 快照回写

创建 `paper_position` 时，固化：

- `social_heat_score`
- `social_mentions_24h`
- `social_growth_6h`
- `mindshare_score`
- `panews_article_count_24h`
- `panews_event_count_7d`
- `narrative_labels`
- `public_board_snapshot_score`

避免复盘时再查实时数据。

---

## 九、复盘与分析设计

扩展 `paper_analytics.py`：

### 9.1 新增分组维度

- `social_heat_bucket`
- `news_heat_bucket`
- `social_growth_bucket`
- `narrative_label`
- `event_flag`

### 9.2 新增问题可回答

- 高社交热度是否真的提升胜率？
- `social_growth_6h > 50%` 的币是否更容易 hit TP1？
- 哪类叙事（AI / politics / meme）更适合短线 paper trade？
- 有 PANews 活动/日历催化的标的，价格反应是否更强？
- `public_board_snapshot_score` 高的币是否更容易给出 follow-through？

---

## 十、开发范围建议

### V1：先做

目标：尽快把新闻与社交从“弱代理”升级为“基本可用”。

范围：

1. 新增 `providers/intel.py`
2. 接入：
   - `surf`：新闻 + social
   - `PANews`：文章/排名/keywords/events/calendar/board
3. 输出统一 `UnifiedSocialIntel`
4. 生成 `15_social_intel.json`
5. 升级 `score_social_heat()` → `social_heat_v2`
6. 将关键字段写入 `paper_position`
7. 在 `paper_analytics` 中补：
   - `direction`
   - `score_bucket`
   - `social_heat_bucket`
   - `narrative_label`
8. 实现降级策略与 30 分钟缓存
9. 采用“基础 OOS 初筛后再查情报层”的分层获取策略

### V2：第二阶段

1. 候选发现增加：
   - `surf_news_hot`
   - `panews_hot_rank`
2. 叙事分类增强：
   - 标题/主题 → LLM 分类
3. KOL 提及统计增强
4. 事件→价格反应回测

### V3：第三阶段

1. 中文社区扩展（如 Telegram / Discord，如后续确认需要）
2. 复杂事件图谱
3. 更高级的叙事共振模型

---

## 十一、开发任务拆分

### P0 — 基础接入

1. 新增 `scripts/providers/intel.py`
   - 定义统一 schema
   - 接入 surf / PANews / OKX / Binance 结果合并

2. 新增 `scripts/social_scoring.py` 或扩展 `scoring_modules.py`
   - 实现 `score_social_momentum()`
   - 实现 `score_news_narrative()`
   - 组合成 `social_heat_v2`

3. 修改 `auto-run.py`
   - 扫描阶段抓取 social/news intel
   - 保存 `15_social_intel.json`
   - 将情报注入 `score_candidate()`

4. 修改 `radar_logic.py`
   - 接收新的 social/news 字段
   - 将 `social_heat` 从 `5` 分升级到 `15` 分模型

### P1 — 持久化与复盘

5. 修改 `history_store.py`
   - 新增 social/news 快照文件

6. 修改 `paper_order_manager.py`
   - 将 social/news snapshot 固化到 position

7. 修改 `paper_analytics.py`
   - 新增 social/news 分组统计

### P2 — 发现层增强

8. 修改 `candidate_discovery.py`
   - 支持 `surf_news_hot`
   - 支持 `panews_hot_rank`
   - 支持 `panews_editorial_hook`

9. 修改报告输出
   - 在 top candidate 解释中显示：
     - 热点关键词
     - 叙事标签
     - 新闻覆盖
     - 事件/日历催化

---

## 十二、实施顺序建议

推荐顺序：

1. `providers/intel.py`
2. `social_heat_v2`
3. `auto-run.py` 接入与快照保存
4. `paper_position` 快照回写
5. `paper_analytics` 分组增强
6. 候选发现增强

原因：

- 先打通数据，再改评分
- 先改评分，再做复盘
- 等复盘指标稳定后，再决定是否让新闻源参与候选发现

---

## 十三、结论

`surf + PANews + OKX + Binance` 形成的是四层互补结构：

- `surf`：全球新闻与社交情报
- `PANews`：中文新闻、活动、热点关键词、公开 board 快照
- `OKX`：链上实时 KOL / smart money 行为
- `Binance`：价格反应与执行承接

这一层完成后，项目将从“链上+执行雷达”升级为“链上 + 社交 + 新闻 + 叙事 + 执行”的综合情报雷达，更适合 meme coin 的真实驱动机制。
