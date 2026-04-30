# OnchainOS JWT Timeout Analysis

> 日期：2026-04-30
> 目的：记录 `OKX OnchainOS JWT 很容易超时` 的排查结论，供后续 agent 按条修复。

---

## 一句话结论

当前问题不应简单归因为“JWT 太短”。

更可能的真实情况是：

- 当前 provider 采用“每次请求单独拉起一次 CLI”的调用模型，放大了 JWT / 会话过期风险。
- OnchainOS 快照抓取是高频串行调用，单次扫描容易积累成几十到上百次 CLI 调用。
- 现有错误分类不足，`auth_error`、CLI 参数漂移、普通超时都可能被混在一起。
- 本机 `onchainos 2.5.0` 已出现命令参数兼容性变化，至少一处失败并非 JWT，而是 CLI 参数失配。

---

## 已确认事实

### 1. OnchainOS provider 当前没有会话复用

文件：
- [scripts/providers/onchainos.py](/Users/zhangpeng/opt/meme-coin-radar/skills/meme-coin-radar/scripts/providers/onchainos.py:23)

现状：
- `_json_command()` 每次都调用 `run(command, timeout=...)`
- `run()` 底层是 `subprocess.run(..., shell=True)`，即每个请求都单独拉起一个 CLI 进程
- provider 中没有 JWT 预热、refresh、缓存、重试分层或常驻连接机制

影响：
- 每次请求都可能触发独立的认证/会话检查
- 在批量扫描中，会显著放大 token 过期和冷启动抖动

### 2. token snapshot 是 6 个串行请求拼装

文件：
- [scripts/providers/onchainos.py](/Users/zhangpeng/opt/meme-coin-radar/skills/meme-coin-radar/scripts/providers/onchainos.py:213)

现状：
- `token_snapshot()` 串行调用：
  - `token_price_info()`
  - `token_advanced_info()`
  - `token_cluster_overview()`
  - `token_cluster_top_holders()`
  - `token_holders()`
  - `token_trades()`

影响：
- 一个候选币就需要 6 次 OnchainOS CLI 调用
- 如果扫描多个候选币，会快速累积为大量请求

### 3. 主流程会对多个候选持续调用快照

文件：
- [scripts/auto-run.py](/Users/zhangpeng/opt/meme-coin-radar/skills/meme-coin-radar/scripts/auto-run.py:301)

现状：
- `auto-run.py` 在 `[2a] OKX OnchainOS token snapshots...` 阶段遍历候选
- 对 `tradable_candidates + onchain_candidates[:10]` 逐个调用 `okx_token_snapshot()`

影响：
- 一次完整扫描的 OnchainOS CLI 调用量很高
- JWT 即使本身不算极短，也可能在长链路中被动过期

### 4. 当前错误分类不足，auth 问题不易识别

文件：
- [scripts/providers/onchainos.py](/Users/zhangpeng/opt/meme-coin-radar/skills/meme-coin-radar/scripts/providers/onchainos.py:33)
- [scripts/providers/common.py](/Users/zhangpeng/opt/meme-coin-radar/skills/meme-coin-radar/scripts/providers/common.py:87)

现状：
- OnchainOS provider 自己构造 `FetchStatus`
- 除超时外，大部分失败会落成 `source_unavailable`
- 没有复用 `common.py` 中更完整的错误归类逻辑

影响：
- JWT 过期、权限失效、rate limit、参数漂移容易被混成一类
- 误诊概率高，不利于后续自动重试和观测

### 5. 本机 CLI 已存在兼容性漂移，不是所有失败都与 JWT 有关

环境确认：
- `onchainos --version` 返回 `2.5.0`

已确认现象：
- `onchainos tracker activities --tracker-type smart_money --chain solana --trade-type 1 --limit 1`
- 本机返回 `unexpected argument '--limit' found`

对应代码：
- [scripts/providers/onchainos.py](/Users/zhangpeng/opt/meme-coin-radar/skills/meme-coin-radar/scripts/providers/onchainos.py:129)

结论：
- 当前 `tracker_activities()` 仍在拼接 `--limit`
- 这类失败会制造“OnchainOS 不稳定 / JWT 超时”的假象
- 应先修 CLI 兼容性，再继续观察真实 auth 超时比例

### 6. CLI 具备常驻模式潜力

已确认命令：
- `onchainos mcp --help`

结论：
- CLI 支持 `mcp` 子命令，说明存在 JSON-RPC over stdio 的常驻服务模式
- 这比当前“一次请求一个 CLI 进程”的模式更适合复用认证态与连接状态

### 7. 当前本机 wallet 登录态为空

