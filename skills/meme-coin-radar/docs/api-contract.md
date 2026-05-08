# 雷达输出 API 契约 v1.0

> 定义 `meme-coin-radar` 扫描输出格式，标准化与 `trading-journal` 的数据交换。

## 输出格式

每次扫描生成一个输出目录，包含以下文件：

| 文件 | 必要 | 说明 |
|------|------|------|
| `result.json` | ✅ | 候选评分概要（核心字段，供 trading-journal 消费） |
| `result_raw.json` | ✅ | 候选完整数据（含 K线、链上快照等原始数据） |
| `00_scan_meta.json` | ✅ | 扫描元数据（版本、模式、时间等） |
| `report.md` | ✅ | 人类可读报告 |

其余文件（`09_fetch_status.json` 等）为辅助诊断文件。

## result.json 格式

### 外层结构

```json
{
  "output_contract_version": "1.0",
  "radar_version": "3.4.0",
  "scan_time": "20260508_101530",
  "run_mode": "scan",
  "candidates": [...]
}
```

| 字段 | 类型 | 必要 | 说明 |
|------|------|------|------|
| `output_contract_version` | string | ✅ | 契约版本号，用于 trading-journal 兼容性检查 |
| `radar_version` | string | ✅ | 妖币雷达版本号 |
| `scan_time` | string | ✅ | 扫描时间戳（YYYYMMDD_HHMMSS） |
| `run_mode` | string | ✅ | 运行模式（`scan` / `monitor`） |
| `candidates` | array | ✅ | 候选列表 |

### 必要字段（每个 candidate）

| 字段 | 类型 | 说明 | 示例 |
|------|------|------|------|
| `symbol` | string | Binance 标准币对名 | `PEPEUSDT` |
| `final_score` | int | 最终评分 (0-100) | `62` |
| `oos` | int | Onchain Opportunity Score (0-100) | `55` |
| `ers` | int | Execution Readiness Score (0-100) | `70` |
| `decision` | string | 决策结果 | `recommend_paper_trade` / `watch_only` / `manual_review` / `reject` |
| `direction` | string | 交易方向 | `long` / `short` / `null` |

### 可选字段

| 字段 | 类型 | 说明 | 示例 |
|------|------|------|------|
| `total_score` | int | 总分（与 final_score 可能重复） | `62` |
| `module_scores` | dict | 各模块评分明细 | `{"oos": {...}, "ers": {...}}` |
| `hard_reject` | bool | 是否硬否决 | `false` |
| `reject_reasons` | list | 否决原因列表 | `["低成交量"]` |
| `hit_rules` | list | 触发的规则 | `["动量>阈值"]` |
| `miss_rules` | list | 未满足的规则 | `["成交量不足"]` |
| `risk_notes` | list | 风险提示 | `["高波动"]` |
| `missing_fields` | list | 缺失字段列表 | `["fundingRate"]` |
| `needs_manual_review` | bool | 是否需要人工复核 | `false` |
| `confidence` | float | 置信度 (0-100) | `75.5` |
| `can_enter` | bool | 是否可入场 | `true` |
| `entry_reasons` | list | 入场理由 | `["趋势确认"]` |
| `candidate_sources` | list | 候选来源 | `["okx_hot", "alpha_hot"]` |
| `mapping_confidence` | string | 映射置信度 | `high` / `medium` / `low` |
| `market_type` | string | 市场类型 | `onchain_spot` / `cex_futures` |
| `relative_metrics` | dict | 相对指标 | `{"volume_vs_7d_avg": 1.5}` |
| `meta` | dict | 元数据（含价格、趋势等） | `{"price": 0.00001234}` |
| `trade_plan` | object | 交易计划（不含具体价格） | `{"setup_label": "ready"}` |
| `execution_result` | any | 执行结果 | `null` |

## 00_scan_meta.json 格式

```json
{
  "output_contract_version": "1.0",
  "radar_version": "3.4.0",
  "scan_timestamp": "20260508_101530",
  ...
}
```

## result_raw.json 格式

`result_raw.json` 使用 `result.json` 相同的格式，但包含**完整原始数据**（K-line 数组、链上快照等）。

## Kline 数据格式（raw JSON 中使用）

每根 Kline 统一格式：

```json
{"open": 84.0, "high": 85.5, "low": 83.5, "close": 85.2, "volume": 1234567}
```

## 版本兼容

- `output_contract_version` 是 API 契约版本
- `radar_version` 是雷达运行时版本
- trading-journal 的 `auto_trade_radar.py` 应检查 `output_contract_version` 进行兼容性判断

## 变更历史

| 版本 | 变更 | 日期 |
|------|------|------|
| 1.0 | 初始契约 | 2026-05-08 |