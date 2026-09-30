# 创建 standalone Extension

本章从 LoopX 官方 scaffold 创建 `loopx-text-stats`。官方 scaffold 提供完整可运行基线；本章
给出需要收窄的 manifest、request/response 合同、核心函数与验证步骤，不依赖配套练习仓库。

## 从一个坏的结局开始

有人要接一个内部统计需求，判断 loopx 自带的能力太"重"，于是手写了一个更小的目录：一个
`extension.toml`、一个 `cli.py`，直接读 stdin、打印结果。`loopx extension install --manifest <path> --execute`
通过了，`run` 也能跑。

两周后审计发现：

```text
request  containspath 字段 -> provider 顺手当文件路径读了
response 无 schema_version -> 下游无法判断兼容版本
doctor   未实现           -> ready 只能证明进程能启动
version  写在 manifest 之外 -> upgrade 无法判定 revision
```

每一项单独看都是小疏漏，合起来是同一件事：**这个 provider 没有可校验的合同，因此 LoopX 无法
判断它是否被合法调用。** 它"能跑"证明的只是进程能启动。

脚手架存在的意义正是让这条路径默认完整：先拿到一份所有合同字段都在的基线，再往下删，而不是
从空目录往上补。删掉一个不需要的领域字段有明确后果；漏掉一个 schema 或 doctor，后果要到审计
时才出现。

## 1. 生成官方 scaffold 与它的边界

```bash
loopx extension init loopx-text-stats \
  --destination standalone-extension \
  --execute \
  --format json
```

`extension init` 默认只预览；必须显式加 `--execute` 才写文件。默认目标是 `packages/<extension-id>`，
用 `--destination` 可以指定别处。目标目录必须不存在，即使空目录也会被拒绝，没有 force 或 merge
模式。

关键是这条命令的边界：它不 build、不 install、不 register、也不 enable。三个动作各有归属，
必须分开执行，否则包管理器状态与 LoopX activation state 会一起漂移：

```bash
python3 -m pip install ./standalone-extension
loopx extension install \
  --manifest standalone-extension/extension.toml \
  --execute \
  --format json
```

生成结构：

```text
standalone-extension/
├── extension.toml
├── pyproject.toml
├── README.md
├── examples/
│   └── request.json
├── schemas/
│   ├── request.schema.json
│   └── response.schema.json
└── src/
    └── loopx_text_stats/
        ├── __init__.py
        └── cli.py
```

这是 complete standalone path，不会猜测 `[[provides]]` 或 `[[implements]]` 所需的
Capability authority。原因很实际：`[[provides]]` 需要真实 caller contract，`[[implements]]`
需要既有的 capability resolver、policy check、action/scope mapping 和 execution-envelope
adapter。通用脚手架无法安全推断这些语义，只能先有 capability integration profile，再针对它
编写 provider。

## 2. 读取 manifest

scaffold 生成并经本章收窄后的 manifest：

```toml
schema_version = "loopx_extension_manifest_v0"
id = "loopx-text-stats"
version = "0.1.0"
requires_loopx_api = ">=1,<2"
permissions = []

[runtime]
protocol = "loopx_text_stats_extension_v0"
entrypoint = "loopx-text-stats"
doctor_args = ["--doctor"]
required_permissions = []
timeout_seconds = 30
```

关键约束：

- `id` 是 lifecycle identity，必须是 lower-kebab 路径段，最长 48 字符；
- `version` 参与 revision 与升级；
- `requires_loopx_api` 明确兼容窗口，当前 API 版本为整数 `1`；
- `protocol` 是 provider wire contract；
- `entrypoint` 与 `python_module` 必须二选一，且 `entrypoint` 必须存在于 LoopX 所在 Python
  environment 的 `PATH`；
- `doctor_args` 指向只读 readiness probe；
- `permissions` 与 `required_permissions` 都为空；
- `timeout_seconds` 取值范围是 1 到 120，由 managed runtime 读取，调用者不能另行覆盖。

另有一条 fail-closed 规则值得单独记住：`runtime.required_permissions` 必须是 provider
`permissions` 的子集。声明权限并不会授予权限，它只是让自己有资格进入需要该权限的调用路径。

## 3. 定义 request contract

示例 request：

```json
{
  "schema_version": "loopx_text_stats_request_v0",
  "text": "LoopX keeps project state explicit.\nExtensions keep delivery lifecycle explicit."
}
```

request schema 要求：

- payload 必须是 object；
- `schema_version` 必须精确匹配；
- `text` 必须是包含非空白字符的 string；
- `additionalProperties` 为 false。

拒绝额外字段是权限边界的一部分，而不是风格偏好。假如 caller 传入：

```json
{
  "schema_version": "loopx_text_stats_request_v0",
  "text": "hello",
  "path": "input.txt"
}
```

provider 必须拒绝，而不是擅自把 `path` 理解为文件读取授权。schema 是 bounded request 的一部分。

## 4. 实现纯计算

示例的核心函数：

```python
def analyze_text(text: str) -> dict[str, int]:
    return {
        "characters": len(text),
        "non_whitespace_characters": sum(
            1 for character in text if not character.isspace()
        ),
        "words": len(re.findall(r"\S+", text)),
        "lines": len(text.splitlines()) or 1,
    }
```

它具有适合作为首个 standalone Extension 的性质：

- 同一输入得到同一输出；
- 不访问环境变量；
- 不读取文件；
- 不访问网络；
- 不写外部系统；
- 不依赖 LoopX project state。

provider 在计算前完成结构验证，错误也通过 versioned response object 返回：

