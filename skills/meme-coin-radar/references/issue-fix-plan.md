# Issue 修复计划

> 针对 GitHub 仓库 7 个 Open Issue 的修复方案

## 总览

| Issue | 类型 | 优先级 | 影响范围 | 预估复杂度 |
|-------|------|--------|---------|-----------|
| #1 OnchainOS JWT 重试循环 | bug | 🔴 高 | `providers/onchainos.py` | 低 |
| #2 result.json JSON 序列化超限 | enhancement | 🟡 中 | `auto-run.py` | 低 |
| #3 VERSION/SKILL.md 同步 | documentation | 🟢 低 | `VERSION` + `SKILL.md` + `test_versioning.py` | 低 |
| #4 多时间框架 K线接口 | enhancement | 🟡 中 | `auto-run.py` + `skill_dispatcher.py` | 中 |
| #5 扫描结果时序追踪 | enhancement | 🟡 中 | `auto-run.py` + `history_store.py` | 中 |
| #6 阈值参数可配置化 | refactor | 🟡 中 | `config.py` + `scoring_modules.py` | 中 |
| #7 API 契约文档 | documentation | 🟢 低 | `docs/api-contract.md` + `auto-run.py` | 低 |

---

## Issue #1: OnchainOS JWT 重试逻辑可能无限循环

### 问题分析

`providers/onchainos.py` 的 `_json_command()` 中，重试逻辑有以下缺陷：

1. **重试条件过于狭窄**：只在 `AUTH_ERROR` 时重试，其他可重试错误（`TIMEOUT`、`NETWORK`、`RATE_LIMIT`）直接被 `break` 吞掉
2. **内层候选循环不重置**：`last_status` 在内层 `candidates` 循环中被覆盖，导致在 `attempt==0` 时若第一个 candidate 是 AUTH_ERROR、第二个 candidate 是其他错误，`last_status` 丢失 AUTH_ERROR 状态，不走重试
3. **缺少最大总尝试硬限制**：即使外循环 `max_attempts=2`，内层 `candidates` 枚举让单次外循环执行最多 2 次 command 调用。但嵌套结构让人难以验证边界

### 修复方案

```python
def _json_command(command: str, timeout: int, source: str) -> tuple[Any, FetchStatus]:
    max_total_runs = 4  # 硬限制：总共最多执行 4 次 command
    run_count = 0

    for attempt in range(2):  # max 2 formal attempts
        candidates = (_cmd(command), _legacy_json_cmd(command))
        last_status = FetchStatus(ok=False, ...)

        for index, candidate in enumerate(candidates):
            if run_count >= max_total_runs:
                break
            run_count += 1
            result = run(candidate, timeout=timeout)
            # ... existing logic ...
        
        # 可重试的错误类型
        retryable = {FetchStatus.AUTH_ERROR, FetchStatus.TIMEOUT, FetchStatus.NETWORK, FetchStatus.RATE_LIMIT}
        if attempt == 0 and last_status.error_type in retryable:
            time.sleep(2.0)
            continue
        
        break

    return None, last_status
```

### 修改文件

- `skills/meme-coin-radar/scripts/providers/onchainos.py`

### 验证

- 运行已有测试 `test_onchainos_provider.py` 确认回归
- 新增测试：模拟 TIMEOUT + 重试成功场景 / 超过 max_total_runs 强制停止场景

---

## Issue #2: result.json 可能超出 JSON 序列化限制

### 问题分析

`auto-run.py` 第 1088 行将完整 candidate 数据写入 `result.json`，包含：
- `module_scores`（10+ 子评分）
- `meta`（K线数据、EMA、ATR 等）
- `trade_plan`
- `onchain_data` 链上快照

50+ 候选时文件体积可达数 MB，可能触发 `json.dumps` 限制。

### 修复方案

1. **拆分输出**：`result.json` 只保存概要字段（symbol, final_score, oos, ers, direction 等核心字段），完整数据写入 `result_raw.json`
2. **大小检查**：写入前检查 JSON 序列化后大小，超过 5MB 时截断大字段并记录警告

### 修改文件

- `skills/meme-coin-radar/scripts/auto-run.py`

### 验证

- 运行一次扫描，确认 `result.json` 体积显著减小
- 确认 `result_raw.json` 包含所有原始数据

---

## Issue #3: VERSION 与 SKILL.md metadata.version 不同步

### 问题分析

- `VERSION`（文本文件）：`3.4.0`，被 `versioning.py` 读取
- `SKILL.md` frontmatter `version: "3.4.0"`，静态字段

当前一致，但缺少自动校验机制。

### 修复方案

1. **在 `test_versioning.py` 新增测试**：读取 `SKILL.md` 的 YAML frontmatter 提取 `version`，与 `VERSION` 文件内容对比，不匹配则测试失败
2. **可选**：自动化同步 — 在 `python scripts/versioning.py --bump` 时自动更新 `SKILL.md`

### 修改文件

- `skills/meme-coin-radar/tests/test_versioning.py`（新增测试）
- `skills/meme-coin-radar/scripts/versioning.py`（可选：自动同步逻辑）

### 验证

- 运行 `pytest skills/meme-coin-radar/tests/test_versioning.py`
- 手动修改 SKILL.md 版本号，确认测试失败

---

## Issue #4: 扩展扫描模块支持多时间框架 K线数据

### 问题分析

当前 `skill_dispatcher.py` 的 `binance_klines()` 支持任意 `interval` 参数，但 `auto-run.py` 只拉取 `1h` + `4h` 两个时间框架。上层策略（trading-journal）需要 `15m`、`5m` 等多层 K线数据做入场确认。

### 修复方案

