# 门禁 discriminativeness 一次性审计报告（论文行动⑦）

> 方法：消融法——逐相位移除其工件，看**下游检查**是否仍过。若“只喂上游 k-1 相位工件，
> 门禁 k 就过”，则该门禁**未测到本相位自身贡献**（对照 LoopsBench §2.5 的
> discriminativeness 验收：gold 截到祖先仍至少一个测试 failing）。
> 基底：r13 运行根（N=3，含全部 8 棒）。日期：2026-10-02。

## 一、判定总表

| 门禁 | 测的是什么 | 消融表现 | 判定 |
|---|---|---|---|
| `{工件} 存在` / `非空` | 本相位工件在且非空 | 移除即 fail（A/B/C 各自的存在检查全 fail） | **discriminative** |
| `research-{k} 引用>=3` | researcher 引用数 | 未被下游消融触发（检查目标=research 工件本身） | 自足 |
| `review-{k} 裁决收尾` | reviewer 裁决行 | 移除 research/architecture 后仍 PASS | **非 discriminative**（见下） |
| `{工件} 结构词` | finalizer 结构词 | 移除 architecture/双评审后仍 PASS | **非 discriminative** |
| `{工件} 主题匹配(绊线)` | 主题灾难性错配 | 移除 research-1/architecture/双评审后仍 PASS | **非 discriminative** |
| `盲评隔离(a不见b)` | reviewer 互不可见 | 结构保证（inputs 目录无对方文件） | **discriminative**（结构） |
| `final-plan.md 引用双评审` | 终稿引用 review-1/2 | 移除双评审后仍 PASS | **非 discriminative** |
| `final-plan.md 含评审处理` | 终稿含采纳/驳回 | 移除双评审后仍 PASS | **非 discriminative** |

## 二、三层结构（门禁语义真相）

**① 存在性门禁是 discriminative 的**——“research-1 存在/architecture 存在/review 存在”
在移除即 fail。这是门禁的真价值：**它确实测到了“这一相位跑没跑”**。

**② 内容型下游门禁集体非 discriminative**——上游工件（research/architecture/双评审）
被整体移除后，下游的“主题匹配/裁决收尾/结构词/引用双评审/含评审处理”**全部照过**。
原因直白：这些检查是对**下游工件自身文本**的机械断言（字数/关键词/字符串存在性），
它们从不读上游工件——所以上游在不在，它们根本不在乎。

**③ 盲评隔离是结构 discriminative 的**——“reviewer-1 inputs 里不得有 review-2.md”
是目录结构检查，与内容无关，天然测到“隔离是否被破坏”。

## 三、判定含义（诚实说清这不是“门禁无用”）

**这不是说门禁没有价值**——它判定的是：当前门禁体系测的是“**每个相位独立交付了
形式上合格的工件**”，而不是“**终稿真的建立在上游基础上**”。前者存在性已证
（discriminative），后者从未被测（非 discriminative）。

具体到两条最受关注的：
- **“final-plan 引用双评审”非 discriminative** 的含义是：终稿引用 review-1/2 的
  字符串检查，在双评审工件**不存在**时也照过——它测的是“终稿里出现了 review-1
  字样”，不是“终稿真的处理了那份评审”。要 discriminative 需比对该评审的内容
  是否被采纳/驳回（语义级，超出机械门禁能力——这正是评审B任务书指令承担的部分，
  见 controller-vs-base.md §E）。
- **“主题匹配”非 discriminative** 的含义是：绊线（命中≥1/3 主题词）在上游全无时
  仍过——它只拦“整体课题替换”级灾难，不拦“脱离上游瞎写”。

## 四、结论

**门禁体系的 discriminativeness 边界 = 存在性检查 + 盲评隔离**；内容型检查是
“工件自身形式合规”的独立断言，对上游消融免疫。该结论与控制器自身定位一致
（controller-vs-base.md §B：“真质量权威始终是评审+穷举门禁，不是代理指标”）——
机械门禁本就只该管“形式合规”，内容-上游一致性归评审。

**不新增门禁**（最小必要；该审计目的是刻画边界不是加机制）。若未来要让某条
内容门禁变 discriminative，候选是它读上游工件做内容对账（成本=引入假阳性），
列为可选评估项。

---
*一次性审计，不重复跑。复现：`.local` r13 副本 + 消融脚本（`%TEMP%`，临时）。*
