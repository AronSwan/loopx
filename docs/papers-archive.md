# 论文档案（LoopX×dsh 最优实践研究·学术底座）

> 法源：用户令"为这些论文单独建档并不时了解业界学界最新动态趋势"。
> 与 `docs/upstream-tracking.md`（底座演化巡读）平行的**学术跟踪档案**。
> 维护规则：每篇带 arXiv ID/身份考据/与我们的关系/行动清单；延伸读复用同模板；
> 学界动态跟踪见文末"跟踪议程"。版本：2026-10-03 立。

## 一、五篇核心（初读+复精读完成）

| # | 论文 | arXiv | 核心主张 | 与我们系统的交接 | 行动清单 |
|---|---|---|---|---|---|
| 1 | **LoopsBench** | 2608.00267 | 依赖DAG基准；obligation retention=**反向保持**（已过闸测试持续回归强制，非前向失效）；RR=Resolve Rate | 修复环义务保持的理论根基；verdicts 时间序列灵感源 | ①verdicts 时间序列落盘（未做）②13场叙事二维化（未做）③discriminativeness 已审计 |
| 2 | **DeMem** | 2605.10870 | 决策中心记忆压缩；保"区分"非描述（Thm1充要）；率失真预算=answer-time 注入字符 | staging 全量复制=最弱一层；repair-feedback=朴素 DeMem 做对了 | ⑧a 注入字符会计已上线；⑧b 决策相关性层判定不做（context 不紧） |
| 3 | **SAVI** | 2210.01948 | 任意时刻有效推断；e-process/confidence sequence；§6.4 e-hacking=我们的病（看完数据选假设） | 锁定协议 v2 的统计学地基；ALL-IN 跨场连乘合法 | 锁定协议 v2 已立（θ₀=0.33 出 CI/e-process/判读封口）；e 值台账机器化待做 |
| 4 | **ALE（Agents' Last Exam）** | 2606.05405 | 职业工作流真实性基准（经济**锚定**非核算）；harness 只解释 4.9-7.2pp 方差 vs backbone 16.8pp=**编队不是差异化变量**；93.2% code judge | 文档域机械门禁获实证背书；"连续100%"缺拒收反证（spuriously permissive） | 门禁对抗抽检常态化（未做）；老板包价值陈述改委托成本+gate化红线（未做） |
| 5 | **Cordis** | （非论文，cordiverse/cordis 元框架，dsh vendored @4.0.4） | 无特权核心的可逆组合；判断与编排永远在 policy/caller 层；caller decides | 修复环自动化的范式背书；机械隔离=completion-time audit | 门禁 owns-decision 标注（未做）；run interval 明文（未做）；门禁拓扑无关化（未做） |

## 二、延伸读（五席进行中，2026-10-03 派出）

| 延伸自 | 选题方向 | 交叉点 | 状态 |
|---|---|---|---|
| LoopsBench | 循环工程/义务保持上游（或 SWE-bench 族） | verdicts 时间序列设计参照 | 在跑 |
| DeMem | 记忆压缩/RAG 基础（Mnemis/MemGPT） | staging 批评补强或缓和 | 在跑 |
| **SAVI 应用** | **Anytime-Valid LLM Leaderboards（2609.32248）** | **模型/系统更新对 e 链的影响=直接命中"底座升级=锚演化事件"** | 在跑 |
| Cordis 同源 | agent 控制平面/编排范式 | 门禁契约拓扑无关化 | 在跑 |
| ALE 关联 | GDPval/RLI（真做经济核算的基准） | 老板包价值陈述核算方法 | 在跑 |

## 三、论文全文存档（`.local/papers/`）

- `loopsbench-2608.00267.{pdf,txt}`
- `demem-2605.10870.{html,txt}`
- ALE/SAVI 抓取稿在审计 scratch（TEMP）——如需重下：`curl -x http://127.0.0.1:7890 arxiv.org/pdf/<id>`（SSL 加 `--ssl-no-revoke`）

## 四、学界动态跟踪议程（常态化，与底座演化巡读同级）

> 目标：不是"读完五篇就完"，是**持续跟踪这些理论线的业界学界最新动态**。

1. **周期巡读（与底座巡读同档，周频/双周频，30-60 分钟）**：
   - 跟踪源：arXiv cs.AI/cs.SE 新帖（关键词：agent harness/loop engineering/agent memory/anytime-valid/agent benchmark/economic value）；五篇核心论文的 **citation 更新**（Google Scholar / Semantic Scholar API 查"谁引了它们"）；上游 LoopX 博客/RFC（RSI 方向文就是活样本）
   - 动作：对每条新动态判"无关/知晓/延伸读"——够分量的进延伸读队列
2. **触发式延伸读**：五篇核心出新版（v2/v3）、同作者新工作、引用它们的重要新论文——任一触发一席延伸精读
3. **档案更新**：每篇延伸读归队后按本模板入第四节表格；学界判断变化（如某理论被证伪/取代）时修订第一节"核心主张"
4. **与研究的闭环**：新洞察按惯例进"已做/该做最小必要/不做"三分——**学术跟踪不是收藏，是给控制器与协议供血**

---
*立档：协调会话 2026-10-03。论文全文在 `.local/papers/`；延伸读五席在跑；跟踪议程与 `docs/upstream-tracking.md`（底座演化）并行——两条治理线：一条跟代码（底座），一条跟理论（学界）。*
