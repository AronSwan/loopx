# 从 Codex CLI 可见 TUI 启动

周四上午，你在 Codex CLI 里连上了项目，把当前 task 设成可见的 `/goal`，然后关掉终端去吃午饭。
下午回来时，那条 Goal 仍然停在第一步。

没有报错，没有失败记录，没有任何东西看起来坏掉。Codex CLI 不会自己醒过来：它没有 heartbeat，没有
定时器，没有一个在你离开后继续问"现在该做什么"的机制。你不发消息，就没有下一轮。Goal 体面地坐在
那里等你，而如果你以为它在跑，这个误会可以持续一整天。

## 为什么"那就加个定时器"接不住

自然反应是给 CLI 也装一套 heartbeat，让它自己定时唤醒。但这会拆掉这条路径存在的理由。

CLI 路径的核心约束是 **visible and interruptible**：工作发生在你眼前的 TUI 里，为了"自动化"默认切到
隐藏的 headless worker 是它明确拒绝的做法。这条约束有实际代价。上一章说过，一次唤醒必须能证明自己
没白花；在 CLI 里，这个证明由你本人提供，因此只在你在线时成立。

第二条直觉是让 Goal body 自己循环，把整套逻辑塞进 prompt。这条路的问题在别处：`/goal` body 是
**稳定协议**，它不知道当前有哪些 Todo、哪个 Gate 正阻塞着、monitor 什么时候到期。把这些判断写进
body，就等于在 TUI 里维护了第二份状态，而这份副本从写下的那一刻起就在过期。

两条路都不通，因为 CLI 的答案本来就不同：它不假装自己能自驱，而是把"何时该动"完整地交还给 LoopX
decision，由你在场时触发。

## 边界：CLI 拥有可见交互，LoopX decision 拥有下一步

分工是这样的：

```text
Codex CLI  —— 提供可见 TUI、接手 /goal continuation、由用户或可见循环触发
LoopX      —— 决定这次调用该不该工作、做哪一个 Todo、何时等待或阻塞
```

CLI 是**按需调用**的 Host。它提供可见性，但不提供持续性。这条路径买到的是：每一步都在你眼前，随时
可以打断，任何时刻都能读懂当前状态。它放弃的是无人值守时的继续推进。

这是一个明确的选择，并非能力缺口。有些任务形态需要的正是可见性：你在调一个行为还不清楚的 bug，你在等
自己的判断，你需要在中途改方向。这些场景里，一个安静空转的 timer 反而更危险。

## 启动可见 TUI

```bash
cd /path/to/your-project
codex
```

在 TUI 中发送：

```text
连接当前项目到 LoopX。先运行 loopx doctor，复用已有 active state，
确认 .loopx/、.codex/goals/ 和 .local/ 已被 Git 忽略。不要使用隐藏的
headless execution。连接完成后，生成 thin heartbeat task body，并把当前
Codex CLI task 设置为可见的 /goal <task_body>。最后报告 active state id、
当前 user gate、top agent todo 和 next safe action。
```

setup Turn 的任务是建立连接和可见 continuation，不应顺手开始一大段未经规划的交付。如果你的第一轮
就产出了大段改动，说明 setup 和 delivery 被混在了一起，后续的每一步都会站在一个没人审过的计划上。

## 用 `$loopx` 开始具体目标

安装 command facade 后，可以在 TUI 中使用：

```text
$loopx 为这个 CLI 增加兼容的 JSON 输出，补充测试并等待维护者确认 schema
```

Host 应保留 task text，规划 Todo，并生成适合 Codex CLI 的 Goal body。若 command skill 不可用，
CLI fallback 是：

```bash
loopx start-goal --guided --project . \
  --goal-text "为这个 CLI 增加兼容的 JSON 输出，补充测试并等待维护者确认 schema" \
  --host-surface codex-cli-tui
```

