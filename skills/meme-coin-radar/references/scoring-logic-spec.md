# 评分逻辑规格文件

更新时间: `2026-05-01`
适用版本: `v3.4.0`
主代码入口:

- [radar_logic.py](/Users/zhangpeng/opt/meme-coin-radar/skills/meme-coin-radar/scripts/radar_logic.py)
- [scoring_modules.py](/Users/zhangpeng/opt/meme-coin-radar/skills/meme-coin-radar/scripts/scoring_modules.py)
- [candidate_discovery.py](/Users/zhangpeng/opt/meme-coin-radar/skills/meme-coin-radar/scripts/candidate_discovery.py)

用途:

- 固化当前版本的评分逻辑，便于后续做版本对比
- 明确每个分数使用了哪些数据源
- 明确每个分数的上限、占比、组合方式和决策门槛
- 作为策略变更、回测复盘、changelog 记录的基线文档

## 1. 总体结构

当前评分流程分四层:

1. 候选发现: 先决定哪些币进入候选池
2. 硬否决: 先过滤明显不能碰的标的
3. 双轴评分: 计算 `OOS` 和 `ERS`
4. 最终决策: 生成 `recommend_paper_trade / watch_only / manual_review / reject`

当前主函数:

- `score_candidate()`: 单标的总评分入口
- `build_trade_plan()`: 基于评分结果生成执行计划
- `direction_signal()`: 基于趋势/费率/热度判断 long / short 偏向与置信度

## 2. 数据源映射

| 模块 | 代码字段 | 来源 | 用途 |
|---|---|---|---|
| 市场基准 | `btc_dir`, `btc_price`, `btc_chg` | OKX CEX / Hyperliquid fallback | 判断大盘 regime |
| 候选发现 | `okx_hot_tokens`, `okx_x_tokens`, `okx_signals`, `okx_tracker_activities` | OKX OnchainOS | 候选召回 |
| 链上结构 | `price_info`, `advanced_info`, `cluster_overview`, `cluster_top_holders`, `holders`, `trades` | OKX OnchainOS | 评估市值、筹码、风险、换手 |
| 执行承接 | `ticker`, `funding`, `klines`, `klines_4h`, `klines_1d`, `oi` | Binance Futures | 评估交易性与时机 |
| 社区热度 | `count24h`, `pct`, `score` | Binance Alpha | 评估交易所承接热度 |
| 社交叙事 | `social_mentions_24h`, `social_growth_6h`, `mindshare_score`, `global_news_count_24h`, `panews_article_count_24h`, `panews_event_count_7d`, `public_board_snapshot_score`, `narrative_labels`, `macro_event_count_24h` | Surf / PANews | 评估情绪、新闻、事件催化 |
| 执行映射 | `mapping_confidence`, `tradable` | 本地映射 + Binance tradable symbols | 判断是否可上模拟盘 |
| 数据完整度 | `missing_fields`, `missing_reasons` | 本地聚合 | 数据缺失降权 / 人工复核 |

## 3. 候选发现逻辑

候选池来源:

- `okx_hot`
- `okx_x`
- `okx_signal`
- `okx_tracker`
- `alpha_hot`
- `key_coins`

候选发现不直接打分，但会影响:

- `candidate_sources` 数量
- 是否有 `token_address`
- 是否能拿到 `onchain_data`
- 是否进入 `meme_onchain` 或 `majors_cex`

策略模式选择:

- 默认是 `meme_onchain`
- 若 symbol 在 `major_coins`，则转为 `majors_cex`

## 4. 硬否决规则

这些规则在 `score_candidate()` 里先于打分执行。命中任一条就直接 `reject`。

| 规则 | 条件 | 使用数据源 |
|---|---|---|
| 前十持仓过高 | `top10_ratio > 0.35` | OnchainOS advanced-info / hot token |
| Cluster rug 风险过高 | `cluster_rug_ratio >= 0.60` | OnchainOS cluster-overview |
| 流动性过低 | `0 < liquidity < 50000` | OnchainOS price-info |
| 可疑持仓过高 | `suspicious_ratio >= 0.20` | OnchainOS advanced-info |
| Dev 持仓过高 | `dev_ratio >= 0.15` | OnchainOS advanced-info |
| 执行映射过低 | `mapping_confidence == "low" and tradable` | 本地映射 |
| 暴涨衰竭 | `chg > 60 and day_pos > 0.95 and 4H trend not bullish/weak_recovery` | Binance ticker + kline + OnchainOS price |

补充风险提示但不直接 reject:

