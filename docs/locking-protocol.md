# 首试率确认性检验·锁定协议（pre-registration v2）

> **锁定即承诺**：本文件 commit 锚工件（lock-anchor.json，含协议锚 hash+推送 sha+push 事件
> 时间，推送远端时人工落盘）之后的第一次模型调用起，确认性窗口开启。
> 依据：SAVI 席（arXiv 2210.01948 §6.4）——历史问题不是 optional stopping，是 e-hacking。
> **v2 变更**（合规组四处死角清偿）：①锚工件钉死+远端祖先校验（原动态取锚漂移无校验）；
> ②第三方锚机器绑定（lock-anchor.json 落 push 事件时间，原 lock.at 本地时钟+自报布尔）；
> ③灾难场排除程序（死于 gate 前的场有独立排除路径，原四要件只在 gate-report 里结构性缺席）；
> ④≥10min 证据产出于同根重开累积（原单次跑 3.5min 产不出）+e 值台账落盘位置。

## 1. 历史定性（不可追溯更改）

**r1-r13 永久标记 exploratory**：两重根因修复的验收样本与效果宣称样本同源。
不做追溯 e-value（事后补正是 §6.4 明示的 e-hacking 实例）。

## 2. 锁定的假设与主张

- **检验命题（按场级数据）**：当前系统的场级 clean 概率 θ_clean 高于基线 **θ₀ = 0.33**。
- **θ₀ = 0.33 的出处（明示）**：修复前历史（r2-r9）场级 clean 率 = 0/8，其 Wilson95 上界 =
  z²/(n+z²) = 3.8416/11.8416 ≈ 0.3244，取 0.33 以真正落在历史 CI 之外。
- 检验形式：e-process——单场 clean 乘子 θ/θ₀ = 0.6/0.33 ≈ **1.818**，¬clean 乘子
  (1-θ)/(1-θ₀) = 0.4/0.67 ≈ **0.597**，跨场连乘（ALL-IN，§6.1）合法。

## 3. 锁定的度量（以 5fb66ec1d 实现为准）

- **权威源**：turn journal（`runtime/goals/<goal>/turns/*.json`）；home 计数仅作对账，
  `attempts_drift` 落 gate-report。
- **主终点（推断用）**：**场级 clean**——一场=一个运行根的最终结算；同根多次发射=同一场
  （journal 累计如实计入，死亡轮不 reset）。clean := 场内全部活棒 attempts==1。
  棒级不独立（SAVI 聚类警告），不作推断用。
- **次终点（描述用）**：棒级首试率+Wilson95（gate-report `passk_wilson95`）——只描述。
- **e 值台账（v2 落盘）**：每场收场记录到 `.local/confirmatory-e-ledger.jsonl`（跨场追加，
  不被单场 gate-report 覆写），每条含 {run_root, gate-report digests 指纹, clean, e_before,
  e_after, computed_by}。e_t = e_{t-1} × [1.818·1{clean} + 0.597·1{¬clean}]。
- **判读规则（两处，无第三种说法）**：①e ≥ 20 → **以 anytime-α=0.05 拒绝 θ₀=0.33 基线**
  （仍不是"证明 θ≥0.6"）；②满 10 场未达 → "未确认"。可达性：p=1 约 5 场、p=0.75 约 9-10 场。

## 4. 锁定的排除规则（预写死；判据须机器可判+留证）

| 类别 | 判据（须留证） | 处置 |
|---|---|---|
| 外部网络事故 | **probe-log 实证**：`probe-log.jsonl` 显示连续不可达≥10min。**≥10min 产出于同根重开累积**（单次 auto 仅 3.5min 即 SystemExit——同根重开属§3"同根=同场"，append 累积合法） | excluded-external，不进分母，透明报告保留 |
| 底座崩溃（非我方代码） | journal `host_failure`（机器可读）+ `controller-start.snapshot.json`（场 start 的 git HEAD+dirty，5fb66ec1d 实装）证明运行期零改动 | 同上 |
| 操作纪律失误 | 违反一场一管（`.pipeline-lock` pid/ts 实证）或宿主并发污染（裁判认定） | excluded-operator，不进分母，**点名记过** |

**援引排除的四要件（v2 修正灾难场死角）**：①probe-log 实证（同根重开累积≥10min）
②**锁锚一致**（gate-report 有 lock_hash 时比对其与锚工件；**死于 gate 前的场**改为比对
根内 lock.json 与锚工件——lock.json 在首个模型调用前已写，灾难场必在场）③journal_order_ok
（有 journal 时）；**无 journal 的场**以 lock.json 的 at 与锚工件 push 时间比对代替
④裁判署名（probe-log `exclusion_referee`）+ audit 复核书面记录（落 `exclusion-record.json`）。
排除只能引用上表三类；**事后发明新排除类=协议违约**，该场强制计入。
裁判：当场 controller 落盘判定+audit 组复核，判定人写 `exclusion-record.json`。

## 5. 锁定锚与排序核验（v2 机器绑定）

- **锁锚工件（lock-anchor.json，人工落盘）**：推送远端时创建，含 {protocol_hash（协议文件
  锚 commit）, pushed_sha（推送的分支 HEAD）, push_event_at（GitHub push 事件时间=第三方锚）}。
  **它才是锁**，不是任何本地时间戳。
- **锚校验（fail-closed）**：`auto()` 写 lock.json 前，校验 lock-anchor.json 的 protocol_hash
  是 `origin/local-harness` 的祖先（`git merge-base --is-ancestor`）——漂移（协议推送后又
  本地改）则拒绝开窗，不静默锚到未推送 commit。
- **场内写锁（K3 已实装）**：`lock.json`（{hash, at, pushed}），hash=锚工件 protocol_hash，
  at 仅作参考（真锚=锚工件的 push_event_at）。
- **排序核验（K4 已实装）**：`gate()` 读最早 journal 时间（真锚=turns/*.lock.holder 的
  `acquired_at`，fallback=journal mtime）与 lock.at 比对——`journal_order_ok=false` 则该场
  不算窗口数据。

## 6. 禁改条款

确认性窗口开启后，以下改动对该窗口无效且记违约：假设数值/主终点定义/排除类别/判读阈值。
需要变更=立 v3 协议+新锚工件+开新窗口，旧窗口数据降级 exploratory。
**窗口开启后，协议文件的任何编辑性改动（typo/行号）也须在新窗口生效**——本窗口锚冻结于
开窗 commit（合规组 G2 灰色清偿）。"修完跑、跑完修"合法，非法的只是对本窗口既改协议又引用结论。

## 7. 防作弊自检（每场收场清单追加）

- [ ] lock-anchor.json 在场且 protocol_hash 通过祖先校验？
- [ ] gate-report 的 attempts_source=turn_journal？attempts_drift 空？lock_hash==锚工件 protocol_hash？
- [ ] journal_order_ok=true？journal_earliest > lock.at？
- [ ] 排除引用是否限于第 4 节三类且四要件齐（含 exclusion-record.json 裁判署名+audit 复核）？
- [ ] e 值台账 `.local/confirmatory-e-ledger.jsonl` 追加一条且可用 §3 公式独立复算？

---
*v2 锁定于锚工件（lock-anchor.json，推送时人工落盘，含 GitHub push 事件第三方时间锚）。
签署=协调会话；监督=审计组。*
