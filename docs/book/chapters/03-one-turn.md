# 一轮受治理的工作

本章回答一个问题：一轮 Agent 工作从"该不该动"到"可以算做完"，中间发生了什么，以及为什么这些步骤的**顺序本身**就是安全边界。

## 从一个坏的结局开始

先看一个场景。它在没有治理的 agent 系统里很常见：

```text
09:00  Agent 第 40 轮。读 Todo 列表，选中一条，开始改文件。
09:04  改完了。回执已经写下：代码改动 + 验证输出。
09:04  机器重启（或进程被杀、或用户按停止、或模型超时）。
09:06  Agent 重启，读状态：Todo 仍是 pending，看不到已完成工作的证据。
09:06  它判断这轮没做过，于是重做一遍。
09:09  第二轮也"成功"了。quota 收了两次，Todo 上出现两条指向同一结果的记录。
```

这个过程里没有任何一步在说谎。Agent 没有虚报，回执真的写了，Todo 状态当时也确实是对的。

问题在于**它们没有一个共同的提交点**：回执落在会消失的地方，收费记在不会消失的地方，而"这轮完成了"这个判断，在重启后的读模型里重建不出来。

这就是长程运行和一次会话的根本差别。会话里，"我说过"约等于"发生过"，因为上下文还在。长程里，**上下文是会被冲掉的工作内存**，"发生过什么"必须由一个不依赖上下文的机制回答。

## 为什么"重试前先检查"不足以解决

自然的反应是：让它重试前先检查一下。但检查本身要读状态，而状态可能正好停在"回执写了、收费没写"的中间，这时两个选择都是错的：

- **跳过**：改动可能真的落盘了，但没被记录，于是它永远无法被验收、交接或审计；
- **重做**：可能对同一份文件改两遍、对同一个外部资源请求两次、对同一份预算扣两次。

真正的难点在于**能不能判断出它当时做到哪一步**。判断不出，重试的每个分支都只能靠猜。

所以设计目标是让**每次失败停在一个可辨识的位置**。失败的数量并不重要。

## 尺度一：一轮内部的事务

### 七个阶段，只承认合法前缀

LoopX 把一轮拆成七个有序阶段，写在一份可校验的契约里：

```text
host_execute → typed_result → validation
             → durable_writeback → quota_spend
             → scheduler_apply → scheduler_ack
```

一轮只会停在这七个阶段构成的某个**前缀**上。第 4 阶段做完就崩，已完成的就是前 4 个；第 6 阶段做完就崩，就是前 6 个。不存在"跳过第 3 阶段但做了第 4 阶段"的状态。

这个约束由校验规则维持，不靠约定。一份事务计划声称自己完成了若干阶段时，LoopX 会检查它是否正好等于某个前缀：

```python
# loopx/control_plane/turn_driver/transaction.py
expected = list(TRANSACTION_PHASES[: len(phases)])
if phases != expected:
    errors.append("completed_phases must be an ordered transaction prefix")
```

**这就是恢复能成立的机制**：可能崩溃的位置从"任意时刻的任意状态"收缩成"七个前缀之一"。恢复不需要猜，只要读最后完成的阶段，从下一个继续。重启四十三次和重启一次走的是同一条路径。

### 收费为什么必须在写回之后

顺着顺序约束能推出一个反直觉的结论。注意这两个阶段的相对位置：

```text
durable_writeback  →  quota_spend
```

先写回、再扣费，意味着"钱花了但结果没落盘"这个状态不可能出现。代价是扣费失败时这一轮白做——LoopX 接受这个损失，因为**一次白做的成本，远低于一次"收了钱却说不清结果在哪"的不可审计状态**。

失败同样有约束。每种失败必须声明停在哪个阶段：

```python
# loopx/control_plane/turn_driver/transaction.py
FAILURE_PHASES = {
    LoopXTurnResultKind.HOST_FAILURE:        "host_execute",
    LoopXTurnResultKind.VALIDATION_FAILED:   "validation",
    LoopXTurnResultKind.WRITEBACK_FAILED:    "durable_writeback",
    LoopXTurnResultKind.QUOTA_SPEND_FAILED:  "quota_spend",
    LoopXTurnResultKind.TERMINAL_CLOSEOUT_FAILED: "terminal_closeout",
}
```

一份声明 `QUOTA_SPEND_FAILED` 却说自己停在 `validation` 的计划会被拒绝。失败不能随意归因，**因为它决定了恢复从哪里开始**。

