# 社交情报层设计审查 — 待优化项

> 审查时间：2026-04-27
> 审查对象：`references/social-intel-design.md`
> 当前状态：设计已定稿，代码尚未实现
> 总体评分：**8/10** — 架构清晰、字段定义完整、四层互补合理

---

## 待优化项清单

### P0 — 必须明确后再开始实现

#### 1. OOS 总分阈值未同步调整

**现状：**
- 设计将 `social_heat` 从 `5` 分升级到 `15` 分（+10）
- 当前 OOS 满分 = 130（social_heat 是 5/130）
- 升级后 OOS 满分 = 140（social_heat 是 15/140）
- 当前 OOS 硬阈值：meme_onchain 模式 `>= 70`

**问题：**
- `70/130 = 53.8%` → `70/140 = 50.0%`
- 阈值不变意味着实际通过条件放宽了 3.8 个百分点
- 会影响候选通过率，可能导致更多 false positive 进入交易

**建议修复：**
- 方案 A：OOS 阈值同步提高到 `75`（保持 53.8% 的通过率）
- 方案 B：保持 `70` 不变，但声明这是主动放宽（需要在复盘阶段验证是否合理）
- 设计中必须明确选择其中一种

#### 2. 缺少 Source Degrade / Circuit Breaker 策略

**现状：**
- `ProviderResult` 定义了 `error_type` 和 `confidence`
- 但没有定义当某个数据源连续失败时的行为
- 设计第 4 节有 status 字段，但未定义降级规则

**待明确的场景：**

| 场景 | 需要的行为 |
|---|---|
| surf API 连续 3 次返回 503 | 静默跳过 surf，用 PANews + OKX 继续 |
| PANews 热点关键词返回空 | 不影响评分，但标记 `source_degraded: panews` |
| OKX x_rank 不可用 | social_momentum 降级为只用其余 4 个输入 |
| 所有社交源都挂了 | social_heat_v2 整体降级为 0，并在报告中说明原因 |

**建议修复：**
- 新增 `SocialIntelDegradeStrategy` 定义各级降级行为
- 在 `merge_intel_results()` 中实现降级逻辑：`available_sources / total_sources < 0.5` 时整体降级

---

### P1 — 建议 V1 实现前确认

#### 3. 单次扫描 API 调用量过高

**现状分析：**
假设单次扫描有 100 个候选币，每个币的 API 调用量：

| 来源 | 每币调用数 | 说明 |
|---|---|---|
| surf search-news | 1 | 按 symbol 搜索新闻 |
| surf social | 1 | 按 symbol 查社交数据 |
| PANews search-articles | 1 | 按 symbol 搜索中文文章 |
| PANews get-rankings | 1× | 这个是全量接口，不应按币调用 |
| PANews get-hooks | 1× | 这个也是全量接口，不应按币调用 |
| OKX OnchainOS | 0 | 已有数据，直接复用 |
| **总计** | ~400 次 | 100 币 × 4 次 + 2 次全量 |

**问题：**
- 400+ 次外部 API 调用/扫描，扫描时间会显著增加
- surf 和 PANews 都可能限制免费 tier 的调用频率
- 大多数候选币最终被过滤掉（OOS < 70），对它们做深度情报查询是浪费

**建议修复：**
- **分层获取**：先计算不依赖情报层的基础 OOS（turnover + momentum + holder + mc_fit + intraday），只有基础排名前 50% 的币才触发情报查询
- **批量化**：PANews `get-hooks`（热点关键词）和 `get-rankings`（热榜）全量获取一次，按关键词匹配所有候选币
- **缓存策略**：热点关键词每 30 分钟拉一次，扫描间复用

#### 4. narrative_labels V1 缺少基线实现

**现状：**
- 设计 V2 阶段提到「标题/主题 → LLM 分类」
- 但 V1 阶段 `narrative_labels` 如何填充没有定义
- 这意味着 V1 的 `news_narrative_score` 中 "处于热点叙事标签：+1" 项永远无法得分

**建议修复：**
- V1 实现一个基于关键词匹配的简单分类器：

