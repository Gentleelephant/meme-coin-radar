# Paper Trading 设计草案

> 项目：`meme-coin-radar`
> 阶段：Phase 3.1 设计讨论
> 目标：在当前 `OKX OnchainOS + Binance Alpha + Binance 模拟盘` 基础上，补齐订单管理、持仓跟踪、绩效统计与胜率分析闭环。

---

## 1. 背景与目标

当前项目已经具备以下能力：

- 候选发现
- `OOS + ERS` 评分
- `trade_plan` 生成
- Binance 风格 bracket 模拟订单创建

但目前模拟交易仍停留在“创建订单快照”层面，尚不具备：

- 完整的订单生命周期管理
- 持仓状态跟踪
- TP/SL 命中回写
- 账户权益与收益曲线
- 胜率、回撤、PnL 等策略统计
- 执行结果反哺评分闭环

本设计文档的目标是确定：

1. Paper trading 子系统的边界
2. 订单 / 持仓 / 事件 / 账户的数据模型
3. 订单状态机与撮合规则
4. 胜率与绩效指标定义
5. V1 / V2 的开发范围

---

## 设计更新说明

本版基于 `paper-trading-design-review.md` 做了收敛，主要调整为：

- V1 明确采用 `PriceTick + chronological reconciler`
- V1 补充基础保证金 / 杠杆 / 强平阈值模型
- V1 补充持仓超时规则，避免 zombie position
- 数据模型补充 `PARTIALLY_FILLED`、`REJECTED`、`stop_loss_order_ids`
- 明确 V1 不支持同 symbol 对冲
- 暂不把 V1 存储层切到 SQLite，继续使用 `json + jsonl`

---

## 2. 系统边界

### 2.1 已有模块

当前已有模块继续保留原职责：

- `candidate_discovery.py`
  负责候选发现
- `asset_mapping.py`
  负责链上标的到 Binance 可执行标的映射
- `radar_logic.py`
  负责评分与 `trade_plan`
- `execution_binance.py`
  负责将 `trade_plan` 翻译为 Binance 风格 bracket 模拟订单

### 2.2 新增模块

建议新增 3 个模块：

- `paper_order_manager.py`
  负责订单、持仓、状态流转
- `paper_reconciler.py`
  负责根据 `PriceTick` 序列推进订单与持仓状态
- `paper_analytics.py`
  负责统计胜率、PnL、回撤与按策略维度复盘

### 2.3 不在本阶段范围

本阶段不做：

- 自动实盘
- WebSocket 实时撮合
- 多账户联动
- 自动加仓/减仓
- 复杂 trailing stop

---

## 3. 数据模型

### 3.1 `paper_order`

表示一张模拟订单。

建议字段：

- `order_id`
- `position_id`
- `symbol`
- `side`
- `order_role`
  - `ENTRY`
  - `STOP_LOSS`
  - `TAKE_PROFIT`
- `order_type`
  - `MARKET`
  - `LIMIT`
  - `STOP_MARKET`
  - `TAKE_PROFIT_MARKET`
- `quantity`
- `price`
- `trigger_price`
- `reduce_only`
- `status`
  - `NEW`
  - `ACTIVE`
  - `TRIGGERED`
  - `PARTIALLY_FILLED`
  - `FILLED`
  - `REJECTED`
  - `CANCELED`
  - `EXPIRED`
- `created_at`
- `triggered_at`
- `filled_at`
- `fill_price`
- `fill_qty`
- `fee_paid`

### 3.2 `paper_position`

表示一次完整交易生命周期。

建议字段：

- `position_id`
- `symbol`
- `strategy_mode`
  - `meme_onchain`
  - `majors_cex`
- `decision`
- `direction`
  - `long`
  - `short`
- `candidate_sources`
- `oos`
- `ers`
- `final_score`
- `entry_reasons`
- `risk_notes`
- `entry_order_ids`
- `stop_loss_order_ids`
- `take_profit_order_ids`
- `planned_entry_price`
- `planned_stop_loss`
- `planned_take_profit_1`
- `planned_take_profit_2`
- `entry_avg_price`
- `opened_qty`
- `closed_qty`
- `remaining_qty`
- `realized_pnl`
- `unrealized_pnl`
- `fee_paid`
- `max_favorable_excursion`
- `max_adverse_excursion`
- `leverage`
- `margin`
- `liquidation_price`
- `liquidation_threshold`
- `status`
  - `PENDING`
  - `OPEN`
  - `PARTIALLY_CLOSED`
  - `CLOSED`
  - `LIQUIDATED`
  - `REJECTED`
  - `CANCELED`