- ATR 偏低
- 滑点未实盘模拟
- 宏观事件临近
- 关键字段拉取失败较多

## 5. OOS: Onchain Opportunity Score

### 5.1 结构

`base_oos = turnover_activity + momentum_window + holder_structure + smart_money_resonance + market_cap_fit + intraday_position`

`oos = base_oos + social_heat + macro_catalyst`

理论上限:

- `base_oos`: `25 + 20 + 20 + 15 + 10 + 5 = 95`
- `social_heat`: `15`
- `macro_catalyst`: `4`
- `OOS` 理论上限: `114`

说明:

- 当前代码没有把 OOS 截断到 100
- 这是排序分，不是严格百分制

### 5.2 分项明细

#### `turnover_activity` 最高 `25`

函数: `score_turnover_activity()`

使用字段:

- `turnover_ratio`
- `trade_density`
- `buyer_ratio`

来源:

- OnchainOS `price_info`
- OnchainOS `trades`
- OnchainOS `hot_token`

规则:

| 条件 | 分数 |
|---|---:|
| `turnover_ratio >= 1.0` | 18 |
| `0.5 <= turnover_ratio < 1.0` | 14 |
| `0.2 <= turnover_ratio < 0.5` | 9 |
| `turnover_ratio < 0.2` | 4 |
| `trade_density >= 0.5` | `+4` |
| `buyer_ratio >= 1.3` | `+3` |
| `1.05 <= buyer_ratio < 1.3` | `+1` |

#### `momentum_window` 最高 `20`

函数: `score_momentum_window()`

使用字段:

- `chg24h`
- `chg4h`
- `trend_1h`
- `trend_4h`

来源:

- Binance ticker
- Binance klines / 4h klines

规则:

| 条件 | 分数 |
|---|---:|
| `3 <= chg24h <= 12` | 20 |
| `12 < chg24h <= 25` | 17 |
| `25 < chg24h <= 35` | 13 |
| `0 <= chg24h < 3` | 10 |
| `-8 <= chg24h < 0` | 6 |
| `35 < chg24h <= 60` | 7 |
| `chg24h > 60` | 2 |
| 其他 | 3 |

附加项:

- `0 < chg4h <= 6 and trend_1h in {"bullish", "weak_recovery"}`: `+2`
- `chg24h > 35 and trend_4h != trend_1h`: `-3`

#### `holder_structure` 最高 `20`

函数: `score_holder_structure()`

使用字段:

- `top10_ratio`
- `new_wallet_ratio`
- `cluster_concentration`
- `cluster_rug_ratio`
- `smart_money_holder_ratio`
- `whale_holder_ratio`

来源:

- OnchainOS advanced-info
- OnchainOS cluster-overview
- OnchainOS holders

规则摘要:

- `top10_ratio <= 0.20`: `+8`
- `top10_ratio <= 0.35`: `+5`
- `top10_ratio <= 0.50`: `+2`
- `cluster_concentration == low`: `+4`
- `cluster_concentration == medium`: `+2`
- `cluster_rug_ratio <= 0.20`: `+4`
- `cluster_rug_ratio <= 0.35`: `+2`
- `0.10 <= new_wallet_ratio <= 0.35`: `+4`
- `0.35 < new_wallet_ratio <= 0.50`: `+2`
- `smart_money_holder_ratio >= 0.05`: `+2`
- `whale_holder_ratio >= 0.08`: `+2`

#### `smart_money_resonance` 最高 `15`

函数: `score_smart_money_resonance()`

使用字段:

- `signal_wallet_count`
- `wallet_type_mix`
- `repeat_signal_count`
- `tracked_wallet_overlap`
- `owned_smart_money_hit_count`

来源:

- OnchainOS `signal list`
- OnchainOS `tracker activities`

规则:

- `signal_wallet_count >= 5`: `+7`
- `signal_wallet_count >= 3`: `+5`
- `signal_wallet_count >= 1`: `+2`
- `wallet_type_mix >= 2`: `+3`
- `repeat_signal_count >= 2`: `+2`
- `tracked_wallet_overlap >= 2`: `+2`
- `owned_smart_money_hit_count >= 1`: `+1`

#### `market_cap_fit` 最高 `10`

函数:

- `score_market_cap_fit()` for `meme_onchain`
- `score_major_market_cap_fit()` for `majors_cex`

来源:

- OnchainOS `price_info.marketCap`

`meme_onchain`:

- `5M ~ 50M`: `10`
- `50M ~ 150M`: `8`
- `150M ~ 300M`: `6`
- `< 5M`: `4`
- `300M ~ 1B`: `2`
- `> 1B`: `0`

