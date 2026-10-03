# 首试率确认性检验·锁定协议（pre-registration v3.1）

> **锁定即承诺**：本文件 commit 锚工件（lock-anchor.json：protocol_hash+pushed_sha+push_event_at，**推送时人工落盘到将要开场的运行根内**——外层 .local 副本仅为母本，新根须拷入，甲席/乙席锚位置陷阱注记）之后的第一次模型调用起，确认性窗口开启。
> **v3.1 变更**（v3 草案经审计两席对抗审核后修正）：v3 的数学骨架（e-过程/anytime/族链/银行化）经甲席独立推导成立；修正四处——①"总 FWER"措辞偷换（跨族 1−0.95^K 不受控）；②crash×禁重开×同根重发矛盾（禁重开仅限终态）；③克隆乘子农场（台账防克隆）；④机器化承诺按**现货/计划分栏**（乙席 grep 实证：新承诺 8 项原为零行，v3.1 已补 3 件便宜现货，其余明标计划）。

## 1. 历史定性与账本

- **r1-r13 永久 exploratory**；不做追溯 e-value。
- **确认性台账**（`.local/confirmatory-e-ledger.jsonl`，已存在）：第一条=r14（¬clean，e=0.597，族=dsh-0.2.0rc2×loopx-v1.2.3，window=v2-window-A）。
- **追溯处置原则（成文，甲 V6）**：本协议对 v2 窗口数据的追溯处置（r14 计入族链）**仅因全部效果统计保守而合法**（e₀=0.597<1 更难拒绝/¬clean 压低链）——**今后任何协议版本对既有数据的追溯处置仅限保守方向**（使拒绝更难的方向），反保守追溯（如把排除场改判 clean）=违约。
- **哈希约定（乙席追加发现，先于机器化）**：台账条目指纹 = sha256 of `json.dumps(entry_without_entry_sha256, ensure_ascii=False, sort_keys=True)`；r14 原条目的 entry_sha256 按此约定重算入档（原值作废，注明重算）。

## 2. 锁定的假设与主张

- **检验命题**：场级 clean 概率 θ_clean > **θ₀=0.33**（谱系：出自旧底座混合 r2-r9 的 0/8 Wilson95 上界 0.3244——新底座下是**预设 margin 参考点**；禁止以升级后观测重推）。
- **主张措辞（降级+甲 V3 精化）**：e≥20 宣称"**控制器谱系（含链内演化）+当前底座**的整体 clean 率>0.33"——不得归因"我们的修复有效"（新底座可能自带改善）。
- 乘子：clean ×**1.818**，¬clean ×**0.597**（θ=0.6/θ₀=0.33 锁死）。
- **可达性+power 披露（甲 V3，诚实条款）**：自 e=0.597，p=1 约 5.9 场、p=0.75 约 10 场达 e≥20；**p<0.55 时 10 场内功效<12%（p=0.5 仅 6.5%）——检验几乎必然"未确认"，且"未确认"≠"θ≤0.33"（不是阴性结论），只是证据不足**。本协议是系统级 Go/No-Go 门槛认证，不是归因研究，功率剖面如上知情。

## 3. 族链规则（核心）

**族 = 底座身份**（dsh runtime 版本 × loopx 版本——**以 sdk 包版本字串为准**（代码可读 importlib.metadata），runtime_bin 与 sdk 版本号同源；族键须落 settled.json/gate-report，见 §5 计划栏）。

1. **族链跨窗累计，永不 reset**：同族内关窗/重开/同根重发/中途修 controller bug 全部 append 同一条族链（族内演化合法：复合零假设 p_t≤0.33 下乘子期望≤1，甲席独立推导验证）。
2. **换族=新链+新锚+新窗**；旧族链按当时 e **定格**（已过 e≥20 则判定已银行化）；新族链 e₀=1。
3. **重回旧族→旧族链续算**。
4. v2 §6"旧窗口数据降级"条款**废除**——降级不重置任何链。
5. **α 记账（甲 V1 修正措辞）**：**每族主张各自 anytime-α≤0.05**（Ville 界覆盖任意停时策略）；**跨族联合错误率=1−0.95^K 不受控制**（K 族各持 0.05；换族=新 estimand 新主张，**禁止做跨族析取式联合主张**）；链有效性以**场的纳入/排除与结果独立**为前提（§6 裁判纪律）。
6. **台账防篡改+防克隆（甲 V7c 新增）**：每条含 prev_entry_sha256 链式指纹；**gate_report_sha256 全局唯一**（同指纹的场不得二次入账——堵克隆乘子农场：复制已结算 clean 根+删 settled+幂等跳过零模型调用刷 e 的攻击）；**新模型调用证据**（journal attempts 较上一条目严格递增）；每场结算后台账 digest 落 git 跟踪路径（计划，见 §5）。

