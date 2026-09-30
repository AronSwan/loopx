# 持久状态与只读投影

本章挂载在[要求一](/loopx/docs/book/chapters/02b-long-horizon-requirements/)上：**状态必须能脱离上下文存在**。

## 从一个坏的结局开始

先看一个在长程系统里反复出现的场景。它没有任何一步在说谎，但事实分叉了：

```text
09:12  Agent A 完成一次交付，写好回执，Todo T1 标记完成。
09:12  status 重新生成一次，dashboard 卡片显示 "T1 done"。
09:40  Agent A 被重启（部署、OOM、用户按停止）。
09:41  Agent B 起来接手。它没有读 event 或 Todo store，而是打开 dashboard
       和上一轮的 review packet，因为那两个页面"看起来就是当前状态"。
09:43  Agent B 在 dashboard 上看到一张卡片写着 "T1 pending"，那是 08:00 的
       缓存的投影，status 在 09:12 之后没有重新生成过。
09:44  Agent B 认为 T1 还没做，重新做了一遍。
09:52  两次交付指向同一份外部资源。T1 的 completion evidence 出现两条 lineage。
```

第二天的复盘会问一个很难回答的问题：**09:41 那一刻，系统的真实状态到底是什么？**
两个答案同时存在，而且都能给出证据——一个来自 event，一个来自页面。

这里的分叉不来自 Agent 的判断错误，而来自一个更基础的设计选择：**页面有没有资格作为事实来源。**
一旦允许"看起来像当前状态"的表面进入决策，事实就有两个来源，重启后的读模型和真实源状态注定会漂移。

所以在长程运行里，恢复的判据不能是"还能读到什么"，只能是"这条信息有稳定的所有者，并且能重新投影成当前决策"。

## 为什么"让所有页面保持同步"解不了这个问题

自然的反应是让每个页面都实时刷新，或者干脆以最方便的那个页面为准。这条路有几个确定的失败点：

- **同步没有共同提交点。** 页面 A 更新了、页面 B 失败，系统就停在中间，和 09:43 一样，只是窗口更短。
- **读的方便性会反向定义事实。** 谁读得最多，谁的缓存最容易过期，也就最容易成为事实来源。
- **同步刷新不解决权限。** 即使每个页面都是最新的，它仍然只是一份读取结果，不能授权一次写入。

真正要回答的是另一个问题：**这条信息归谁所有，谁有权改它。** 有了归属，投影是否滞后只是一个可检测、可修复的偏差；
没有归属，同步再快也只是把分叉窗口缩小，不会消除它。

## 设计：五类状态表面

LoopX 的答案是**持久状态与只读投影的分离**。哪些表面保存事实，哪些只负责阅读，在协议里是显式写明的。

先看身份。持久身份是 **Goal**，而不是某个 Host thread：

```text
Goal
├── objective and boundary
├── todos, gates and evidence lineage
├── registered peer identities
└── runtime and projection routes

Session / thread
└── one temporary executor context
```

一个 Goal 可以先后由 Codex App、Codex CLI 或其他 Host 推进；一个 session 也可能读取多个 Goal。
读取 Goal 不会自动授予写权限，结束 session 也不会使 Goal 消失。

### 精确复用 Goal，不靠文本猜测

Goal 复用依赖 stable `goal_id` 和 registry 连接，不依赖 objective 的模糊相似度：

```text
one registered goal
  -> reuse that exact goal boundary

multiple registered goals
  -> read-only goal_selection_gate
  -> choose one exact goal_id
  -> rerun before any mutation
```

如果项目注册了多个 Goal，`start-goal --guided` 应列出可选 id、状态和精确重跑命令。在选择完成前，
Todo 写入、Agent 注册和 Host activation 都不应发生。目标文本相似、来自同一 repository，甚至
共享一部分 acceptance，都不构成静默合并 Goal 的依据。

还要把 Goal reuse 与 Agent takeover 分开。新 Agent 可以读取同一 Goal 的公共 frontier 和历史，
但在无已注册 lane 时默认注册 fresh `agent_id`；复用已有 Agent identity 需要用户明确选择那个精确 id。这样历史
lineage 能连续，执行责任却不会被新 session 冒名继承。

因此恢复模型可以写成：

```text
next decision =
  replay(durable project facts)
  + inspect(fresh workspace and external facts)
```

