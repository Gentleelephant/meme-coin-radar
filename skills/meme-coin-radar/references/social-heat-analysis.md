# 社交热度与舆情评分分析

> 分析时间：2026-04-27
> 目标：评估当前系统对社交传播、热点事件、叙事驱动的捕获能力

---

## 一、结论

**当前系统的社交热度评分非常初级，对于 meme coin 最核心的上涨驱动力（社交传播+叙事热点）覆盖极弱。**

---

## 二、当前实现

### 2.1 社交评分函数

`scoring_modules.py:217-231` — `score_social_heat()`

```python
def score_social_heat(okx_x_rank, alpha_count24h):
    okx_score = 0
    if okx_x_rank <= 5:      okx_score = 3
    elif okx_x_rank <= 15:   okx_score = 2
    elif okx_x_rank <= 30:   okx_score = 1

    alpha_score = 0
    if alpha_count24h >= 100000:  alpha_score = 2
    elif alpha_count24h >= 50000: alpha_score = 1

    return min(okx_score + alpha_score, 5)  # 满分仅 5 分
```

### 2.2 依赖的数据源

| 指标 | 来源 | 说明 |
|---|---|---|
| `okx_x_rank` | OKX OnchainOS | OKX 内部计算的 X/Twitter 提及热度排名 |
| `count24h` | Binance Alpha | Binance 社区 24h 交易/交互量 |
| `alpha_pct` | Binance Alpha | 24h 涨跌百分比 |

### 2.3 权重占比

| 评分维度 | 满分 | 占比 |
|---|---|---|
| OOS 总分 | 125 | 100% |
| 其中社交热度 | 5 | 4% (of OOS) / 2.5% (of total OOS+ERS) |

---

## 三、缺失的能力

| 能力 | 是否有 | 影响 |
|---|---|---|
| X/Twitter 实时搜索量 | ❌ 没有 | 无法获取实时推文热度 |
| X/Twitter 趋势排名 | ❌ 没有 | 无法判断是否登上热门 |
| 国际热点事件检测 | ❌ 没有 | 无法关联"特朗普概念"、"AI 叙事"等 |
| 社交媒体情感分析 | ❌ 没有 | 无法区分 FOMO 与 FUD |
| 新闻/舆情爬取 | ❌ 没有 | 无法追踪监管/上线/合作新闻 |
| 叙事主题分类 | ❌ 没有 | 无法识别"这是 AI meme 还是政治 meme" |
| KOL/大V 提及监测 | ❌ 没有 | 无法识别关键传播节点 |
| Telegram/Discord 热度 | ❌ 没有 | 无法覆盖中文社区传播 |

---

## 四、为什么这对 meme coin 项目很关键

Meme coin 与传统资产的核心区别：

| 特征 | 传统资产 | Meme Coin |
|---|---|---|
| 定价基础 | 基本面/现金流 | 叙事+情绪+传播 |
| 爆发驱动 | 财报/宏观 | 社交传播/名人喊单 |
| 生命周期 | 年/季度 | 小时/天 |
| 关键指标 | PE/营收 | 推文量/搜索量/KOL提及 |

**当前系统擅长分析"链上数据是否健康"和"CEX 执行条件是否成熟"，但无法回答最核心的问题：这个币现在有没有人在社交网络上讨论？**

一个链上数据完美、但没人讨论的 meme coin，和一个链上数据一般、但正在 X/Twitter 疯传的 meme coin，后者涨的概率远高于前者。

---

## 五、建议改进方案

### P0 — 快速接入

**X API 搜索量统计（半天）**
- 通过 X API v2 `tweets/counts/recent` 搜索 token symbol
- 获取 24h/1h 推文量、趋势变化
- 接入简单，成本低

### P1 — 中等复杂度

**叙事主题识别（2-3 天）**
- 用 LLM 对当日推文摘要做主题分类
- 识别当前主流叙事（AI、DeFi、政治、动物、名人等）
- 对处于热点叙事的 token 加分

**KOL 提及检测（1-2 天）**
- 追踪关键 KOL 地址/账号
- 当 KOL 提及某 token 时标记为高权重信号

### P2 — 高复杂度

**热点事件关联系统（1-2 周）**
- 爬取国际新闻/监管动态/名人推文
- 建立事件→币种映射（Trump 被提及 → MAGA/TRUMP 币）
- 事件热度映射为评分权重

**Telegram/Discord 热度（1 周）**
- 接入中文社区群聊
- 统计群名/关键词提及频率

---

## 六、推荐先行方案

**从最简单的开始** — 直接调 X API v2 的搜索计数接口：

```
GET https://api.twitter.com/2/tweets/counts/recent?query={symbol}&granularity=hour
```

返回 24h 内每小时的推文量，直接就能拿到：
- 24h 推文总量
- 最近 1h 增速
- 趋势方向（上升/下降）

这是投入产出比最高的改进，一天内就能让社交热度从"聊胜于无"变成"基本可用"。

---

*分析时间：2026-04-27*
*项目：meme-coin-radar Phase 3.0*