- `opened_at`
- `closed_at`

### 3.3 `paper_event`

表示任意状态变化事件。

建议字段：

- `event_id`
- `position_id`
- `order_id`
- `event_type`
  - `ORDER_CREATED`
  - `ORDER_TRIGGERED`
  - `ORDER_FILLED`
  - `POSITION_OPENED`
  - `POSITION_PARTIALLY_CLOSED`
  - `POSITION_CLOSED`
  - `STOP_LOSS_HIT`
  - `TAKE_PROFIT_HIT`
  - `VALIDATION_FAILED`
- `payload`
- `snapshot`
- `ts`

### 3.4 `paper_account`

表示模拟账户维度状态。

建议字段：

- `starting_equity`
- `total_equity`
- `current_equity`
- `available_equity`
- `used_margin`
- `free_margin`
- `realized_pnl`
- `unrealized_pnl`
- `fees_paid`
- `peak_equity`
- `max_drawdown`
- `liquidation_threshold`
- `updated_at`

---

## 4. 存储结构

当前已有 `paper_positions.json`，建议升级为以下结构：

- `history/paper_positions.json`
  当前未关闭持仓
- `history/paper_orders.json`
  当前活动订单
- `history/paper_account.json`
  当前模拟账户状态
- `history/paper_events.jsonl`
  事件流水
- `history/paper_closed_positions.jsonl`
  已平仓记录
- `history/paper_metrics.json`
  聚合统计结果

说明：

- `json` 用于当前快照
- `jsonl` 用于追加型历史记录
- V1 继续使用文件存储即可
- SQLite 是明确可行的后续升级方向，但本阶段先不引入，避免在 reconciler 与状态机尚未稳定时扩大实现面

---

## 5. 订单状态机

### 5.1 `paper_order` 状态流转

`ENTRY` 订单：

- `NEW` -> `ACTIVE`
- `ACTIVE` -> `PARTIALLY_FILLED`
- `ACTIVE` -> `FILLED`
- `ACTIVE` -> `REJECTED`
- `ACTIVE` -> `CANCELED`
- `ACTIVE` -> `EXPIRED`

`STOP_LOSS / TAKE_PROFIT` 订单：

- `NEW` -> `ACTIVE`
- `ACTIVE` -> `TRIGGERED`
- `TRIGGERED` -> `PARTIALLY_FILLED`
- `TRIGGERED` -> `FILLED`
- `ACTIVE` -> `REJECTED`
- `ACTIVE` -> `CANCELED`

### 5.2 `paper_position` 状态流转

- `PENDING`
  主单尚未成交
- `OPEN`
  主单已成交，保护单已生效
- `PARTIALLY_CLOSED`
  已 hit TP1，但仍有剩余仓位
- `CLOSED`
  已完全平仓
- `LIQUIDATED`
  保证金不足触发强制平仓
- `REJECTED`
  下单前校验或交易规则检查失败
- `CANCELED`
  主单未成交且订单被取消/过期

---

## 6. 撮合规则

胜率统计是否有意义，取决于撮合规则是否先定义清楚。

### 6.1 `PriceTick` 时间推进模型

V1 明确采用 bar-based chronological 推进，不允许 reconciler 只读取单点价格。

建议统一输入结构：

```python
@dataclass
class PriceTick:
    open: float
    high: float
    low: float
    close: float
    timestamp: int
```

建议核心接口：

```python
def reconcile_position(position: PaperPosition, ticks: list[PriceTick]) -> list[PaperEvent]:
    ...
```

处理原则：

- `ticks` 必须按时间升序推进
- 每根 bar 都要判断 `ENTRY / SL / TP` 是否触发
- 不能只拿 scan 时刻的最新 `close`
- 若同一 bar 内同时可能触发 `TP` 与 `SL`，V1 必须定义固定规则

### 6.2 V1 撮合规则

建议使用简化但稳定的 bar-based 撮合：

