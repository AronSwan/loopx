# 消耗的上限与外部观察

本章回答一个问题：一个没人盯着也停不下来的系统，怎么让它**在没人看的时候既不空转、也不假装自己在工作**。这一章接在"要求四"后面：消耗必须有上限且可被外部观察。

## 从一个坏的结局开始

先看一个场景。它不需要任何一方出错，只要有两个 monitor 就够：

```text
10:00  Goal 上有两个外部条件待观察：PR #123 的 CI，与 PR #456 的 review。
       M1 盯 #123（cadence 30m），M2 盯 #456（cadence 45m）。
10:30  M1 到期。轮询结果与上次相同，它的 no-change streak 记为 1。
10:45  M2 到期。轮询结果与上次相同，它的 streak 记为 1。
11:00  M1 到期。streak 记为 2。
11:15  M2 到期。streak 记为 2。
...    两个 monitor 交替到期，各自的计数器都在缓慢上升，
       但它们永远到不了 backoff 需要的阈值，因为每次醒来看到的都是"另一条 lane 刚跑过"。
```

这个过程里没有任何一方在说谎。每次轮询都合法：monitor 确实到期了，外部条件确实没有变化，观察结果也确实被写了回去。

问题在于**退让的判据被放在了错误的尺度上**。如果"是否退让"由全局的相邻 run 判断，那么 M1 的每一次 run 都在打断 M2 的无变化序列，M2 的每一次 run 也反过来打断 M1。两条 lane 互相给对方续命，系统看起来一直在工作，实际上在**热轮询**一个不变的世界。

同一个根的另一种表现更安静：

```text
22:00  最后一个 Agent Turn 结束。frontier 上剩一个外部条件，没有 monitor 订阅它。
次日
09:00  用户回来，发现什么都没发生。
```

**静默停滞**。没有机制在无人监督时推进工作，也没有机制在无人监督时宣布"我在等"。

两个结局看起来相反，其实是同一个缺陷：系统没有一个**可被外部观察的消耗判据**。热轮询是因为退让没有被正确地计数，静默停滞是因为等待没有被登记成一条可唤醒的状态。

## 为什么"设一个预算上限"不是解药

直觉反应是给系统加一个额度：每轮扣一点，扣完就停。这个设计会同时错过两个方向。

**它拦不住空转。** 热轮询的每一次轮询都是"合法"的轮次，额度会照常扣减，直到花完为止。上限只是让热轮询有一个终止时间，没有让它停止。更糟的是，真正需要响应外部变化的那一轮，可能正好排在额度耗尽之后。

**它拦不住静默停滞。** 没有任何人观察的外部条件不会自己产生一个 run。额度充裕并不能让系统知道"该去看一眼 #456 的 review 了"。上限管的是花费，管不到观察。

**它也对合法的无费轮次判断错误。** monitor poll、dry-run、preflight 都是合法工作，它们的成本不在配额里（协议上，monitor poll 是不计费结算）。一个按余额判断的系统会把"还有额度"读成"可以开跑"，而这一轮真正需要的可能是"继续等"。

所以真正需要的是三个互相配合的机制，而不是一条孤立的上限：**准入**决定这一轮该不该动；**backoff** 决定连续无变化时如何退让；**monitor** 决定由谁来唤醒。

## 设计

### 准入：这一轮该不该动

第一个机制是准入。它在"决定做什么"之前先回答"现在允许做什么"，并且答案不能由执行者自己给出。

Quota 的模型在 [一轮受治理的工作](03-one-turn.md) 里已经作为 decision compiler 讲过，这里只补它的预算含义：**准入把"还剩多少"换成"这一轮允许几次 spend、允许哪些行为"**。进入决策的是 source facts 之间的优先级，余额数字不在其中。

被禁止的捷径有一致的形状：把局部信号当成全局授权。