```json
{
  "ok": false,
  "schema_version": "loopx_text_stats_response_v0",
  "extension_id": "loopx-text-stats",
  "error": "extension input has unsupported fields ['path']"
}
```

不要把 traceback、环境变量或本机路径直接输出到 public receipt。

## 5. 定义 response contract

成功 response 的稳定 domain 部分：

```json
{
  "ok": true,
  "schema_version": "loopx_text_stats_response_v0",
  "extension_id": "loopx-text-stats",
  "request_schema_version": "loopx_text_stats_request_v0",
  "result": {
    "characters": 80,
    "non_whitespace_characters": 71,
    "words": 10,
    "lines": 2
  }
}
```

response schema 使用 `oneOf` 区分成功与失败。测试应断言 domain contract，而不是绑定 LoopX CLI
外层展示的每个字段，否则 minor release 的 receipt 扩展会导致无意义失败。

## 6. 保持 doctor 无副作用

starter 的 doctor：

```python
if args.doctor:
    return 0
```

对于这个纯计算 provider，readiness 只需要证明 entrypoint 可启动和参数可解析。doctor 不应：

- 创建文件；
- 连接网络；
- 写入凭据；
- 修改 extension state；
- 产生业务 effect；
- 输出未经约束的大量日志。

真实 Provider 可以做必要的只读依赖检查，但 readiness probe 仍应有界、可重复、无 effect。
doctor receipt 始终报告 `external_writes_performed: false`，这条断言本身就是合同的一部分。

## 7. 安装 package 并运行 tests

在同一个 Python environment 中：

```bash
cd standalone-extension
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -e '.[test]'
python3 -m pytest
```

同环境要求源于 LoopX 通过已安装 console entrypoint 定位 provider。package 装在另一个 venv 时，
正确结果是 `entrypoint_missing`，而不是静默搜索任意源码路径。

## 代价与边界

脚手架把默认成本从"审计时补"变成"开始时就有"，这份成本需要讲清楚。

**代价一：起手就有 8 个文件。** 一个只算字符数的 provider 也要带两份 JSON Schema、一份 README
和 `pyproject.toml`。对一次性脚本，这份重量的确偏大。

**代价二：starter 的 request/response 是文档，而非领域合同。** 生成的东西能跑通，但它描述的
并非你的领域。产品化之前要把它替换成有界、领域专属的语义。

**代价三：scaffold 不做四件事。** 不 build、不 install、不 register、不 enable。想少敲几条命令
就得手动补，而跳过 install 会造成包与 activation state 漂移。

**边界一：`extension init` 当前只生成 standalone path。** 需要 `[[provides]]` 或 `[[implements]]`
的 Extension 应先有 capability integration profile，再据此编写 provider。不要为了"能装"而加
manifest 表。

**边界二：doctor 证明 readiness，`--execute` 证明意愿。** 两者都不授权任何业务 effect。

**边界三：目标目录不可复用。** 已存在的目录一律拒绝，这保护的是"不会把新扩展覆盖到既有 package 上"。

## 具名失败：这些约束拦住了什么

**脚手架拒绝不安全标识符。** `test_scaffold_rejects_unsafe_identifiers` 对 `LoopX-example`、
`loopx_example` 和版本号 `v1` 逐个断言失败。`id` 会进入路径与 lifecycle identity，宽松的
校验会把命名问题推迟到安装之后。

**preview 不写任何文件。** `test_scaffold_preview_is_read_only` 断言预览返回精确的 8 文件列表，
并且 `managed_entrypoint == "loopx extension run"`、`starter_kind == "standalone"`、
`capability_id is None`。最后一项是本章最重要的一条证据：脚手架明确不认领任何 capability。

**生成的 provider 拒绝越界输入。** 同一批测试断言它拒绝非 object 输入，也拒绝 `_v1` 结尾的
request contract，返回码非零且 `ok is False`。

对应测试：`tests/extensions/test_extension_scaffold.py`。

## 常见错误

### 手写一个比 scaffold 更小的目录

容易漏掉 schema、doctor、manifest compatibility 或 package entrypoint。先生成完整官方路径，再删改
不需要的领域字段。

### 让 provider 接受任意 kwargs

这会破坏 bounded request，并可能意外扩大权限。request schema 和 provider validation 应同时
fail closed。

### 用 doctor 执行业务请求

doctor 证明 readiness，不证明某个 effect 已获授权。业务调用必须通过 managed runtime 或
Capability/domain command。

### 为演示擅自增加 permission

一旦声明 permission，`extension run` 会在调用 provider 之前直接拒绝，错误信息是
"standalone extension run grants no effect dispatch"。先确定真实 Capability 和 authority，再设计
effectful provider，不要为了展示 manifest 字段制造假的权限合同。

## 不变式

1. **脚手架产出的目录里，每个合同字段都必须先存在再被删。** 空目录起手一定会漏掉某项，
   而漏掉的后果只在审计时暴露。
2. **`extension init` 只生成 standalone path。** 它不认领 capability，也不推断
   `[[provides]]` 或 `[[implements]]` 所需的 authority。
3. **一次 provider 调用必须带上可校验的 `schema_version`。** 缺少它的 receipt 无法判定兼容版本。
4. **未知字段一律拒绝。** 把额外字段理解成隐式授权，等于绕过了权限边界。
5. **doctor 必须具备 zero side effect。** `external_writes_performed` 出现 `true`，说明 readiness
   probe 越界了。
6. **package 与 LoopX 必须在同一个 Python environment。** 跨环境的正确结果是
   `entrypoint_missing`，不是静默降级。

下一章把这份结构放进真实生命周期：安装、启用、调用、升级与回滚。
