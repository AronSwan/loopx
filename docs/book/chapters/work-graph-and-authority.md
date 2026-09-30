# 工作图、权限与 Peer 协作

本章挂在**要求三：唯一可问责的行动者**上。一条 Todo 可以同时被多个 peer 看见，但在任何一个时刻，只应有一个执行实例有权推进它。下面的问题就从这条要求被破坏开始。

## 从一个坏的结局开始

看一条时间线。它不需要任何一方说谎：

```text
09:00  agent-a 选中 Todo T，acquire 到 lease，version=1，ttl=600s。
09:00  agent-a 开始改代码，改到一半去跑一个长测试。
09:10  agent-a 的 renew 失败：宿主进程被抢占，或者网络抖了一下。
09:10  它没有重试成功，但进程还活着，手里的判断还是"我持有 T"。
09:11  lease 过期。agent-b 看到 T 无人持有，acquire 成功，version=2。
09:14  agent-b 改完，写回 version=2，验证通过，quota 记一次。
09:20  agent-a 的长测试终于回来，它拿着 version=1 的判断写回。
09:20  agent-a 的写回也成功了。
```

09:14 和 09:20 两次写回都返回成功。后者覆盖前者，T 上现在只有 agent-a 的结果，agent-b 的工作从状态里消失。quota 却老老实实记了两次。

这就是**丢失更新（lost update）**，也是**过期持有者（stale holder）**。它比"两个 agent 同时写坏了文件"更难发现：没有任何一方报错，状态自洽，账目自洽，只有一份真实完成的工作不见了。等到有人问"agent-b 那天做了什么"，读模型回答不了。

## 为什么"claim 一下就该没人来抢"解决不了这个问题

直觉反应是：开工前 claim 这条 Todo，别人看到 claimed 就不碰了。

Claim 说的是"这个 peer 当前负责这项工作"，它帮 quota 和其他 Agent 避免重复领取。它**不证明持有者还活着**，也不证明持有者还在正确的 worktree 里。上面 09:10 的 agent-a 进程还活着、claim 还挂在自己名下，可它手里的判断已经过期十分钟了。

于是那个自然的补丁——"写回前先检查一下自己是不是还持有"——也救不了场。检查和写回是两次独立操作，中间隔着一次进程调度；如果检查通过之后、写入落盘之前 lease 被转移，你检查得再勤也只是把窗口收窄，没有关掉。

真正的难点是：**一次写入要么由当前持有权威的执行实例发出，要么根本不该落盘**。判断不能发生在写入之前，只能发生在写入提交的那一瞬。这就要求 Todo 不只是彼此独立的条目，而是一张能表达"谁在推进我、我推进谁、谁取代了我"的图。

## Goal、Acceptance 与 per-Agent Vision

Goal、Acceptance 与 per-Agent Vision 服务不同层次，同时在场时才拼出"该由谁推进"的完整依据：

| 对象 | 归属 | 回答的问题 |
| --- | --- | --- |
| Goal | 项目 | 最终要达成什么结果 |
| Acceptance | Goal 或明确的交付阶段 | 哪些可观察证据足以判断完成 |
| Agent Vision | `agent_id` | 这个 peer 当前承担什么方向、scope、acceptance summary 与 replan trigger |