`majors_cex`:

- `>= 10B`: `10`
- `>= 1B`: `8`
- `>= 300M`: `6`
- `<= 0`: `6`
- 其他: `4`

#### `intraday_position` 最高 `5`

函数: `score_intraday_position()`

使用字段:

- `day_pos`

来源:

- Binance ticker `high24h/low24h`
- OnchainOS `maxPrice/minPrice`

规则:

- `0.75 <= day_pos <= 0.95`: `5`
- `0.60 <= day_pos < 0.75`: `3`
- `day_pos > 0.95`: `2`
- `day_pos >= 0.40`: `1`

#### `social_heat` 最高 `15`

函数:

- 无 `social_intel` 时: `score_social_heat()`
- 有 `social_intel` 时: `score_social_heat_v2()`

组成:

- `social_momentum` 最高 `8`
- `news_narrative` 最高 `7`

来源:

- OKX X rank
- Binance Alpha
- Surf
- PANews

`social_momentum`:

- `okx_x_rank <= 5`: `+2`
- `okx_x_rank <= 15`: `+1`
- `social_mentions_24h >= 100`: `+2`
- `social_mentions_24h >= 25`: `+1`
- `social_growth_6h >= 0.5`: `+2`
- `social_growth_6h > 0.1`: `+1`
- `mindshare_score > 0`: `+1`
- `alpha_count24h >= 50000 and social_growth_6h > 0.1`: `+1`

`news_narrative`:

- `global_news_count_24h >= 3`: `+2`
- `global_news_count_24h >= 1`: `+1`
- `panews_article_count_24h >= 2`: `+2`
- `panews_article_count_24h >= 1`: `+1`
- `panews_editorial_keywords` 非空: `+1`
- `panews_event_count_7d >= 1`: `+1`
- `public_board_snapshot_score > 0` 或 `narrative_labels` 非空: `+1`

#### `macro_catalyst` 最高 `4`

函数: `score_macro_catalyst()`

使用字段:

- `macro_event_count_24h`
- `high_importance_macro_event`

来源:

- PANews calendar / events

规则:

- 无事件: `0`
- 有事件: `min(macro_event_count_24h, 3)`
- 若高重要性事件: 再 `+1`
- 最终封顶 `4`

## 6. ERS: Execution Readiness Score

### 6.1 结构

`ers = execution_mapping + execution_alpha + execution_liquidity + execution_timing + data_quality`

理论上限:

- `35 + 20 + 20 + 15 + 10 = 100`

### 6.2 分项明细

#### `execution_mapping` 最高 `35`

函数: `score_execution_mapping()`

使用字段:

- `mapping_confidence`
- `tradable`

来源:

- 本地映射逻辑
- Binance tradable symbols

规则:

- 非可交易: `0`
- `native / exact / high`: `35`
- `medium / probable`: `20`
- 其他: `0`

#### `execution_alpha` 最高 `20`

函数: `score_execution_alpha()`

使用字段:

- `alpha_count24h`
- `alpha_pct`

来源:

- Binance Alpha

规则:

- `alpha_count24h >= 100000 and alpha_pct >= 0`: `20`
- `alpha_count24h >= 50000 and alpha_pct >= 0`: `15`
- `alpha_count24h >= 20000`: `8`
- `alpha_count24h > 0`: `4`

#### `execution_liquidity` 最高 `20`

函数: `score_execution_liquidity()`

使用字段:

- `atr_pct`
- `volume`
- `chg24h`

来源:

- Binance ticker
- Binance klines

规则:

- `volume >= 100M`: `+10`
- `volume >= 20M`: `+7`
- `volume >= 5M`: `+4`
- `0.04 <= atr_pct <= 0.12`: `+10`
- `0.02 <= atr_pct <= 0.18`: `+6`
- `atr_pct > 0.18 or abs(chg24h) > 60`: `+2`

#### `execution_timing` 最高 `15`

函数: `score_execution_timing()`

使用字段:

- `day_pos`
- `chg24h`

来源:

- Binance ticker
- OnchainOS price

规则:

- `0.70 <= day_pos <= 0.92 and chg24h <= 30`: `15`
- `0.60 <= day_pos <= 0.95 and chg24h <= 45`: `10`
- `day_pos > 0.95 or chg24h > 60`: `3`
- 其他: `6`

#### `data_quality` 最高 `10`

函数: `score_data_quality()`

使用字段:

- `missing_count`
- `mapping_confidence`

来源:

- 本地缺失字段统计

规则:

