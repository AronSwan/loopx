# Harness 0.1.5rc1 → 0.2.0rc2 受控升级手册（2026-10-01）

> 法源：用户令"跟上新时代，我们落后了就要重视起来，要更新"+"我们的控制器不是不可以做，但是底座是官方的"。
> 本文 = 构建链复现手册 + 官方偏离台账。重装/换机时按 §2 重建轮子，按 §3 对账偏离。

## 1. 为什么这样升

- PyPI 分发链（deepseek-harness-sdk / deepseek-harness-runtime-bin）最高只到 0.1.5rc1，0.2.0rc2 无官方轮子。
- 官方仓库 deepseek-ai/deepseek-harness 把 Python SDK 与运行时的**构建链全开源**（python/sdk、python/sdk-runtime、scripts/build-exe-for-python-sdk.ts）。
- LoopX 的 SDK 用面极小（`DeepSeekHarness(Config)` + `harness.run()`），两版本 Config 模型 673 行零差异。
- 结论：克隆官方 tag **dsh-v0.2.0-rc.2**，用官方自己的构建链出官方代码的轮子——底座仍是官方的，我们只做了"官方构建在本地跑通"。

## 2. 构建链复现（五个坑已修，按序执行）

前置：Node 22.22.3（`/c/Users/Administrator/ZCodeProject/node22/node-v*-win-x64`）、pnpm 11.7.0（corepack）、uv、磁盘 ~4GB。

```bash
git clone --depth 1 --branch dsh-v0.2.0-rc.2 https://github.com/deepseek-ai/deepseek-harness.git harness-020
cd harness-020
# 坑1: 供应链年龄检查对未满龄包网络超时 → 镜像+放宽; 坑3: lefthook postinstall 在 --production 下必炸 → 置空
printf '\nminimumReleaseAge: 0\n' >> pnpm-workspace.yaml
printf 'registry=https://registry.npmmirror.com\nfetch-retries=6\nfetch-retry-factor=3\nfetch-timeout=180000\n' > .npmrc
python -c "import json; d=json.load(open('package.json',encoding='utf-8')); d['scripts']['postinstall']='node -e \"\"  # 本地构建补丁:lefthook仅git钩子,--production下必炸'; json.dump(d,open('package.json','w',encoding='utf-8'),indent=2)"
export CI=true npm_config_confirm_modules_purge=false   # 坑2: 无TTY时pnpm拒绝清modules目录
pnpm install --frozen-lockfile
```

坑4 前置（pkg 底座预种，绕开其内置下载器的 undici 网络问题）：

```bash
# 按 scripts/primary-runtime/lock.json 的 sha256 预下载 6 资产到 %TEMP%/dsh-primary-runtime-downloads/
#   Node 24.21.0 win-x64.zip ← npmmirror.com/mirrors/node/...（校验和必须匹配 lock.json）
#   cpython-3.12.14 底座 ← github astral-sh/python-build-standalone（直连快）
#   numpy/pandas/pillow/lxml 四轮子 ← pypi.tuna.tsinghua.edu.cn
# 再把官方 zip 里的 node.exe 种进 pkg 缓存:
mkdir -p ~/.pkg-cache/v24.21 && cp <解压>/node-v24.21.0-win-x64/node.exe ~/.pkg-cache/v24.21/fetched-v24.21.0-win-x64
```

构建脚本本地补丁两处（见 §3 构建树偏离）：
1. `verifyClosure()` 跳过——其 `pnpm install --production` 会把构建自身需要的 pkg/tsx 剪掉（官方 CI 不踩是因为它的调用序不同）；
2. `pack()` 开头补一次 `pnpm install --frozen-lockfile`——deploy 步骤会清根 node_modules。

```bash
npm i -g tsx --registry=https://registry.npmmirror.com   # 全局tsx,防被根目录剪掉
tsx scripts/build-exe-for-python-sdk.ts --targets=node24-win-x64
# 产物: dist-exe/ 四件套(主exe 279MB + -rg.exe + -office/ + win-x64/)并自动同步进 python/sdk-runtime
cd python/sdk-runtime && uv build --wheel    # 只出wheel,hatch拒绝sdist(wheel-only包)
cd ../sdk && uv build --wheel                # 版本已手工stamp为0.2.0rc2(源内是0.0.0.dev0占位)
```