### 五段闭环：一次正常交付的形状

中断之外，正常路径也有固定形状。一次交付至少包含五段：

```text
Decide  →  Act  →  Validate  →  Write back  →  Account
```

**Decide。** 读取当前 decision，选择 `agent_channel.primary_action` 对应的 Todo。不得用旧 prompt、旧 dashboard 卡片或上一次的 `recommended_action` 覆盖当前 contract。

**Act。** 完成一个可恢复的 bounded segment。Bounded 不等于"只改一行"，而是这个工作段有明确输入与边界、产生连贯的 artifact/observation/blocker、能独立验证、并能形成下一项 Todo 或等待条件。只读一个文件、重复"正在分析"、跑无关命令都不构成交付。

**Validate。** 验证检查真实 postcondition，不采信执行者的自述：

| 交付类型 | 验证方式 |
|---|---|
| 代码 | focused test、contract test、smoke 或 build |
| 文档 | 构建、链接、命令表面、public-boundary scan |
| 外部 effect | 远端 readback、revision 或 service state |
| blocker | 缺失依赖、权限或可观察 handle 的明确证据 |

`process exited 0` 可能只证明工具启动成功，它不自动证明目标行为、外部状态或 acceptance。

**Write back。** 验证后通过 Todo lifecycle、event、evidence 或 `refresh-state` 把 compact truth 写回，至少说明：交付了什么、依据哪个 revision/command/readback、推进了哪个 acceptance 或 blocker、下一步是什么、per-Agent Vision 是否改变。Raw transcript 和大段日志不进 public-safe state。

**Account。** 只有在 validated writeback 已存在时，才按 CLI channel 记一次 quota spend。Gate notification、dry-run、失败 preflight、未变化的 monitor poll、scheduler cadence change 和重复 writeback 都不应冒充 delivery spend。

顺序不能倒置：

```text
wrong:  act → spend → 事后判断有没有做成
right:  act → 独立验证 → 持久写回 → 只 spend 一次
```

### 缺层的故障模式

五段是连续依赖链。缺哪一段，都会产生一种特定的故障，系统并不会因此"继续循环"：

| 缺失层 | 可见症状 | 后果 |
|---|---|---|
| 缺 Validation | 有 artifact 但无 postcondition 检验 | 不合格交付进入 writeback，后续决策基于错误证据 |
| 缺 Writeback | artifact 已生成但 Todo 仍 open | 下一 peer 看不到完成，重复工作或选错 frontier |
| 缺 Refresh | Todo 已更新但 status/vision 仍是旧值 | quota 选错目标，monitor 按过期条件判断 |
| 缺 Spend | 交付已写回但没有 quota 记录 | quota accounting 与 delivery causality 不一致 |

**Validation 缺失最危险**，因为它把内部信心当成了外部事实。**Writeback 缺失最常见**，因为 agent 在"完成工作"后跳过闭环，只留了本地 artifact 或聊天记录。**Refresh 缺失最隐蔽**：表面上状态正确，实际 quota 和 monitor 在读取决策前已经过时。

## 尺度二：这一轮该不该动

到此为止讲的都是"已经决定要动之后"的事。但长程系统里更常见的问题是**根本不该动的时候动了**：凭"配额还有"就开跑，凭"用户没投诉"就跳过验证，凭"goal 还是 active"就忽略 Gate。

### Quota 是决策编译器

"还剩多少配额"是减法思维：每轮扣一次，扣完就停。但一轮合法工作可能不需要 spend（monitor poll、dry-run、preflight），一轮 spend 也不等于做了有效交付（artifact 没有 validation）。按余额检查来理解，系统会在这几个场景出错：

- **PR checks 挂起时**：不能因为 goal 仍 active 就调用模型，必须先等外部结果；
- **连续 dry-run 或 preflight 失败**：spend 没发生，但系统不该无限重试，连续失败需要 repair 或 replan；
- **monitor 未到期**：不该因为"还有配额"就提前 poll，浪费外部资源。

Quota 的正确模型是从 source facts 按稳定 precedence 编译成一个 interaction contract，它决定"本轮允许什么行为、允许几次 spend"，把"余额大于零就开始"这类判断排除在外。

### Decision Pipeline：顺序本身就是安全合同

决策要求多条规则按依赖顺序共同编译出一份 contract，共九个阶段：

