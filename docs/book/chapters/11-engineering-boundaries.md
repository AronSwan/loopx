# 验证、兼容与安全

本章讲的是如何证明一个设计成立，以及如何不把成本转移到别处。它是工程边界的核心：一套设计可以写得漂亮，但如果没有人能证明它成立，它只是一段主张。

## 从一个坏的结局开始

看一条时间线。它比大多数人愿意承认的更常见：

```text
周一 14:20  作者改了一条 status 输出路径，本地 focused smoke 通过。
周一 15:05  PR CI 红：CLI 输出预算超标 4.1%。
周一 15:30  作者复算了一遍，确认输出确实变大了。他把预算上限从 24000 调到 25000。
周一 15:31  CI 绿。PR 合并。
下周一      下游 lane 的 agent 在一次长路径调用里读到截断的输出，开始选错 Todo。
下周五      没有任何人把这次事故和一周前那个 4.1% 联系起来。
```

失败消失了，但工程约束也被取消了。预算的存在是为了让输出悄悄变大这件事可见。把它调高，可见性就没了；真正的问题仍然在那里——那条路径确实多产出了信息——只是不再有人能看见。

第二种坏结局更安静：

```text
周二 09:10  作者把某个 update event 的默认字段从可选改成必需：反正只有一个 producer。
周二 09:11  全部测试通过。没有 smoke 编码过这个默认值，所以没有测试变红。
周二 11:00  合并。
周三        两个下游 lane 开始用错字段，因为它们的 producer 从未写那个必填字段。
```

这里没有人违反任何一条被检查的规则，因为**被改掉的正是那条没人检查的规则**。默认行为变更不会像一次测试失败那样自己举手。

### 这两个结局的共同结构

两条时间线里，没有一条是忘了跑测试。第一件事作者跑了测试，测试也如实报了红；第二件事测试确实全绿。真正的缺口在两个地方：

- **判断**：预算超标时该压缩、该保留上限，还是该扩容？这个问题没有任何自动化工具能替你回答，因为它取决于那个字段服务哪个消费者、哪个决策。
- **声明**：默认行为变了，这件事必须由作者主动说出来。凡是不落在任何断言里的行为，都不会因为没人报告而变得没发生。

## 为什么再加一层验证不解决问题

自然的反应是加一层验证，或者干脆每次跑全套。这两条路都堵着：

- **全套验证很慢、很贵。** 确定性测试、focused smoke、canary premerge、真实后端集成、模型行为资格、release gate，全跑一遍的成本足以让作者开始找捷径，而找捷径正是本章开头那个结局的成因。
- **重新验证不等于重新判断。** 把 `measurement-only` 当成通过、把跳过的测试当成环境问题、把调高上限当成修复，这三件事在语义上完全一样：都是用一次绿替换一次未回答的问题。

所以设计目标从有没有验证换成两个更窄也更可执行的问题：**这份证据证明了什么，以及它还留了什么没证明。** 判断归作者和 review，证据的形状归合同。

## 证据梯子：各层证明不同的事

这些层按代价递增排列。每层回答的问题不同，高层的绿不能替代低层的绿。

### 一层：确定性测试

确定性测试是梯子的地基，其余各层都踩在它上面：schema、非法状态转移、精确字段存在性、冷路径恢复、重放幂等，全部归它。一条不能稳定复现的测试不能作为证据，只能作为线索。

```bash
uv run --extra test python -m pytest -q
uv run --extra test python examples/control_plane/cli-output-budget-regression-smoke.py
```

这一层里最小的一步是 artifact validation，确认文件和 schema 自洽：Markdown 可以构建、内部链接存在、JSON 与 TOML 可解析、request/response 满足 JSON Schema、fixture 可以从头创建。主书自身的门禁是：

```bash
python3 -m pip install -r docs/requirements-docs.txt
python3 examples/dev-book-publication-smoke.py
mkdocs build --strict
```

不要只验证 Markdown 能被单独解析，还要验证它在 LoopX 的统一 `mkdocs.yaml` 导航、GitHub Pages base path 和首页 Learn 路径中可发现。站点由 LoopX monorepo 的 MkDocs Material 发布链路构建，依赖范围以 `docs/requirements-docs.txt` 为准，book 导航、双语路由、官方首页入口与 Labs 排除边界由 `examples/dev-book-publication-smoke.py` 守护。依赖变更后补跑 `python3 -m pip check` 与 `mkdocs build --strict`。改动任何 UI 或文档视觉之前，先读 `docs/development/design.md`。

