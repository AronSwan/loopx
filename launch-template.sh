#!/usr/bin/env bash
# 编队发射模板(脱敏): 复制后改三处——ROOT/BRIEF/课题名,密钥经 secrets.env 注入
# 用法: cp launch-template.sh rN-launch.sh && echo 'export DEEPSEEK_API_KEY="<真实key>"' > secrets.env
set -u
export PATH=/c/Users/Administrator/ZCodeProject/node22/node-v22.22.3-win-x64:$PATH
source ./secrets.env   # DEEPSEEK_API_KEY=<真实key>  (secrets.env 已被 .git/info/exclude 拦? 没有——见下)
export DEEPSEEK_BASE_URL="https://open.bigmodel.cn/api/coding/paas/v4"
export DSH_MODEL=glm-5.3-flash
export DSH_EFFORT=max
cd /c/Users/Administrator/ZCodeProject/loopx-green
ROOT=.local/<新根>; BRIEF=brief-<课题>.md
[ -f "$ROOT/demo.json" ] || python -m uv run --extra test --extra deepseek-harness \
  python research_run2.py prepare --root "$ROOT" --brief-file "$BRIEF"
exec python -m uv run --extra test --extra deepseek-harness \
  python research_run2.py auto --root "$ROOT"
