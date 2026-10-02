# 首试率确认性检验·锁定协议（pre-registration v1.1）

> **锁定即承诺**：本文件提交（commit 哈希+时间戳，经远端推送锚定）之后的第一次模型调用起，
> 确认性窗口开启。依据：SAVI 席（arXiv 2210.01948 §6.4）——历史问题不是 optional stopping，
> 是 e-hacking（同一批数据既选假设又下结论）。
> **v1.1 变更**（乙席审计 ea2bd1b48 后重发；v1 未开窗零成本废弃）：①基线口径改写（原"r2-r4
> 实测 0.31"经 journal 复核为记忆蒸馏品——r2-r4 棒级实测 62.5-78%、场级 0/3，没有任何现存
> 口径算出 31%）；②判读措辞超卖修正（e≥20 拒的是基线，不直接"建立 θ≥0.6"）；③排除规则
> 补可判定程序；④锁定锚改远端推送+场内写锁哈希+排序核验条款；⑤optimal-practices 残留标注。

## 1. 历史定性（不可追溯更改）

**r1-r13 永久标记 exploratory**：两重根因修复的验收样本与效果宣称样本同源。
不做追溯 e-value（事后补正是 §6.4 明示的 e-hacking 实例）。

## 2. 锁定的假设与主张

- **检验命题（按场级数据）**：当前系统的场级 clean 概率 θ_clean 高于基线 **θ₀ = 0.3**。
- **θ₀ = 0.3 的出处（明示）**：修复前历史（r2-r9）场级 clean 率 = 0/8，其 Wilson95 上界 =
  z²/(n+z²) = 3.8416/11.8416 ≈ **0.324**，保守取整 = 0.3。**选在历史 CI 上界之外**——
  乙席否决过 0.05（落在历史 CI 内，拒绝它区分不了"修复后"与"历史上限"：p=0.3 的系统
  10 场 4 场 clean 即可达 e=115）。
- 检验形式：e-process——单场 clean 乘子 θ/θ₀ = 0.6/0.3 = **2.0**，¬clean 乘子
  (1-θ)/(1-θ₀) = 0.4/0.7 ≈ **0.571**，跨场连乘（ALL-IN，§6.1）合法。

## 3. 锁定的度量（以 14a024475 实现为准）

- **权威源**：turn journal（`runtime/goals/<goal>/turns/*.json`）；home 计数仅作对账，
  `attempts_drift` 落 gate-report。
- **主终点（推断用）**：**场级 clean**——一场=一个运行根的最终结算；同根多次发射=同一场
  （journal 累计如实计入，死亡轮不 reset——14a024475 r13 实证 14 journal 含 run1 的 11 件）。
  clean := 场内全部活棒 attempts==1。棒级不独立（SAVI 聚类警告），不作推断用。
- **次终点（描述用）**：棒级首试率+Wilson95（gate-report `passk_wilson95`）——只描述。
- **e 值台账**：每场收场记录 e_t = e_{t-1} × [2.0·1{clean} + 0.571·1{¬clean}]。
- **判读规则（两处，无第三种说法）**：①e ≥ 20 → **以 anytime-α=0.05 拒绝 θ₀=0.3 基线**
  （=与"修复前历史上限"不相容；仍不是"证明 θ≥0.6"）；②满 10 场未达 → "未确认"。
  **期望可达性**：真值 p=1 时约 4.3 场、p=0.75 时约 7.9 场达 20——判读非虚设。

## 4. 锁定的排除规则（预写死；判据须机器可判+留证）

| 类别 | 判据（须留证） | 处置 |
|---|---|---|
| 外部网络事故 | **probe-log 实证**：`probe-log.jsonl`（每次决策周期把 should-run/API 探针结果+UTC 时间戳 append 落盘）显示连续不可达≥10min | excluded-external，不进分母，透明报告保留 |
| 底座崩溃（非我方代码） | journal `host_failure`（kind/retryable，机器可读）+ **场 start 记录的控制器 git HEAD+dirty 快照**证明运行期零改动 | 同上 |
| 操作纪律失误 | 违反一场一管（`.pipeline-lock` pid/ts 实证）或宿主并发污染（裁判认定） | excluded-operator，不进分母，**点名记过** |

排除只能引用上表三类；**事后发明新排除类=协议违约**，该场强制计入。
**裁判**：排除援引由当场 controller 落盘判定+audit 组复核——判定人写入 probe-log 同一条。

## 5. 锁定锚与排序核验（v1.1 实装兑付）

- **锁锚**：本文件 commit 哈希+时间戳，且**必须推送远端**（GitHub 服务端 push 事件时间=
  第三方可验证锚；本地 commit 时间戳可伪造）。**推送前跑场=非窗口数据，且不得事后追认**——
  堵 v1.1 原条款真空（乙席 K6）。
- **场内写锁（K3 兑付，已实装）**：窗口开启后 controller 在运行根写 `lock.json`（
  {hash, at, pushed}）；`gate()` 在 gate-report 落 `lock_hash`/`lock_at`/`journal_order_ok`
  /`journal_earliest`——与锁锚一致才算本窗口数据。
- **排序核验（K4 兑付，真实锚已实装）**：`gate()` 读最早 journal 时间并与锁锚比对——
  **真锚=turns/*.lock.holder 的 `acquired_at`**（底座 file_lock.py 写的 UTC 微秒，瞬态，
  现行根均有）；fallback=journal 文件 mtime（holder 已覆写时）。`journal_order_ok=false`
  → 该场不算窗口数据，gate-report 照报。

## 6. 禁改条款

确认性窗口开启后，以下改动对该窗口无效且记违约：假设数值/主终点定义/排除类别/判读阈值。
需要变更=立 v2 协议+开新窗口，旧窗口数据降级 exploratory。
"修完跑、跑完修"的迭代**合法**（ALL-IN 性质），非法的只是对本窗口数据既改协议又引用结论。

## 7. 防作弊自检（每场收场清单追加）

- [ ] gate-report 的 attempts_source=turn_journal？attempts_drift 空否？
- [ ] lock_hash/lock_at 与锁锚一致？本场最早 journal acquired_at > 锁时间？
- [ ] 排除引用是否限于第 4 节三类且 probe-log 留证？裁判署名在？
- [ ] e 值可用 §3 公式独立复算？

---
*v1.1 锁定于提交+推送时点（远端 push 事件为第三方锚）。签署=协调会话；监督=审计组。*