旧对话可以帮助理解，但不能比当前 Git、当前 Gate、当前 CI 和 LoopX canonical state 更权威。

### 1. Registry：身份、连接与长期策略

Registry 回答"这个 Goal 是谁、连接到哪里、允许哪些运行路径"：

- Goal id、repository 与 active-state 路由；
- local/global runtime root；
- registered Agent identities；
- coordination、write scope 与 guard；
- default-off feature 的配置。

Registry 不证明某个 Host 已经成功启动，也不保存每一轮 Agent 输出。它是连接与策略事实，并非执行回执。

### 2. Event ledger：发生过什么

[`event_sourced_state_contract_v0`](https://github.com/loopx-project/loopx/blob/main/docs/reference/protocols/event-sourced-state-contract-v0.md)
把 Todo、Gate、run、evidence、projection 和 quota 变化表达为 append-only events。

事件至少需要满足四个不变量：

| 不变量 | 作用 |
| --- | --- |
| Append-only | 新事实追加，不能重写历史来伪装旧动作没有发生 |
| Ordered | replay 能重建相同的生命周期顺序 |
| Idempotent | 同一 `event_id` 与相同 payload 重放不会重复生效 |
| Privacy-partitioned | public-safe 摘要与 local/private payload 不混在同一公开流中 |

例如"Todo 已完成"不能靠把 Markdown 复选框改成 `[x]` 来证明。合法转换应留下 Todo id、producer、
completion evidence、时间和 event lineage，使 status、review packet 与下一轮 quota 能复用同一事实。

### 3. Active-state workbench：人可读工作台

`ACTIVE_GOAL_STATE.md` 让人和 Agent 能快速阅读 Objective、Next Action、User Todo、Agent Todo 与
Progress。它是重要的工作台，但"所有真相都在 Markdown 里"是错误模型。

在迁移或兼容阶段，Markdown 可能仍参与 Todo 读取；规范写入仍应通过 LoopX lifecycle commands
形成事件或受控 writeback。直接编辑一个被投影出来的段落，不等于完成状态转换。

[`active_state_structured_projection_v0`](https://github.com/loopx-project/loopx/blob/main/docs/reference/protocols/active-state-structured-projection-v0.md)
定义了如何从这个工作台生成 typed、read-only 的 Todo、Gate 与 Next Action 视图。协议的 Reader Contract 明确：

- projection 可以重算；
- projection 不授予写权限；
- generated compatibility id 不等于 migration-ready canonical id；
- duplicate id、缺失 section 等问题应成为 diagnostics，而非被静默忽略。

### 4. Run history：一轮发生了什么

Run history 保存一轮 bounded work 的紧凑索引，例如：

- 哪个 Agent、Todo 与 Goal 参与了本轮；
- 观察、交付或 blocker 的分类；
- validation 与 evidence refs；
- delivery scale 与 outcome；
- successor、replan 或 no-follow-up；
- 是否满足 spend 条件。

Run snapshot 覆盖不了完整 project memory。它回答"这一轮看到了什么、做了什么、证明了什么"，而
Goal lifecycle 仍由 Todo、Gate、events 与 acceptance 组合决定。

富日志、raw transcript 和 verifier tail 可以留在 local/private runtime artifact；公开 projection
只保留足以复核和恢复的 bounded references。

### 5. Status 与其他 projection：当前如何阅读

`loopx status`、`quota should-run`、dashboard、review packet 和 task graph 都是面向不同消费者的
读模型。

它们可以：

- 聚合多个 source facts；
- 压缩大 payload；
- 按 user、agent、CLI 或 operator 视角重新组织；
- 暴露 stale、gap、repair 与 attention signals。

它们不能：

- 发明一个 source 中不存在的 Todo；
- 用展示顺序替代 lifecycle priority；
- 通过修改卡片或图节点绕过 write API；
- 把 stale external observation 当成当前事实。

[`task_graph_projection_v0`](https://github.com/loopx-project/loopx/blob/main/docs/reference/protocols/task-graph-projection-v0.md)
尤其强调：图中的 `blocks`、`validates`、`continues` 和 `hands_off_to` 是派生关系，而非新的调度命令。

## 三种 Ledger：Turn Journal、Goal State、Run History

把"所有记录"都当成同一类状态，会导致"阶段已记录"冒充"business transition"。LoopX 区分三种 ledger：

| Ledger | 拥有什么 | 生命周期 | 典型用途 |
| --- | --- | --- | --- |
| Turn journal | 单次事务的恢复信息 | 单次事务 | 恢复一个中断的 bounded segment |
| Goal/event state | 持久 lifecycle transition | 跨 session、跨 Host | 判断当前 frontier、Gate、acceptance |
| Run history/status | 历史的证据索引与投影 | 只读，不可重写 | 复审、replan、handoff 时的上下文 |

**Turn journal** 回答"本轮发生了什么，如果中断如何恢复"。它记录的是单次事务内的临时状态，而非
持久业务事实。把 journal 当 goal state 的典型错误：agent 在 journal 中看到"已进入阶段三"，就认为
goal 已经 transition 到阶段三。但 journal 只记录 agent 有过的意图，只有 goal/event state 才记录
实际完成的 transition。

**Goal/event state** 回答"当前 frontier 是什么，谁可以做什么"。它通过 append-only event 记录
lifecycle transition（Todo 完成、Gate 解决、Vision 更新），并支持跨 session 重建。它是
durable lifecycle fact 的权威来源，quota 将其与 registry/boundary、Todo/Gate、
capability/workspace、run outcomes/history、scheduler context 以及 fresh external fact 一起编译。

**Run history/status** 回答"历史上发生了什么，有什么证据"。它是只读的，不能反向写入 goal state。
run 记录说"这轮测试通过"，不等于 goal state 中对应的 acceptance 已闭合；只有通过 lifecycle
command 写入的 transition 才算。

这三者混用的代价在恢复时最明显。一个只读 run history 的执行者会重复工作；一个只读 turn journal
的执行者会以为意图已经落地；只有读 goal/event state 的执行者知道 frontier 真正推进到了哪里。

区分这三者的实践意义：每次写回前，确认要写入的是 goal/event state（transition）而非 turn
journal（临时记录）；每次读取 decision 前，确认读的是 goal/event state，而非 run history 的旧
投影。完整三类 ledger 的源码路径和实验见
[Control-Plane Course 第 8 讲](/loopx/docs/development/control-plane-course/08-evidence-refresh-and-self-repair/)。

## 五个 source facts 与 projection truth contract

到这里五类表面已经分开，但"投影不可写"还需要一个机器可检查的声明，否则它只是文档里的一句话。

[`long_horizon_agent_state_protocol_v0`](https://github.com/loopx-project/loopx/blob/main/docs/reference/protocols/long-horizon-agent-state-protocol-v0.md)
的 Projection Protocol 一节把 source 与 projection 的关系写成了一个判据：

```json
{
  "schema_version": "long_horizon_agent_state_protocol_v0",
  "projection_is_writable": false,
  "source_of_truth": [
    "registry",
    "active_state",
    "todo_item_v0",
    "run_history",
    "rollout_event_log",
    "operator_gate",
    "human_reward"
  ],
  "write_apis": [
    "loopx todo",
    "loopx refresh-state",
    "loopx operator-gate",
    "loopx reward",
    "loopx quota spend-slot"
  ]
}
```

`source_of_truth` 里的每一项都有对应的 source state 行，包括 registry、active_state、
`todo_item_v0`、`run_history`、`loopx_rollout_event_v0`（rollout event log）、`operator_gate`
和 `human_reward`。

协议对它们的定义是：**只会通过 LoopX lifecycle commands 或 project-owned state files 写入；
dashboard 和 showcase fixture 不得直接改动。**

同一份文档紧接着写出另一条边界：

> Projection protocol fields are read-only views. They may summarize, rank, and
> compress state, but they do not own truth or grant permission.

这三个动词加一个否定是最小完备的。

**summarize** 允许投影把长 payload 压成可读摘要；**rank** 允许它按 priority 排序；**compress**
允许它丢掉细节。

**grant permission** 则被明确排除：无论投影看起来多么权威，它都不构成写权限。投影的权威性来自
它引用的 source，而不来自它自己的存在。

同一个 pattern 在其他 projection 上重复出现。

`task_graph_projection_v0` 的 payload 里带有：

```python
# loopx/control_plane/work_items/task_graph.py
"truth_contract": {
    "event_ledger_is_source_of_truth": True,
    "projection_is_writable": False,
    "write_api": False,
    "recompute_rule": "Recompute from status, active state, gates, leases, and run history after each lifecycle event.",
}
```

`loopx/control_plane/agents/management_projection.py` 的 agent management projection 也带同样的
`projection_is_writable: False` 与 `write_api: False`。这给读者一个可检查的信号：**打开任何一份
projection JSON，找 `truth_contract`；如果它声称可写，那就是缺陷，而非特性。**

## Canonical、Workbench、Projection 与外部事实

四类表面必须分开，因为它们对"能否直接支持状态转换"的回答不同：

| 层 | 典型内容 | 谁能改变 | 能否直接支持状态转换 |
| --- | --- | --- | --- |
| Canonical state | event、typed Todo、Gate resolution、quota spend | LoopX lifecycle writer | 可以 |
| Workbench | active-state Markdown、人工说明 | 受控 writeback 或兼容编辑 | 需要转成规范事实 |
| Projection | status、quota packet、dashboard、task graph | projection builder | 不可以，只供决策读取 |
| External fact | Git commit、PR、CI、cloud resource | 对应外部系统 | 需要 fresh readback/evidence |

"某个页面显示 PR 已合并"可能只是旧 projection；"某次 run 说测试通过"也可能绑定旧 commit。
只有重新读取外部事实并检查 revision、freshness 与 scope，才能把观察用于当前转换。

## 存储介质与 authority contract

LoopX 当前是**本地优先**的控制面：项目 registry、active-state workbench、event/run history 和
runtime state 位于项目或用户本地。这个事实不意味着"Markdown 文件本身就是 authority"，也不
意味着把目录换成数据库就自动获得正确的并发与恢复语义。

[`event_sourced_state_contract_v0`](https://github.com/loopx-project/loopx/blob/main/docs/reference/protocols/event-sourced-state-contract-v0.md)
明确允许 JSONL、SQLite 或其他 local-first append-only 实现，只要它们保持：

- stable event id 与 ordered replay；
- idempotent append；
- projection head 与 event-store head 对齐；
- public-safe、local-private 与 private-pointer 分区；
- Markdown 继续作为 workbench/projection，而非任意写入口。

[`local_state_write_correctness_v0`](https://github.com/loopx-project/loopx/blob/main/docs/reference/protocols/local-state-write-correctness-v0.md)
当前标记为 public-safe protocol draft。它把更强的写入正确性目标分成
`prepare -> preview -> apply -> record -> project`：

- 同一 `idempotency_key` 不应重复产生逻辑 effect；
- `expected_revision` 不匹配时应 fail closed 或从新 revision 重算非重叠 patch；
- foreign/expired lease 不应被静默清除；
- lock 默认以 Goal 为目标边界，只有单 Todo 且不影响共享顺序时才可更窄；
- 外部写、凭据、production 和 private read 仍需独立 Gate。

当前 Todo lifecycle 命令已经在 active-state file lock 下重读并写回，preview 也会暴露 write
intent。协议文档同时明确：hard idempotency、统一 optimistic CAS 和 lease conflict enforcement
仍按 writer 分阶段 promotion，不能假设所有 writer 已完整执行上述 Draft。

因此，文件、SQLite 或未来 provider 回答的是"字节存在哪里"；event、revision、CAS、lease 与
authority 回答的是"哪次状态转换合法"。

### 已经发布的边界与仍在设计中的边界

`v0.5.4` 的 shared-authority 工作已经不只是纸面方案：仓库包含 provider-neutral TypeScript
`AuthorityStore` contract，以及 file、NoKV 和 PostgreSQL 的 staged candidate 与 conformance evidence。
但这仍不等于已启用 shared control plane。发布版没有把这些 candidate 接到默认运行时，也没有
提供可直接启用的远端 authority service；安装 Provider 更不会自动改变某个 Goal 的事实源。

`v0.5.4` 之后的 `main` 可能继续出现 default-off shadow、parity、fencing 或 provider-first cutover
切片。它们证明迁移机制，不应倒推成 `v0.5.4` 已交付云端协作。稳定版行为以对应 tag 和 release
notes 为准，实验状态以
[Shared Control-Plane Authority RFC](/loopx/docs/architecture/rfcs/shared-goal-authority-state-provider-v0/)
的当前 stage 为准。

当前可以依赖：

- 本地项目状态与 global registry projection；
- Todo lifecycle writer 的 active-state file lock、preview/readback 和当前已实现的幂等行为；
- registered peer、soft claim、可选 task lease 与独立 worktree guard；
- 不同 Host 通过同一 registry/Goal 读取并受控写回；
- 用于开发和 qualification 的 staged file/NoKV/PostgreSQL candidate；它们不自动获得 runtime
  authority。

当前不应承诺：

- 多台设备自动共享一个在线 authority；
- 离线设备可以新 claim、complete、续 lease 或执行 protected write；
- 把项目目录放进同步盘就得到一致的分布式状态；
- NoKV、数据库或 IM 自动替代 LoopX lifecycle owner。

如果要实现跨设备控制面，应保留一个 canonical LoopX authority，要求 revision-bound、幂等的受控
命令与 receipt，并把消息传递、上下文记忆和状态 authority 分开。直到 shared mode 经过独立
promotion、运行时接线和发布验证，Dev Book 只教授这些协议边界，不提供"云端模式已可用"的操作
步骤。

## 历史产物的三层完整性

LoopX 可以让研究、验证和决策产物不被静默改写，但这不等于旧结论永远适用于当前状态。

判断一条历史 evidence 能否进入当前决策，要分三层：

| 层次 | 需要回答 | 典型检查 |
| --- | --- | --- |
| Lineage integrity | 这条产物来自谁、何时生成，是否被追加、纠正或 supersede？ | `event_id`、`run_id`、producer、recorded revision、append-only refs |
| Current applicability | 它支持的输入、范围和外部事实与当前问题仍一致吗？ | commit、target key、source revision、time window、Gate scope、fresh readback |
| Supersession | 后来的 evidence 或决定是否替代、收窄或撤销了它？ | `supersedes`/`superseded_by`、compensating event、newer decision、replan delta |

因此，append-only lineage 解决的是**防止历史被无声重写**，它不自动证明**旧结论仍然新鲜**。

研究笔记、测试结果或 PR readback 要进入当前 frontier，至少应带稳定 join key，并在 material input
变化后重新验证 applicability。

无法确认时，把它标为 historical observation 或 stale evidence，不要删除历史，也不要继续把它当作
current authority。这一点也是 09:52 那两条 lineage 的处置依据：两条都保留，但只有与当前 source
revision 匹配的那一条可以进入本轮决策。

[`agent_scoped_evidence_ledger_v0`](https://github.com/loopx-project/loopx/blob/main/docs/reference/protocols/agent-scoped-evidence-ledger-v0.md)
提供 bounded、read-only 的 Agent chronology，适合 replan 和 handoff；它不替代 current status、
quota decision 或外部系统 readback。

## Replay 不保留旧结论

Replay 的目标是从有序事实重建当前状态，它不负责永久保留旧判断。

假设事件流记录：

```text
todo_added(T1)
todo_claimed(T1, agent-a)
gate_added(G1, scope=public_claim:action:homepage)
run_recorded(R1, tests_passed_at=commit-a)
```

随后 Git 前进到 `commit-b`，用户又改变首页方向。Replay 仍能说明 R1 和 G1 曾经存在，但不会自动
证明：

- R1 对 `commit-b` 仍有效；
- G1 已覆盖新的首页方案；
- agent-a 仍在当前 workspace 执行；
- 当前 frontier 可以继续发布。

恢复者必须把 replay 后的 project facts 与新鲜环境重新组合。这也解释了为什么 09:41 那个问题的
答案只能是"去读 source"，而不能是"去读那个最方便的页面"。

## Projection gap 是控制面故障

当 source 与读模型不一致时，不能任选一个看起来方便的表面继续：

- event 中有 open Todo，status 却没有；
- Gate 已解决，quota 仍显示 operator wait；
- active state 有 Next Action，但对应 Todo 不存在；
- dashboard 显示 runnable，workspace guard 却指向另一个 worktree。

这些情况属于 **projection gap**。正确动作是：

1. 找到 authoritative source；
2. 判断是 source 写入失败、projection stale、migration drift 还是 external observation 过期；
3. 通过原 lifecycle/writeback 路径修复；
4. 重算 projection 并验证 source revision；
5. 在修复前不运行依赖该状态的交付。

手工把多个展示面改成一致，只会隐藏问题。开头那个 09:43 的场景之所以发生，正是因为 Agent B
跳过了第一步，直接在第 5 步之前就开始工作。

## 代价与边界

这套分离换来的是"事实只有一个所有者"，代价需要说清楚，因为它们是读者判断"什么时候不该指望投影"的依据。

**代价一：投影是最终一致的，可能滞后。** 任何一次 source 写入之后，都存在一个窗口，投影仍显示
旧值。这个窗口可能只有几毫秒，也可能像 09:43 那样是 31 分钟，取决于谁在什么时候重算。系统不会
因此停止工作，但**读投影必须带 freshness 判断**。

**代价二：读投影不能替代重新决策。** 投影面向的是"给人快速阅读"，它已经做了 summarize、rank
和 compress。压缩掉的细节可能正是本轮决策需要的——例如某个 Todo 的 `resume_when` 条件，或者
一条 evidence 绑定的 revision。拿到一个 status 摘要之后，仍然需要回到 source 做一次决策读取。

**代价三：任何写入都必须走 write_apis。** `loopx todo`、`loopx refresh-state`、
`loopx operator-gate`、`loopx reward` 和 `loopx quota spend-slot` 是协议列出的写入路径。绕过它们
直接改投影，产生的是 09:52 那种分叉：两条 lineage 都自称是 T1 的完成证据，而系统没有依据裁决
哪一条合法。

**代价四：每次恢复都多一次读取。** 恢复者不能只读一个页面就动手，至少要读 source 并检查外部
fact 的 freshness。这是真实成本，也是要求一在实现上的价格。

**边界一：投影只描述它重算时的 source。** 一个 projection 的 `generated_at` 早于最近的 lifecycle
event 时，它描述的是过去。判断一条投影能否用于当前决策，看的是它是否携带足够的 source refs，
以及 source 是否已经前进。

这也意味着"投影刚生成"和"事实刚发生"是两件事。重算一次投影可以让它变新，但不会让底层
transition 重新发生，也不会撤销已经落地的写入。

**边界二：source owner 只在协议覆盖的范围内是权威。** Git、CI、PR 和 cloud resource 的 authority
在外部系统手里，LoopX 只保存 bounded readback。要求这些系统"同步"到 LoopX 并非这套设计的目标。

反过来说，LoopX 的 canonical state 也不能凭一份旧 readback 去断言外部系统现在的状态。两边各自
持有自己的事实，交汇点是 revision 与 fresh readback。

**边界三：`local_state_write_correctness_v0` 是 Draft，并非已启用的保证。** 它的 hard idempotency、
统一 CAS 和 lease conflict enforcement 按 writer 分阶段 promotion。把 Draft 当作所有 writer 已经
遵守的合同，会得出比实际更强的结论。

## 具名失败：这些规则拦住了什么

**一个可写的投影就是一个缺陷。** 打开 `loopx --format json status --include-task-graph`，检查
返回对象里的 `truth_contract`：

```text
expected: projection_is_writable = false, write_api = false
actual:   projection_is_writable = true
          -> 某个 projection builder 声称了写权限，先修复它再继续
```

这两个字段的消费者不止文档：

- `examples/long-horizon-agent-state-protocol-smoke.py` 直接断言协议文本包含
  `"projection_is_writable": false`；
- `examples/project/goal-channel-status-export-smoke.py` 断言导出 payload 的
  `truth_contract["projection_is_writable"]` 为 `False`。

任何一个失败都意味着某个 projection builder 开始声称写权限，而这类缺陷不会自己消失：一旦有
消费者按可写处理，分叉就从这一刻开始。

**直接编辑 Markdown 不产生 transition。** 把 `ACTIVE_GOAL_STATE.md` 里的复选框改成 `[x]` 之后，
Todo 的 status 不会因此改变，因为 canonical 写入路径没有走过。合法做法是走 `loopx todo` 的
lifecycle command，让它留下 Todo id、producer 和 completion evidence。

区别不在"谁写的"，而在"有没有留下 lineage"：手工编辑留下的是一次无人负责的字节改动，lifecycle
command 留下的是可被 status、review packet 和下一轮 quota 复用的同一个事实。

**stale 投影不能提供当前事实。** 上面 09:43 的场景检验的是同一条规则：一张卡片说 T1 pending，
同时 event 说 T1 已完成，此时 Agent B 必须停下来读 source，而不该选一个更方便的答案继续。

这条规则对人也成立。operator 在 dashboard 上看到的 open gate 数量可能落后于 `loopx operator-gate`
的真实状态；用它来判断"现在需不需要人介入"，读到的可能是一个已经解决的 Gate。

## 如何决定一个新字段放在哪里

新增字段前按顺序问：

1. 它描述长期配置、身份或路由吗？放 registry。
2. 它描述一次 lifecycle transition 吗？放 event。
3. 它描述一轮观察或交付吗？放 run snapshot/evidence。
4. 它只服务某个读者视角吗？从现有事实生成 projection。
5. 它属于 GitHub、CI 或其他系统吗？保留外部 authority，只存 bounded readback。
6. 它是 Issue-Fix、Explore 等领域专属结果吗？放 Domain State，不要塞进通用 Todo/Quota。

如果一个字段同时想承担配置、事件、展示和权限四种责任，通常说明协议边界还没有拆清。

## 协议阅读入口

本章拥有概念顺序，不复制完整 schema。需要修改 LoopX 状态行为时，优先阅读：

- [`event_sourced_state_contract_v0`](https://github.com/loopx-project/loopx/blob/main/docs/reference/protocols/event-sourced-state-contract-v0.md)：
  event、replay、ordering、privacy；
- [`active_state_structured_projection_v0`](https://github.com/loopx-project/loopx/blob/main/docs/reference/protocols/active-state-structured-projection-v0.md)：
  Markdown workbench 的 typed read model；
- [`task_graph_projection_v0`](https://github.com/loopx-project/loopx/blob/main/docs/reference/protocols/task-graph-projection-v0.md)：
  Todo、Gate、evidence 与 handoff 的只读关系图；
- [`long_horizon_agent_state_protocol_v0`](https://github.com/loopx-project/loopx/blob/main/docs/reference/protocols/long-horizon-agent-state-protocol-v0.md)：
  长程工作中的 source/projection、并发 Agent 与 lifecycle；
- [`agent_scoped_evidence_ledger_v0`](https://github.com/loopx-project/loopx/blob/main/docs/reference/protocols/agent-scoped-evidence-ledger-v0.md)：
  replan/handoff 前的 Agent-scoped chronological read model；
- [Status Data Contract](https://github.com/loopx-project/loopx/blob/main/docs/status-data-contract.md)：
  operator 与 Agent 读取的聚合表面。

如果你准备修改 registry、event、Domain State、replay 或 projection builder，继续阅读
[Control-Plane Course 第 4 讲](/loopx/docs/development/control-plane-course/04-state-substrate/)。
它从 Issue-Fix、Auto ML 与 Auto Research 的事实归属进入源码路径和实验；本章继续作为外部
开发者的概念入口。

## 不变式

读完这一章，你应该能带走六句可以自己检查的话。

1. **一个投影永远不能授予写权限。** 打开任意一份 projection JSON，`truth_contract` 里的
   `projection_is_writable` 必须是 `false`。它变成 `true` 就是缺陷。
2. **source 和投影不一致时，答案是 source。** 卡片、dashboard 和 review packet 都不担任裁决者；
   读到分歧时，先找 authoritative source，再决定动作。
3. **投影可能滞后，读投影必须带 freshness 判断。** 一份 `generated_at` 早于最近 lifecycle event
   的投影描述的是过去，不能当作当前事实。
4. **任何写入都必须经过 write_apis。** 直接改投影会产生第二条 lineage，而系统没有依据裁决它的合法性。
5. **Append-only 只保证历史不被无声改写，不保证旧结论仍然新鲜。** Lineage integrity、current
   applicability 和 supersession 是三次独立检查。
6. **恢复是 replay 加一次新鲜检查。** 只做 replay 会得到一份正确的历史，和一份过期的现在。

这六条回答的是同一个问题：**当上下文被冲掉之后，"发生过什么"凭什么还能被回答？** 本章给的是
LoopX 在状态归属上的答案。下一章在这套底座上建立工作图：谁可以做什么、什么条件阻塞它，以及
一项工作如何合法地继续、交接或结束。
