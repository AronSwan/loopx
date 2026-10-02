# LoopX + dsh 最优实践手册

> 法源：用户令"深刻研究loopx+dsh的最优实践方式"（2026-10-02）。
> 数据基础：11 场编队实测（r2-r11，78 棒）+ 官方文档/示例对比（LoopX main / dsh v0.2.0-rc.2）。
> 研究方法：双席并发——数据席（自家运行数据挖掘）+ 官方差距席（文档/示例 vs 用法对比），交叉合并。

---

## 一、当前用法 vs 官方推荐：完整对比表

### 1.1 LoopX 控制面（已用 ✓ / 未用 ✗）

| 能力 | 我们 | 官方 | 差距 | 改进建议 |
|---|---|---|---|---|
| turn run-once | ✓ 全链 | ✓ demo 串行 7 棒 | **我们更深**：并行 DAG fan-out（N 路）+ 难度路由 | 保持 |
| todo add/update | ✓ 每棒绑定 | ✓ | 一致 | 保持 |
| peers.request/deliver | ✓ 控制器代办 | ✓ + sha256 摘要 | **缺 sha256**：修复环重跑后无法区分对哪版 inputs 发的 | staging 时算 sha256 塞进 brief inputs |
| drain/readback | ✗ 从未调用 | ✓ demo `readback` 动作 | **终稿不回管家对话**：老板永远停在 "Delegation saved." | auto() 末尾加 drain() 回传终稿结论（~15 行） |
| registry | ✓ | ✓ | 一致 | 保持 |
| goals 子系统 | ✗ 单发 DAG 不需要 | ✓ 长周期目标 | 设计差异非差距 | 不接（单回合有界任务无续跑需求） |
| delegation/settlement | ✗ | ✓ | 部分用（turn 结算） | settlement 恢复流待接 |
| authority/quota | ✗ | ✓ should-run 外环 | 重试判断全在控制器 | "单棒该不该再跑"可换调 should-run |
| deepresearch | ✗ | ✓ claim/evidence 台账 | 我们的"引用≥3 URL"是数量门禁，官方是主张-证据-立场结构化台账 | reviewer-1 可增配 claim 登记任务 |

### 1.2 dsh 运行时（已用 ✓ / 未用 ✗）

| 能力 | 我们 | 官方 | 差距 | 改进建议 |
|---|---|---|---|---|
| glm-5.3-flash@max | ✓ 全棒恒定 | demo 用 high | effort=max 是用户令（红线）；planner 是最明确降档候选 | 申请受控 A/B：仅 planner 降 high |
| isolated-headless | ✓ | ✓ | 一致 | 保持 |
| per-actor workspace | ✓ | ✓ | 一致 | 保持 |
| per-actor model | ✗ 全体同模型 | ✓ `--dsh-model` 每棒可传 | "角色-难度-模型"分层未用 | execute_turn 加 PHASE_MODEL 字典 |
| subagent/fork | ✗ | ✓ | 与"控制器 authored DAG"方向相反 | 仅评审棒试点（机械扇出场景） |
| skill 系统 | ✗ | ✓ | 裁决契约/引用契约硬编码在任务书 | 可做成 workspace skill（更可能被读到） |
| jobs 后台并行 | ✗ | ✓ run_in_background + job_output | **research 段最大耗时段未并行** | 调研员任务书改为并行 fetch |
| workflow | ✗ | ✓ | 有意取舍（可审计性优先） | 声明为 intentional divergence |
| read_image | ✗ | ✓ | 纯文本课题不适用 | 未来图表/截图类课题再开 |

### 1.3 工件管理

| 能力 | 我们 | 官方 | 差距 | 改进建议 |
|---|---|---|---|---|
| 工件转移 | shutil.copy | git add → commit → show | **无版本溯源**：reviewer 看到的 inputs 无 commit 证据 | architect/reviewer 转移走 worktree commit |
| 工件摘要 | gate-report 终局一次性 | demo 每次转移带 sha256 | 中途无法对账 | peer 请求加 sha256（同 1.1） |
| 工人协作工具 | OPERATING.md 一句提及 | demo 每任务教五件套 | **read_context/return_result 等零调用** | finalizer 任务书加 return_result 步骤 |

---

## 二、11 场实测数据关键发现

### 2.1 首试率趋势

| 时代 | 场次 | 首试率 | 根修 |
|---|---|---|---|
| 前时代（r2-r4） | 3 场 | 31-62%（**exploratory**；"31%"系记忆蒸馏下端，journal 复核棒级实测 62.5-78%——口径已废弃，见 locking-protocol.md §1） | 调研员引用格式失败 |
| v1.2 引用双模式后（r5-r9） | 5 场 | 62-88%（**exploratory**） | 评审员裁决格式失败（0/2 四连场） |
| **裁决契约修复后（r10-r11）** | 2 场 | **100%**（9/9 + 8/8，**exploratory·未注册**——验收样本与效果宣称同源，e-hacking 形态，见 locking-protocol.md §1；确认性结论待锁定协议后新场次） | 连续两场零重试 |