| Source fact | 准入含义 |
|---|---|
| Goal 是否注册、Agent 是否识别 | 身份不明时 fail closed，不消耗任何资源 |
| User Gate 是否阻塞当前 scope | 被阻塞的路径不执行，未被阻塞的 fallback 独立运行 |
| 外部依赖是否已经登记等待 | 有 typed 依赖时不重试，转入等待并保留独立 successor |
| 本轮是否已有结算身份 | 一个 heartbeat Turn 只有一个 settlement Todo，不能被另一个 monitor 替换 |
| 交付类型是否允许 spend | 无 validation 的 writeback、dry-run、未变化的 poll 都不产生 delivery spend |

最后一行的形状值得单独说，因为它是"上限"最容易漏掉的部分：**该花的不花、不该花的必须不花**。协议规定 Gate notification、dry-run、失败 preflight、未变化的 monitor poll、scheduler cadence change 和重复 writeback 都不冒充 delivery spend。所以"消耗有上限"真正约束的是**哪一类动作才配得上一次扣费**，扣费次数还在其次。

准入的另一个产品形态是等待被登记。一个已准入的 advancement Turn 发现真实依赖时，会登记 `monitor_changed:<todo_id>` 或 `todo_done:<todo_id>`，同时保留一个独立可运行的 successor。结算返回 `typed_blocked_writeback_no_spend`：有 validation 与 durable writeback 回执，不扣额、不计交付进展。旧 Turn 因此不会被卡住，独立工作照常可选。

```text
loopx quota should-run --goal-id "$GOAL" --agent-id "$AGENT"   # 读本轮准入
loopx task-lease inspect --goal-id "$GOAL" --todo-id "$MONITOR" # 读 monitor 的当前租约
```

### 退避：连续无变化时如何退让

第二个机制是 backoff，它回答"没人改变的时候，多久以后再问一次"。

Scheduler hint 把当前状态投影成一个 cadence，其中包含 unchanged-poll 的策略：一个 backoff multiplier（当前实现取 2）、每个执行面的 unchanged poll limit，以及一个 max interval。连续的无变化轮次会把间隔逐步拉长，直到触达上限为止。

更关键的是**什么会重置它**。Scheduler state 绑定 `reset_token` 与 `identity_signature`；用户反馈、新 Todo、reassignment、Gate resolution 或 material evidence transition 都会改变 identity，并把 cadence 恢复到当前 profile 的初始值。只有连续 unchanged polls 才继续 backoff。

这条设计的效果是：**退让换来的效果，是把观察成本降到与"确实没有变化"相称。** 一旦世界真的变了，重置条件触发，间隔立刻回到初始值，响应速度不受之前退让的影响。

同一条退让逻辑还有一个强得多的版本，用于 monitor 长时间观察而无进展时。当一条 monitor-only lane 的连续无变化次数到达阈值，Goal frontier 不再安静等待，而是要求一次 autonomous replan：

```text
kind: monitor_no_change_streak
threshold: 5
```

阈值取 5 在源码里有明确理由：它被刻意放在 2 轮的 run-history stall 阈值之上，因为安静的 monitor 合法地需要等好几个 cadence 周期；用两次无变化就强制 replan，会给慢速外部源制造无谓的 churn。具体数值会随协议演进，但**"退让到什么程度就该改问法"需要一个数**这件事本身是稳定的。

### Monitor：由外部条件驱动唤醒

第三个机制是不再由 Agent 反复询问，而是把"等什么"登记成一个状态。

当 frontier 只剩外部条件时，建立 `continuous_monitor`。一个 Monitor 至少需要六件东西：

- **stable target key**：被观察对象的稳定标识（一个 PR、一个 tag、一份 release），别在每轮轮询时重新推断；
- **cadence 与 next due**：期望多久看一次，以及下次什么时候看；
- **bounded observation handle**：可读回的观察句柄，让"看过了"有证据可查，不停留在自述；
- **material-change 判据**：什么才算变化；
- **expiry 或终止条件**：这条 monitor 什么时候不再有意义，必须能被停掉；
- **no-change accounting policy**：连续无变化怎么记账、记在哪。