- 初始分 `10`
- `mapping_confidence in {"low", "none"}`: `-4`
- 每缺一项 `-1`
- 最多扣 `6`

## 7. Final Score 组合权重

`meme_onchain`:

- `final_score = round(oos * 0.7 + ers * 0.3)`

`majors_cex`:

- `final_score = round(oos * 0.5 + ers * 0.5)`

原因:

- 妖币优先看链上机会，执行承接次之
- 主流币对执行流动性依赖更高

## 8. 主流币代理逻辑

当 `strategy_mode == "majors_cex"` 时，部分链上分项会切换到代理逻辑，避免因为链上字段不完整而被误伤。

### `score_major_holder_structure_proxy()`

当 `holder_structure_score == 0` 时启用:

- `volume >= 100M`: `+2`
- `trend_1h` 多头或弱修复: `+2`
- `trend_4h` 多头或弱修复: `+2`
- `alpha_count24h >= 50000`: `+2`
- 基础分 `4`
- 上限 `12`

### `score_major_participation_proxy()`

当原始 `smart_money_resonance == 0` 时启用:

- `alpha_count24h >= 100000`: `+6`
- `alpha_count24h >= 50000`: `+4`
- `alpha_count24h > 0`: `+2`
- `oi_change_pct >= 5`: `+4`
- `oi_change_pct >= 2`: `+2`
- 上限 `10`

## 9. 方向与置信度逻辑

函数: `direction_signal()`

目标:

- 给出 `long / short`
- 给出 `confidence`
- 判断是否满足方向侧的入场条件

输入:

- `chg`
- `fr`
- `trend_struct`
- `count24h`
- `sm_count`
- `total`
- `trend_4h`

多空偏置规则:

- `chg >= 5`: long `+16`
- `chg <= -5`: short `+16`
- `fr < -0.2`: long `+14`
- `fr > 0.5`: short `+14`
- `fr > 0`: short `+5`
- `fr < 0`: long `+5`
- `trend_struct == bullish`: long `+14`
- `trend_struct == bearish`: short `+14`
- `trend_struct == weak_recovery`: long `+8`
- `trend_struct == below_ema20`: short `+8`
- `trend_4h == bullish`: long `+6`
- `trend_4h == bearish`: short `+6`
- `count24h >= 100000`: 顺趋势方向 `+6`
- `count24h >= 50000`: 顺趋势方向 `+4`
- `sm_count >= 3`: long `+6`
- `sm_count >= 1`: long `+3`

置信度:

- `confidence = min(100, total * 0.65 + dominant_score * 0.35)`

入场门槛:

- `total >= settings.min_recommend_score`
- `dominant_score >= settings.min_direction_bias`
- `bias_gap >= settings.min_direction_gap`

默认配置:

- `min_recommend_score = 75`
- `min_direction_bias = 18`
- `min_direction_gap = 6`

## 10. 决策门槛

### `meme_onchain`

| 条件 | 决策 |
|---|---|
| `oos >= 75 and ers >= 65 and tradable` | `recommend_paper_trade` |
| `oos >= 75` | `watch_only` |
| `oos >= 55` 或缺失字段 `>= 3` | `manual_review` |
| 其他 | `reject` |

### `majors_cex`

| 条件 | 决策 |
|---|---|
| `final_score >= 68 and ers >= 68 and tradable` | `recommend_paper_trade` |
| `final_score >= 58` | `watch_only` 或 `manual_review` |
| 缺失字段 `>= 3` | `manual_review` |
| 其他 | `reject` |

补充规则:

- 如果不是 `recommend_paper_trade`，则 `can_enter = False`
- 不可交易标的会追加 `risk_notes`

## 11. 缺失字段与人工复核

函数:

- `_classify_missing()`
- `score_data_quality()`

关键字段:

- `atr14`
- `trend`
- `oi`
- `fundingRate`
- `volume`
- `alpha_count24h`
- `marketCap`
- `volume24H`
- `top10_holder_ratio`

分类:

- `fetch_error`
- `not_supported`
- `asset_type`

人工复核触发:

- `decision == manual_review`
- 或 `fetch_error_count >= 2`

## 12. 建议的后续维护方式

每次改评分逻辑时，至少同步更新本文件中的这些部分:

1. 数据源映射
2. OOS / ERS 分项表
3. Final Score 权重
4. 硬否决规则
5. 决策门槛
6. 版本号与更新时间

建议变更记录模板:

```md
## [vX.Y.Z] scoring diff

- 变更函数:
- 新增/删除数据源:
- 分项权重变化:
- 决策门槛变化:
- 预期结果影响:
```
