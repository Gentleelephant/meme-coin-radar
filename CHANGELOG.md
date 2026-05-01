# Changelog

All notable changes to `meme-coin-radar` are recorded here.

## [Unreleased]

- 修改内容: 新增独立评分规格文档 `references/scoring-logic-spec.md`，详细记录评分函数、数据源、分项上限、权重组合、硬否决规则、方向置信度与决策门槛；同时把 `data-sources-and-scoring.md` 调整为总览入口。
  影响范围: `docs`, `strategy`
  是否影响结果: `否`。本次仅整理和固化现行逻辑，不修改运行时打分行为。

## [3.4.0] - 2026-05-01

- 修改内容: 新增显式运行模式 `scan` / `monitor`，`auto-run.py` 与 `paper_control_loop.py` 支持 `--mode`、`--symbols`，并把模式信息写入 `report.md`、`result.json`、`00_scan_meta.json`。
  影响范围: `strategy`, `execution_logic`, `output_contract`
  是否影响结果: `是`。`monitor` 模式会只聚焦目标代币；`scan` 模式会在报告与 JSON 中输出新增模式元数据。

- 修改内容: 统一版本与流程文档，更新 `SKILL.md`、`commands.md`、`AGENTS.md`，补充模式触发条件、建议执行频率、Tag 要求和 Changelog 流程。
  影响范围: `docs`
  是否影响结果: `否`。不直接改变评分逻辑，但改变协作与发布流程。

- 修改内容: 新增数据源与评分体系文档，梳理链上、行情、情绪、社交与执行承接层的职责，以及 OOS / ERS / Final Score 组合方式。
  影响范围: `docs`, `strategy`
  是否影响结果: `否`。文档化现行规则，便于后续对比优化。

- 修改内容: 新增配置测试，覆盖 `RADAR_RUN_MODE` 与 `RADAR_TARGET_SYMBOLS` 读取行为。
  影响范围: `execution_logic`, `docs`
  是否影响结果: `否`。属于回归保障。