- `MARKET` 主单
  - 按创建后下一根 bar 开盘价成交
  - 或当前价 + 固定滑点成交
- `LIMIT` 主单
  - 只要后续 bar 的 high/low 触及价格，即视为成交
- `STOP_MARKET`
  - 只要后续 bar 触及 trigger price，即视为触发并成交
- `TAKE_PROFIT_MARKET`
  - 规则同上

同一根 bar 内触发顺序建议：

- `long`
  - 先检查 `low -> stop`
  - 再检查 `high -> tp`
- `short`
  - 先检查 `high -> stop`
  - 再检查 `low -> tp`

说明：

- 这是偏保守的假设
- 目的是避免胜率被乐观高估
- V2 如有需要，再引入更细粒度成交模型

### 6.3 费用与滑点

建议 V1 就引入两个参数：

- `fee_bps`
- `slippage_bps`

原因：

- 不加费用，收益会系统性偏高
- 不加滑点，止损和追涨单会失真

建议默认：

- `fee_bps = 4`
- `slippage_bps = 3`

### 6.4 保证金与强平规则

V1 增加基础保证金模型，至少记录：

- `position.margin = position_notional / leverage`
- `account.used_margin`
- `account.free_margin`
- `position.liquidation_threshold`

简化规则建议：

- `liquidation_threshold = 90% * margin`
- 当 `unrealized_pnl <= -liquidation_threshold` 时：
  - position 进入 `LIQUIDATED`
  - 以当前 bar 的保守价格强制平仓
  - 记录 `LIQUIDATION` 事件

说明：

- V1 不追求精确复刻 Binance 强平引擎
- 但必须避免“高杠杆模拟单永不爆仓”的不真实结果

---

## 7. 持仓管理规则

### 7.1 开仓规则

- 只有 `decision == recommend_paper_trade` 才允许自动创建持仓
- 同 symbol 同方向已有 `OPEN/PARTIALLY_CLOSED` 持仓时，不重复开新仓
- V1 不支持同 symbol 对冲
- 若同 symbol 已有 `long` 或 `short` 任一未关闭仓位，则新的 opposite signal 跳过

### 7.2 部分止盈规则

当前计划默认：

- `TP1` 平 50%
- `TP2` 平剩余 50%

### 7.3 止损联动

若 `TP1` 已成交：

- 剩余 `SL` 数量同步缩减
- 避免保护单数量大于剩余仓位

### 7.4 过期规则

若 `LIMIT` entry 在 N 根 bar 内未成交：

- 状态改为 `EXPIRED`
- position 改为 `CANCELED`

V1 建议：

- `entry_expire_bars = 6`

### 7.5 持仓超时规则

若 position open 后长时间未 hit TP/SL，需要防止 zombie position。

建议新增：

- `position_max_age_bars = 48`
  - 超期后按市价强制关闭
- `tp1_hit_timeout_bars = 24`
  - TP1 命中后，若 N 根 bar 内 TP2 未命中，则剩余仓位全部退出

对应状态变化：

- `OPEN/PARTIALLY_CLOSED` -> `CLOSED`
- `exit_reason = timeout_close`

---

## 8. 胜率与绩效指标定义

不建议只统计一个“胜率”。建议同时维护以下指标。

### 8.1 交易级指标

- `realized_pnl`
- `realized_pnl_pct`
- `r_multiple`
- `holding_minutes`
- `max_favorable_excursion`
- `max_adverse_excursion`
- `exit_reason`
  - `tp1_tp2`
  - `tp1_then_sl`
  - `stop_loss`
  - `manual_close`
  - `expired`

### 8.2 核心胜率指标

- `raw_win_rate`
  - 平仓后 `realized_pnl > 0`
- `tp1_hit_rate`
  - 至少 hit TP1
- `full_tp_rate`
  - 达到最终止盈目标
- `stop_loss_rate`
  - 最终由止损结束
- `protected_loss_rate`
  - 有保护单且最终止损出场

### 8.3 账户级指标

- `total_trades`
- `win_rate`
- `avg_win`
- `avg_loss`
- `profit_factor`
- `expectancy`
- `max_drawdown`
- `net_pnl`
- `sharpe_proxy`

---

## 9. 统计维度