后两条容易被省略，代价却最高。没有 expiry 的 monitor 会永远保持到期；没有 no-change 策略的 monitor 无法参与退让。协议把这两条落成字段：`expires_at`、`last_checked_at`、`result_hash`、`consecutive_no_change` 与 `material_change` 同在 monitor metadata 里。

写入观察时，不变的那次和变了的那次走的是不同的路径。计数器只在无变化且 hash 未变时递增；material change 或 hash 变化把它归零：

```typescript
// loopx/control_plane/todos/monitor_metadata.ts
const noChange = replay ? previousNoChange : material || (previousHash && previousHash !== resultHash)
  ? 0 : previousNoChange + 1;
```

`material-change` 判据是人为选择的，这一点后面还要单独付代价。这里先记住它的位置：**它是唯一能触发 successor 的入口**，所以它决定了后续工作到底由什么驱动。

### 多 Monitor、多 Agent 的 per-lane 计数

回到开头的热轮询。修法在于**换计数的尺度**，调整阈值解决不了它。

正确做法是每个 monitor todo 维护独立的 `consecutive_no_change` 计数器。M2 有 material change 时只重置 M2，M1 不受影响；回合顺序（A1、B1、A2、B2……）不会互相清零。

这个 per-lane 设计同样适用于多 agent：每个 agent 的 monitor 是独立 lane，它们共享同一个 frontier 读模型，但 no-change 判断是 per-lane 的。共享读模型让全局视角一致，per-lane 计数让退让判据不被别的 lane 的活跃度污染——这两件事必须同时成立，只做前者就会退化成热轮询，只做后者则看不到全局。

实际效果可以直接观察。下面这个 fixture 里四条 lane 交错存在：两条 streak 为 1、一条为 5（且属于当前 Agent）、一条为 5 但属于 peer Agent。结果是恰好那一条被触发：

```text
kind: monitor_no_change_streak
todo_id: todo_unchanged_twice
target_key: github-pr-456
run_count: 5, threshold: 5, agent_id: <当前 Agent>
```

另外两条 streak 为 1 的 lane 安静待命，streak 为 5 的 peer lane 不进入当前 Agent 的 replan 义务。**计数是按 lane 的，唤醒也是按 lane 的。**

### Scheduler hint 是"何时唤醒"

最后一个区分，也是本章最容易混用的一个：**scheduler hint 与 execution permission 是两件事。**

```text
scheduler hint: when to wake
interaction contract: what this turn may do
```

Scheduler hint 把当前状态投影成 Host cadence：现在运行、等待 fresh evidence、等待重分配，或者按 monitor cadence 唤醒。它回答的是时间问题。而"这一轮能不能写、能不能扣费"由 interaction contract 回答。

因此有一条硬规则：**Host 即使在正确时间唤醒，也必须重新运行 current decision。** 旧的 scheduler proposal、旧的 `should_run`、旧的 selected Todo 都不能跨状态变化直接复用。否则 scheduler 就从"闹钟"变成了"授权"。

同理，三个与唤醒相关的动作都不产生 delivery spend：cadence apply、failure writeback、以及 ACK。唤醒本身不构成一次交付。

## 代价与边界

上面三个机制都换来了一个性质，代价需要说清楚。

**代价一：准入会让该做的事被推迟。** fail closed 的代价是慢。一个身份解析暂时不明、一个 Gate 正在路由、一份 evidence 需要先刷新，都会让本来可以动手的一轮变成等待。系统选择先弄清楚权限，再决定动不动手。

**代价二：backoff 阈值设错会忽略真实变化。** 阈值设得太低，安静的慢速外部源会被反复要求 replan，制造 churn；阈值设得太高，一条已经死掉的 lane 会长时间没人管。中间那个数不存在"正确"取值，只有与观察对象的时间尺度相称的取值。

**代价三：material-change 判据是人为选择的。** 这是本章最需要诚实交代的一条。什么算变化由人决定：只比对 result hash，可能漏掉"hash 没变但内容其实已经不同"的变化；加入更丰富的判据，又会引入误报并触发无谓的 successor。判错了两条路都要付：漏报让真实变化被当成无变化继续等待，误报让系统围绕噪音建 Todo。

