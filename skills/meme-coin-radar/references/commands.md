# 妖币雷达 Phase 3.x 命令速查手册

> 适用范围：当前 `meme-coin-radar` 实现。
> 当前主链路：`OKX OnchainOS + Binance Alpha + Binance Futures/Paper Trade + Social Intel`
> 如与历史审查或旧版设计文档冲突，以 [SKILL.md](/Users/zhangpeng/opt/meme-coin-radar/skills/meme-coin-radar/SKILL.md) 和 `scripts/` 下实际代码为准。

## 一句话总览

当前项目不再以 `OKX Demo market filter / GMGN / Obsidian 五模块` 为主流程。

现行流程是：

| Step | 内容 | 入口 | 主要来源 |
|---|---|---|---|
| 0 | BTC 市场状态 | `skill_dispatcher.okx_btc_status()` | OKX CEX |
| 0.5 | Binance Alpha 热度 | `skill_dispatcher.binance_alpha()` | Binance Alpha |
| 1 | 链上候选发现 | `okx_hot_tokens()` / `okx_signal_list()` / `okx_tracker_activities()` | OKX OnchainOS |
| 2 | Token 快照补全 | `okx_token_snapshot()` | OKX OnchainOS |
| 2.5 | 社交/新闻情报 | `providers/intel.py` | Surf / PANews / OKX / Binance |
| 3 | Binance 执行承接数据 | `batch_binance()` | Binance Futures |
| 4 | 评分与交易计划 | `score_candidate()` / `build_trade_plan()` | 本地 Python |
| 5 | 模拟订单与复盘 | `execution_binance.py` / `paper_reconciler.py` | 本地 Paper Engine |

## 当前运行入口

完整扫描：

```bash
python3 skills/meme-coin-radar/scripts/auto-run.py
```

快速查看当前模拟盘状态：

```bash
python3 skills/meme-coin-radar/scripts/paper_status.py
```

## 关键输出文件

默认输出目录为 `$XDG_STATE_HOME/meme-coin-radar/`，若未配置则回退到 `~/.local/state/meme-coin-radar/` 或系统临时目录。

常用文件：

| 文件 | 含义 |
|---|---|
| `report.md` | 本次扫描 Markdown 报告 |
| `result.json` | 候选评分结果 |
| `04_binance_alpha.json` | Binance Alpha 原始快照 |
| `05_okx_hot_trending.json` | OKX 热门趋势榜 |
| `06_okx_hot_x.json` | OKX X 热度榜 |
| `07_okx_signals.json` | OKX 聚合买入信号 |
| `08_okx_tracker.json` | OKX 地址追踪活动 |
| `09_fetch_status.json` | 多源获取状态 |
| `11_onchain_snapshots.json` | 链上快照集合 |
| `12_execution_results.json` | Paper 执行结果 |
| `15_social_intel.json` | 社交/新闻情报快照 |

## 常用环境变量

### 扫描与执行

```bash
export RADAR_EXECUTION_MODE=paper
export RADAR_AUTO_EXECUTE_PAPER_TRADES=true
export RADAR_VALIDATE_ORDERS_WITH_BINANCE=true
```

### 固定止盈止损

```bash
export RADAR_STOP_LOSS_ATR_MULT=0.8
export RADAR_TAKE_PROFIT_1_R_MULT=1.6
export RADAR_TAKE_PROFIT_2_R_MULT=2.4
export RADAR_TP1_FRACTION=0.5
export RADAR_MIN_RR=1.5
export RADAR_REQUIRE_PROTECTION=true
export RADAR_REQUIRE_DUAL_TP=true
```

### 移动止损

```bash
export RADAR_TRAILING_MODE=break_even
export RADAR_TRAILING_CALLBACK_RATE=1.5
export RADAR_BREAK_EVEN_OFFSET_BPS=5
export RADAR_TRAILING_ACTIVATION=tp1_hit
```

说明：

- `break_even`：`TP1` 命中后，把剩余仓位止损上移到开仓价附近。
- `callback`：启用 callback trailing stop。
- 当前项目支持“固定双止盈 + 动态止损”，还不支持独立的 trailing take profit。

## 现行命令关注点

### 1. OKX OnchainOS 候选发现

项目当前主要依赖以下能力：

- `token hot-tokens`
- `signal list`
- `tracker activities`
- `token price-info`
- `token advanced-info`
- `token holders`
- `token cluster-overview`
- `token cluster-top-holders`

这些能力已被封装在：

- [onchainos.py](/Users/zhangpeng/opt/meme-coin-radar/skills/meme-coin-radar/scripts/providers/onchainos.py)
- [skill_dispatcher.py](/Users/zhangpeng/opt/meme-coin-radar/skills/meme-coin-radar/scripts/skill_dispatcher.py)

### 2. Binance Alpha 与 Futures 承接

项目当前主要使用：

- `alpha token-list`
- futures ticker / funding / OI / kline
- `test-order`
- `new-order`
- `new-algo-order`

这些能力已被封装在：

- [binance.py](/Users/zhangpeng/opt/meme-coin-radar/skills/meme-coin-radar/scripts/providers/binance.py)
- [execution_binance.py](/Users/zhangpeng/opt/meme-coin-radar/skills/meme-coin-radar/scripts/execution_binance.py)

### 3. Surf / PANews 情报层

当前情报层会聚合：

- `surf`：社交热度、mindshare、sentiment、新闻搜索
- `PANews`：中文新闻、活动日历、编辑热点、board/highlights

入口：

- [intel.py](/Users/zhangpeng/opt/meme-coin-radar/skills/meme-coin-radar/scripts/providers/intel.py)

## 当前不再推荐作为主手册使用的旧路径

以下内容属于历史实现，不应再作为当前命令流程依据：

- `Phase 1.5` 的 OKX Demo `market filter / oi-change` 主流程
- `GMGN` 作为主数据源
- `Obsidian` 五大模块作为现行评分主模型

如果需要查看历史背景，请单独阅读历史参考文档，并结合其“归档”标识使用。