为了让结果能反哺策略，指标至少按以下维度分组：

- `strategy_mode`
  - `meme_onchain`
  - `majors_cex`
- `direction`
  - `long`
  - `short`
- `candidate_sources`
  - `okx_hot`
  - `okx_signal`
  - `okx_tracker`
  - `alpha_hot`
  - `key_coins`
- `score_bucket`
  - `60-70`
  - `70-80`
  - `80+`
- `data_quality_tier`
  - `full`
  - `partial`
- `decision`
  - `recommend_paper_trade`

这样可以回答：

- `majors_cex` 是否比 `meme_onchain` 更稳定
- `okx_signal + okx_hot` 是否比单一来源更有效
- 高分桶是否真的对应更高胜率
- 同一分数段里，是不是数据质量差导致误判

---

## 10. 复盘闭环

每一笔 `paper_position` 必须固化当时的策略快照，而不是事后重算。

建议保存：

- `scan_id`
- `symbol`
- `candidate_sources`
- `strategy_mode`
- `oos`
- `ers`
- `final_score`
- `direction`
- `entry_reasons`
- `risk_notes`
- `trade_plan`
- `meta`

后续 `paper_analytics.py` 只读取这些快照进行统计，不回头重新打分。

建议事件流中重要节点也保存 `position` 快照，用于事后审计：

- `ORDER_FILLED`
- `STOP_LOSS_HIT`
- `TAKE_PROFIT_HIT`
- `POSITION_CLOSED`
- `POSITION_LIQUIDATED`

---

## 11. V1 / V2 范围划分

### V1

必须完成：

- `paper_order / paper_position / paper_event / paper_account` 数据模型
- 主单 + 止损 + 两档止盈
- `MARKET` 与 `LIMIT` 主单撮合
- `STOP_MARKET / TAKE_PROFIT_MARKET` 触发
- `PriceTick` chronological reconciler
- fee/slippage
- margin / free_margin / liquidation threshold
- position timeout
- 当前持仓 / 当前订单 / 已平仓记录
- 账户权益与基础指标
- 胜率与按 `strategy_mode` / `candidate_sources` 分组统计

### V2

可后续增强：

- trailing stop
- break-even stop
- 自动移动止损
- 多次加仓/减仓
- WebSocket 级别实时推进
- SQLite 存储
- 图表化回测报表

---

## 12. 当前代码落点建议

- `scripts/execution_binance.py`
  继续保留“Binance 风格订单翻译”
- `scripts/paper_order_manager.py`
  新增，负责持仓与订单状态
- `scripts/paper_reconciler.py`
  新增，按 `PriceTick` 序列推进状态
- `scripts/paper_analytics.py`
  新增，汇总胜率与绩效指标
- `scripts/history_store.py`
  扩展文件读写与账户快照存储
- `scripts/auto-run.py`
  保留扫描入口，追加：
  - 创建 paper orders
  - 运行 reconciler
  - 输出统计摘要

---

## 13. 需要拍板的设计决策

以下 3 项建议先确认，再进入开发：

### A. 成交模型

推荐：

- `MARKET` 按当前价 + 滑点
- `LIMIT` 按后续 bar 触价成交
- `reconciler` 输入为 `PriceTick` 列表，按时间顺序推进

理由：

- 实现简单
- 结果稳定
- 不会 miss 中间 bar 的触发事件
- 足够支撑胜率统计

### B. 胜率口径

推荐同时保留：

- `raw_win_rate`
- `tp1_hit_rate`
- `full_tp_rate`
- `stop_loss_rate`

理由：

- 妖币策略里，是否 hit TP1 与最终是否盈利是两回事

### C. 存储方案

推荐 V1 继续使用：

- `json + jsonl`

理由：

- 与当前项目一致
- 实现快
- 后续可平滑迁移 SQLite
- 当前更关键的是先把状态机与 reconciler 跑稳，而不是过早扩大存储层范围

---

## 14. 推荐结论

建议按以下顺序推进：

1. 先开发 `paper_order_manager + reconciler`
2. 再开发 `paper_account + metrics`
3. 最后把结果回灌到策略分析

如果只做一件事，优先做：

`paper_reconciler`

因为没有它，就没有真正的持仓生命周期，也不会有可信的胜率统计。
