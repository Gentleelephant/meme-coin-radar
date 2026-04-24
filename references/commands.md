# Phase 1.5 命令速查手册

> ⚠️ **Demo 模式限制**：`market filter` / `oi-change` / `sentiment` 在 Demo 环境不可用。
> 见 SKILL.md 顶部的「OKX Demo 限制说明」。

## 快速总览（Phase 1.5 新增）

| Step | 命令 | 用途 | 备注 |
|---|---|---|---|
| 0 | `okx market ticker BTC-USDT-SWAP --json` | BTC大盘状态 | ✅ Demo可用 |
| 0 | `okx market tickers SWAP` | 全量314个USDT-M tickers | ✅ Demo可用 |
| 1 | Python解析tickers | 24h涨幅/跌幅异动币 | ⭐替代filter |
| 3 | `okx market funding-rate <instId>` | 资金费率（逐个查）| ✅ Demo可用 |
| 6 | Binance API curl/Python | 价格+费率交叉验证 | ✅ 全局可用 |

---

## Step 0 — 大盘 & 全量 tickers（实测可用 ⭐）

### BTC 状态
```bash
okx market ticker BTC-USDT-SWAP --json
# 返回: last, open24h, high24h, low24h, volCcy24h
# 涨跌计算: (last - open24h) / open24h * 100
```

### 全量 USDT-M tickers（⭐ Demo 唯一可用的大范围筛选方式）
```bash
okx market tickers SWAP
# 返回所有 live USDT-M SWAP 的：instId, last, 24h high, 24h low, 24h vol
# 格式: "XPD-USDT-SWAP   1469.58   1558.89   1468   245875"
#
# Python 解析示例:
okx market tickers SWAP > /tmp/all_tickers.txt
python3 -c "
lines = open('/tmp/all_tickers.txt').read().splitlines()
coins = []
for l in lines:
    p = l.strip().split()
    if len(p)>=5 and '-USDT-SWAP' in p[0]:
        last,high,low,vol = map(float, p[1:5])
        mid = (high+low)/2
        chg = (last-mid)/mid*100
        coins.append({'name':p[0].replace('-USDT-SWAP',''),'last':last,'chg':chg,'vol':vol})
coins.sort(key=lambda x:x['chg'],reverse=True)
for c in coins[:5]: print(c['name'], c['chg'])
"
```

### OKX 情绪雷达（需要真实 API Key，Demo 不可用）
```bash
okx news sentiment-rank --period 1h --sort-by hot --limit 20 --json
# Demo报错: "News features are not available in demo/simulated trading mode."
# 真实账户才可用
```

---

## Step 1-3（Demo 替代方案）

```bash
# Demo 不支持 market filter，用 Python 解析 tickers 输出代替:
# 1. okx market tickers SWAP → 保存
# 2. Python: 按24h高低区间计算涨跌幅度，排序
# 3. 找异常币: top 20涨幅 + bottom 20跌幅

# 资金费率（逐个查）
okx market funding-rate SOL-USDT-SWAP
# 返回: instId, fundingRate, nextFundingRate, fundingTime, nextFundingTime
```

## ⚠️ OKX Demo 实测命令清单（必读）

| 命令 | Demo 可用 | 说明 |
|---|---|---|
| `okx market tickers SWAP` | ✅ 可用 | 全量 293 个 USDT-M SWAP tickers（**核心数据源**）|
| `okx market ticker <instId>` | ✅ 可用 | 单币 ticker，含 open24h/high24h/low24h |
| `okx market funding-rate <instId>` | ✅ 可用 | 单币资金费率 |
| `okx market filter ...` | ❌ 不可用 | Demo 不支持，真实账户可用 |
| `okx market oi-change ...` | ❌ 不可用 | Demo 不支持，真实账户可用 |
| `okx news sentiment-rank ...` | ❌ 不可用 | Demo 不支持，真实账户可用 |
| `okx trade ...` | ✅ 可用 | Demo 可挂单验 |

**Demo 替代方案**：`tickers SWAP` → 解析全部 293 个币的 high/low/last/vol → 计算涨跌幅度找异动币 → Binance `premiumIndex` API 补资金费率。