本书配套的 standalone Extension 示例可以这样独立复现（在一个含 `standalone-extension/` 的工作区里执行）：

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -e './standalone-extension[test]'
python3 -m pytest standalone-extension
```

这四步是"文档里的代码确实可运行"的最小证明；只在 Markdown 层面检查语法，证明不了这一点。

### 二层：product-surface validation

确认教程使用的是发布物真实表面：

```bash
loopx --version
loopx doctor
loopx doctor --deep
loopx start-goal --help
loopx capability list --format json
loopx extension --help
```

命令存在不等于流程已验证。Host automation、visible Goal 与 Extension activation 各自需要 readback；`doctor --deep` 还会启动并探测发布物携带的 TypeScript Effect runtime。迁移中的 Python facade 成功返回，也不单独证明 TypeScript semantic owner、runtime decoder 和 durable effect path 都已通过。

### 三层：lifecycle validation

项目接入至少验证：reconnect 复用已有状态、status 能找到 active Goal、local state 被 Git 忽略、Host activation 可观察、quota 与 selected Todo 一致。

Extension/package lifecycle 贡献至少验证：package entrypoint 可解析、doctor 成功且无 effect、install 生成 revision-bound state、disable 后不能 run、enable 重新 doctor、invalid request fail closed、upgrade 失败不破坏当前 revision。

Control Plane、Capability、Provider、Host/Runner 或 Projection 贡献至少验证：预期决策来自独立审阅的 invariant 而非当前实现输出；unit/contract test 覆盖正例、反例与非法状态；focused smoke 或 public-safe replay 经过真实协议链；受影响的 consumer（agent-facing output、scheduler、writeback）得到对应检查；Capability 有真实 caller、outcome contract 和 Domain State owner；Provider 只返回 bounded observation/effect/readback，不获得 Goal authority；Host/Runner 保持 typed request/result、独立 validation 与真实 runtime readback；Projection/Dashboard 只消费 typed public-safe read model，不创建 browser write authority；docs/fixtures 绑定公开 contract 与维护触发器，不复制 private runtime state；`loopx canary premerge --from-git-diff` 或等价的按风险选出的验证集已覆盖跨 surface 改动；PR 只包含同一协议结果所需的 product、docs 与 durable validation。

### 四层：canary premerge

单跑一个 focused smoke 只能证明你想到的那条路径。跨 surface 的变化需要一个按 Git diff 选出来的风险集合：

```bash
uv run --extra test loopx canary premerge --from-git-diff
# 当 PR base 是 upstream/main 时：
uv run --extra test loopx canary premerge --from-git-diff --git-diff-base upstream/main
```

`premerge` 会把调用方 Git 根目录用于 diff 卫生、变更 Python 编译和公开边界扫描，而 canary catalog 从自身已安装的 release root 运行。手工挑一个 smoke 不足以覆盖 runtime、quota/status、scheduler、todo、install、dashboard、benchmark-boundary 或 public/private evidence 这类改动。对应的门禁自身也有 smoke：`examples/canary/premerge-validation-gate-smoke.py`。

### 五层：模型行为资格

有些问题确定性测试问不出来，因为它们问的是模型在真实信号下会不会守协议：它是否识别 selected todo、是否尊重 human Gate、onboarding transition 之后是否继续、是否认得已知的 projection gap。这类问题用一条低频、显式的手动门禁回答，日常 CI 承载不了它：

```bash
python3 scripts/qualify-doubao-model-behavior-live.py \
  --qualification-id <public-safe-run-id>
```

它的证据边界比前几层严：`ARK_API_KEY` 只从进程环境注入，prompt、packet、模型响应、凭证与对话都不进仓库，只有有界 receipt 和 mismatch code 可以保留。fake transport 只测 adapter 的序列化、清洗与 fail-closed，它不构成对模型行为的资格认定。命令要求干净的 candidate checkout，并把回执绑定到该 checkout 的 Git source identity；只要有一次真实 provider 调用未通过就非零退出。

### 六层：release gate

发布门不通过第二套编排框架重跑测试。它聚合各条既有通道的紧凑回执，证明它们指向同一个干净源码身份：

```bash
loopx canary release-qualification \
  --manifest-json release-qualification.json \
  --repo-root .