1. **新增 `fetch_multi_tf_klines()`**：在 `auto-run.py` 中增加函数，并行拉取 `4h`、`1h`、`15m`、`5m` 四个时间框架的 K线数据
2. **配置化**：时间框架列表通过 `RADAR_TF_INTERVALS` 环境变量可配置
3. **输出增强**：每个 candidate 的 `meta` 中增加 `klines_multi` 字段，按时间框架组织
4. **大小控制**：每个时间框架限制最多 50 根 K线（trading-journal 实际只需要近期数据）

### 修改文件

- `skills/meme-coin-radar/scripts/auto-run.py`
- `skills/meme-coin-radar/scripts/config.py`（新增 `tf_intervals` 配置）

### 验证

- 运行 `--mode monitor --symbols PEPE`，确认 `result_raw.json` 包含 `klines_5m`、`klines_15m` 数据
- 确认 K线格式兼容 trading-journal 的 `PriceActionAnalyzer`

---

## Issue #5: 扫描结果时序追踪 + 观察清单自动管理

### 问题分析

已有 `history_store.py` 保存每日快照，但：
- 只存 ticker、alpha、social 三类快照，不存每次扫描的评分结果
- 没有评分趋势分析
- 没有自动观察清单管理

### 修复方案

1. **扫描评分历史**：每次扫描后追加一行到 `scan_history.jsonl`，格式为 `{timestamp, symbol, final_score, oos, ers, decision, direction}`
2. **趋势分析**：`history_store.py` 新增 `analyze_score_trend(symbol)` 函数，计算评分趋势（rising/stable/falling）和波动率
3. **观察清单自动管理**：
   - 新增 `data/watchlist.json` 文件
   - 自动添加条件：ERS ≥ 70 且连续 3 次排前 5
   - 自动移除条件：连续 10 次未进入前 10
4. **输出增强**：`result.json` 每个 candidate 附加 `trend` 字段

### 修改文件

- `skills/meme-coin-radar/scripts/history_store.py`
- `skills/meme-coin-radar/scripts/auto-run.py`
- `skills/meme-coin-radar/scripts/config.py`（新增 watchlist 路径配置）

### 验证

- 连续运行两次扫描，确认 `scan_history.jsonl` 追加了数据
- 确认 `watchlist.json` 正确生成

---

## Issue #6: 扫描阈值和参数可配置化

### 问题分析

`config.py` 已通过环境变量实现了大部分参数的配置化，但仍有部分硬编码：
- `scoring_modules.py` 中的评分权重（如 `score_turnover_activity` 的分档阈值）
- `candidate_discovery.py` 中的 `top_alpha_n=15` 
- `skill_dispatcher.py` 中的 `BATCH_WORKERS=12`、`BATCH_TIMEOUT_SECONDS=60`

Issue body 还提到跨仓库问题（trading-journal 的 `auto_trade_radar.py` 中的硬编码阈值），此部分需要在 trading-journal 仓库单独解决。

### 修复方案

1. **评分权重可配置**：`config.py` 新增 `scoring_weights` 配置组
2. **发现参数可配置**：`config.py` 新增 `discovery_limit`、`discovery_timeframe`、`discovery_top_alpha_n`
3. **批处理参数可配置**：`config.py` 新增 `batch_workers`、`batch_timeout`

### 修改文件

- `skills/meme-coin-radar/scripts/config.py`
- `skills/meme-coin-radar/scripts/scoring_modules.py`（可选：接受配置参数）
- `skills/meme-coin-radar/scripts/candidate_discovery.py`（接受配置参数）
- `skills/meme-coin-radar/scripts/skill_dispatcher.py`（读取配置）

### 验证

- 设置环境变量覆盖默认参数，确认生效
- 运行现有测试，确认回归通过

---

## Issue #7: 定义雷达输出格式的 API 契约文档

### 问题分析

`result.json` 的输出格式是隐式接口，`trading-journal` 仓库的 `auto_trade_radar.py` 依赖特定字段名。输出格式变化会导致无声失败。

### 修复方案

1. **创建 `docs/api-contract.md`**：定义 `result.json` 的输出结构，包括必要字段、可选字段、输出模式、版本号
2. **输出校验**：`auto-run.py` 新增 `validate_output()` 函数，在写入 `result.json` 前校验字段完整性
3. **版本号追踪**：`result.json` 和 `00_scan_meta.json` 中包含 `version` 字段

### 修改文件

- `skills/meme-coin-radar/docs/api-contract.md`（新建）
- `skills/meme-coin-radar/scripts/auto-run.py`

### 验证

- 运行扫描，确认 `result.json` 通过字段校验
- 手动删除某个必要字段，确认校验失败

---

## 实施顺序

| 阶段 | Issue | 理由 |
|------|-------|------|
| Phase 1 | #1 bug 修复 | 影响系统稳定性的 bug 优先修复 |
| Phase 2 | #7 API 契约文档 | 定义输出规范，为 #2/#4/#5 提供格式依据 |
| Phase 3 | #6 阈值可配置化 + #3 版本同步 | 基础架构改造，为后续扩展提供配置基础 |
| Phase 4 | #2 JSON 大小限制 + #4 多时间框架 + #5 时序追踪 | 功能增强，依赖前序阶段的 API 契约和配置化 |

---

## 验证总纲

- 每个 Issue 修复后运行：`python -m pytest skills/meme-coin-radar/tests/ -v`
- 每个 Issue 修复后运行一次 `python skills/meme-coin-radar/scripts/auto-run.py --mode monitor --symbols PEPE` 确认可运行
- 全部完成后运行一次完整 scan 模式确认端到端通过
- 更新 `CHANGELOG.md`
- 创建 Git tag