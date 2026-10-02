# 底座优缺点总账（LoopX 1.2.3 × dsh 0.2.0rc2，立账 2026-10-02）

> 法源：用户令"先深刻了解底座，优点缺点都要有数"。
> 与 controller-vs-base.md 互补：那份答"控制器 vs 底座谁做什么"，本份答"底座本身好坏在哪"。
> 维护规则：每条带证据等级+版本/行号锚；销账须外部锚（"多副本共识"若证人互为抄写=自证循环，2026-10-02 教训）；底座升级后逐条复核。

## 证据等级

铁证（可复现+已排除"有文档"反证）｜实证（实跑过）｜代码级（读码+行号，未端到端复现）｜使用方证词（我们的生产经历）｜设计立场（像缺点但不是缺陷）

## 一、优点账

| # | 优点 | 证据 | 等级 |
|---|---|---|---|
| 1 | **质量机制族：甲席全量 27 / 双席共识 18 核心**（口径注明，见 controller-vs-base.md §底座节）：turn 后验三态/`--validation-command-json`/goal 验收 pin/change_quality/typed 裁决/证据台账/穷举 oracle 示范/typed retry/turn journal/恢复评估/检查点/预合并闸门/就绪分等 | controller-vs-base.md（双席交叉；27 为甲席逐文件全量口径，18 为两席共识核心） | 实证 |
| 2 | **turn journal 是 attempt 唯一权威**——外层观测只被对账、绝不被相信 | managed_step.py:14-16 逐字 | 铁证 |
| 3 | **change_quality 的 scope_fingerprint+receipt stale 语义**——判定只对被计算时的精确内容有效 | scope.py:168/receipt.py:46-48；已移植为 repair-receipt | 实证 |
| 4 | **typed 裁决契约**——verdict 枚举+强制 minimum_repair/validation_commands 字段 | review_contract.py:323-329/346-348/384-404 | 代码级 |
| 5 | **Cordis 范式：无特权核心可逆组合**——一切能力是插件，判断永远在 policy/caller 层 | vendored `@deepseek-ai/cordis` **4.0.4**（harness-020/vendor/cordis/package.json 实证；上游 cordiverse/cordis 4.0.0-rc.7@56b3d4f，vendor/README.md 清单）；cordis-primer.md 五观念 | 实证 |
| 6 | **实战成绩：13 场实跑零底座崩溃**（r9=宿主并发污染、r13=网络+我方旧代码，均非底座崩）。**对读注（精读审计补）**：中途死亡 3/13（r9/r12/r13）——锐利契约×无守卫控制器年代的代价面，须与缺点#1 对读，勿单引战绩 | .local/research1-13-run 全存证；台账 3-1-2/r12 复活/r13-run3 | 使用方证词 |
| 7 | 冷启动 2.6-5.8s（三样本），180s initialize 门余量 30x+ | 台账 2-1-5（c356847） | 实证 |
| 8 | **上游响应性好**：我方 #5356 当周合并、#5397 次日修复 | git 上游记录 | 铁证 |
| 9 | 官方 demo 示范**独立穷举 oracle** 模式（8 正例+6 反例含无效输入拒收） | examples/collaboration-delivery/verify.py | 实证 |
| 10 | 官方修复 playbook 手册化（repair-feedback.md + --attempt N）——底座给原语、文档给流程 | demo README；managed_step.py:19-21 "caller decides" | 代码级 |

## 二、缺点账