```python
NARRATIVE_KEYWORDS = {
    "ai": ["ai", "intelligence", "gpt", "chatgpt", "agent", "llm"],
    "politics": ["trump", "election", "congress", "sec", "regulation"],
    "meme": ["meme", "dog", "cat", "pepe", "woof"],
    "defi": ["defi", "lending", "swap", "yield", "liquidity"],
    "gaming": ["game", "gaming", "metaverse", "play"],
}
```

- 对 symbol + news headline + PANews 标题做关键词匹配
- 匹配到的标签加入 `narrative_labels`
- 这比空列表好，而且几乎零成本

---

### P2 — 可第二阶段优化

#### 5. UnifiedSocialIntel 缺少统一快照时间戳

**现状：**
- 每个 `ProviderResult` 有 `fetched_at`（各数据源各自的抓取时间）
- 但 `UnifiedSocialIntel` 本身没有聚合快照的时间戳

**问题：**
- 复盘时无法判断 "这份情报是在扫描的哪个时间点生成的"
- 如果多个数据源的 `fetched_at` 相差很大（例如 surf 慢、PANews 快），无法知道整体情报的时效性
- 与设计文档自己的 "快照优先" 原则矛盾（第 2.3 节）

**建议修复：**
- `UnifiedSocialIntel` 增加 `snapshot_timestamp: int` 字段
- 值为 `merge_intel_results()` 的调用时间，而非数据源抓取时间

#### 6. 候选发现增强缺少过滤机制

**现状：**
- 设计 P2 阶段允许 `surf_news_hot` 和 `panews_hot_rank` 参与候选发现
- 但没有设置任何最低门槛

**问题：**
- 新闻热门话题可能包含大量非交易对的 meme 币
- 可能引入 "只上过新闻但没有链上流动性" 的垃圾候选
- 增加候选池噪音，浪费后续评分资源

**建议修复：**
- 新闻来源发现的候选至少需满足：
  - 链上存在（OKX OnchainOS 可查到）
  - 至少有 LOW 置信度的 CEX 映射
  - 24h 链上交易量 > $10K
- 不满足上述条件的新闻候选标记为 `watch_only`，不进入正式评分

#### 7. social_growth 计算依赖未定义

**现状：**
- 设计定义了 `social_growth_6h` 和 `social_growth_24h` 字段
- 含义是 "与前一窗口相比的变化率"
- 设计 8.2 节提到保存历史快照
- **但没有明确 growth 计算在哪个环节执行**

**问题：**
- 第一次扫描时没有前一窗口数据，growth 全部为 `None`
- 计算是在 provider 层做？评分层做？还是独立的 post-processing？
- 如果扫描间隔不规律（有时隔 2h，有时隔 8h），6h 窗口对比怎么对齐？

**建议修复：**
- 明确 growth 计算由**评分层**执行（提供层只保存原始 counts）
- 评分层从历史快照读取前一窗口数据，计算出 growth
- 第一次扫描 / 窗口不足时，growth 默认为 0（而非 None），避免评分降级

---

## 总结

| # | 问题 | 优先级 | 影响面 | 建议操作 |
|---|------|--------|--------|----------|
| 1 | OOS 阈值未同步调整 | P0 | 评分决策 | 实现前确定阈值方案 |
| 2 | 缺少 degrade 策略 | P0 | 系统稳定性 | 新增降级规则定义 |
| 3 | API 调用量过高 | P1 | 性能 | 分层获取 + 批量缓存 |
| 4 | narrative_labels V1 无填充 | P1 | V1 功能完整性 | 关键词匹配基线 |
| 5 | 统一时间戳缺失 | P2 | 复盘准确性 | 新增 snapshot_timestamp |
| 6 | 新闻候选无过滤 | P2 | 候选质量 | 增加链上 + 映射门槛 |
| 7 | growth 计算时机未定义 | P2 | 数据一致性 | 明确评分层计算 |

---

*审查时间：2026-04-27*
*项目：meme-coin-radar Phase 3.0*