> BTC 方向计算：`(last - open24h) / open24h * 100`，**不要用 `sodUtc8` 字段**（那是 UTC+8 开盘价，非 24h 前价格）。

## 快速总览

| Step | 命令 | 用途 | 新增 |
|---|---|---|---|
| 0 | `okx market ticker BTC-USDT-SWAP` | BTC大盘状态 | ⭐ |
| 0 | `okx news sentiment-rank` | 情绪热度排行 | ⭐ |
| 1 | `okx market filter` | 24h涨幅榜 | — |
| 2 | `okx market filter` | 24h跌幅榜 | — |
| 3 | `okx market oi-change --bar 5m` | 5分钟OI变化 | ⭐ |
| 3 | `okx market oi-change --bar 1H` | 1小时OI变化 | — |
| 4 | `okx market filter` | 资金费率排行 | — |
| 5 | `okx market filter` | 成交额排行 | — |
| 6 | `curl Binance API` | 价格+费率交叉验证 | ⭐增强 |

---

## Step 0 — 大盘 & 情绪（新增）

### BTC 状态
```bash
okx market ticker BTC-USDT-SWAP --json
# 返回: last, chg24hPct, high24h, low24h, volCcy24h
```

### OKX 情绪雷达（需要 API 凭证）
```bash
# 按讨论热度排行
okx news sentiment-rank --period 1h --sort-by hot --limit 20 --json

# 按看多情绪排行
okx news sentiment-rank --period 1h --sort-by bullish --limit 10 --json

# 按看空情绪排行
okx news sentiment-rank --period 1h --sort-by bearish --limit 10 --json

# BTC 情绪快照
okx news coin-sentiment --coins BTC --period 1h --json
```

返回字段: `symbol`, `label` (bullish/bearish/neutral/mixed), `bullishRatio`, `bearishRatio`, `mentionCount`

---

## Step 1-2 — 涨幅/跌幅排行

```bash
# 24h涨幅 TOP30（涨幅>=3%）
okx market filter --instType SWAP --quoteCcy USDT   --sortBy chg24hPct --sortOrder desc --limit 30 --minChg24hPct 3

# 24h跌幅 TOP20（跌幅>=3%）
okx market filter --instType SWAP --quoteCcy USDT   --sortBy chg24hPct --sortOrder asc --limit 20 --maxChg24hPct -3
```

---

## Step 3 — OI 变化（双周期）

```bash
# 5分钟 OI 异动（捕捉盘中爆拉/砸盘）
okx market oi-change --instType SWAP --bar 5m   --sortBy oiDeltaPct --sortOrder desc --limit 15 --minAbsOiDeltaPct 3

# 1小时 OI 变化
okx market oi-change --instType SWAP --bar 1H   --sortBy oiDeltaPct --sortOrder desc --limit 15 --minAbsOiDeltaPct 5

# 4小时 OI 变化
okx market oi-change --instType SWAP --bar 4H   --sortBy oiDeltaPct --sortOrder desc --limit 10
```

关键字段: `oiDeltaPct`（正=资金涌入，负=资金撤离）

---

## Step 4 — 资金费率排行

```bash
# 正费率排行（做空候选）
okx market filter --instType SWAP --quoteCcy USDT   --sortBy fundingRate --sortOrder desc --limit 20 --minFundingRate 0.05

# 负费率排行（做多候选）
okx market filter --instType SWAP --quoteCcy USDT   --sortBy fundingRate --sortOrder asc --limit 20 --maxFundingRate -0.01
```

---

## Step 5 — 成交额排行

```bash
okx market filter --instType SWAP --quoteCcy USDT   --sortBy volUsd24h --sortOrder desc --limit 20 --minVolUsd24h 100000000
```

---

## Step 6 — Binance Alpha 社区活跃度（⭐ Phase 1.6 新增）

> ⚠️ **币安广场（Square）无公开 API**，所有端点返回 403 Forbidden。
> **Binance Alpha 是更好的替代**：638 个代币的链上交易活跃度排行，无需认证。
> `count24h` = 24h 链上交易次数，直接反映社区热度，比广场帖子更量化。