| # | 缺点 | 证据 | 等级 | 现状 |
|---|---|---|---|---|
| 1 | **契约锋利：三种静默失败**——append_message 同 ID 吞新文本无信号 / drain 入口不校验 external_sender 可调用性 / latest_session 双通道命名空间 goal 查询静默空手 | **issue #5462 已报**（三段复现脚本+两起我方生产受害）；chat_store.py:663-666/600/97-101, roundtrip.py:876/1119-1123 | 铁证 | 已上报+自纠评论（5951699007），待响应 |
| 2 | **API 无文档**：四个公开方法三个零 docstring；append_message/channel 语义/external_sender 要求在 loopx 与 dsh 双 docs 语料**零命中**（python rglob 双语料复核） | docs 语料 grep=0 | 铁证 | 随 #5462 |
| 3 | **硬常量无旋钮**：就绪/锁 15s 死线为模块级常量，无 env/config 通路 | effect_runtime.py:46-47 唯一定义+两处使用 | 代码级 | 裁定维持+翻案条件（台账 12-2-4 补丁版） |
| 4 | **宿主并发无保护**：同 DSH_HOME 多进程官方明示未承诺；r9 首犯=宿主并发 pytest（非管线，防撞闸不覆盖） | 台账 2-1-7/3-1-2/乙席 C4 | 使用方证词+官方明示 | 一场一管（口头纪律，未入守则——待办） |
| 5 | **提供方协议坑 12 条**（GLM 端点，非底座之罪但 SDK 不加警告）：thinking:disabled 静默吞/401 三信封并存/message_start usage 全零真值在 delta/tool_use 用 call_ 前缀/SSE 无首心跳（<5s 判活误杀）等 | 台账 2-2-1~12 | 实证 | 主手册 v1.7+ 已载（**版本引用须查台账 5-2-4 现值，勿引快照版本**）；v2.2 守卫判据表待三信封化 |
| 6 | **观察通道单薄**：last-cli-failure.log 每次覆写只存末份——历史击穿全靠 stdout 重定向纪律 | 乙席 C5 边界 | 代码级 | 监测 grep 已钉收场清单（12-2-4） |
| 7 | shutdown_timeout 默认 1.0s 激进（每棒收尾硬杀 292MB runtime） | 台账 2-1-2 | 实证 | 已用官方旋钮 10s（c356847） |
| 8 | **context 足迹增长快（底座×GLM 组合，三次勘误后定稿）**：底座 `contextPressure` 字段实测——finalizer 单请求上下文峰值 r9=62,259 → r10=124,975（**两场翻倍**；占 1M 配置窗 12.5%，当前不紧但增长曲线陡）；棒均 token +58%（台账 4-2-1）订阅不疼钱但 context 随题材复杂度上行；staging 全量复制是最强增长源（DeMem 席）。**勘误链存证**：原"96% of 128K"系双重错（累计 uncached≠单请求压力；新底座窗=1M）；63dfcd3cb 的"精修 124,977"更错——r9 累计输入与 r10 压力值巧合差 2，拿巧合数字验证巧合数字 | r9/r10 finalizer projcache `contextPressure`/`tokenUsage` 字段级实测 | 实证 | 待办：staging 决策相关性层+每棒注入字符会计（论文行动清单⑧） |

## 三、设计立场（像缺点，不是缺陷——引用时勿当弹药）

- **"caller decides"不闭环**：Cordis 明示立场（followup 无句柄/恢复须 human-authorized/观察通道切断能力泄露）——我们修复环的正当性根基，正当性条件=run interval 明文+判断只挂文档化扩展点（Cordis 席 N1，待办）。
- **fail-fast 15s**：官方设计，真兜底=重试本身（r9 实证修复轮救回）。
- **空内容不入史/未知终态按失败**：settlement 纪律，正确。

## 四、未知数（诚实清单——"有数"包括知道自己没数的地方）

| # | 未知 | 为什么没数 |
|---|---|---|
| 1 | 多会话 chat UI 场景下 latest-session 胜出语义 | 13 场全是单管家会话（甲席 B3 理论风险） |
| 2 | 新防线下 15s 死线真实余量 | 未做静默对照实验；靠翻案监测兜着 |
| 3 | 27 机制族实际能力边界 | 只正确复用 3 处，多数族未在我们场景用过 |
| 4 | #5462 三契约是否上游认定 by design | 待上游响应；ergonomics 定性已预写反例防线 |

## 五、结论口径（对外一句话）

底座**无急症、有慢病**：质量机制厚实（27 族）+实战零崩+上游响应快；慢病集中在**契约锋利（静默失败）+文档缺位+无旋钮**——全部可在调用侧规避（我们已规避），报上游让所有人受益（#5462）。

---
*立账：协调会话 2026-10-02。证据锚均在本仓或台账可查；升级底座后逐条复核，销账须外部锚。*
