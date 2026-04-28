# Code Review Report — 妖币雷达 Phase 3.0

> 审查范围: 13 个修改文件 + 3 个新文件 + 测试文件
> 审查时间: 2026-04-28
> 审查重点: Bug / 代码质量 / 可优化项

---

## 目录

1. [Bug 级别](#1-bug-级别)
2. [代码质量问题](#2-代码质量问题)
3. [可优化项](#3-可优化项)
4. [安全与健壮性](#4-安全与健壮性)
5. [总结](#5-总结)

---

## 1. Bug 级别

### B1. `radar_logic.py:517` — `intraday_low` 使用 `max()` 导致日内位置计算偏差

```python
# 当前代码:
intraday_high = max(to_float(price_info.get("maxPrice")), to_float(ticker.get("high24h")))
intraday_low = max(to_float(price_info.get("minPrice")), 0.0)
```

**问题**: `intraday_low` 只引用了 `price_info.minPrice`，未考虑 `ticker.low24h`，而 `intraday_high` 同时考虑了两种来源。当 `price_info.minPrice` 缺失而 `ticker.low24h` 有值时，`intraday_low` 回退到 0.0，导致 `day_pos` 严重失真。

**影响**: 对 `score_intraday_position()` 和 `score_execution_timing()` 两个评分函数产生错误输入。

**修复建议**: 保持高低对称性：
```python
intraday_low = min(to_float(price_info.get("minPrice")), to_float(ticker.get("low24h"))) or to_float(price_info.get("minPrice"))
# 或更简洁:
intraday_low = to_float(price_info.get("minPrice")) or to_float(ticker.get("low24h"))
```

---

### B2. `radar_logic.py:884` — `kline_source` 元数据使用了错误字段

```python
# 当前代码:
"kline_source": ticker.get("source", "binance") if (ticker and klines) else "",
```

**问题**: 条件检查的是 `klines` 是否存在，但 `.get("source")` 却取自 `ticker`。当 klines 来自 hyperliquid fallback 时，source 元数据丢失，报告显示来源不准确。

**修复建议**:
```python
"kline_source": (klines_meta.get("source") or ticker.get("source", "binance")) if klines else "",
```
不过 `_klines_meta()` 不保存 source 字段。建议在返回 `meta` 时保存 klines 的 source。

---

### B3. `history_store.py:229-238` — `cleanup_old_snapshots` 日期解析忽略非标准文件名

```python
date_str = path.stem.split("_")[-1]
file_date = datetime.strptime(date_str, "%Y%m%d")
```

**问题**: 目录中存在多种文件名模式：
- `ticker_20260428.json` — 正常，`%Y%m%d` 可解析
- `alpha_20260428.json` — 正常
- `social_2026042815.json` — 格式 `%Y%m%d%H`，会抛出 `ValueError`
- `intel_cache_panews_rankings_en.json` — 无日期后缀，同样报错

任一文件解析失败会导致整个 `try` 块跳过（`continue`），但该文件不会被清理，长期累积造成历史残留。

**影响**: 小，但长期运行可能导致目录膨胀。

**修复建议**: 使用更灵活的模式匹配：
```python
# 方案 A: 只清理已知模式的 snapshot 文件
for prefix in ("ticker_", "alpha_", "oi_", "social_"):
    for path in hdir.glob(f"{prefix}*.json"):
        ...
# 方案 B: 多种日期格式 fallback
for fmt in ("%Y%m%d", "%Y%m%d%H"):
    try:
        file_date = datetime.strptime(date_str, fmt)
        break
    except ValueError:
        continue
else:
    continue  # skip unmatched
```

---

### B4. `intel.py:373` — `panews_hot_rank` 关键词匹配过于宽松

```python
"panews_hot_rank": 1 if symbol.lower() in " ".join(shared_keywords).lower() else None,
```

**问题**: 子串匹配会导致误报。例如 `symbol="a"` 会匹配任何含字母 "a" 的关键词，`symbol="INJ"` 会匹配 "INJECTIVE"。应该用分词级别的精确匹配。

**修复建议**:
```python
kw_set = set(w.lower() for w in shared_keywords)
"panews_hot_rank": 1 if symbol.lower() in kw_set else None,
```

---

### B5. `paper_analytics.py:100-101` — 零盈亏交易分类逻辑

```python
wins = [pos for pos in closed if float(pos.get("realized_pnl", 0.0)) > 0]
losses = [pos for pos in closed if float(pos.get("realized_pnl", 0.0)) <= 0]
```

**问题**: 盈亏为 0 的交易被归类为亏损，影响胜率计算。虽然严格来说 0 不算赢，但归类为亏损会拉低胜率。更常见的做法是单独统计打平交易。

**影响**: 小额，当存在大量保本出场的交易时，胜率会系统性偏低。

---

### B6. `radar_logic.py:631-638` — `volume_vs_7d` 使用硬编码 klines 索引

```python
vols = [float(k[4]) for k in klines_1d[-8:]]
```

**问题**: 索引 `4` 对应 Binance klines 的 volume 字段，但这个约定没有注释或常量定义，可读性差。

**影响**: 可维护性问题，当 klines 格式变化时容易断裂。

---

## 2. 代码质量问题

| # | 文件 | 问题 | 说明 |
|---|------|------|------|
| Q1 | 全部 .py 文件 | 重复的 try/except import 模式 | 每个文件都在 try/except 中处理 `.providers.` 和直接 import，约 15 处重复。建议改为绝对 import 或公共 import 辅助函数 |
| Q2 | `radar_logic.py` | 文件过长 (887 行) | 包含 klines 计算、评分、交易计划构建、方向判断等多个模块，建议拆分 |
| Q3 | `auto_run.py` | 文件过长 (939 行) | 集成了数据获取、评分、执行、报告生成的完整流程，建议拆分步骤函数 |
| Q4 | `skill_dispatcher.py:263-288` | `binance_smartmoney_signals()` 是死代码 | 定义了函数但从未被任何模块引用或调用 |
| Q5 | `auto_run.py:52` | `MEDALS` 列表格式不一致 | `["🥇", "🥈", "🥉", "4.", "5.", ...]` — 前三名用 emoji，后面用数字点，可能在 Markdown 渲染中对不齐 |
| Q6 | `binance.py:242-292` | `open_interest()` 返回结构不一致 | 其他函数返回 `(data, FetchStatus)` 元组，但 `open_interest` 返回内嵌 `status` 的字典，接口不统一 |
| Q7 | 全部 | 使用 `print()` 而非 `logging` | 约 50+ 处 `print()` 语句，无法控制日志级别、格式或输出目标 |
| Q8 | `config.py:119` | `.env` 路径硬编码 | `_load_dotenv(Path(".env"))` 依赖于当前工作目录，从其他目录运行会找不到 `.env` |
| Q9 | `radar_logic.py:484-488` | `market_cap` 计算使用 `max` 合并多源 | 如果两个源都返回 0（缺失时），`max(0, 0)` 返回 0，但缺失字段的 tracking 在 `missing_reasons` 中判断 `market_cap <= 0` 额外赋值。逻辑正确但不直观 |
| Q10 | `paper_strategy_feedback.py:64` | `_worst_groups` 排序键含义不明确 | 使用 `lambda item: (item["raw_win_rate"], item["net_pnl"], -item["stop_loss_rate"])`，正值和负值的语义混合 |
| Q11 | `onchainos.py:149` | 函数参数 `range_filter=1` 作为魔数 | 缺少注释说明 `1` 的含义（top 1% holders? 范围过滤级别？） |

---

## 3. 可优化项

### 3.1 性能优化

| # | 建议 | 文件 | 说明 |
|---|------|------|------|
| P1 | 添加 onchain snapshot 缓存 | `auto_run.py:301-336` | 每个候选 token 独立调用 6 个 onchainos 接口（price_info / advanced_info / cluster / holders / trades），无缓存。批量扫描 10-20 个 token 时产生 60-120 次 API 调用。建议添加短 TTL（60s）的内存缓存或 LRU 缓存 |

### 3.2 架构优化

| # | 建议 | 说明 |
|---|------|------|
| A1 | 引入 Pipeline/Stage 模式 | `auto_run.py` 的 7 个步骤（BTC→Alpha→OnchainOS→评分→执行→报告）当前是线性函数调用。提取 `ScanStage` 抽象可提高可测性和可扩展性 |
| A2 | 统一 Provider 接口 | `binance.py` 用 `(data, FetchStatus)` 元组，`onchainos.py` 也用 `(data, FetchStatus)`，但 `open_interest()` 用内嵌字典。所有 provider 应返回统一结构 |
| A3 | 配置验证 | `config.py` 的 `Settings` 无运行时校验（如 `top_n` 应 > 0, `min_rr` 应 > 1.0）。建议添加 `__post_init__` 验证 |

### 3.3 可维护性优化

| # | 建议 | 说明 |
|---|------|------|
| M1 | 抽取 common import helper | 将 `.providers.` 的相对/绝对 import 抽取到 `__init__.py` 中 |
| M2 | 为 klines 索引添加常量 | `INDEX_OPEN, INDEX_HIGH, INDEX_LOW, INDEX_CLOSE, INDEX_VOLUME` 提高可读性 |
| M3 | 为 Settings 字段添加文档注释 | 每个字段应说明单位（如 `stop_loss_atr_mult` 是 ATR 的倍数）、默认值含义、推荐范围 |

### 3.4 测试覆盖

| # | 文件 | 当前覆盖 | 建议 |
|---|------|----------|------|
| T1 | `test_paper_feedback.py` | 仅有 feedback 测试 | 缺少对 `scoring_modules.py` 中 20+ 个评分函数的单元测试 |
| T2 | `radar_logic.py` | 无测试 | `build_trade_plan()` 和 `score_candidate()` 是最核心逻辑，应添加参数化测试 |
| T3 | `score_candidate` 的 hard_reject 路径 | 无测试 | 7 条硬否决规则应各有对应测试用例 |

---

## 4. 安全与健壮性

### 4.1 输入验证

- `candidate_discovery.py:54` — `_norm_chain()` 链 ID 映射是封闭字典，未知链 ID 直接返回原始值，行为可预期
- `intel.py:36-39` — `NARRATIVE_KEYWORDS` 关键词匹配使用 `in` 运算符，可能存在子串误匹配。**已在 B4 中报告**

### 4.2 异常处理

- 整体异常处理覆盖良好，`FetchStatus` 提供了结构化的错误分类
- `http_json_safe()` 中的 `urllib` 错误处理覆盖了 HTTPError、超时等常见场景
- `run()` 函数中 `subprocess` 调用有时间控制和异常捕获

### 4.3 数据持久化

- `history_store.py` 的所有 I/O 操作都有 `try/except` 保护
- JSONL 文件 (`paper_events.jsonl`, `paper_closed_positions.jsonl`) 的逐行追加模式在并发写入时不安全（缺乏文件锁）

---

## 5. 总结

### 需要立即修复 (Must Fix)

| 优先级 | Bug ID | 说明 | 影响范围 |
|--------|--------|------|----------|
| **高** | B1 | `intraday_low` 使用 `max()` 导致 `day_pos` 计算偏差 | `score_intraday_position`, `score_execution_timing` |
| **中** | B2 | `kline_source` 元数据使用 ticker 字段 | 报告数据来源展示 |
| **中** | B4 | `panews_hot_rank` 子串匹配过于宽松 | 社交评分稳定性 |
| **低** | B3 | `cleanup_old_snapshots` 非标准文件名异常 | 历史目录维护 |

### 建议修复 (Should Fix)

| 优先级 | ID | 说明 |
|--------|-----|------|
| 高 | Q4 | 删除死代码 `binance_smartmoney_signals()` |
| 高 | P1 | 添加 onchain snapshot 缓存 |
| 中 | Q6 | 统一 `open_interest()` 返回结构与其他 provider 一致 |
| 中 | Q7 | 引入 `logging` 替代 `print()` |
| 低 | Q5 | `MEDALS` 列表格式统一 |

### 代码健康度评分

| 维度 | 评分 (1-10) | 说明 |
|------|-------------|------|
| 正确性 | 7/10 | 核心逻辑无明显大 bug，但 B1 影响评分准确性 |
| 可维护性 | 6/10 | `radar_logic.py` 和 `auto_run.py` 过长，import 模式重复 |
| 可测试性 | 5/10 | 核心评分函数缺少单元测试，仅 feedback 有测试覆盖 |
| 健壮性 | 7/10 | 错误处理覆盖好，但 onchain snapshot 无缓存 / 并发写入无锁 |
| 可读性 | 7/10 | 命名清晰，注释充分，但存在少量魔数索引和类型混合 |

---

*审查人员: Claude Code (Code Review Agent)*
*审查模式: 静态代码分析 + 人工复核*