```text
identity
  → authority and boundary
  → scoped decision
  → repair obligation
  → capability and workspace eligibility
  → frontier and continuation
  → interaction contract
  → scheduler
```

1. **Identity**：解析精确 Goal 与 registered Agent，身份不明时 fail closed；
2. **Goal boundary**：建立 repository、write scope、authority source、spawn 与 public/private boundary；
3. **User Gate**：归一化 blocking scope、decision scope、具体问题与 projection gap；
4. **Outcome / repair obligation**：检查连续 surface-only progress、Vision 或 acceptance gap，判断是否必须 replan 或 self-repair；
5. **Capability**：筛出当前执行面真正具备能力的候选；
6. **Workspace**：检查 task repository、worktree、branch 与 required write scope；
7. **Frontier**：解析 priority、claim/lease、dependency、successor、monitor 与 terminal closure；
8. **Interaction contract**：组合成 user、agent、CLI 三个 channel；
9. **Scheduler hint**：从已确定的 lifecycle 状态派生下一次 wake、backoff 与 ACK。

**顺序本身就是安全合同。** 先选 Todo、后查 workspace，会让 Host 在发现"当前目录错了"之前就已经开始写；把 open user item 当成全局阻塞，则会饿死不依赖该决定的安全工作。

### 三个 channel 可以同时成立

一轮义务有三个视角，三者可以同时为真：

| Channel | 回答什么 |
|---|---|
| User | 用户现在是否必须行动；该通知还是保持安静；Gate 阻塞哪个 action、lane 或整个 Goal |
| Agent | 当前 Agent 是否必须尝试工作；是否允许 delivery 或 quiet no-op；唯一 primary action 是什么 |
| CLI | 哪些 lifecycle command 是下一步；validation 后如何 refresh/writeback；何时允许 spend；Gate/wait/no-change 为何不应 spend |

```text
user channel:
  action_required = true
  action = approve homepage publication
agent channel:
  must_attempt = true
  primary_action = run an independent link check
CLI channel:
  spend_after_validation = true
```

用户 Gate 仍然可见，但它没有覆盖那个独立的 link-check Todo。压成"有用户 Todo 所以 Agent 停止"会丢掉 scoped fallback，压成"Agent 可以做事所以不通知用户"同样错误。

### 常见 interaction mode

三个 channel 组合出的结果会被压成一个**可测试的 mode**。外部开发者至少要能识别这几种：

| Mode | Agent 行为 | User 行为 | Spend |
|---|---|---|---|
| `bounded_delivery` | 完成一个有界 artifact、blocker 或 state delta | 通常无需打断 | validation + writeback 后一次 |
| `user_gate` | 不运行被 Gate 覆盖的路径 | 回答、拒绝、取消或改向 | 不 spend |
| `scoped_user_gate_fallback` | 只运行不依赖该 Gate 的 selected fallback | Gate 仍可见 | fallback 验证后一次 |
| `external_evidence_observation` | 读取 bounded handle / readback，不发明交付 | 必要时提供缺失 handle | material transition 后才可能 spend |
| `monitor_quiet_skip` | 未到期或无 material change 时保持安静 | 无需打断 | 不 spend |
| `agent_scope_wait` | 当前 peer 没有 in-scope candidate，等待重分配 | 通常无需行动 | 不 spend |
| `autonomous_replan` | 写入 Todo、Vision、acceptance 或 no-follow-up delta | 只有 owner-held 决策才打断 | 有 accountable delta 后 |
| `outcome_floor_recovery` | 只恢复缺失的 outcome evidence 或写 blocker | 视 blocker owner 而定 | 通过恢复验证后 |
| `blocked_health` / repair | 先修复 registry、projection 或 boundary | 仅在需要 owner authority 时介入 | 无有效 delta 不 spend |

具体 mode 会随协议演进。**要保存的是判别方法**，而不是背诵一个永久不变的枚举列表：谁拥有下一个 transition、什么行为被允许、什么证据允许 writeback。

### Observation、Evidence 与 Receipt 各证明什么

三者在一轮里承担不同责任，混用会导致"我以为有人验证过了"这类事故：

| 对象 | 证明什么 | 不证明什么 |
|---|---|---|
| Observation | 某个时刻看到了什么 | 结论已被接受或仍然新鲜 |
| Evidence | 哪些材料支持一个判断 | 状态转换已实际写入 |
| Receipt | 某个 action / transition 在绑定输入与 revision 下被接受 | 外部世界从此不变 |