Vision 超出泛化产品愿景，但本身属于 bounded 状态，而不是自由格式 scratchpad。[`goal_vision_replan_contract_v0`](https://github.com/huangruiteng/loopx/blob/main/docs/reference/protocols/goal-vision-replan-contract-v0.md) 将它定义为 bounded、per-Agent 的执行路由状态，可以包含 `role_scope`、`vision_summary`、`acceptance_summary`、`advancement_policy`、`replan_trigger_summary` 与最近一次 bounded patch。当一个 peer 产生 material progress 时，需要记录 Vision 是否 patched、unchanged with reason、retired 或 superseded；否则后续 quota 可能看到 `vision_checkpoint_missing`，要求先补齐 replan 证据，而不是静默继续。

这能防止两种漂移：Todo 队列一直繁忙但没有推进 Goal acceptance；多个 peer 围绕同一 Goal 工作，却各自维护一套不可见的"我以为下一步是……"。

## 设计：工作图与它的五种关系

Todo 是工作图的节点，也是最小可执行或等待单元。它可以承载 role 与 priority、`task_class` 与 `action_kind`、dependency / resume condition、required capability 与 write scope、claim / lease / continuation policy，以及 Gate、evidence、successor 和 supersession refs。它比完整项目计划小得多，也不该只是 prompt 里的一条提醒。

节点之间的边表达"一个节点为什么影响另一个"，[`task_graph_projection_v0`](https://github.com/huangruiteng/loopx/blob/main/docs/reference/protocols/task-graph-projection-v0.md) 允许的 `relation` 值里，起决定作用的是这几种：

```text
blocks        A 未闭合前，B 无法成为合法候选
validates     B 产出的证据，决定 A 是否真的完成
repairs       A 失败后，B 负责诊断并恢复
hands_off_to  A 结束后，B 接手，且保持 unclaimed 直到有人领取
supersedes    B 取代 A，同时保留 lineage
```

每条边都要写 `from_node_id`、`to_node_id`、`relation` 和一段 compact public-safe 的 `reason`。关键在于最后一句约束：**边不授予运行命令或改动状态的权限**。它能解释"谁在推进 T"，也能让 review 看清依赖，但不能替代后面几节讲的 claim、lease 与 fence。

`repairs`、`audits` 与 `continues` 属于 lineage 关系而非 lifecycle 命令，它们从既有 run history、todo/gate metadata 与 compact blocker 或 validation writeback 推导出来；`repairs` 表示一个 repair/replan 节点打算恢复某条工作通道，`audits` 表示 compact run evidence 复核或限定某条通道。把这几种关系与"谁有权写"混为一谈，正是开头 09:20 那个 bug 的来源。

这几种关系是本章其余部分的前提。没有它们，"谁在推进 T"只能从聊天记录里猜。

### 五类常见工作

| 类型 | 谁负责 | 典型语义 |
| --- | --- | --- |
| `advancement_task` | Agent | 当前可交付的实现、文档、分析或修复 |
| `user_gate` | User/controller | 缺少决定时，相关 action 不可合法继续 |
| `user_action` | User/controller | 需要用户处理，但不自动阻塞独立 Agent work |
| `continuous_monitor` | Agent/Host | 按 cadence 观察外部条件，仅 material change 时推进 |
| `blocker` | Agent/controller | 当前缺少可执行条件，需要明确恢复路径 |

Todo text 可以供人阅读；机器路由不能只从自然语言猜任务类型。

### Frontier 是算出来的，不能只靠列出 open Todo

**Frontier** 是当前满足全部前置条件的候选集合：

```text
open todos
  -> dependency and resume
  -> decision scope and authority
  -> agent claim and lifecycle authority
  -> host capability
  -> workspace and write scope
  -> freshness and evidence
  -> current frontier
```

因此：open 不等于 runnable；priority 不等于绕过 Gate；claimed 不等于仍可执行；capability available 不等于获得 authority；Todo done 不等于 Goal complete。

[`task_graph_projection_v0`](https://github.com/huangruiteng/loopx/blob/main/docs/reference/protocols/task-graph-projection-v0.md) 可以把这些关系渲染成图，但图本身仍是 read-only projection。真正的状态变化继续通过 Todo、Gate、refresh 与 event protocols。

## 谁有权写：claim、lease 与 lifecycle authority

三个概念经常被错误合并，上面那条时间线正是合并它们的后果。

### Claim：软性工作归属

Claim 帮助避免重复领取，它只是协作信号。

### Lease：一次执行的占用凭证

Lease 用于需要 TTL、renew、transfer、version/CAS 或幂等 identity 的显式互斥场景。它适合高成本或有副作用的执行占用，但不自动替代 Todo lifecycle。一个实现可以有 claim 而没有 lease；可以有 lease 却因为 Gate 仍不能运行；可以在 lease 到期后重新分配；也可以在 handoff 时不传递旧 lease。

### Lifecycle Authority：谁能改变状态

Claim 回答谁计划执行；lifecycle authority 回答谁有权 complete、supersede、reassign 或执行特殊 override。显式委托某个 peer 完成一次 lifecycle mutation，不会把它升级为全局 leader。

### Fence：写在提交那一刻才校验

`task_lease_v0` 里真正拦住 09:20 那次写回的，是 acquire key 与返回 version 组成的 **execution-instance fence**。一份 lifecycle writer 不能只凭 `agent_id` 放行，因为多个宿主进程可能共用同一个注册 peer 身份。只要存在有效 lease，`todo complete` 与 `todo supersede` 就必须同时带上 idempotency key 和 expected version，并在 canonical writeback 全程持有 lease lock；缺失、过期或对不上的 fence 会被拒绝，而且是在创建 successor 之前就拒绝。

Release 不删除记录，而是留下一条 inactive 的 terminal record。这样下一次 acquire 会推进 per-todo version 与 `lease_epoch`，而不会把 version 重新变成 1。下面这条测试把整个序列跑了一遍：

```bash
uv run --extra test pytest tests/control_plane/test_canonical_lease_acquire.py -q
```

它断言 acquire 后 `lease.version == lease.lease_epoch == 1`，用同一 `--idempotency-key` 重放会返回 `idempotent: true` 且 `acquired: false`，重放结果的 `lease` 与原 receipt 完全一致。release 之后再用同一个 key 去 acquire，会被拒成 `idempotency_key_reuse`；换一个 key 重新 acquire，version 变 3 而 `lease_epoch` 变 2。测试最后确认 lease 文件与 state 文件都不存在残留，即"放行"和"清理"是同一件事的两面。

## 权限边界：谁被拒绝，依据是什么

权限由几条正交的轴共同决定，而单一开关表达不了它。把任意两条合并，都会让"能不能动手"这个判断失去依据。

| 边界 | 主要问题 | 不能证明 |
| --- | --- | --- |
| Decision scope | 是否获得这项动作需要的人类/控制器决定 | Host 是否能执行 |
| Capability gate | 当前 Host/runtime 是否具备所需能力 | 是否获得用户授权 |
| Workspace guard | 当前 Agent 是否位于正确 repository/worktree/write scope | 业务结果是否正确 |
| Write fence | 这次写入是否来自当前持有权威的执行实例 | 业务结果是否正确 |

Decision scope 来自 [`decision_scope_v0`](https://github.com/huangruiteng/loopx/blob/main/docs/reference/protocols/decision-scope-v0.md)，它要求 user/controller decision 说明 `kind`、`granularity`、`scope_key`，以及可选 expiry、decision id 与 reason。Agent Todo 可以声明 `required_decision_scopes`，只有 unresolved Gate 的 scope 覆盖当前 action 需求时，它才阻塞这项工作：

```text
Gate G1
  decision_scope = public_claim:action:bilingual_homepage

Todo A
  required_decision_scopes = public_claim:action:bilingual_homepage

Todo B
  write internal link checker
  required_decision_scopes = none
```

G1 阻塞 A，不阻塞 B。如果 projection 只有"等待用户确认"这句 prose，却没有 scope relation，正确动作是修复 projection 或询问具体决定，不能默认给 Agent authority，也不能默认冻结整个 Goal。`user_action` 更不能冒充 authority：用户看到了提醒，不等于批准了 production、publish 或 private read。

Workspace guard 是另一条独立的拒绝依据。当 selected Todo 要写 repository state 时，执行者必须位于 origin 与 `task_repository` 匹配的 linked independent worktree；匹配 repository 只是必要条件，canonical checkout 仍可能被拒绝。`task_repository` 是不含凭据的 repository identity，它选择 workspace isolation 的目标仓库，**不授予写权限**，也不替代 claim、lease、Goal boundary 或 repository maintainer policy。

### 拒绝要能说清理由

边界之所以有用，一半在于它拒绝，一半在于它**说明为什么拒绝**。当 legacy coordination writer 被围栏挡住时，错误带着具体字段的 remediation，而非一句笼统的"写入失败"：

```text
legacy coordination writer is fenced; use the promoted canonical authority
(file_v0) for goal goal-a; fence fence-a; the primary record was not changed
```

`tests/control_plane/test_legacy_coordination_writer_fence.py` 逐条钉住了这个形状：无围栏时保持默认行为且不启动 TypeScript；围栏存在时抛出的异常 `code == "legacy_coordination_writer_fenced"`，payload 里带 `reason_code`、`authority_mode`、`fence_id`，消息末尾固定是 `the primary record was not changed`。测试还断言同一句 remediation 在 Python 与 TypeScript 两侧渲染完全一致，并覆盖 `authority_mode` 缺失时的 `unknown_fail_closed` 行为。缺了 `fence_id` 这类字段不会退化成含糊文案，而是走 fail closed。

## 多 peer 协作：ownership、evidence 与 review 责任的保持

LoopX 的 live multi-agent 模型是 **equal peer**。Agent id 是工作身份，它证明不了 Host 表面，也证明不了组织层级；`codex-*` 命名不能单独证明任务运行在 Codex App 还是 CLI。这条边界决定了协作的默认形态：完成一项工作**不会**自动授予整个 Goal 的后续工作，默认 continuation 是 `independent_handoff`，即后续保持 unclaimed，任何合格 peer 都可接手，除非显式指派。

Handoff 传递 bounded state references，而非 transcript 副本。一个 bounded handoff 至少应让接手者重建：Goal、Todo 与 stop condition；current revision/workspace；Gate、capability 与 authority boundary；evidence/material references 及 freshness；next action 与 validation；以及哪些内容被截断或留在 private store。

### 接手者必须重新校验

Handoff 不转移权限。旧 Agent 的 receipt 不会自动授予新 Agent source permission，旧 workspace observation 也不能证明当前环境未变化。接手者仍要重新运行 current guard。

`tests/control_plane/test_canonical_lease_lifecycle.py` 把这条规则变成可执行的：测试故意在 legacy 路径下放一份与 provider 矛盾的 lease 文件（`version: 99`，owner 为 `stale-agent`），然后要求所有 `task-lease` 命令都只能读 provider。transfer 之后 `lease.owner` 变 `agent-b`，version 从 3 变 4，`lease_epoch` 从 7 变 8。此时如果 agent-a 拿着旧 proof 去 release，会被拒成 `version_mismatch`，而且 provider head 一字未变。测试结尾断言那份 legacy 文件字节未改动、state 文件始终不存在。

### 同一份证据只该有一个来源

多个 peer 并行时，最容易被悄悄破坏的是 evidence 的归属。每个实现 Todo 写回 exact revision、validation 和 completion evidence；下游按 dependency 与 fresh readback 进入 frontier，而非从"它们应该完成了"这句话推断 ready。

跨仓库依赖也必须带 repository identity。`resume_when=pr_merged:#123` 只在 Todo 的 GitHub `task_repository` 与 merge event repository 匹配时成立；跨仓库应使用 `pr_merged:owner/repo#123`。缺少 repository identity 时，当前实现会 fail closed，而不会按相同 PR 编号猜测。

### 哪些工作不适合多 peer

| 工作类型 | 并行策略 |
| --- | --- |
| 研究、源码定位、triage、只读 review | 可以 fan-out；结果以 bounded evidence 回收 |
| 不同 repository 的实现 | 每个 Todo 绑定自己的 `task_repository` 与 worktree |
| 同一 repository、disjoint write scopes | 仅在 scope 可证明不重叠且验证可独立时并行 |
| 同一文件或共享 schema/state machine | 默认串行，或先拆 owner/seam 后再并行 |
| 外部 effect、merge、publish | 仍由 scoped Gate 和 repository policy 决定 |

最后一行值得强调：当工作本身是强串行依赖的——每一步的输入是上一步的输出，或者多方共享同一个 state machine——lease 和 fence 只能保证"没有两次写入同时成功"，不能替你创造并行度。把这类工作拆给多个 peer，得到的是一串等待和一个更长的关键路径。Claim 是软 owner，并非锁；只有确切存在并发写冲突的 Host 才需要可选 `task_lease_v0`。

### 等待之后如何恢复

工作图不仅要表达"先做 A，再做 B"，还要表达等待结束后这件事怎么重新进入决策。Resume condition 是一条机器可读的条件：

```text
todo_done:<todo-id>
pr_merged:<pr-id>
capacity_available:<capability>
monitor_changed:<monitor-todo-id>
```

条件满足不等于原 Todo 立刻可运行。旧任务可能已经 stale，需要 successor replan —— 这正是为什么 resume 必须写成结构化条件，而不是"等它好了再说"。

当前 Todo 完成后，下一项工作的身份有四种合法表达：

- **Successor**：明确下一项有身份的工作，让"下一步"进入 durable graph，而不是留在完成者的聊天里；
- **Supersede**：方向改变时用新 Todo 取代旧 Todo，同时保留 lineage，不把已失效工作伪装成 done；
- **No-follow-up**：确实不需要后继时，记录为什么 acceptance 已闭合或为什么后续不属于当前 Goal，结构化记录比"看起来做完了"更可审计；
- **Continuation policy**：`same_agent_non_delivery` 让同一 peer 继续一项明确、非独立交付的后续，`independent_handoff` 让后续保持 unclaimed。

### 一个跨仓库的目标

同一 release 需要修改四个 repository 时，仍然只有一个 Goal：

```text
Goal: ship-cross-repo-release
├── Todo A -> repo-a -> agent-a -> worktree-a
├── Todo B -> repo-b -> agent-b -> worktree-b
├── Todo C -> repo-c -> agent-c -> worktree-c
└── Todo D -> integration verification -> waits for A/B/C evidence
```

A、B、C 可以并行，但 D 不能从自然语言"它们应该完成了"推断 ready。每个实现 Todo 写回 exact revision、validation 和 completion evidence；D 再按 dependency 与 fresh readback 进入 frontier。

## 代价与边界：这套设计放弃了什么

上面每条规则都换来一个性质，代价需要说清楚。

**代价一：lease 需要续期，续期失败会中断工作。** 09:10 那次 renew 失败，本身就是设计在起作用：执行实例没能证明自己仍然持有权威，于是它的后续写入会被拒绝。对长任务而言，这意味着 TTL 必须按最坏情况设置。TTL 定得太短，一个正常的编译或长测试就会把持有者挤出；定得太长，一次崩溃留下的空窗会让别的 peer 干等。`test_canonical_lease_renew.py` 里 renew 一次只推进一次 version（1→2→3→4），`lease_epoch` 保持不变；这说明续期是"延长同一次执行"，重新 acquire 才是"换一次执行"。

**代价二：写入可能被拒绝，调用方必须处理这个拒绝。** 围栏不是建议，它会让一次看起来正常的写回失败。调用方不能把 `version_mismatch` 当成瞬时错误去重试同一个 key——`test_canonical_lease_acquire.py` 断言同一 `--idempotency-key` 在 release 之后复用会被拒成 `idempotency_key_reuse`，Todo 已 done 时再 acquire 会被拒成 `todo_not_open`。正确的处理是重新读取当前 version、重新 acquire、重新验证，而不是憋着劲重放。

**代价三：围栏规则会扩到写回路径的其他角落。** `tests/control_plane/test_split_root_todo_writeback_fence.py` 记录的就是这件事：当 `--runtime-root` 与 registry root 分离时，围栏必须落在**生效的那个 root** 上，并且在真正开始收集数据之前就拒绝。它断言被围栏的 writeback 让 state 字节不变，并把 `local_authority_todo_list_unavailable` 与 `legacy_fallback_used: false` 一起返回。这类错误会出现在 monitor poll、Turn repair 与 validated completion 等多条路径上。

**边界一：claim 与 lease 都证明不了"持有者还活着"。** 它们说明的是写入是否有权落盘，而非持有者的进程是否健康、上下文是否还新鲜。一个持有有效 lease 的 agent 仍可能基于一小时前的判断在推进。

**边界二：工作图是只读投影。** `task_graph_projection_v0` 渲染出的关系图不能用来改状态；能看到一条边不等于可以据此改动 Todo。

**边界三：当前不承诺自动编排。** 产品不承诺"给一个 root 目录就自动并行四个 Goal"，也不承诺云端 coordinator 自动选择设备并 claim。bounded multi-agent orchestration 可以启用 child-agent planning，但 peer identity、claim、workspace guard、Gate 和 writeback 仍逐 Todo 生效；跨设备在线 authority 仍属于 Draft 设计边界。

## 具名失败：这些约束拦住了什么

抽象地谈"并发安全"没有说服力。下面四个场景各有对应测试，可以直接运行。

**过期持有者写回被拒。** 这正是开头 09:20 的那一刻。`test_canonical_lease_lifecycle.py` 里 transfer 之后旧持有者用旧 version 去 release，得到 `version_mismatch`，并且断言 provider head 与 transfer 之后完全一致。丢失更新不再是"两份工作静默合并"，而是一次明确的拒绝。

**围栏挡住旧写入者。** `test_legacy_coordination_writer_fence.py` 锁定 `legacy_coordination_writer_fenced`：写入被拦下，payload 里带着应该改走哪个 canonical authority 和哪个 `fence_id`，末句声明 primary record 未被修改。它还断言 `--runtime-root` 覆盖下的围栏能挡住 legacy writer，且被围栏时事务体根本不执行。

**围栏必须落在生效的 root 上。** `test_split_root_todo_writeback_fence.py` 覆盖分离 root 的场景：registry source 被围栏时，即使通过 override 走同一份 source state，原围栏依然生效，state 字节不变；而未被围栏的 override 可以正常写出 receipt。缺了这条，围栏会变成可以绕开的摆设。

**跨仓库 identity 缺失时 fail closed。** `pr_merged:#123` 缺少 repository 前缀时，实现不会按编号猜仓库，而是直接拒绝。这条防的是"两条 PR 恰好编号相同"这种极难排查的错配。

对应测试：`tests/control_plane/test_canonical_lease_acquire.py`、`tests/control_plane/test_canonical_lease_renew.py`、`tests/control_plane/test_canonical_lease_lifecycle.py`、`tests/control_plane/test_legacy_coordination_writer_fence.py`、`tests/control_plane/test_split_root_todo_writeback_fence.py`。这些断言本身就充当这套设计的可执行证据，而远不止是文档插图。

## 协议阅读入口

需要修改工作图或权限语义时，优先按问题读取协议：

- [`task_graph_projection_v0`](https://github.com/huangruiteng/loopx/blob/main/docs/reference/protocols/task-graph-projection-v0.md)：依赖、Gate、validation、repair 与 handoff 的只读图；
- [`decision_scope_v0`](https://github.com/huangruiteng/loopx/blob/main/docs/reference/protocols/decision-scope-v0.md)：Gate 覆盖关系与 fail-closed 行为；
- [`goal_vision_replan_contract_v0`](https://github.com/huangruiteng/loopx/blob/main/docs/reference/protocols/goal-vision-replan-contract-v0.md)：per-Agent Vision、checkpoint 与 replan；
- [`local_state_write_correctness_v0`](https://github.com/huangruiteng/loopx/blob/main/docs/reference/protocols/local-state-write-correctness-v0.md)：`write_intent`、revision conflict 与 lease conflict 的语义；
- [Peer Agent Runtime v1](https://github.com/huangruiteng/loopx/blob/main/docs/reference/protocols/peer-agent-runtime-v1.md)：equal peer、continuation 与 identity；
- [Host Integration Surface](https://github.com/huangruiteng/loopx/blob/main/docs/reference/protocols/host-integration-surface-v0.md)：claim、execution-instance fence、optional lease 与 Host 边界。

如果改动涉及 equal peer、lifecycle authority、handoff、dependency 或 successor，继续阅读 [Control-Plane Course 第 5 讲](/loopx/docs/development/control-plane-course/05-work-graph-and-peers/)。课程提供组合 case 与源码领读；本章保留外部贡献者需要的工作图和权限模型。

## 当 Goal 结束：多查几步

单条 Todo 离开 frontier 和整个 Goal 终止是两件事。Goal terminal closure 还要额外确认：

- acceptance 是否满足；
- 是否存在 unresolved Gate；
- 是否有 due monitor、pending external effect 或 stale readback；
- 是否有 successor、replan obligation 或 acceptance gap；
- 是否有 retryable postcondition；
- 是否明确记录 no-follow-up。

这六项的共性在于：它们都可能被"Todo 都 done 了"这句话掩盖。

## 不变式

读完这一章，你应该能带走六句可以自己检查的话。

1. **一条 Todo 在任一时刻只有一个持有权威的执行实例。** 见到两份都"成功"的写回指向同一结果，那是 fence 失效，而非可接受的并发结果。
2. **写入的合法性在提交那一刻判定，不在准备阶段判定。** 拿旧 version 的写回必须被拒绝，而非先写后纠正。
3. **重放安全不等于可以复用 key。** 同一个 `idempotency_key` 重放同一逻辑写入是幂等的；换了语义再复用同一个 key，会被拒成 `idempotency_key_reuse`。
4. **续期失败是合法结局。** 持有者没能证明自己仍持有权威时中断工作，比让过期持有者写完更可接受；TTL 因此要按最坏任务时长设置。
5. **handoff 传递引用，不传递权限。** 接手者必须重跑 current guard，旧 receipt 不授予新 Agent 任何 source permission。
6. **离开 active frontier 只有三种合法方式。** completed with evidence、superseded with lineage、blocked/deferred with resume contract；"从列表里删掉"不构成生命周期。

这六条回答的是同一个问题：**当同一个目标有多个 peer 同时在场、而没人能实时协调时，系统凭什么知道此刻该由谁写？** 本章给的是 LoopX 在工作图尺度上的答案。下一章把答案编译成一次受治理的 Turn：谁应行动、谁应等待、何时允许 writeback 与 spend。
