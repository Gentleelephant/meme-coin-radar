# Paper Trading Control Loop Design

## 1. Background

当前项目已经具备以下能力：

- 候选发现：`OKX OnchainOS + Binance Alpha + Social Intel`
- 评分决策：`OOS + ERS + Final Decision`
- 交易计划：`build_trade_plan()`
- 模拟执行：`paper bracket orders`
- 基础对账与统计：`paper_reconciler.py`、`paper_analytics.py`

但如果 agent 只负责“发现信号并创建模拟订单”，后续不持续推进持仓状态，就无法形成稳定的：

- 已平仓样本
- 胜率统计
- 分组复盘
- 参数优化建议

因此需要补齐一层明确的 `Paper Trading Control Loop`，让 agent 可以稳定执行：

1. 扫描
2. 创建新模拟单
3. 持续 reconcile
4. 更新 metrics
5. 输出策略反馈

## 2. Goals

本设计的目标是让系统具备以下闭环能力：

- 模拟订单创建后可持续推进状态
- 已平仓交易可稳定沉淀到 closed trades
- 可计算总胜率与分组胜率
- 可输出策略表现反馈
- 可为后续参数优化提供可解释依据

本设计不包含：

- 自动修改策略参数
- 自动实盘下单
- 高频撮合或毫秒级回测

## 3. System Boundaries

系统划分为 5 层：

### 3.1 Discovery Engine

职责：

- 发现链上或 CEX 候选
- 输出候选池

当前实现：

- `candidate_discovery.py`
- `asset_mapping.py`

### 3.2 Scoring Engine

职责：

- 计算 `OOS`
- 计算 `ERS`
- 输出 `decision`
- 输出 `trade_plan`

当前实现：

- `radar_logic.py`
- `scoring_modules.py`

### 3.3 Execution Engine

职责：

- 创建模拟仓位
- 创建 bracket orders
- 固化 entry snapshot

当前实现：

- `execution_binance.py`
- `paper_order_manager.py`

### 3.4 Reconciler Engine

职责：

- 推进订单状态
- 判断 entry / TP / SL / liquidation / timeout
- 关闭仓位
- 更新账户状态

当前实现：

- `paper_reconciler.py`

### 3.5 Analytics Engine

职责：

- 读取 closed trades
- 统计胜率与分组表现
- 生成策略反馈

当前实现：

- `paper_analytics.py`

新增建议：

- `paper_strategy_feedback.py`

## 4. Agent Actions

建议不要让 agent 直接调用一个“大而全”的脚本，而是定义 3 个稳定动作。

### 4.1 `scan_only`

用途：

- 只扫描，不下模拟单

输入：

- 当前配置
- 数据源快照

输出：

- 候选池
- 分数
- 决策
- trade plan 预览

适用场景：

- 策略验证
- 参数调试
- 手动审核

### 4.2 `scan_and_trade`

用途：

- 扫描并对 `recommend_paper_trade` 创建新模拟仓位

动作：

1. 发现候选
2. 评分
3. 生成交易计划
4. 创建 paper positions / orders
5. 保存本轮 scan snapshot

输出：

- 新建仓位列表
- 新建订单列表
- 当前 open positions 摘要

### 4.3 `reconcile_and_update_metrics`

用途：

- 不依赖新信号
- 只推进已有仓位并更新统计

动作：

1. 拉最新行情
2. 推进 open positions
3. 触发 TP/SL/timeout/liquidation
4. 写入 closed positions
5. 重算 metrics

输出：

- 本轮新关闭仓位
- 当前 open positions
- 最新胜率与指标

### 4.4 `strategy_review`

用途：

- 定期复盘
- 输出参数建议

动作：

1. 读取 closed trades
2. 做分组统计
3. 比较不同策略模板表现
4. 输出策略反馈文件

输出：

- 周期性策略反馈
- 参数调整建议

## 5. Scheduling Model

推荐双循环：

### 5.1 Discovery Loop

频率建议：

- 每 30 分钟
- 或每 1 小时

执行动作：

- `scan_and_trade`

### 5.2 Reconcile Loop

频率建议：

- 每 5 分钟
- 或每 15 分钟
- 至少每 1 小时一次

执行动作：

- `reconcile_and_update_metrics`

原则：

- 对账循环必须稳定高于发现循环
- 胜率统计依赖 closed trades，而不是新信号

### 5.3 Review Loop

频率建议：

- 每日 1 次
- 或每周 1 次

执行动作：

- `strategy_review`

## 6. Core Data Flow

完整闭环如下：

1. scan
2. score
3. build trade plan
4. create paper position
5. reconcile repeatedly
6. close position
7. append closed position
8. recompute metrics
9. generate strategy feedback

每笔交易必须有两类快照：

### 6.1 Entry Snapshot

开仓时固化：

- `symbol`
- `strategy_mode`
- `plan_profile`
- `candidate_sources`
- `oos`
- `ers`
- `final_score`
- `direction`
- `entry_reasons`
- `risk_notes`
- `social_snapshot`
- `narrative_labels`
- `trade_plan`

### 6.2 Exit Snapshot

