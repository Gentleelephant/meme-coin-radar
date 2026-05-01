# 妖币雷达优化报告

更新时间: `2026-05-01`
当前版本: `3.4.0`

## 1. 本次落地结论

### 运行流程

- 已拆分为两种显式运行模式:
  - `scan`: 全市场妖币扫描
  - `monitor`: 指定代币监控
- 两种模式都已进入真实实现，不再只是文档约定。
- `auto-run.py` / `paper_control_loop.py` 已支持 `--mode`、`--symbols`。

### 版本管理

- 已补充流程约束:
  - 版本变更时同步 `VERSION` / `SKILL.md` / `CHANGELOG.md`
  - 每次 push 前必须先打 tag
- tag 建议:
  - 正式策略变更: `vX.Y.Z`
  - 临时回放快照: `snapshot-YYYYMMDD-HHMMSS`

### 输出契约

- `report.md`、`result.json`、`00_scan_meta.json` 已加入运行模式元数据。
- `00_scan_meta.json` 现在承载:
  - `run_mode`
  - `mode_profile`
  - `target_symbols`
  - `output_contract`

## 2. 模式设计建议

### `scan`

目标:

- 找候选
- 做策略横向比较
- 建候选池

建议调度:

- 常规市场: `15-60` 分钟
- 波动窗口: `5-15` 分钟

适配场景:

- 新妖币发现
- 因子回顾
- 日内选币

### `monitor`

目标:

- 盯单一或少数标的
- 做 T
- 跟踪执行承接与风控节奏

建议调度:

- `1-5` 分钟
- 应由 `paper_control_loop.py` 或外部 cron / worker 持续驱动

适配场景:

- 已确定研究对象
- 模拟持仓管理
- 风险事件前后复核

## 3. Skills 命名规范评估

### 顶层 skill 是否改名

结论:

- 现阶段不建议重命名顶层 `meme-coin-radar`

原因:

- 对外语义已经稳定，且触发词和历史输出都绑定该名字。
- 当前更大的维护成本不在 skill 名，而在内部模块职责边界。
- 直接重命名顶层 skill 会带来触发习惯、历史文档、自动化脚本兼容成本。

### 内部命名优化建议

建议保留 skill 名，但统一内部术语:

- `pipeline`: `auto-run.py`, `paper_control_loop.py`
- `providers`: `providers/*.py`
- `modules`: `candidate_discovery.py`, `asset_mapping.py`, `scoring_modules.py`
- `strategy`: `radar_logic.py`, `paper_strategy_feedback.py`

建议:

- 后续目录和文档都优先使用 `strategy / pipeline / modules / providers` 这组词。
- 先统一命名语义，再考虑是否在更大版本做结构重构。

## 4. 数据源与评分体系

详细文档:

- `references/data-sources-and-scoring.md`

本次结论:

- 发现层核心仍是 `OKX OnchainOS`
- 承接层核心仍是 `Binance Alpha + Futures`
- 情绪层已经扩展到 `Surf + PANews`
- 当前 Final Score 不是单纯百分制，而是策略排序分

建议持续优化项:

- 将 `social_heat` 拆成 `social_signal` 与 `narrative_signal`
- 将 `macro_catalyst` 独立列出，便于做 ablation test
- 为 OOS / ERS 增加版本化 schema，支持跨版本回放对比

## 5. 数据源扩展与性能优化

### 当前瓶颈

- OKX OnchainOS、Binance、Surf、PANews 多数通过 CLI 取数
- CLI 有额外进程启动、序列化、错误解析开销
- `scan` 模式下 OKX 发现层与社交层的耗时最明显

### OnchainOS API 判断

基于官方公开资料与本仓库现状:

- 当前仓库仍通过 CLI 调用 `onchainos`，见 `scripts/providers/onchainos.py`
- 官方仓库表明技能集已经面向 “OKX OnchainOS API”:
  - https://github.com/okx/onchainos-skills
- 官方 SDK 显示至少部分 Onchain Gateway 能力可直接 API / SDK 化:
  - https://github.com/okx/okx-dex-sdk

判断:

- `OnchainOS -> API` 路线值得推进
- 但不应一次性替换全部接口

建议实施顺序:

1. 抽象 `transport` 层，允许 `cli` / `api` 双实现
2. 高频低风险接口先 API 化:
   - `wallet status`
   - `token price-info`
   - `token advanced-info`
3. 对复杂接口做灰度:
   - `hot-tokens`
   - `signal list`
   - `tracker activities`
   - `cluster-*`
4. 保留 CLI fallback，直到 API 在字段完整性和稳定性上通过对比测试

### 性能优先级

优先级从高到低:

1. `monitor` 模式 API 化
2. 高频 token snapshot API 化
3. 社交层缓存与 TTL 优化
4. `scan` 模式全局发现层 API 化

## 6. 后续开发建议

### P0

- 为 `monitor` 模式补单独的回归测试
- 给 `00_scan_meta.json` 增加 schema 文档
- 增加 tag 创建 checklist 到 CI 或 pre-push hook

### P1

- OnchainOS transport 抽象
- API / CLI 双路径耗时对比
- `result.json` 增加 score breakdown version

### P2

- 将 `scan` 和 `monitor` 拆成独立 pipeline 文件
- 支持多链监控
- 补策略版本回放与结果 diff 工具