```bash
npx -y @binance/binance-cli alpha token-list --json
```

返回字段（核心）：

| 字段 | 含义 | 妖币雷达价值 |
|---|---|---|
| `symbol` | 代币符号 | 匹配候选币 |
| `count24h` | 24h 链上交易次数 | 🔥 **社区活跃度核心指标** |
| `score` | Binance 官方评分 | 高 score = 官方关注 |
| `hotTag` | 热门标签 | 热点事件标记 |
| `percentChange24h` | 24h 价格变动 | 极端波动识别 |
| `volume24h` | 24h 成交额 | 流动性确认 |

**Python 解析示例：**

```python
import json, subprocess

result = subprocess.run(
    ['npx', '-y', '@binance/binance-cli', 'alpha', 'token-list', '--json'],
    capture_output=True, text=True, timeout=30
)
tokens = json.loads(result.stdout).get('data', [])

# 高活跃 + 大波动 (>50k tx & |chg|>10%)
active = [t for t in tokens
          if int(t.get('count24h','0') or 0) > 50000
          and abs(float(t.get('percentChange24h','0') or 0)) > 10]
for t in sorted(active, key=lambda x: abs(float(x.get('percentChange24h','0'))), reverse=True)[:10]:
    print(f"{t['symbol']} | tx24h={t['count24h']} | chg={t['percentChange24h']}% | score={t['score']}")

# 社区活跃度 TOP10
for t in sorted(tokens, key=lambda x: int(x.get('count24h','0') or 0), reverse=True)[:10]:
    print(f"{t['symbol']} | tx24h={t['count24h']} | chg={t['percentChange24h']}%")
```

**评分加成规则（Phase 1.6）：**

| 条件 | 得分 |
|---|---|
| Binance Alpha count24h > 100,000 | +15 |
| Binance Alpha count24h > 50,000 | +10 |
| Binance Alpha score >= 100 | +5 |
| Binance Alpha score >= 500 | +10 |
| 同时出现在 Alpha TOP10 & OKX 涨幅/跌幅榜 | +10 |

**使用说明：**
- Step 6 先跑 `binance-cli alpha token-list` 获取全部 638 个代币数据
- 用 Python 按 `count24h` 排序，找出候选币的活跃度排名
- 把 Alpha 活跃度得分加入做空/做多评分模型的「情绪」维度
- **特别适用**：OKX Demo 不支持 OI 变化时，`count24h` 可作为替代情绪指标
- ⚠️ SPK、BOME、HYPE 等币可能不在 Alpha 列表中（未上线的币种无数据）

---

## Step 7 — Binance 价格 + 费率交叉验证

```python
import json, urllib.request, time

def binance_batch(coins):
    results = []
    for c in coins:
        try:
            t = json.loads(urllib.request.urlopen(
                f'https://fapi.binance.com/fapi/v1/Ticker/24hr?symbol={c}USDT', timeout=5).read())
            f = json.loads(urllib.request.urlopen(
                f'https://fapi.binance.com/fapi/v1/PremiumIndex?symbol={c}USDT', timeout=5).read())
            rate = float(f['lastFundingRate']) * 100
            results.append({
                'coin': c,
                'price': t['lastPrice'],
                'chg24h': t['priceChangePercent'],
                'fundingRate': f'{rate:.4f}%',
                'annualRate': f'{rate*3*365:.1f}%',
                'volume': f'{float(t["quoteVolume"])/1e6:.1f}M'
            })
        except Exception as e:
            results.append({'coin': c, 'error': str(e)})
        time.sleep(0.1)
    return results

# 使用: binance_batch(['RAVE','SPK','SOL','ZEC','HYPE'])
```

---

## 单币深度分析

```bash
# 4H K线（趋势结构）
okx market candles <instId> --bar 4H --limit 20 --json

# 资金费率历史
okx market funding-rate <instId> --history --limit 6 --json

# OI 历史
okx market oi-history <instId> --bar 1H --limit 24 --json

# 情绪趋势
okx news coin-trend <COIN> --period 1h --points 24 --json
```