平仓时记录：

- `exit_reason`
- `closed_at`
- `realized_pnl`
- `tp1_hit`
- `max_favorable_excursion`
- `max_adverse_excursion`
- `fee_paid`

## 7. Data Model Additions

当前模型已具备基础字段，建议补强以下字段。

### 7.1 `paper_position`

建议确保包含：

- `strategy_mode`
- `plan_profile`
- `protection_strategy`
- `tp1_fraction`
- `decision`
- `candidate_sources`
- `oos`
- `ers`
- `final_score`
- `data_quality_tier`
- `entry_reasons`
- `risk_notes`
- `narrative_labels`
- `trade_plan`
- `exit_reason`

### 7.2 `paper_metrics`

建议包含：

- `total_trades`
- `raw_win_rate`
- `tp1_hit_rate`
- `full_tp_rate`
- `stop_loss_rate`
- `profit_factor`
- `net_pnl`
- `current_equity`
- `open_positions`
- `breakdown`

### 7.3 `paper_strategy_feedback`

新增建议文件：

- `paper_strategy_feedback.json`

建议内容：

- `window_trades`
- `best_groups`
- `worst_groups`
- `plan_profile_comparison`
- `direction_comparison`
- `source_combo_comparison`
- `parameter_suggestions`

## 8. Metric Definitions

建议固定以下核心指标。

### 8.1 `raw_win_rate`

定义：

- `realized_pnl > 0` 的 closed trades / total closed trades

### 8.2 `tp1_hit_rate`

定义：

- 至少命中过一次 `TP1` 的 closed trades / total closed trades

### 8.3 `full_tp_rate`

定义：

- `exit_reason == "take_profit"` 的 closed trades / total closed trades

### 8.4 `stop_loss_rate`

定义：

- `exit_reason == "stop_loss"` 的 closed trades / total closed trades

### 8.5 `profit_factor`

定义：

- 总盈利 / 总亏损绝对值

### 8.6 Additional Metrics

建议后续增加：

- `avg_R`
- `expectancy`
- `max_drawdown`
- `break_even_exit_rate`
- `avg_hold_bars`

## 9. Grouped Analytics

不要只看总胜率，必须做分组。

建议固定分组如下：

### 9.1 By `strategy_mode`

- `meme_onchain`
- `majors_cex`

### 9.2 By `plan_profile`

- `majors_trend_follow`
- `majors_breakout_confirmed`
- `meme_breakout_follow`

### 9.3 By `direction`

- `long`
- `short`

### 9.4 By `candidate_source`

- `okx_hot`
- `okx_signal`
- `okx_tracker`
- `alpha_hot`
- `key_coins`

### 9.5 By `score_bucket`

- `<55`
- `55-69`
- `70-79`
- `80+`

### 9.6 By `data_quality_tier`

- `A`
- `B`
- `C`
- `D`

### 9.7 By `narrative_label`

- `ai`
- `meme`
- `defi`
- `exchange`
- `politics`

## 10. Strategy Feedback Layer

第一阶段不要让 agent 自动改参数，只输出建议。

建议反馈文件中包含：

- 最近 `20 / 50 / 100` 笔表现
- 最优 `strategy_mode`
- 最优 `plan_profile`
- 最差 `candidate_source`
- 多空方向对比
- 分数桶表现
- 参数建议

### 10.1 Example Suggestions

- `majors_trend_follow` 的 `tp1_hit_rate` 高、`full_tp_rate` 低
  - 建议上调 `RADAR_MAJORS_TP1_FRACTION`

- `majors_breakout_confirmed` 的 `stop_loss_rate` 过高
  - 建议收紧 `entry_buffer`
  - 或提高最低 `ERS`

- `meme_onchain` 的高社交热度组胜率下降
  - 建议降低社交权重
  - 或提高执行门槛

## 11. Required Files

建议系统稳定维护以下文件：

- `paper_positions.json`
- `paper_orders.json`
- `paper_account.json`
- `paper_events.jsonl`
- `paper_closed_positions.jsonl`
- `paper_metrics.json`
- `paper_strategy_feedback.json`

## 12. V1 Scope

V1 必须具备：

- `scan_and_trade`
- `reconcile_and_update_metrics`
- closed trades 统计
- grouped metrics
- strategy feedback 文件

V1 不要求：

- 自动改参数
- 自动实盘执行
- 高频多源回放

## 13. Recommended Implementation Order

建议按以下顺序开发：

1. 补 `plan_profile` 和 `protection_strategy` 到 closed positions
2. 明确 `scan_and_trade` 入口
3. 明确 `reconcile_and_update_metrics` 入口
4. 新增 `paper_strategy_feedback.py`
5. 生成 `paper_strategy_feedback.json`
6. 在报告中展示反馈摘要

## 14. Success Criteria

设计落地后的成功标准：

- agent 创建的每一笔模拟单都能被后续 reconcile 追踪
- 每笔平仓交易都进入 closed positions
- 胜率与 PnL 可持续累积
- metrics 能按策略模板和来源分组
- 每日或每周都能产出策略反馈
- 参数优化不再凭主观判断，而有统计依据
