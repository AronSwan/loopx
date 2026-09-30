# Control-Plane Developer Course

> 面向准备修改 LoopX Kernel、CLI、状态投影、调度或扩展能力的开发者。

## 与 Dev Book 的关系

Dev Book 给外部开发者一条“从机制模型到接入/贡献”的完整路径；Control-Plane
Developer Course 是独立章节，面向需要进入源码实现、判断规则优先级、定位 bounded
context 或新增一条控制面规则的开发者。

两者共享官方协议与源码事实，但不维护两份完整课程：

- Dev Book 讲清楚预测行为所需的机制；
- Course 提供 Showcase 推导、decision table、源码领读、实验与 review 问题。

## 课程地图

| 课程章节 | 主题 | 适合在读完 Dev Book 哪部分后进入 |
|---|---|---|
| [概念导读：先把 LoopX 放进一张图](/loopx/docs/development/control-plane-course/00-concept-primer/) | 有限上下文、外置状态与核心概念总图 | [四个要求](02b-long-horizon-requirements.md) |
| [长程任务如何收敛](/loopx/docs/development/control-plane-course/topic-long-horizon-convergence/) | 方向、证据、Delta、活性与终局不变量 | [恢复与运行边界](04-runtime-boundaries.md) |
| [第 1 讲：Harness 是 effectful program](/loopx/docs/development/control-plane-course/01-agent-loop-effectful-program/) | effect interpreter 心智模型，以及三类 adapter 如何复用 typed settlement algebra | [一轮受治理的工作](03-one-turn.md) |
| [第 2 讲：从三个 Showcase 理解 LoopX 架构](/loopx/docs/development/control-plane-course/02-goal-control-plane-architecture/) | Agent / Provider / Capability / Kernel 分工 | [会话、Goal 与 LoopX](02-session-goal-loopx.md) |
| [第 3 讲：从 Showcase 到第一次真实 Loop](/loopx/docs/development/control-plane-course/03-first-real-loop/) | guided start、todo、quota、refresh、spend | [连接项目](05-connect-existing-project.md) |
| [第 4 讲：状态底座与可重放事实](/loopx/docs/development/control-plane-course/04-state-substrate/) | registry、event、active state、run history、projection | [持久状态](state-substrate.md) |
| [第 5 讲：Todo 工作图与 Peer 协作](/loopx/docs/development/control-plane-course/05-work-graph-and-peers/) | claim、lease、handoff、equal peer | [工作图与权限](work-graph-and-authority.md) |
| [第 6 讲：Quota 决策内核与 Interaction Contract](/loopx/docs/development/control-plane-course/06-quota-decision-kernel/) | `should-run`、route、mode、interaction contract | [一轮受治理的工作](03-one-turn.md) |
| [第 7 讲：Host、Heartbeat 与 Stateful Backoff](/loopx/docs/development/control-plane-course/07-host-scheduler-and-heartbeat/) | execution context、RRULE、ACK、backoff | [预算、准入与观察](04b-budget-and-admission.md) |
| [第 8 讲：证据、Refresh 与 Self-Repair](/loopx/docs/development/control-plane-course/08-evidence-refresh-and-self-repair/) | material progress、replan、repair delta | [恢复与运行边界](04-runtime-boundaries.md) |
| [第 9 讲：如何给 Control Plane 增加一条规则](/loopx/docs/development/control-plane-course/09-engineering-a-control-plane-rule/) | invariant、ordered rules、schema、smoke | [修改规则](source-change-control-plane-rule.md) |
| [第 10 讲：Agent 自主写代码时的分层质量门禁](/loopx/docs/development/control-plane-course/10-autonomous-agent-quality-gates/) | 确定性测试、canary、模型行为、release gate | [验证到 PR](source-validation-to-pr.md) |
| [第 11 讲：扩展层、Governed Execution、Explore 与领域产品](/loopx/docs/development/control-plane-course/11-extension-layer/) | 外部 effect 的可恢复结算、默认关闭的 Graph/Harness 与领域产品 | [Extension 生命周期](10-extension-lifecycle.md) |