输出是 guided packet，不会替你在另一个终端偷偷启动 Agent。它应该包含或指向可粘贴的
`/goal <task_body>`。这一条值得单独确认：如果 guided start 在后台把 Agent 跑起来了，你就失去了这条
路径唯一的优势，而且很难发现，因为表面上看一切正常。

## Native Goal 与 LoopX 的组合

Codex CLI native Goal 拥有同一 TUI 内的 continuation。LoopX 拥有项目级 frontier：

```text
Visible Codex /goal
  -> run LoopX quota decision
  -> execute selected bounded Todo
  -> validate
  -> write LoopX state
  -> continue, wait, block, or complete
```

当 LoopX 返回 Gate 时，Goal 可以进入 blocked 状态；当用户处理 Gate 后，再通过 Host 的 Goal 恢复
表面继续。不要通过创建第二个 Goal 绕过原 Gate：第二个 Goal 会拿到同一个 frontier，两个 Goal 于是
争抢同一批 Todo。

## 每一轮仍然要过 Quota Gate

从另一个 shell 读取状态不会改变 TUI：

```bash
loopx status --goal-id <goal-id>
loopx history --goal-id <goal-id> --limit 10
loopx quota should-run \
  --goal-id <goal-id> \
  --agent-id <agent-id> \
  --runtime-profile codex_cli
```

你应该看到 Host runtime 指向 `codex_cli`，scheduler owner 属于 Goal/agent loop，而不是 Codex App
heartbeat。这个区别决定了"该唤醒时谁负责唤醒"：如果 packet 报告 scheduler context 缺失，先修复
runtime profile，不要忽略 warning。缺少 scheduler context 时，系统既不会自己醒来，也不会告诉你它
不会醒来。

## 保持身份与 Todo 归属

新的 argument-bearing guided start 在 Goal 已有已注册身份（哪怕只有一个）时不会默认注册 fresh
Agent，而是返回 identity gate 要求选择其中一个 lane；只有 Goal 没有任何已注册 lane 或显式
`--new-peer` 时才默认 fresh。已有 id 只在用户明确要求 takeover 那个 peer 时复用。完成选择后，
visible Goal、quota、refresh 与 writeback 都应显式保留同一个 `--agent-id`；缺失或不匹配时应
fail closed，而不是回退到"唯一身份"。

这条 fail closed 规则防的是一个很具体的错误：Goal 里只有一个身份时，"用它就行"看起来无害，但如果
那个身份属于另一个 Host 或另一个 lane，工作归属就被静默改写了。

Agent identity 表达 LoopX 工作 lane，不证明具体 Host。判断工作是否真的在 Codex CLI 运行，要看
`host_surface`、runtime profile 或对应 run metadata。

交接时的正确顺序是：

1. 当前 Agent 写回验证结果；
2. 更新或完成 Todo；
3. 新 Agent 以 fresh id 预览并完成原子注册；
4. 新 Agent claim 未完成 Todo；
5. 新 Host 读取同一 registry 与 Goal；
6. 再启动 visible Goal。

## 代价与边界

**代价一：没有外部触发就没有进展。** 你不调用，它不动。这不是配置问题，是这条路径的定义。指望它
在夜里自己推进，等于把 App 的能力投射到一个明确不具备该能力的地方。

**代价二：可见性依赖你在线。** 可见 TUI 的价值在你看着它时兑现。你离开的时间越长，这段不推进的
时间越长，而它不会在日志里留下任何异常痕迹。

**代价三：稳定性靠流程而不是机制。** `/goal` body 要稳定，setup 和 delivery 要分开，handoff 要按
顺序走。这些都依赖正确操作，CLI 不会替你强制。App 那侧至少有 automation 这个物理事实可以 readback；
这里能核对的是 registry、identity 和 history。

**边界一：native Goal 的 continuation 不是 LoopX 的 frontier。** Goal 保证同一 TUI 内能接着做，
它不保证这个 Todo 就是该做的那个。二者一致时才推进。

**边界二：可见 Goal 不等于自动化。** 把 `/goal` 设好只是让工作可见可续；它不产生定时唤醒，也不能
替代 decision。

