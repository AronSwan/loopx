# 控制器 vs 底座质量能力对照（双席交叉终版，2026-10-02）

> 缘起：用户质疑“质量判断和修复逻辑是自制控制器的核心竞争力（底座没有）”——“你确定？先深入了解底座吧”。
> 两席独立深查后交叉验证：甲席逐文件翻底座包，乙席逐项对照控制器函数。结论收敛。

## 一句话结论

**“底座没有质量判断”是错的。** 底座有 27 个质量机制族，我们只用了零头；
控制器的正确叙事是——**在底座质量原语之上，补文档域机械门禁 + 把官方手动修复 playbook 自动化**。

## 底座质量能力（27 机制族，两席共识）

turn 后验三态 / `--validation-command-json` argv 级验证器 / goal 验收 pin（TOCTOU 双读）/
change_quality（oracle 发现 + scope 指纹 + receipt stale 语义）/ 评审批组装（typed verdict 契约，
`pr_review_queue/review_contract.py`）/ 证据台账（deep_research ledger：无台账证据的回答被拒，
`deep_research/runtime.py:504`）/ 穷举 oracle 示范（`examples/collaboration-delivery/verify.py`
正例 8+反例 6）/ typed 修复重试状态机（`loop_controller.py:438-479`）/ LLM 请求内重试 /
恢复评估 + session 恢复和解 / 检查点守卫 / 预合并闸门 / 就绪分（promotion-gate/readiness）/
沙箱边界 / todo 完成门禁 / turn journal（attempt/max_attempts **唯一权威**，
`turn_driver/managed_step.py:14`）/ finish_reason 结构化分类（截断≠完成）/ 首过率质量指标
（`issue_fix/metrics_projection.py:903` first_push_ci_pass_rate）等。

## 控制器 40 函数的四分类（双席交叉后）

### A. 正确复用底座（留着，别动）——3+ 处
- `quota should-run` 接入重试决策（3ae22d801，用户令“充分用到底座先进功能”）
- `execute_turn` 把自己的 validate 作 `--validation-command-json` 传给 `turn run-once`
  ——与官方 `examples/collaboration-delivery/demo.py:366-404` **逐字同款接线**
- 盲评 oracle 模式（verify.py 独立验证器）的精神沿用

### B. 底座有 typed 等价物，形态不同（知晓即可，不强行迁移）——6 处
- 裁决收尾正则 ↔ 底座 typed verdict_values（goal_achieved/…，强制 minimum_repair 字段）：
  底座管 JSON 裁决，我们管 markdown 自由文本——两条路线
- 三段式诊断 ↔ not_yet_proven 的 trigger/observed_evidence/minimum_repair typed 三段
- 终稿引用双评审 ↔ manager_context 文档化契约（“incorporates or rejects the findings”）
- 盲评隔离机械检查 ↔ 官方 demo 的**结构性隔离**（独立 worktree+独立 home+串行两轮，
  设计上回避并行盲评）——手段自研，目的相同
- 修复反馈文件 ↔ 官方手册化 `outputs/repair-feedback.md` + `--attempt N` playbook
  ——我们把它自动化了（见 D）
- 指数退避 ↔ 底座 blocked_retry/llm-retry：层次不同（编排级 vs 请求级），不算重复

### C. 重复造轮（该改，按优先级）——2 处
1. **pass^k 台账自造数据源**：`attempts_ledger` 数 home-* 目录，而底座 turn journal 才是
   attempt 唯一权威（`managed_step.py:14` 实锤），且 `metrics_projection.py` 已有首过率指标。
   → 待办：迁读 turn journal（需先对齐“0 次棒不进分母”等自有语义，另案评估）。
2. ~~API 健康探针~~：**已修**（3ae22d801 降级为 should-run 不可用时的保底）。

### D. 真空白（控制器的真正价值，留着并讲好）——两族
1. **文档域机械质量门禁**：URL 归一化引用计数（粘尾/大小写/末斜杠防骗）、裁决收尾正则、
   主题匹配灾难绊线、终稿双评审字符串门禁、Jaccard 跨 agent 同质化度量
   ——底座对自由文本成品文档没有任何机械门禁。
2. **修复环自动化编排**：`_failing_phases`（失败项→负责 phase 路由）+ `ensure_phase` /
   `gate_with_repair`（反馈→重跑→重验闭环）。底座只给原语和手动 playbook
   （`managed_step.py:1-18` 明说“caller decides”——**底座故意不做闭环**），闭环是我们写的。

### E. 学底座（本次已落地）——1 处
- **change_quality 的 scope_fingerprint + receipt stale 语义**
  （`capabilities/change_quality/scope.py` 指纹 + `receipt.py` stale_receipt 状态机）：
  质量判定只对其被计算时的精确内容有效。
  → 已落地为 `repair-receipt.json`（repair_receipt_v0）：每修复轮记被修工件前后 sha256
  （证明“修复真动了工件”；没变却过验=审计疑点）+ 下游陈旧信号
  （LoopsBench obligation retention：上游变了下游未修——full re-gate 本就会重验全部工件，
  此字段是信号非拦截）。无修复轮=底座 no_changes 语义，不落回执。

## 对“核心竞争力”判断的修正

| 原判断 | 修正后 |
|---|---|
| 质量判断和修复逻辑底座没有，是我们的核心竞争力 | 底座质量原语远比“没有”厚；竞争力 = **文档域门禁 + 修复环自动化**这两族真空白的组合，且修复环本身站在底座 validation-command 机制肩膀上 |

## 待办（不阻断，另案）

| 项 | 内容 | 依据 |
|---|---|---|
| 1 | pass^k 台账迁读 turn journal（先对齐自有语义再动） | C-1，managed_step.py:14 |
| 2 | 盲评隔离：评估是否借官方结构性隔离（串行两轮）简化并行盲评设计 | B，collaboration-delivery README |
| 3 | 底座 typed verdict 契约是否引入评审任务书（与现行文本裁决并行评估） | B，review_contract.py:323 |

---
*甲席：逐文件深查（27 机制族清单）；乙席：逐项对照（40 函数四分类）。分歧已合议：退避/幂等跳过属编排级正当关注，不算重复；pass^k 台账经实锤降级为重复项。*