```

`exact_release_commit_qualification_manifest_v0` 会在每个检查回执里重复 `git_commit`、Git tree id、干净工作树状态、包版本与版本 tag；缺失、失败、跳过、脏工作树、rebase 漂移或版本不一致一律 fail closed，旧 commit 的结果不能给新 tag 背书。

这一步的边界要说清楚：它是只读 reducer，不运行测试、不调用模型、不移动 ref、不创建 tag、也不发布。**回执 ready 不等于发布决定**，那一步仍然归 owner。

### 七层：真实路径验证

前面每一层都可以完全在 mock 或内存替身上通过。重构交付前必须验证受影响的真实生产入口和真实后端，这条要求记在 `AGENTS.md` 的 Refactor Real-Path Validation 一节，方法与安全边界记在 `docs/development/testing-and-quality.md`：

```bash
LOOPX_TEST_POSTGRES_URL="$DISPOSABLE_POSTGRES_URL" \
npm run test:postgresql-authority-store
```

URI 必须指向一次性隔离实例。file 与 PostgreSQL 两个 provider 执行同一套新规则，所以两边一致不能单独证明兼容。测试不得碰活跃状态：用独立 database/tenant 与一次性 runtime，配 synthetic fixture 或 owner 授权的只读快照。不要通过 promote、重写或破坏一个 active goal、它的 registry、writer fence、Todo 或 lease 状态来测。

### 最后一步：outcome validation

前面各层检查命令与回执，最后一步检查读者与消费者的目标本身：

- 项目接入后，Agent 是否真的从同一 canonical state 恢复？
- Control Plane 或 Capability 改动是否保持 authority、precedence、replay 与 recovery invariant？
- Provider/Host 是否通过真实 readback 和 independent validator 证明结果？
- Projection、docs 与 fixtures 是否仍指回同一事实源？
- Extension 是否返回稳定、正确的 domain result？
- 有权限的动作是否被拒绝或正确路由？
- 文档是否让读者知道失败后怎么恢复？

## 兼容性不是一个版本号

Extension 兼容至少有四层，任何一层的含义变化都要单独披露：

| 层 | 示例 |
| --- | --- |
| package | Python version、dependency range |
| LoopX API | `requires_loopx_api = ">=1,<2"` |
| wire protocol | `loopx_text_stats_extension_v0` |
| domain schema | request/response schema version |

升级 package version 不得静默改变同一 schema 的含义。破坏性 wire contract 需要新的 protocol 或 schema version，并为 caller 提供迁移路径。

### 默认行为变更的披露义务

这是本章受检查最少、也最容易出事的一条。默认行为变了，作者必须做三件事：

1. **重命名编码旧默认的 smoke**，让它不再假装旧行为仍然成立；
2. **更新文档与 release notes**，把新默认写进去；
3. **点名受影响的 lane**，让下游知道自己的假设变了。

`.gitignore`、CI 全绿、以及只有一个 producer，都豁免不了这件事。同时要说清一件事的性质：**guidance 与机器强制的义务**（例如 `must_attempt_work`）必须在合同里写明白，不能靠行文暗示。把一条机器会执行的义务写成建议，是比漏写更坏的错误。

## Public/private boundary

公开提交前，先看工作树里到底有什么：

```bash
git status --short
git diff --name-only
git ls-files --others --exclude-standard

loopx check \
  --scan-path README.md \
  --scan-path docs/book/
```

如果按书内示例生成了可运行目录，这些路径也要扫：

```bash
loopx check \
  --scan-path README.md \
  --scan-path standalone-extension/