以 `git push` 超时为例，把这条链拆开看：

```text
tool invocation        → 只是 attempt
git ls-remote 的结果   → readback observation
remote ref 与 expected commit 相同 → 可以成为 evidence
LoopX 记录发布 transition → 才形成 durable receipt
```

**Proposal 也不是 effect。** 一份协议声明"建议 publish"，不会自动授予凭据、权限，也不能证明远端已经改变。

### 缺层的另一种表现：把局部信号当全局授权

| Source Fact | 决策含义 |
|---|---|
| Goal 是否注册、Agent 是否识别 | 身份不明时 fail closed，不消耗任何资源 |
| User Gate 是否阻塞当前 scope | 被阻塞的路径不执行，不被阻塞的 fallback 可以独立运行 |
| Frontier 是否有 claimable Todo | 无可运行候选时进入 monitor/agent-scope wait |
| 连续 delivery 是否缺乏 outcome | 多轮 surface-only 后要求真正 outcome 或 self-repair |
| 外部 evidence 是否 fresh | 过期证据不能进入当前决策，必须先刷新 readback |

被禁止的捷径包括：凭"goal active"跳过 Gate、凭"曾有配额"跳过 workspace check、凭"用户未投诉"跳过 validation。这些都是把局部信号当成全局授权。

完整的 decision table、九类组合 case 和规则优先级见 [Control-Plane Course 第 6 讲](/loopx/docs/development/control-plane-course/06-quota-decision-kernel/)；证据阶梯每层的失败回放与修复路径见 [第 8 讲](/loopx/docs/development/control-plane-course/08-evidence-refresh-and-self-repair/)。本章只讲判断方法，不逐个背诵会随协议演进的 mode 枚举。

### 谁是规则的唯一所有者

尺度二的九阶段顺序要真正成立，还有一个前提：**同一条规则只能有一个所有者**。如果 Python 和 TypeScript 各自实现一遍"什么时候允许扣费"，两份实现迟早会分叉，而分叉意味着顺序合同在某一侧悄悄失效。

LoopX 的做法是把完整 transaction 的 canonical semantics 迁到 TypeScript：

```text
Python CLI / Host adapter
  → typed request
  → managed TypeScript Effect runtime
  → domain-owned decision or effect receipt
  → Python compatibility projection / explicit external Provider
```

已发布的 typed owner 包括 **Turn settlement**、**Todo completion** 与 **Host Todo settlement**，quota delivery routing、**spend/void/monitor-poll commit**、**本地 task-lease 完整生命周期**、**Vision refresh**、governed capability-lifecycle validation，以及 scheduler heartbeat/state 与 **receipt-bound scheduler follow-up**。

Python 仍然负责当前 CLI transport、明确的外部 Provider/Host effect、legacy projection 和尚未迁移的 Markdown/event 写回。所以迁移并不意味着"**Python 已被移除**"——但也不能在 Python facade 里重新实现同一条规则，那会制造第二个事实来源，正好破坏这一节要保的东西。`v0.5.4` 仍提供可执行的 `turn plan` / `turn run-once` 路径，迁移也是从这个版本实际开始的。