## 与 Effect Interpreter RFC 的关系

课程第 1 讲与
[Agent Loop Effect Interpreter RFC](/loopx/docs/architecture/rfcs/agent-loop-effect-interpreter-v0/)
共用同一套语言：harness 是 agent loop 外面的 effectful program，状态机只是
interpretation table。进入 Kernel 实现前，建议先读第 1 讲，再按需要进入后续专题。

## 从“读懂”到“能够判断” {#reader-checkpoints}

不必把整门 Course 当作接入项目的前置条件。只想操作自己的项目，先走
[项目接入](05-connect-existing-project.md)与 [Workspace](workspace-v1.md)；准备修改实现，
再做下面的检查。它们把[贯穿任务](00-reading-guide.md#running-example)中的四个问题交给
已有回归测试，不新增一套教学状态机，也不要求运行模型或真正发布 T3。

每项先写下预测，再运行测试，最后找到支持答案的断言。记录“输入事实、允许结果、禁止结果、
证据范围”四项即可，不需要新建 Goal、验收协议或提交自己的练习笔记。

### 环境与证据范围 {#checkpoint-environment}

命令在完整 LoopX 源码 checkout 的仓库根目录执行，不在待管理的业务项目中执行。
需要 Python 3.11+、Node.js 22.22.3+、uv 与 test extra；依赖安装可能访问包源。
先记录本次 checkout，而不是把书中的结果当作本机已经通过：

```bash
git rev-parse HEAD
python --version
node --version
uv sync --extra test
```

前三项使用临时目录中的真实本地状态或 CLI，第四项使用构造的 quota 输入。
它们不是“完全无写入”的演示：会创建测试状态，也可能启动本地 Effect runtime。
不要把 fixture 的 registry、状态删除或损坏注入步骤换成自己的 live Goal。
依赖或 runtime 不可用属于环境阻塞，不是规则通过，也不要通过删除 guard 让练习变绿。

下面的源码链接固定在核对过的主线提交；运行命令使用你刚记录的 checkout。
测试重命名或行为发生变化时，应沿原 invariant 找到当前 owner，重新核对说明；不能简单把
新输出抄成期望。测试通过只覆盖列出的路径，不构成整个产品或真实 Host 的资格验证。

<!-- reader-checkpoint:state:start -->
### 检查一：哪个状态可以用于准入？ {#checkpoint-state}

**先预测。** T1 在选定的 File/SQLite authority 中已经 done 或 blocked，旧 Markdown
却仍显示 open。可以执行 T1 吗？如果 authority 暂时读不到，能否以 Markdown 兜底？

```bash
uv run --extra test pytest -q \
  tests/control_plane/test_quota_authority_settlement_journey.py::test_stale_markdown_cannot_admit_terminal_or_blocked_work \
  tests/control_plane/test_quota_authority_settlement_journey.py::test_failed_canonical_read_cannot_fall_back_to_markdown
```

**对照答案。** 第一项覆盖 File/SQLite 与 done/blocked 的组合：返回 `decision=skip`，
没有 selected Todo，heartbeat receipt 为 `not_committed`。第二项使 File authority
不可读：不得选中 Todo，也不得创建本轮 heartbeat receipt。显示存在不构成新的准入来源。

**证据边界。** 这是已选 authority 的准入保护，不表示所有 Markdown 都只是缓存；legacy
路径仍可能以 Markdown 为源。它也没有证明损坏的 provider 已被修好。
回读[状态章节](state-substrate.md)，并检查
[原测试](https://github.com/loopx-project/loopx/blob/67930ab6af78491f10ca3de4ff74ef7a39954a51/tests/control_plane/test_quota_authority_settlement_journey.py)。
<!-- reader-checkpoint:state:end -->

<!-- reader-checkpoint:lease:start -->
### 检查二：历史成功是否仍是执行权？ {#checkpoint-lease}

**先预测。** A acquire 后 renew，再用原 acquire 请求读回，会得到当前 lease 还是一份
自动恢复旧执行权的凭证？release 后继续使用原 acquire key，应该重新获得执行权吗？

```bash
uv run --extra test pytest -q \
  tests/control_plane/test_canonical_lease_acquire.py::test_public_acquire_renew_complete_and_retired_retry
```

**对照答案。** 在该 File/SQLite、`hard_lease` fixture 中，renew 后的重试返回当前 lease，
同时保留原始 receipt。release 后复用退役 acquire key 被拒为 `idempotency_key_reuse`；
新的合法 acquire 使用新 key。完成写回后，Todo 为 done，lease 为 released。
测试中 `state.exists()` 在真正完成后为真，并不是“最后所有状态文件均不存在”。

**证据边界。** 历史回执和当前执行证明必须分别阅读。这个顺序执行的测试不证明所有
soft-claim 路径具有强互斥，也没有覆盖两个真实 Host 的并发、TTL 到期或外部写入围栏。
回读[权限章节](work-graph-and-authority.md)，并检查
[原测试](https://github.com/loopx-project/loopx/blob/67930ab6af78491f10ca3de4ff74ef7a39954a51/tests/control_plane/test_canonical_lease_acquire.py)。
<!-- reader-checkpoint:lease:end -->

<!-- reader-checkpoint:settlement:start -->
### 检查三：记录不完整时，应重做哪一部分？ {#checkpoint-settlement}

**先预测。** T1 的写回已发生，quota 扣减也已经记录，但对应结算回执缺失。
应该重做 T1、再次扣额，还是恢复原操作的回执？怎样证明恢复没有再次扣减？

```bash
uv run --extra test pytest -q \
  tests/control_plane/test_quota_authority_settlement_journey.py::test_returned_command_settles_and_repairs_receipts_without_another_debit
```

**对照答案。** 原写回返回 `spend_required`，执行其绑定命令后达到 `settled`。
fixture 随后只模拟回执缺失；重新读回是 `spend_receipt_required`。
执行返回的恢复命令得到 `appended=false`，扣减记录仍为一次；再次读回达到 `settled`，
不再存在 `settlement_owed`。检查的是计数与最终状态，不只是命令退出码。

**证据边界。** 不要把 fixture 删除回执的做法变成操作 runbook，也不要手工拼接缺少原
Goal/Agent/Todo/Turn 绑定的恢复命令。此测试不证明未知外部 effect 已确认、不证明 API
账单为零，也不完成 G1 或 Goal acceptance。
回读[正常 Turn](03-one-turn.md)和[恢复](04-runtime-boundaries.md)，并检查
[原测试](https://github.com/loopx-project/loopx/blob/67930ab6af78491f10ca3de4ff74ef7a39954a51/tests/control_plane/test_quota_authority_settlement_journey.py)。
<!-- reader-checkpoint:settlement:end -->

<!-- reader-checkpoint:monitor:start -->
### 检查四：没有变化就一定重规划吗？ {#checkpoint-monitor}

**先预测。** 当前 Agent 的一条 monitor lane 已有五次无变化，peer 仍有自己的工作。
当前 Agent 一定继续等待吗？若它自己有可选 advancement，或 Monitor 是显式
`watch_only`，答案是否相同？

```bash
uv run --extra test pytest -q \
  tests/control_plane/test_monitor_replan_agent_scope.py::test_interleaved_monitors_keep_independent_no_change_streaks \
  tests/control_plane/test_monitor_replan_agent_scope.py::test_current_agent_advancement_still_preempts_monitor_streak_replan \
  tests/control_plane/test_monitor_replan_agent_scope.py::test_watch_only_monitor_streak_does_not_create_replan_obligation
```

**对照答案。** 交错 lane fixture 只为符合条件的当前 Agent lane 产生
`monitor_no_change_streak`，不把 peer lane 变成自己的义务。当前 Agent 有 advancement
时，结果为 `run`，不产生这项 replan obligation。显式 watch-only fixture 即使 streak
为 50，也不因此产生该义务。五次是这里的具体策略阈值，不是所有等待的通用定理。

**证据边界。** 这些测试预置计数器并执行决策，没有实际交错发送五次远端 poll；因此不能
拿它们证明计数写入的并发正确性、真实 Host 唤醒或 scheduler backoff 时间。
回读[预算、准入与观察](04b-budget-and-admission.md)，并检查
[原测试](https://github.com/loopx-project/loopx/blob/67930ab6af78491f10ca3de4ff74ef7a39954a51/tests/control_plane/test_monitor_replan_agent_scope.py)。
<!-- reader-checkpoint:monitor:end -->

## 用四项检查定位真实问题 {#diagnostic-routing}

真实项目出现问题时，先收集当前只读事实，不要照抄测试的故障注入步骤。
以下是查阅顺序，不是另一个自动恢复算法；具体 mutation 仍由当前入口和 owner 决定。

| 观察到的现象 | 先查什么 | 不要据此做什么 | 返回章节 |
| --- | --- | --- | --- |
| 页面与 Todo 状态不同 | 当前 authority、精确 Todo 和投影新鲜度 | 以看起来较新的页面覆盖源状态 | [状态](state-substrate.md) |
| acquire 曾成功，当前写回被拒 | 当前 lease、模式、owner 和版本；分开看历史 receipt | 用旧 receipt 或同名 Agent 绕过实例检查 | [权限](work-graph-and-authority.md) |
| 写回存在，本轮尚未结算 | 原身份的 settlement 状态与返回的待完成动作 | 重跑 Host 或手工重复扣额 | [Turn](03-one-turn.md) |
| 外部请求超时，结果未知 | 原操作 identity 与 provider readback 是否可用 | 把超时当作“肯定没有执行” | [恢复](04-runtime-boundaries.md) |
| Monitor 安静，或不断要求 replan | 当前 lane、可选工作、watch-only、due 与真实 Host 活性 | 只凭 quota 余额强制轮询，或伪造 ACK | [观察](04b-budget-and-admission.md) |

使用[附录的只读入口](appendix-reference.md)定位信息；取证前核对命令的实际行为和目标。
任何公开问题或 PR 只带最小 public-safe 事实，不上传 live registry、原始 transcript、凭据
或完整私有运行记录。证据不足时，写清缺少哪一种读回，而不是宣布系统健康或恢复成功。

## 换一个领域，检查模型是否仍成立 {#transfer-exercise}

再做一个不用运行命令的合成练习：将 JSON 输出任务换成“根据两份公开材料完成一份比较
报告”。它不是新的已交付产品旅程，也不证明领域结论正确，只检查你是否把 Git/CI 当成了
控制面的必要概念。

| 原任务 | 报告任务中的对应问题 |
| --- | --- |
| commit C1 与测试 | 材料版本、范围、引用，以及能够复核的比较方法 |
| T1 实现、T2 文档 | 两项可分别验收、必要时互相依赖的资料整理与分析工作 |
| M1 等待 CI | 有明确来源和结束条件的资料更新观察；无观察能力时说明人工边界 |
| G1 批准发布 | 明确由谁接受报告及允许什么发布范围；产物生成不等于批准 |
| T3 交付 | 在当前材料与决定仍有效时返回可审阅的结果 |

**自测答案的形状。** 材料从 C1 对应版本变为 C2 后，旧分析应重新检查适用范围，而不是
整份聊天自动变成新的事实；报告完成也不自动授权外部发布。能够保留事实归属、有效证据、
当前授权与下一步，就说明你学会的是控制关系，而不只是一套编程命令。

准备贡献时，将练习里的一个禁止结果带到[规则修改](source-change-control-plane-rule.md)
与[验证到 PR](source-validation-to-pr.md)，形成真实的反例、owner 和验收证据。
文档中路径仍存在、两种语言使用相同测试命令，只是维护检查，不替代这些行为测试或双语
语义评审。
