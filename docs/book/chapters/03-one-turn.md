# 一轮受治理的工作

本章回答一个问题：一轮 Agent 工作从"该不该动"到"可以算做完"，中间发生了什么，以及为什么这些步骤的**顺序本身**就是安全边界。

## 写回完成后，进程停了

考虑一个教学情境：Agent 为一项兼容性修复生成了代码，验证通过，结果已经写回；随后 quota 结算超时，进程退出。重新启动时，CLI 没有返回成功，但代码和部分持久记录已经存在。

此时整轮重做可能重复副作用，直接宣告完成又会掩盖尚未完成的结算。需要先回答：**哪些步骤已提交，哪些确认未执行，哪些结果仍未知？**

## 为什么需要可恢复的提交边界

只在最后保存一条“成功”记录很简单，却无法区分执行途中留下的结果。逐步记录有助于恢复，但外部操作和本地 checkpoint 之间仍可能中断。

LoopX 为受治理的 Turn 记录身份、阶段和回执，并对未决操作保留读回路径。恢复的目标是保留已完成工作、确认不确定结果，再决定能否继续；证据不足时可以安全地停住。

## 尺度一：一轮内部的事务

### 七个阶段描述已确认的进展

LoopX Turn 的事务契约给出七个有序阶段：

```text
host_execute → typed_result → validation
             → durable_writeback → quota_spend
             → scheduler_apply → scheduler_ack
```

回执中的 `completed_phases` 必须是这条序列的合法前缀。它约束的是**可以声称已完成什么**；并不保证进程只能在阶段之间崩溃，也不证明未记录的副作用没有发生。

例如 provider 已完成写回，但进程来不及保存 checkpoint，journal 里仍可能只有 `prepared` 意图。恢复需要按同一 settlement identity 和 effect 引用读回：

| 读回结果 | 处理方式 | 仍需满足的条件 |
| --- | --- | --- |
| `committed`，且回执有效 | 记录已有结果，跳过该副作用 | 身份、payload 与阶段匹配 |
| `absent` | 可以执行尚未提交的步骤 | 当前恢复判定与授权允许 |
| `unknown`，或读回不可用 | 停止这条恢复路径，保留待确认状态 | 获取有效读回或由对应 owner 修复 |

因此，合法前缀只是恢复条件之一。当前 executor 还检查 journal 身份、绑定关系、失败类型和恢复许可。已保存 Host result 时可能从 validation 继续；需要重新调用 Host 的失败还有显式 retry 和预算限制。

### 配额记账为什么跟在写回之后

`durable_writeback → quota_spend` 让交付配额记录能够关联已经验证并持久化的结果。这里的 spend 是 LoopX 的预算 slot 记账；模型 API 或外部服务的实际费用可能在执行时已经发生，不能据此推断真实账单。

写回成功而 spend 失败时，**已有写回会保留**。系统记录尚未完成的结算，恢复时复用已确认的结果，避免重新调用 Host 或重复写回。它既没有丢弃工作，也没有让整轮跨外部系统变成一个原子事务。

失败类型帮助定位后续动作，例如 `HOST_FAILURE` 对应 `host_execute`，`WRITEBACK_FAILED` 对应 `durable_writeback`，`QUOTA_SPEND_FAILED` 对应 `quota_spend`。这些字段须与回执一致；仅知道失败阶段还不足以授权重试。

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

遇到两侧行为不一致时，先查这条规则当前的 contract owner。已迁移的 Turn settlement 由 TypeScript 拥有；部分 Todo 读规则仍由 Python 拥有。实现语言本身不能决定哪边正确，迁移 RFC 的交付边界和真实调用路径才是依据。

## 代价与边界：恢复需要哪些条件

**要维护可读的恢复记录。** journal、绑定身份和 provider 回执带来存储、校验和迁移成本。它们损坏或不可用时，恢复可能被阻塞，不能把缺失记录当成未执行。

**结果未知时可能需要等待。** 保留已完成工作减少重复执行，但也要求 provider 能读回未决结果。一个只支持写、不支持查询或幂等标识的外部 API，需要单独设计恢复策略。

**阶段约束结算协议。** `host_execute` 内部可以包含多个工具调用；固定结算阶段没有禁止“修改文件后清理缓存”。新增外部副作用仍须满足权限和自身的幂等、读回边界。

TurnEnvelope 是显式启用的 bounded projection；LoopX Turn 提供 experimental protocol 与可执行的 `turn plan` / `turn run-once` 路径。它们支持显式 opt-in 集成，不能据此宣称每个 Host 的每次工具调用都获得相同的恢复保证。

## 怎样判断能否恢复

从原 Turn 的标识开始，不因一次 CLI 超时创建新任务重新执行。需要诊断时，可读取 journal：

```bash
loopx turn inspect-journal \
  --goal-id <goal-id> --agent-id <agent-id> \
  --turn-key <turn-key> --format markdown
```

检查 `recorded_effects` 与 `recovery_decision`。`null` 表示未知；诊断命令不会执行恢复，也不授予重试权限。随后依当前 executor 判定和 provider 读回处理，保留原有身份。

| 主张 | 证据入口 | 证据边界 |
| --- | --- | --- |
| 完成阶段必须构成合法前缀 | `turn_driver/transaction.py`、`test_effect_program_fault_replay_matrix.py` | 校验记录形状；测试使用受控回执，不穷尽现实崩溃 |
| 未知 prepared effect 不能盲目执行 | `turn_driver/settlement.ts`、`tests/control_plane_ts/turn_settlement.test.ts` | 仍依赖 provider 提供可信 readback |
| spend 失败保留 writeback | `tests/test_loopx_turn_executor.py` 的 spend 拒绝与恢复用例 | 合成 provider 验证 executor 分支，不验证外部账单 |

完整字段与恢复条件见 [LoopX Turn 协议](/loopx/docs/reference/protocols/loopx-turn-v0/)。这些证据支持特定边界内的保证；它们不承诺任意外部操作的 exactly-once。

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

## 使用时守住的边界

1. 完成阶段是已确认结果的合法前缀；未记录的副作用可能仍需读回。
2. 保留同一 settlement identity 下的有效回执；spend 失败不撤销已完成的写回。
3. 结果未知时先确认，不能用新 identity 绕过原 Turn 的恢复检查。
4. user、agent 与 CLI 三个 channel 可以同时有义务，按各自 scope 执行。
5. 优化读取与执行成本时，仍须保持准入优先级和提交前的授权检查。
6. 按当前 settlement contract 记账；Gate 通知、dry-run 和未变化的 poll 不冒充 delivery spend。

下一章讨论这些规则在多轮运行中的作用：什么时候重试，什么时候重新规划，以及何时必须交还给人。
