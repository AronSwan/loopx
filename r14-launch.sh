#!/usr/bin/env bash
# 第十四场(首场确认性运行): SaleSmartly免费档4周试点SOP(原题,r13同题)
# ——锁定协议v2首场: 锚工件lock-anchor.json已落(.local/,push_event_at=2026-10-02T16:57:29Z)
# RESEARCH_LOCK_PUSHED=1: 锁锚已推送fork(780ec867@AronSwan/loopx)
set -u
for d in /c/Users/Administrator/ZCodeProject/node22/node-v*-win-x64; do export PATH="$d:$PATH"; done
cd /c/Users/Administrator/ZCodeProject/loopx-green || { echo "FATAL: cd 主仓失败" >&2; exit 1; }
source ./secrets.env || { echo "FATAL: secrets.env 缺失" >&2; exit 1; }
export DEEPSEEK_BASE_URL="https://open.bigmodel.cn/api/anthropic"
export DSH_MODEL=glm-5.3-flash
export DSH_EFFORT=max
export DSH_TELEMETRY_DISABLED=1
export RESEARCH_LOCK_PUSHED=1
ROOT=.local/research14-run
BRIEF=.local/brief-salesmartly-pilot.md
if [ ! -f "$ROOT/demo.json" ]; then
  python -m uv run --extra test --extra deepseek-harness \
    python research_run2.py prepare --root "$ROOT" --brief-file "$BRIEF" \
    --reference final-v5.md .local/research7-run/project/reference/final-v5.md \
    --reference tool-verify.md "../custom-tool-verification-DAG编队产出/final-plan.md" \
    || { echo "FATAL: prepare 失败(残根则删 $ROOT 重试)" >&2; exit 1; }
fi
# 锚工件在prepare之后、auto之前拷入(prepare的exist_ok=False要求根不存在;
# v2§5场内写锁的锚校验读取点=运行根)
cp .local/lock-anchor.json "$ROOT/lock-anchor.json" || { echo "FATAL: 锚工件缺失,先推送+落锚" >&2; exit 1; }
exec python -m uv run --extra test --extra deepseek-harness \
  python research_run2.py auto --root "$ROOT"
