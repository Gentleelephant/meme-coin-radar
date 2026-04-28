# Paper Trading 设计审核

> 审核时间：2026-04-27  
> 审核目标文档：`paper-trading-design.md`  
> 审核结论：**框架合理，3 项关键缺失建议 V1 补充后即可开发**

---

## 1. 合理的设计决策

| 设计点 | 评价 |
|--------|------|
| 四层模型分离（order/position/event/account） | 清晰覆盖下单到结算全链路，jsonl event 流水优秀 |
| 状态机分离（order vs position） | `TRIGGERED` intermediate state 对 SL/TP 完全必要 |
| bar-based 撮合 | 对当前 scan 节奏足够，结果稳定 |
| fee/slippage V1 引入 | 正确决断；不加则收益系统性偏高 |
| 统计维度设计 | `strategy_mode` / `candidate_sources` / `score_bucket` 分组复盘是亮点 |
| V1/V2 切分 | 聚焦静态快照而非实时，方案务实 |

---

## 2. 需要修正的问题

### 🔴 关键缺失（建议 V1 补充）

#### A. reconciler 时间推进模型

**问题**：文档只说"scan 时运行 reconciler"，但 scan 间隔内可能跨越多根 bar，只拿最新 close 会导致：

- miss 中间 bar 的 high 先触及 TP 又回落
- SL/TP 的触发顺序（先 high 还是先 low）不明确

**建议**：

```python
@dataclass
class PriceTick:
    open: float
    high: float
    low: float
    close: float
    timestamp: int

# reconciler 接收 tick 列表，chronological 推进
def reconcile_position(pos: PaperPosition, ticks: list[PriceTick]) -> list[PaperEvent]: ...
```

每根 bar 内按 `(high, low)` 判断 stop/tp 触发，不依赖 single point。

#### B. 资金/保证金模型缺失

**问题**：`trade_plan` 生成了 leverage 建议值（5x），但 `paper_account` 未记录 margin 状态。

**建议 V1 至少加上**：

```python
class PaperAccount:
    ...
    total_equity: float     # USDT
    used_margin: float      # position_notional / leverage
    free_margin: float
    liquidation_threshold: float  # -90% * used_margin
```

position 级别加：

```python
class PaperPosition:
    ...
    leverage: int
    margin: float
    liquidation_price: float | None
```

当 unrealized_pnl 达到 `-liquidation_threshold` 时，position 进入 `LIQUIDATED` 状态，按当前 bar 收盘价强制平仓。

#### C. 持仓超时（zombie position）

**问题**：如果 position open 后没有任何保护单触发（价格在 SL 和 TP 之间窄幅波动但长时间不回），position 永远 open。

**建议补充**：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `position_max_age_bars` | 48 | 超期强制市价平（close at market） |
| `tp1_hit_timeout_bars` | 24 | TP1 后 N 根 bar 内 TP2 没触发则全部退出 |

---

### 🟡 数据模型缺陷

#### 订单状态缺少 `PARTIALLY_FILLED`

`paper_order.status` 目前只有 `NEW → ACTIVE → TRIGGERED → FILLED → CANCELED → EXPIRED`。对于 TP1（平 50%），position 是 `PARTIALLY_CLOSED`，但 order 只有 `FILLED`。如果 TP1 order 实际只成交了 30%，状态无法表达。

**建议**：order.status 补充 `PARTIALLY_FILLED`。

#### position 命名不对称

`entry_order_ids` 是 `list[str]`，`stop_loss_order_id` 是 `str`，`take_profit_order_ids` 是 `list[str]`。

**建议统一**：
- `entry_order_ids: list[str]`
- `stop_loss_order_ids: list[str]`
- `take_profit_order_ids: list[str]`

#### position 缺少 `REJECTED` 状态

`validation_failed` 后直接 `CANCELED` 不够准确。`REJECTED` 和 `CANCELED` 业务含义不同（交易所拒绝 vs 用户取消）。

---

### 🟢 次要优化

#### 同 symbol 不同方向的处理

§7.1 说"同 symbol 同方向已 open 不重复开新仓"，但对冲仓位（long + short 同时 open）未明确规则。

**建议明确**：V1 不支持同 symbol 对冲，long 或 short 任一已 open 则跳过。

---

## 3. 更好的方案建议

### 3.1 V1 直接使用 SQLite 替代 json/jsonl

文档推荐 V1 用 `json + jsonl`，但存在风险：

| 考虑点 | json + jsonl | SQLite |
|--------|-------------|--------|
| 并发写保护 | 无文件锁，多个进程同时写会丢数据 | 内置 WAL 模式，并发安全 |
| 查询复杂统计 | 全量读取 + 内存过滤 | SQL 查询效率高 |
| 外部依赖 | 无 | `sqlite3` 标准库，零外部依赖 |

**推荐方案**：V1 用 `sqlite3`，抽象一层 `PaperStore`：

```python
# paper_store.py ─ 单层抽象，V1 sqlite3，V2 可无缝切换
class PaperStore:
    def insert_order(self, order: PaperOrder) -> str: ...
    def update_order_status(self, order_id: str, status: str): ...
    def get_open_positions(self) -> list[PaperPosition]: ...
    def create_event(self, event: PaperEvent): ...
    def get_metrics(self, strategy_mode: str | None = None) -> dict: ...
```

### 3.2 reconciler 输入改为 `list[PriceTick]`

**当前隐含的问题**：

```
scan 间隔 1 小时，klines 1 小时
reconciler 只拿到当前 close，会 miss 中间的 high 到达 TP
```

**推荐方案**：传递完整的 kline list，chronological 顺序逐根推进，每根 bar 按 (high, low) 判断 stop/tp。

### 3.3 event 快照包含 position 的深拷贝

`paper_event.payload` 字段目前是通用 dict，建议强制要求保存触发时刻的 position 完整快照：

```python
class PaperEvent:
    event_id: str
    position_id: str
    order_id: str
    event_type: str
    snapshot: dict    # 触发时刻 position 深拷贝
    ts: int
```

事后复盘不需要回溯多文件。

### 3.4 score_bucket 增加 data_quality_tier

当前 bucket 只按分段区分，但 75 分（数据完整）和 75 分（缺失 3 个字段）不应归入同一组。

**推荐方案**：

```python
score_buckets: [
    "60-70_full", "60-70_partial",
    "70-80_full", "70-80_partial",
    "80+_full", "80+_partial",
]
```

这直接回答设计文档提出的反哺问题：**到底是评分逻辑不好，还是数据质量导致误判？**

---

## 4. 综合评分

| 维度 | 评分 | 说明 |
|------|------|------|
| 功能完整性 | 8/10 | 缺少 reconciler 时间推进模型、资金模型、持仓超时 |
| 数据模型设计 | 9/10 | 非常完整，建议从 jsonl 升级到 SQLite |
| 与现实交易对齐 | 7/10 | slippage 有但爆仓模型缺失 |
| V1/V2 切分 | 9/10 | 切分合理，无需调整 |
| 闭环反馈设计 | 7/10 | 有目标但缺路径，建议先离线复盘再在线自适应 |

---

## 5. 开发前核心建议（不改大框架，补这 3 项）

1. **reconciler 输入**：传 `PriceTick(open/high/low/close)` 列表，chronological 顺序推进
2. **资金模型**：V1 加入 `position_margin`、`used_margin`、`liquidation_threshold`
3. **存储**：直接用 SQLite（`sqlite3` 标准库），比 jsonl 更安全且后期无需迁移

*以上为设计审核，不修改原始设计文档。*