**边界三：两种 Host 可以读同一 Goal，但不共享执行权。** App 与 CLI 同时激活时，检查 claim、lease
与 scheduler ownership。同一个有副作用的 Todo 只能有一个合法执行者。

## 何时选 CLI，何时选 App

两者面对同一个 frontier，差别在唤醒模式：

| 任务形态 | 更适合 | 原因 |
|---|---|---|
| 需要反复看中间结果、随时介入 | CLI 可见 TUI | 每一步都在眼前，可随时打断 |
| 短时集中会话，人不离开 | CLI 可见 TUI | 不需要在会话结束后继续唤醒 |
| 外部状态在变化，要等它变 | App heartbeat | 你不在时仍会被唤醒 |
| 有稳定节奏，可持续推进 | App heartbeat | 定时唤醒匹配按步推进 |

两条经验规则：

- **你要盯着过程，选 CLI**；你需要它在你不在时继续尝试，选 App。前者买到可见性，代价是不会自驱；
  后者买到持续性，代价是定时开销和 ACK 收敛链。
- **无论选哪个，LoopX decision 都拥有"下一步是否合法"**。CLI 不产生这个判断，它只是在你调用时把
  问题交给 LoopX。

## 恢复路径

### TUI 关闭

重新从同一项目根目录启动 `codex`，读取 `loopx status`，再恢复原 Goal。不要重新 bootstrap
一个相同 objective，那会给你两个指向同一目标的 Goal。

### `/goal` body 过期

稳定 body 不复制动态 Todo，但协议或 CLI 版本可能变化。重新生成当前 thin task body，并让 Host
替换 visible Goal；不要手改内部字段来"兼容"旧 prompt。

### 误用了隐藏 worker

停止该 worker，检查它是否写回了新 evidence 或 lease。先恢复 Todo ownership，再回到 visible
TUI；不要让两个执行者并发修改同一工作树。检查这件事时要看 claim 与 lease 的实际归属，而不是看你
记忆中谁在跑。

### Goal 无变化轮询

达到 unchanged limit 后，Goal 应阻塞或安静等待。外部状态观察应转成 monitor Todo；用户通过
Host 的 Goal resume 表面恢复，而不是反复重发完整任务。反复重发会让同一轮工作看起来像多轮进展。

### App 与 CLI 同时激活

检查 claim、lease 与 scheduler ownership。两种 Host 可以读同一 Goal，但同一个有副作用的 Todo
只能有一个合法执行者。

## 不变式

1. **没有调用就没有那一轮。** CLI 不自驱，任何"它在后台跑"的假设都需要单独证据。
2. **setup Turn 只建立连接。** 连接和交付混在一轮里，后续每一步都建立在一个未审的计划上。
3. **`/goal` body 保持稳定。** 动态 Todo、Gate 和能力来自当次 decision packet，不来自 prompt。
4. **visible Goal 与 selected Todo 是两件事。** Goal 能继续，不代表这个 Todo 就该做。
5. **identity 一律显式。** 缺失或不匹配时 fail closed，不回退到"唯一身份"。
6. **一个 effectful Todo 只有一个合法执行者。** 两个 Host 可以并存，执行权不能。

## 完成项目接入之后

到这里，你已经可以在不修改 LoopX core 的情况下：

- 让现有 Git 项目拥有可恢复的 Goal、Todo、Gate 与 evidence；
- 从 Codex App 或 visible Codex CLI TUI 启动同一套项目状态；
- 在 Host 切换时保留 authority、identity 与 workspace boundary；
- 用 status、history 与 quota 检查真实 continuation。

接下来按目标选择：

- 要给 LoopX core 提交协议级改动，进入[协议地图与贡献入口]（./source-protocol-map.md）；
- 要交付独立安装的 Provider，进入[选择正确的放置位置]（./08-extension-placement.md）；
- 只使用 LoopX 管理项目，可以直接把本章模式应用到自己的 repository。