## 4. 窗口三态与中止程序

判读三处，无第四种：①e≥20 拒绝基线（措辞见 §2）；②满 10 场未达→"未确认"（**计数口径：族链累计场数**，r14 计入）；③**中止**（外因关闭）→"中止（N 场，无确认性结论）"——链上数据定格保留。

**中止程序**：原因分类+证据指纹+**人工落盘 settled.json（status=settled+裁判署名+台账条目引用）**+根冻结。（v3 曾写"settle 机器落盘"——乙席判半空头：settle 子命令是计划（§5），当前为人工程序，措辞如实。）

## 5. 场的结算——现货/计划分栏（乙席框架，v3.1 落实）

**[现货✅]（本轮已实装+测试）**：
- 禁重开 fail-closed **仅限终态 {settled, completed}**——crashed+pending 凭裁判复核可同根重开（甲 V7a：v3"在场即拒"使 r14 式复活机械不可达，已修，auto() 读 status）。
- **auto() 正常完成→settled.json status=completed**（shakeout 件 4 缺口已补）。
- **CLI 失败 append 式留证**：cli-failures.jsonl（时间戳+returncode+args+输出尾 200 字符，覆盖并发）——v3 的"probe-log 风格"现货化；旧 last-cli-failure.log 兼容保留。
- crash-settle 钩子（main() catch-all）/urllib 探针+probe-log+裁判署名/gate-report 锁四字段/排序核验（shakeout 实测过）。
- **场纳入口径（甲 V2b）**：同 lock_hash 下发生过模型调用的根，**须进台账或由裁判书面分类为非确认性场**（exploratory 判据=lock.pushed=false 或裁判注记）。首例裁决：shakeout-run（lock 780ec867 但 pushed=false，exploratory 器械验证场）分类为非确认性场，不进族链——本条即裁决记录。

**[计划📋]（锚定前逐项实现或持续人工，禁止陈述语气冒充现货）**：
- gate() 终局后自动 append e 台账（e 值计算+9 字段 schema+幂等去重，~100 行）——实现前 e 值人工计算，verdict_source=manual+裁判署名。
- settle CLI 子命令（~50 行）——实现前按 §4 人工程序。
- 升版 pre-flight 扫描（有 lock.json 且无 settled.json 的根存在→禁升版）——实现前人工检查（须区分确认性/exploratory 根：lock.pushed 字段）。
- 台账 digest 落 git 跟踪路径。
- window_id 机器生成/族键落盘（gate-report+settled 加 family 字段）。

**升版 pre-flight 人工清单（计划期间执行）**：①扫 `.local/*-run` 的 lock.json/settled.json；②确认性根（pushed=true）全部终态；③裁判对 exploratory 根留分类注记。

## 6. 排除规则（三类不变，补墓碑）

- 三类排除+四要件不变（外部网络≥10min **cli-failures.jsonl/probe-log 时间戳序列实证**/底座崩溃 host_failure+controller-start 快照/操作纪律失误）。
- **排除改判墓碑机制（甲 V2a 新增）**：机器 append（计划）与裁判事后改判冲突的解法——改判不删条目，追加 **voided 条目**（乘子 ×1、status=voided、原条目指纹+裁判署名）；人工台账时代改判同此。
- §4 证据通道补 CLI 阶段：**已现货**（cli-failures.jsonl 覆盖 cli() 全部调用点含 stage_route；timeout/JSON 解析两路在计划栏——当前这两路崩溃走 crash-settle 留痕）。

## 7. 防作弊自检（每场收场）

- [ ] settled.json 在场且 status 与结局相符（completed/crashed→重开时裁判留痕/settled）？
- [ ] gate-report：attempts_source=turn_journal？attempts_drift 如实？锁四字段？journal_order_ok=true？
- [ ] e 台账：人工计算则 verdict_source=manual+裁判署名+prev_entry_sha256 链式连续（哈希约定 §1）？
- [ ] 排除援引三类+证据在（cli-failures 时间戳序列）？改判走墓碑？
- [ ] 场纳入：同 lock 有模型调用的根全部入账或裁判分类？
- [ ] （每 N 场）台账链式指纹人工复算（约定 §1）？

---
*v3.1 锁定于锚工件（推送时人工落盘到运行根）。签署=用户；监督=审计组。法源：终审 G2/G3+门三+shakeout 件 4+审计甲乙两席 v3 对抗审核（2026-10-03）。v2 窗口"中止（1 场，r14 ¬clean，e=0.597 定格）"关闭，族链继承。*