当前 `main` 的 [TypeScript Control-Plane Migration RFC](https://github.com/huangruiteng/loopx/blob/main/docs/architecture/rfcs/typescript-control-plane-migration-v0.md) 把后续工作定义为 transaction-payoff：一次迁移应当切走一个完整 transaction，并删除被替代的 Python semantic path。只增加 leaf handler、DTO 或 bridge call 不算迁移进展。

这条边界对读者有实际意义：**当你发现两侧行为不一致时，canonical 答案在 TypeScript 侧**，Python 侧是适配或兼容投影。判断一处逻辑归谁，看它是否已经是一个 domain-owned decision 或 effect receipt。

## 代价与边界：这套设计放弃了什么

上面每条规则都换来一个性质，代价需要说清楚，它们决定你什么时候不该指望这套机制。

**代价一：每轮必须先读状态。** 不能沿用一个多小时前 prompt 里的判断直接动手。这比"接着干"慢，而且读到的状态可能在你读完时就已经失效。

**代价二：阶段数固定。** 一轮里不能临时插入新步骤，比如"改完文件顺手清一下缓存"。这种灵活性被换成可枚举性，而可枚举性是恢复的前提。

**代价三：白做的可能。** 写回后扣费失败，这轮工作不产生任何记账，系统选择丢弃它而不是留下说不清状态的部分结果。

**代价四：不能凭直觉跳步。** 九个阶段的顺序意味着一个看起来显然的判断——"用户没投诉，所以可以继续"——在 pipeline 里没有位置。想加快决策，只能改进 source facts 的质量，不能压缩顺序。

**边界一：这七个阶段只描述"一次受治理的 Turn"，不覆盖"Agent 的全部行为"。** 模型在 `host_execute` 内部的推理、工具调用的具体顺序，不受这七个阶段约束，那属于 harness 的职责。LoopX 管的是**跨进程边界、会被中断、需要被记账的那部分**。

**边界二：TurnEnvelope 和 LoopX Turn 不是默认路径。** TurnEnvelope 目前是显式启用的 bounded projection，不是默认 quota 输出；LoopX Turn 是 experimental protocol，但当前版本提供可执行的 `turn plan` / `turn run-once` 路径与 Host adapter。它们适合理解边界和做显式 opt-in 集成，不该被描述成所有 Host 都默认采用的 recurring runtime。

**边界三：Python 仍在负责真实职责。** Python 承担当前 CLI transport、明确的外部 Provider/Host effect、legacy projection 和尚未迁移的 Markdown/event 写回。迁移不是"Python 已被移除"，也不能在 Python facade 里重新实现同一条规则——那会制造第二个事实来源。

## 具名失败：这些约束拦住了什么

抽象地谈"可恢复性"没有说服力。下面三个场景各有对应测试，可以直接运行，看约束如何生效。

**合法前缀重放不产生重复效果。** 对每一个合法前缀，重放都必须收敛到同一结果：不会因为重放多扣一次费、多写一条记录。测试覆盖全部前缀组合，无一抽样。核心断言是重放时 `replay_calls == []`，且 `combined_calls` 里 `DURABLE_WRITEBACK` 与 `QUOTA_SPEND` 各不超过一次。

**没有写回的扣费必须 fail closed。** 一份计划声称要扣费却没有对应的 `durable_writeback`，必须被拒绝，而不是先扣了再说。这防的正是开头那个 09:04 的状态：钱花了，但不知道落在哪。

**一次失败短路所有后续效果。** 第 3 阶段失败后，第 4 到第 7 阶段都不执行。否则会出现"验证没过但写回成功"这种内部矛盾的状态。

对应测试：`tests/control_plane/test_effect_program_fault_replay_matrix.py`。这些是这套设计在每个崩溃点上的可执行证据，用途远不止演示。

## 一轮如何结束

一轮可以以多种结果结束，它们都是合法的：

- validated delivery + writeback + spend；
- concrete blocker + recovery condition；
- user Gate notification；
- bounded external observation；
- quiet monitor / no-candidate wait；
- replan 或 repair delta；
- terminal audit 后停止。

**"没有写代码"不一定是失败**——Gate、wait 和 quiet no-op 可能正是协议要求的正确结果。反过来，写了很多代码也不代表这轮有效，如果它绕过了 selected Todo、authority、workspace 或 validation。

## 不变式

读完这一章，你应该能带走六句可以自己检查的话。

**关于单轮事务：**

1. **一次 Turn 的完成状态只能是七个阶段中的某个前缀。** 观察到"做了扣费但没做写回"，那不是恢复边界，是缺陷。
2. **同一轮 Turn 的重放不产生额外效果。** 重放幂等，所以重试是安全的，但重试不掩盖"当时做到哪"这个事实。
3. **失败必须声明它停在哪。** 一个说不出自己停在哪个阶段的失败，无法被恢复，也就无法被交接。

**关于跨轮准入：**

4. **三个 channel 可以同时为真。** 把任一个压成全局布尔，都会丢失合法的并行工作或必要的人工介入。
5. **决策顺序不可压缩。** 想加快决策，只能提高 source facts 的质量。
6. **没有 delta 就不该 spend。** Gate notification、dry-run、未变化的 poll 都不是交付。

这六条回答的其实是同一个问题：**当没人记得刚才发生了什么、也没人盯着的时候，系统凭什么知道该不该动、动到哪了？** 本章给的是 LoopX 在单轮尺度上的答案。下一章把尺度拉长——当一个目标需要几十上百轮、跨越多次中断和交接时，这套约束如何继续成立。
