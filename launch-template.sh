#!/usr/bin/env bash
# 编队发射模板(脱敏): 复制后改两处——ROOT/BRIEF,密钥经 secrets.env 注入
# 用法: cp launch-template.sh rN-launch.sh && echo 'export DEEPSEEK_API_KEY="<真实key>"' > secrets.env
# 守卫(丙席审计#3/#5修复): cd/source/prepare 任一失败必须立刻退,否则会在错误目录
# 或残根上继续跑——"重装后一次跑通"的靶心路径。
set -u
export PATH=/c/Users/Administrator/ZCodeProject/node22/node-v22.22.3-win-x64:$PATH
cd /c/Users/Administrator/ZCodeProject/loopx-green || { echo "FATAL: cd 主仓失败" >&2; exit 1; }
source ./secrets.env || { echo "FATAL: secrets.env 缺失(key未注入)" >&2; exit 1; }
export DEEPSEEK_BASE_URL="https://open.bigmodel.cn/api/coding/paas/v4"
export DSH_MODEL=glm-5.3-flash
export DSH_EFFORT=max
ROOT=.local/REPLACE_ME_ROOT; BRIEF=brief-REPLACE_ME_TOPIC.md
if [ ! -f "$ROOT/demo.json" ]; then
  python -m uv run --extra test --extra deepseek-harness \
    python research_run2.py prepare --root "$ROOT" --brief-file "$BRIEF" \
    || { echo "FATAL: prepare 失败(若为残根: 删 $ROOT 后重试)" >&2; exit 1; }
fi
exec python -m uv run --extra test --extra deepseek-harness \
  python research_run2.py auto --root "$ROOT"