```

扫描之外仍需人工复查：

- credentials、token、cookie 与 API key；
- 本机绝对路径与一次性环境 URI；
- `.loopx/`、`.codex/goals/` 或任何 runtime state；
- raw Agent transcript、trajectory、verifier output；
- 私有 issue、内部链接与未经脱敏的组织叙事；
- 临时探针与生成日志。

`.gitignore` 不能替代扫描，也不能让一个已经被跟踪的文件自动消失。

## 文档的 authority 分工

| 内容 | 放置位置 |
| --- | --- |
| 学习顺序、概念解释、恢复思路与 scaffold 导读 | `loopx-book` |
| 完整 CLI 参数、协议与 release behavior | LoopX 官方仓库 |
| 产品代码、durable fixture 与 smoke | 对应 LoopX 或 Extension 源码仓库 |
| 当前项目 Goal、Todo、Gate 与 evidence | 项目本地 LoopX state |
| commit、PR、CI、外部资源事实 | 对应外部系统 |

本书不复制完整 reference。高漂移命令只保留完成任务所需的最小路径，并指向 `--help` 和官方文档。

### 维护触发器

每次 LoopX minor release 后优先复查 installer 与 `doctor`、`connect` 与 `start-goal`、Host surface 名称、Codex App heartbeat 与 Codex CLI Goal activation、Runtime Connector Catalog、TypeScript migration RFC 的 shipped baseline、active phase 与 facade exit condition、core protocol 与 bounded-context owner、Extension manifest 与 lifecycle，以及书内步骤能否在当前官方 scaffold 上复现。理论章节只在公开 contract 改变时更新；内部文件重构不足以重写用户心智模型。

## 代价与边界：这套验证放弃了什么

**代价一：全套验证慢且贵。** 每层都跑一遍的成本不允许按每次改动摊，所以实际做法是按风险选子集，而选得对不对本身就是一个需要 review 的判断。

**代价二：真实路径验证可能做不到，而且此时必须停。** 没有安全的隔离环境时，答案是报告证据缺口并暂停交付，跳过不算通过。这条代价是故意设计成不便的：一个不方便的停，好过一条悄悄变成 mock 的合格线。

**代价三：披露义务有一部分无法自动检查。** 重命名 smoke 和更新文档可以检查，点名受影响 lane 和说清这是 guidance 还是义务只能靠作者声明与 reviewer 读懂。

**代价四：抬上限是一个合法选项，这是有意的。** 有时扩容确实是对的取舍。代价在于它必须带理由：保留信息的价值与成本、新旧上限、实测余量、预期波动或规模，还要重跑原场景与受影响的语义／规模检查。纯预算调整不必捆绑无关清理，但已冻结的实验或 promotion 阈值不能追溯放宽。

**边界一：这套梯子覆盖的是工程验证，而非全部质量控制。** 它不证明一次发布改善了多少长程结果。结果声明需要另一套东西：stable-release-vs-candidate manifest，并匹配任务语义、runner、模型、reasoning、timeout 与重复次数；任一不匹配或不完整都 fail closed。

**边界二：确定性测试和模型行为测试验证的是合同，而不是产品价值。** 它们能证明一个 control-plane 合同成立，不能证明这个合同值得存在。

**边界三：绿不等于可发布。** release gate 是聚合器，发布者是另一个人。回执齐了之后，发布决定仍然归人。

## 发布前 checklist

- [ ] 首页第一屏说明读者、价值和两条实践主线；
- [ ] 中文为主，代码与必要术语保留英文；
- [ ] 六章基础覆盖 Session、Goal、state、work graph、Turn、recovery 与运行边界；
- [ ] 项目接入覆盖 Codex App 与 Codex CLI；
- [ ] 开发者贡献覆盖 Control Plane、Capability、Provider、Host/Runner、Projection/Docs/fixtures；
- [ ] 贡献内容按 placement、协议、不变量和证据组织，而不是函数列表；
- [ ] Extension 作为贡献子路径，示例基于当前官方 scaffold 可复现；
- [ ] `python3 examples/dev-book-publication-smoke.py` 成功；
- [ ] `mkdocs build --strict` 成功；
- [ ] internal links 与 public boundary scan 通过；
- [ ] 首页预览已由 owner 审阅。

完成这些检查后，GitHub Pages workflow 才应从 `main` 发布站点。Pages 是展示面，不是内容或 LoopX 状态的事实源。

## 具名失败：这些约束拦住了什么

**预算超标时把上限调高。** 正确的第一步是同口径测量：记录 base/head revision、负载、指标和测量边界。紧凑 JSON 字符、UTF-8 字节、嵌套键数、真实 stdout 和 token 是不同的指标，不能互换。然后说明每个变化字段服务哪个消费者、哪个决策。最后才在压缩、保持上限、合理扩容之间选择并披露取舍。完整决策边界见 `docs/development/testing-and-quality.md` 的 Budget Failure Decisions 一节。判断一个上限属于哪一类是第一步：外部或授权的硬上限，改测试不能扩容。

**改了默认行为却没有留下痕迹。** 判据是旧默认的 smoke 是否已经改名、文档是否已经更新、受影响的 lane 是否被点名，而非 CI 是否绿。三条里缺任一条，这次变更就已经在无人察觉时改变了别人的行为。

**重构只在 mock 上验证。** 单测、mock 与内存 conformance 都有用，但不能替代真实后端的证据。影响 PostgreSQL authority 时，验证是对着隔离临时实例跑的真实套件。没有这个环境就报告缺口并暂停交付；跳过只构成一处证据缺口。

## 不变式

读完这一章，你应该能带走六句可以自己检查的话。

1. **每一层证据只证明它自己那一层的事。** 一层的绿不能替另一层背书，release gate 的 ready 也不能替 owner 的发布决定。
2. **失败被修复的方式必须可读。** 出现一次调高上限、一次跳过、一次 `measurement-only`，就必须同时出现一次写下来的理由；否则那只是把问题挪走。
3. **默认行为变更必须留下三处痕迹：** 改名的 smoke、更新的文档、被点名的 lane。缺一处就等于未披露。
4. **真实路径没有验证过，就谈不上已验证。** mock 上的通过可以进 PR，但不能当作交付证据；环境不可用时要报告缺口，不要把它折算成通过。
5. **公开提交前，工作树里的每一处隐私都必须被看见或被扫描。** `.gitignore` 不追溯，已跟踪的文件不会自动消失。
6. **上限的三类性质不能互换。** 外部硬上限、回归预算、展示上限各自有不同的修复方式，把回归预算当成可以随手调整的数字，就是本章开头那个周一 15:30。

这六条回答的是同一个问题：**当一次改动看起来成功时，凭什么说它真的成立，而没有把成本转到别处？** 到这一章为止，第四部分「工程边界」的验证、兼容与安全三个侧面已经合上。下一章把这些约束放进课程体系：control-plane course 讲的是同一批规则如何被一步步工程化，以及每一步留下什么证据。
