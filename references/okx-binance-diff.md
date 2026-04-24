# OKX / Binance 合约价格差异说明

## 为什么价格会差10倍？

OKX 和 Binance 使用不同的合约乘数（contract multiplier / contract value）。

| 交易所 | 合约格式 | 合约乘数示例 |
|---|---|---|
| OKX | BTC-USDT-SWAP | ctVal = 0.01 BTC |
| Binance | BTCUSDT | ctVal = 0.01 BTC |

看起来相同，但有些币的 OKX 合约实际上用的是 **USD 结算**（inverse）而非 USDT 结算（linear），导致价格数字完全不同。

**已知差异案例**：

| 币种 | OKX 显示价 | Binance 实际价 | 差异倍数 |
|---|---|---|---|
| DOT | $12.18 | $1.24 | ~10x |
| ZETA | $0.50 | $0.054 | ~10x |
| STRK | 正常 | 正常 | — |

## 判断方法

当发现同一币种在 OKX 和 Binance 的价格相差超过 2x 时：

1. **价格比率**：计算 `OKX价格 / Binance价格`
2. 如果比率 ≈ 10 → OKX 合约乘数是 Binance 的 1/10
3. 如果比率 ≈ 0.1 → 反过来（较少见）
4. 如果比率 ≈ 1 → 两所合约规格一致，无需处理

## 验证脚本

```python
import json, urllib.request

coins = ['DOT', 'ZETA', 'RAVE', 'SPK', 'SOL', 'ZEC', 'HYPE']
okx_prices = {
    'DOT': 12.18,   # 手动填入 OKX 显示的价格
    'ZETA': 0.50,
}
# Binance API
for c in coins:
    url = f'https://fapi.binance.com/fapi/v1/ticker/24hr?symbol={c}USDT'
    d = json.loads(urllib.request.urlopen(url).read())
    okx_p = okx_prices.get(c, 0)
    ratio = okx_p / float(d['lastPrice']) if okx_p else 1
    flag = '⚠️ 差异' if abs(ratio - 1) > 2 else '✅ 一致'
    print(f'{c}: OKX={okx_p} Binance={d["lastPrice"]} ratio={ratio:.2f} {flag}')
```

## 本项目的处理规则

1. **所有价格相关判断，以 Binance 价格为准**
2. OKX 数据仅用于：涨跌幅趋势、资金费率、OI 变化
3. 报告第一行注明：`⚠️ 本报告价格以 Binance 为准，OKX 仅作趋势参考`
4. 对价格差异 > 2x 的币种，在报告中单独标注为"数据异常，暂不参与"

## 快速检查命令

```bash
# Binance 批量查价
python3 -c "
import json,urllib.request
for c in ['DOT','ZETA','RAVE','SPK','SOL','ZEC','HYPE']:
    try:
        d=json.loads(urllib.request.urlopen(f'https://fapi.binance.com/fapi/v1/ticker/24hr?symbol={c}USDT').read())
        print(f'{c}: {d[\"lastPrice\"]}')
    except: print(f'{c}: NOT FOUND')
"
```