**代价四：没有 monitor 能力的外部条件用不上这套机制。** 如果一个条件既没有可读回的 handle，也无法被登记成 cadence，那它就只能靠人看。这时系统不会退化成轮询，它会退化成**人**。这不是可接受的默认值，而是这套设计的适用边界。

**边界一：上限约束的是消耗，和工作量无关。** 一个从容运行的系统可能一整天只花很少的额度，也可能在真正需要时连续多轮 spend。把"消耗低"当成健康指标，和把"消耗高"当成勤奋指标一样没有依据。

**边界二：monitor 的安静不等于系统健康。** `monitor_quiet_skip` 是正确结果之一，但它与"静默停滞"在表面上完全一样。区分它们的唯一办法是读 monitor 的状态：有没有 next due、有没有 expiry、streak 走到哪了。只看"当前有没有在动"，两者无法分辨。

**边界三：准入不授予执行权。** 一次观察或一条租约结论都不授予新的 mutation 权限。协议对此的措辞是直接的：回执证明历史结果，不授权新的 mutation；被调度选中本身不授予执行租约。准入与执行是两条不能互相推导的链条。

## 具名失败：这些约束拦住了什么

下面三个场景各有对应测试或协议锚点，可以直接运行或查阅。

**交错 monitor 不会互相清零 streak。** 四条 lane 交错时，只有真正连续无变化的那一条触发 replan，其余 lane 的计数不受影响；peer Agent 的 lane 不进入当前 Agent 的义务。对应测试：`tests/control_plane/test_monitor_replan_agent_scope.py::test_interleaved_monitors_keep_independent_no_change_streaks`。它守住的正是开头那张时间表：如果计数是全局的，这个测试无法同时得到"一条触发、两条安静、一条不属于我"的结果。

**辅助观察必须不计费，且不能替换结算身份。** 当 advancement 已绑定本 Turn 的 settlement Todo 时，新到期的 monitor 可以在同一 Turn 写入辅助观察，但它不能替换结算身份，也不能产生第二次扣费。重放必须幂等。对应测试：`tests/control_plane/test_monitor_observation_admission.py`，以及协议 `docs/reference/protocols/quota-monitor-observation-receipt-v0.md`（其中明确"回执证明历史结果，不授权新 mutation"）。

**有真实依赖时不靠短定时器硬撑。** 一个已准入的 Turn 发现真实依赖时，应当登记 causal wait 并保留独立 successor，别用一个短 `resume_at` 反复重试。结算返回 `typed_blocked_writeback_no_spend`，不扣额、不计进展，Todo 保持开放且原验收器不变。对应协议：`docs/reference/protocols/quota-blocked-causal-closeout-v0.md`。

## 不变式

读懂这一章，你应该能自己检查下面六句话。

**关于准入与退让：**

1. **没有 delta 就不该 spend。** Gate notification、dry-run、未变化的 poll 都算不上交付。反过来，一次 spend 也不证明发生了有效交付。
2. **退让按 lane 计数，不按全局计数。** 观察到"系统一直在忙但什么都没变"，先检查 no-change 是否被放到了全局尺度。
3. **唤醒不授予权限。** 在正确时间被唤醒的 Host，仍须重新运行 current decision。

**关于观察：**

4. **没有被登记的等待，等于静默停滞。** 判断依据是它有没有 stable target key、next due 与 expiry。
5. **material-change 判据决定谁在驱动后续工作。** 它是人为选择的，所以也是可以选错的。
6. **没有可观察 handle 的外部条件用不上这套机制。** 这时系统的兜底是人，而人是有成本的。

这六句回答的是同一个问题：**当没有人盯着、也没有任何变化发生的时候，这个系统凭什么说自己还在正常等待，还是已经空转或停摆？** 判断的依据不在它跑了多少轮，而在它能不能说出自己在等什么、等到什么时候、以及什么算等到了。