## 3. 官方偏离台账（重装对账清单）

### 3a. harness 构建树（ZCodeProject/harness-020，本地克隆不进任何 git）
| 偏离 | 性质 | 影响 |
|---|---|---|
| package.json postinstall 置空 | 打包期 | 不进轮子 |
| pnpm-workspace/.npmrc 镜像与放宽 | 打包期 | 不进轮子 |
| build-exe-for-python-sdk.ts 两处 LOCAL BUILD PATCH | 构建期 | 不进轮子；**运行时代码 100% 官方源** |
| 轮内 runtime.json 版本号 0.0.0-dev | 化妆性(官方原样) | 审计对账勿误判为篡改 |

### 3b. loopx-green 对官方 loopx/ 包的偏离（2026-10-01 瘦身后：3 文件 6 行）
| 文件 | 偏离 | 回馈上游 | 回归官方条件 |
|---|---|---|---|
| loopx/file_lock.py | holder 侧车去 .json 后缀（1 行） | 协议文档已加 LOCAL DEVIATION 注记; 关联 issue #5397 | 上游修 #5397 后改回（改名 vs 扫描器跳过，以上游裁决为准） |
| collaboration/inbox.py | 非 sha256 条目显式 continue（4 行） | 同 #5397（扫描器跳过规则） | 同上 |
| collaboration/peers.py | returns() glob 过滤 .lock（1 行） | 同 #5397 | 同上 |

**已瘦身两笔（2026-10-01"33行必要性"核查，官方对照后删/重分类）**：
- ~~collaboration_mcp.py file_sha256 工具（27 行）~~ **已删**——官方 0.2.0 的 24 个原生工具无 hash 类，但 shell 已修复：
  官方正路 `pwsh Get-FileHash`（实测模型算出的 SHA256 与期望逐位一致）。当年做此工具正是 shell 坏时代的
  替代品；底座修好后回归官方。工人指引同步改为官方工具。
- ~~turn_host_adapter.py initialize_timeout_seconds（1 行）~~ **重分类，不算偏离**——官方 0.2.0 SDK 原生字段
  （api.py:33，默认 30.0）；我们的调用行只是给官方旋钮传值，与 patch 无关。不再回馈、无需回归。

### 3c. 我们的控制器（research_run2.py / test_controller.py / claim_audit.py）
- 全部走官方接口：loopx.cli turn run-once + 官方 SDK。**不 patch 官方行为，只调用**。
- pyproject 的 `[tool.uv.sources]` 把两包钉到本地轮子；uv.lock 被 .git/info/exclude 拦（本地文件）。

## 4. 升级后语义变化（运维必读）

1. **智谱端点换协议路径**：0.2.0 的 deepseek provider 走 Anthropic Messages 协议，
   `DEEPSEEK_BASE_URL=https://open.bigmodel.cn/api/anthropic`（不再是 coding/paas/v4）。
2. **max_tokens 必须显式 ≤131072**（默认值超智谱上限报 400 "[1210]max_tokens参数非法"）。
3. shell 工具已可用（0.1.5 的 `--profile is required` 已修）——第九场起可评估撤除工人 OPERATING.md 的 shell 告示。

## 4b. 二轮审计补充语义（升级组二轮，2026-10-01）

- SDK 默认 shutdown 超时 1 秒=每棒收尾硬杀运行时；适配器应显式传 10s（**排队待改，随 r9 后测试批**）
- turn run-once 手工调用默认 115 秒请求预算——手工必显式传超时
- SDK 轮路径曾指向 4GB 构建树（单点）——已修复为仓内 .local 双轮（uv sources）
- DSH_HOME 全局 export=所有进程静默汇入同一 home（并发红线，见手册）
- 流式首事件延迟=思考完成(实测~4.5秒)——任何看门狗判活阈值不得低于 5 秒
- 401 三信封/工具id为 call_ 前缀/reasoning_content 迁移为 thinking 块——判据与解析器适配见 v2.2 编译席

## 5. 验证链（升级当日全绿）

隔离 venv boot ✓ / 真模型 completed+回复 ✓ / shell 写文件 ✓ / 45 控制器测 ✓。
第九场全链实测为最终验收（待做）。