已确认命令：
- `onchainos wallet status`

本机结果要点：
- `loggedIn: false`
- `accountCount: 0`

说明：
- 本次排查没有复用到真实登录态
- 因此这里的文档重点是“代码结构上为什么容易超时/误诊”，不是声称本机已完整复现某次生产 JWT 过期

---

## 根因判断

按优先级排序，当前更可能的根因是：

1. 调用模型问题
   - 每次请求都拉起独立 CLI，没有会话复用
   - 对 JWT / session lifetime 极不友好

2. 请求编排问题
   - 快照抓取过重，且对多候选串行执行
   - 单次扫描总时长过长

3. 可观测性问题
   - `auth_error` 没有被明确识别和记录
   - 真正的 JWT 失效与其他故障没有被区分

4. CLI 兼容性问题
   - 当前至少有 `tracker activities --limit` 参数漂移
   - 一部分失败与 JWT 无关

5. 登录态治理问题
   - 扫描前没有显式预热/检查 wallet 状态
   - 容易在扫描中途才暴露 auth 问题

---

## 建议修复顺序

### P0. 修复 CLI 兼容性与错误分类

目标：
- 先把“伪 JWT 问题”剔除掉

建议：
- 修复 `tracker_activities()` 对 `--limit` 的使用
- 为 OnchainOS provider 接入统一错误归类逻辑
- 将至少以下错误类型明确写入 `status`：
  - `auth_error`
  - `timeout`
  - `rate_limit`
  - `parse_error`
  - `source_unavailable`
  - `command_not_found`

验收：
- 参数不兼容时，输出能明确显示为参数错误或 source error
- auth 失败不再被模糊记为 `source_unavailable`

### P1. 加入扫描前预热与 auth 检查

目标：
- 不要等到扫描中途才发现登录态失效

建议：
- 扫描开始前执行一次轻量 preflight：
  - `onchainos wallet status`
  - 可选的一次轻量 token/signal 请求
- 若识别到 auth 失效：
  - 立刻失败并给出明确诊断
  - 或执行一次受控 refresh / re-login 流程

验收：
- 扫描开始前即可发现未登录或已失效状态
- 报告中能看到 auth preflight 结果

### P1. 降低单次扫描的 OnchainOS 调用量

目标：
- 缩短从首个请求到最后一个请求的总时长

建议：
- 把 `token_snapshot()` 拆成两层：
  - 轻量层：`price-info + advanced-info`
  - 深度层：`holders + trades + cluster`
- 仅对 top N 或进入候选后半程的标的补深度数据
- 对 `holders`、`trades`、`cluster` 加 TTL cache

验收：
- 同样规模扫描下，OnchainOS 调用次数明显下降
- JWT 过期概率下降

### P2. 引入常驻连接模式

目标：
- 解决“每次 shell 拉起一次 CLI”的结构性问题

建议：
- 评估将 OnchainOS 接入为长期存活的 `mcp` / stdio 会话
- 或实现一个本地 daemon / sidecar，专门托管会话与调用

预期收益：
- 降低进程冷启动成本
- 更容易复用认证态
- 更容易统一做重试、限流、熔断与 telemetry

验收：
- 同批请求不再依赖重复 spawn CLI
- auth 抖动显著下降

---

## 推荐的最小修复包

如果只安排一个 agent 做第一轮修复，建议 scope 限定为：

1. 修复 `tracker activities` CLI 兼容问题
2. 重构 OnchainOS provider 的错误分类
3. 增加扫描前 `wallet status` preflight
4. 为 auth failure 增加一次受控重试
5. 为 snapshot 增加轻量模式或最小 TTL cache

这样可以先拿到两类结果：

- 真实 JWT/登录态故障比例
- 修完兼容性和降载后，超时是否明显下降

---

## 建议补测

最低建议：

- provider 单测：
  - auth 错误分类
  - CLI 参数兼容回归
  - snapshot 轻量/深度路径

- 集成 smoke test：
  - 已登录态下跑一次最小扫描
  - 未登录态下确认能提前失败

- 观测输出：
  - 在 scan metadata 中记录每个 OnchainOS 子步骤的 `status`
  - 统计 auth_error / timeout / source_unavailable 数量

---

## 结论

这次问题更适合按“调用架构 + 兼容性 + 可观测性”来修，而不是只盯 JWT 刷新本身。

在当前结构下，即使 JWT 有效期不算很短，也会因为：

- CLI 反复拉起
- snapshot 过重
- 串行链路过长
- 错误分类不清

而表现成“很容易超时”。

建议先修 `P0/P1`，再决定是否推进 `mcp` 常驻化改造。