**规律**（exploratory 观测，非确认性结论）：planner/architect/finalizer 31 棒观测期内**零重试**（契约清晰的角色观测期内未失败）；失败全部集中在契约描述不足的角色。

### 2.2 性能瓶颈

| 段 | 占比（干净场中位） | 备注 |
|---|---|---|
| research 并行 | 20% | N=4 时 research 仅+23%（并行取最慢棒） |
| finalizer | 15-34% | N=4 时下游+50-115%（读 N 份文档） |
| 双盲评 | 17-31% | 并行 2 路 |
| architect | 10-20% | |
| planner | 7-11% | 恒小且稳定 |
| **修复环** | **0% 或 21-32%** | **全有/全无——首试率是耗时第一杠杆** |

### 2.3 同质化

全部 46 对 J ≤ 0.25，中位 0.0。法规类课题 J 高（0.11-0.25）源于共享官方一手源 = 健康佐证收敛；条目/话术/询证类天然分源 J = 0。**门禁从未因同质化触发。**

### 2.4 Token 经济

| 指标 | 旧底座(0.1.5) | 新底座(0.2.0rc2) | 备注 |
|---|---|---|---|
| output/场 | 157-277K | 232-243K | 持平 |
| **input(未缓存)/场** | **514-737K** | **1.16-1.41M** | **膨胀 2.2-2.7 倍** |
| cacheRead | 3.5-5.9M | 4.9-6.5M | 缓存健康（4-5 倍于未缓存输入） |
| 重试浪费 output | 18-42% | 0-17% | 契约修复后趋零 |

---

## 三、Top 5 优先实施清单

| # | 改进 | 预期收益 | 改动量 | 优先级 |
|---|---|---|---|---|
| **1** | **格式检查前置推广**：把 2bf9d6c 模式（门禁要求前置进任务书+OPERATING.md 双通道）用到一切格式类检查（引用、结构词、裁决收尾） | 契约清晰角色历史零重试（exploratory 观测，非确认性承诺——见 locking-protocol.md）→ 修复环趋零 → 提速 | 任务书模板改动 | **最高** |
| **2** | **drain 回传激活**：auto() 末尾终稿过门禁后加 drain() 回传结论到管家对话 | 协议闭环（委托-回传账本完整） | ~15 行控制器代码 | 高 |
| **3** | **peer 请求加 sha256 + operation_id 轮换**：staging 时算工件哈希塞进 brief inputs；修复轮换 operation_id | 陈旧审批防线（修复环重跑后账本可区分对哪版 inputs 发的） | ~10 行 | 高 |
| **4** | **jobs 后台并行**：调研员任务书改为"独立 web_fetch 用 run_in_background 并行发出，用 job_output 收集" | research 段（最大耗时段）提速 | 纯任务书改动，零控制器改动 | 中高 |
| **5** | **tokenUsage 自动采集**：auto() 结算时从 session_projcache 汇总各棒 tokenUsage 写进 gate-report | 成本可见性（当前数据藏得深，说明书未记载此数据源） | ~10 行 | 中 |

---

## 四、明确不接的（有意取舍，防后人误接）

| 能力 | 不接理由 |
|---|---|
| goal 工具（create_goal/update_goal） | 面向跨自动续跑的长目标；我们的棒是单回合有界任务，接入引入无人授权续跑风险 |
| workflow/ralph | 控制器 authored DAG 是刻意的可审计性选择，与 LoopX 账本强绑定 |
| task-lease 硬租约 | 异 agent 异 lane + TURN_LANE_IN_FLIGHT 已等效 |
| authority/goal-acceptance/checkpoint/dreaming | 均为长周期受监督 goal 的机制，单发 DAG 场景不合 |
| agent-directory/ready-score/capability catalog | 静态 fixture（ACTORS 硬编码注册）下冗余 |

---

## 五、方法论沉淀（从 11 场 + 多轮审计中提炼）

1. **契约前置**：门禁要什么格式，任务书+OPERATING.md 就先教什么格式——"考了没教过的题"是首试率的最大杀手（五连红实证）
2. **自造样本不可自证**：自己写的检查用自己造的例验证=自证循环；真工件（如 r9 两版终稿）当考卷
3. **正则不做语义分析**：方向自洽门禁的失败证明——正则在真实文档上主语错配+否定盲区，语义级检查归模型（评审任务书）承担
4. **修复环不是失败是保险**：21/21 救回 0 耗尽——但首试率是耗时第一杠杆，最优目标=修复环零触发
5. **N 是覆盖面决策不是质量决策**：planner 按子课题自然块数自主路由与全部历史数据一致

---

*v1.0 2026-10-02。数据席（11 场 78 棒）+ 官方差距席（20 项对比）合并。下一步=Top 5 实施。*
