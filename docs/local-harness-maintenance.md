# local-harness 分支维护手册

> 竣工检验丙席整改项: 此前 rebase 操作顺序只活在对话里,上游一动就裸奔。本文件是唯一权威。

## 分支定位

- `local-harness`: 本地编队资产+框架补丁,**永不 push 到 origin**(公开仓库)。
- `main`: 只做上游快进拉取,不做任何本地提交。
- `freeze-p3`: 代码冻结点 tag(P5 盲测/P6 实验的基线)。

## 上游同步顺序(rebase 前 must-read)

```bash
cd loopx-green
git fetch origin                       # 1. 拉上游
# 2. 注意: 本仓库是 depth=1 浅克隆,首次 rebase 前必须先:
#    git fetch --unshallow   (一次性,拉全历史,否则可能缺合并基直接 fatal)
git switch main && git pull --ff-only  # 3. main 快进
git switch local-harness
git rebase main                        # 4. 8笔补丁按序重放
# 5. 回归验证(必须全绿才算同步成功):
export PATH=/c/Users/Administrator/ZCodeProject/node22/node-v22.22.3-win-x64:$PATH
python -m uv run --extra test --extra deepseek-harness python -m pytest test_controller.py -q
# 6. 冻结点随迁:
git tag -f freeze-p3                   # 指向新tip
# 7. 泄密复扫(每次同步后):
git log -p local-harness | grep -c "<key指纹>"   # 把<key指纹>换成真实key前8位执行,结果必须=0
```

## 冲突预警(丙席上游实查,30天窗口)

补丁文件中 4 个是上游热点: inbox.py(12次)/file_lock.py(18次)/peers.py(24次)/
turn_host_adapter.py(30次)。冲突概率高;好在补丁极小(+36/-3),手工解冲突成本可控。
demo.py 与 collaboration_mcp.py 为冷文件(0次)。

## CRLF 红线

本仓库基线为 **CRLF**(上游 blob 与我们的提交两侧一致,已实测)。系统级
`core.autocrlf=true` 换机会失效。**禁止** `git add --renormalize`、禁止切
`autocrlf=input/false` 后提交——否则全文假 diff + 整文件冲突。
若上游将来归一化为 LF,先评估再动。

## 提交纪律

一坑一提交(`fix/test/feat/docs(scope): 坑N或一句话`);提交前
`pytest test_controller.py -q` 必须绿;含密钥文件(r?-launch.sh/secrets.env/*.log/
uv.lock)已被 `.git/info/exclude` 拦截——该拦截是**本机配置**,换机需重配
(见 `.git/info/exclude` 内容),这也是"永不 push"的第二重理由。
