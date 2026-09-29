# -*- coding: utf-8 -*-
"""LoopX × dsh 协作研究编队:自动电商客服系统方案研究。

复用 collaboration-delivery 的机制(registry/goal/todo/turn run-once/cordis MCP),
任务换成真实研究: analyst 网络调研 -> builder 设计方案 -> reviewer 独立审查 -> builder 终稿。
用法:
  export DEEPSEEK_API_KEY=sk-xxx
  uv run --extra test --extra deepseek-harness python research_run.py prepare|run --phase X|validate ...
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from loopx.capabilities.manager_context import deliver
from loopx.chat_store import ChatSessionStore

HERE = Path(__file__).parent
GOAL = "ecommerce-cs-research"
ACTORS = ("builder", "analyst", "reviewer")
ROOT = Path(".local/research-run")

TASKS = {
    "builder-1": (
        "You are the research analyst for this phase. Use web_search and web_fetch (bounded: at most 12 "
        "searches, 8 fetches) to survey the 2026 landscape of AI customer service for B2B foreign-trade / "
        "cross-border e-commerce: (1) multi-channel inbox SaaS (email/WhatsApp/widget, pricing), "
        "(2) LLM-powered customer service practices and pitfalls, (3) anything new since mid-2026 that "
        "changes build-vs-buy for a small factory. Then read REQUIREMENTS.md and reference/v4.1.md for "
        "our context. Write outputs/research.md IN CHINESE: findings with source URLs, a priced "
        "comparison table, and 5-8 concrete implications for our plan. Cite every claim."
    ),
    "analyst-1": (
        "You are the solution architect. Read REQUIREMENTS.md, reference/v4.1.md (our current plan), "
        "reference/v3-plan.md, and inputs/research.md (the research survey staged for you). Critically "
        "upgrade our plan: what to keep, what to change, what the 2026 landscape makes cheaper or "
        "riskier. Write outputs/architecture.md IN CHINESE: full system design (channels, knowledge "
        "base, red lines, approval gates, rollout ladder with the 150-sample rule, monthly cost table, "
        "8-week schedule, top risks with mitigations). Be decisive, no option-matrix hedging."
    ),
    "reviewer-1": (
        "You are the independent reviewer. Read REQUIREMENTS.md, inputs/research.md and "
        "inputs/architecture.md. Write outputs/review.md IN CHINESE: (1) factual errors or outdated "
        "claims, (2) missing requirements or risks, (3) where the plan is over-engineered or "
        "under-engineered, (4) cost errors, (5) the three changes that would most improve the plan, "
        "(6) a verdict: adopt / adopt-with-changes / redesign. Judge against our real constraints in "
        "REQUIREMENTS.md, not generic best practices. Be specific, cite sections."
    ),
    "builder-final": (
        "You are the solution architect finalizing. Read REQUIREMENTS.md, inputs/research.md, "
        "inputs/architecture.md and inputs/review.md. Incorporate valid review findings (you may reject "
        "specific points with reasons). Write outputs/final-plan.md IN CHINESE: the complete, "
        "execution-ready plan for our automatic e-commerce customer service system. Structure: "
        "\u51b3\u7b56\u6458\u8981(10\u884c\u5185) / \u67b6\u6784 / \u7ea2\u7ebf / \u653e\u6743\u9636\u68af / \u6210\u672c / 8\u5468\u6392\u671f / \u98ce\u9669 / \u4e0ev4.1\u7684\u5dee\u5f02\u6e05\u5355. "
        "This document will be read by the factory owner directly."
    ),
}
PEER_ROUTE = {
    "analyst-1": ("builder", "analyst"),
    "reviewer-1": ("builder", "reviewer"),
    "builder-final": ("reviewer", "builder"),
}
ARTIFACT = {
    "builder-1": ("builder", "outputs/research.md"),
    "analyst-1": ("analyst", "outputs/architecture.md"),
    "reviewer-1": ("reviewer", "outputs/review.md"),
    "builder-final": ("builder", "outputs/final-plan.md"),
}


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def git(repo, *args):
    return subprocess.check_output(
        ["git", "-C", str(repo), "-c", "user.name=Research Controller",
         "-c", "user.email=research@example.invalid", *args],
        text=True,
    ).strip()


def cli(root, *args, cwd=None):
    env = {k: v for k, v in os.environ.items()
           if k.lower() not in ("http_proxy", "https_proxy", "all_proxy")}
    env["NO_PROXY"] = "*"
    env["no_proxy"] = "*"
    result = subprocess.run(
        [sys.executable, "-m", "loopx.cli", "--registry", str(root / "registry.json"),
         "--runtime-root", str(root / "runtime"), "--format", "json", *args],
        capture_output=True, text=True, check=False, cwd=cwd, env=env,
    )
    if result.returncode:
        (root / "last-cli-failure.log").write_text(result.stdout + "\n" + result.stderr, encoding="utf-8")
        raise SystemExit("CLI failed; inspect last-cli-failure.log")
    return json.loads(result.stdout)


BRIEF = """# 研究委托:自动电商客服系统(家具出口工厂)

## 我们是谁(真实约束,评审以此为据)
- 中国家具出口工厂,B2B,客户在欧美;渠道:邮件+官网挂件+WhatsApp+阿里国际站(国际站只起草不自动发)
- 周询盘几百封;老板本人是唯一审批关卡(兼职,每天1-3小时);无专职IT但会用AI编码工具
- 预算:试运行期月成本<1000元;一次性开发倾向近零(自建用现成开源件)
- 已有方案 v4.1(见 reference/v4.1.md): FastGPT + DeepSeek双档 + 国内VPS + 企业邮IMAP/SMTP +
  钉钉链接审批 + 阿里云ChatApp(WhatsApp);红线15条;放权阶梯(累计150件零重大错误);月成本约225-645元
- SaaS 备选已调研过一轮( SaleSmartly Pro 等),老板已拍板自建(数据主权)

## 本次研究要回答
1. 2026年的新变化里,哪些让 v4.1 更便宜/更稳/更简单?哪些让它过时?
2. v4.1 有哪些错误或遗漏(尤其:知识库工程、多语言、幻觉治理、防套话、评价体系)?
3. 给出可直接执行的终案(老板直接照做)。

## 硬性红线(不可协商,继承v4.1)
AI 不得自行:报价折扣/交期承诺/认证合规声明/索赔赔付/合同性确认/评价同行/泄露客户间信息/
谈收款账户/海关申报类表述/材质绝对化声明/验货打包票/付款条款细节/知识产权承诺/独家代理承诺。
"""


def prepare(root):
    root.mkdir(parents=True, exist_ok=False)
    (root / ".gitignore").write_text("*\n")
    project = root / "project"
    (project / "inputs").mkdir(parents=True)
    (project / "reference").mkdir(parents=True)
    (project / ".gitignore").write_text(".local/\nACTIVE_GOAL_STATE.md\n__pycache__/\n")
    (project / "REQUIREMENTS.md").write_text(BRIEF, encoding="utf-8")
    for src, dst in [
        ("自动客服小组-自建方案-v4.md", "reference/v4.1.md"),
        ("自动客服小组-落地计划-v3.md", "reference/v3-plan.md"),
    ]:
        s = HERE / src
        if s.exists():
            shutil.copy(s, project / dst)
        else:
            (project / dst).write_text(f"(原始文件缺失: {src})\n", encoding="utf-8")
    (project / "ACTIVE_GOAL_STATE.md").write_text(
        "---\nstatus: active\n---\n# 电商客服系统研究\n\n## User Todo\n\n## Agent Todo\n\n"
        "## Next Action\n\n- Run the assigned bounded research phase.\n", encoding="utf-8")
    git(project, "init", "-b", "main")
    git(project, "add", ".")
    git(project, "commit", "-s", "-m", "Initialize research brief and references")
    registry = {
        "schema_version": 1,
        "common_runtime_root": str(root / "runtime"),
        "goals": [{
            "id": GOAL, "domain": "ecommerce-cs-research", "status": "active",
            "repo": str(project), "state_file": "ACTIVE_GOAL_STATE.md",
            "adapter": {"kind": "fixture_v0", "status": "connected-delivery"},
            "quota": {"compute": 20.0, "window_hours": 24},
            "coordination": {"agent_model": "peer_v1", "registered_agents": list(ACTORS),
                             "write_scope": ["**"],
                             "workspace_guard_policy": {"peer_independent_worktree_required": False}},
        }],
    }
    write(root / "registry.json", registry)
    for actor in ACTORS:
        workspace = root / "agents" / actor
        workspace.parent.mkdir(exist_ok=True)
        git(project, "worktree", "add", "-b", actor, str(workspace))
        (workspace / "outputs").mkdir()
        (workspace / "tasks").mkdir()
        args = ["-m", "loopx.collaboration_mcp", "--registry", str(root / "registry.json"),
                "--runtime-root", str(root / "runtime"), "--goal-id", GOAL,
                "--agent-id", actor, "--workspace", str(workspace)]
        write(root / f"{actor}-cordis.yml", [{
            "insert": [{
                "id": "loopx-collaboration", "name": "@deepseek-ai/dsh-mcp-client",
                "config": {"transport": "stdio", "serverName": "loopx_collaboration",
                           "command": sys.executable, "args": args, "cwd": str(workspace),
                           "failOnStartupError": True},
            }]
        }])
    store = ChatSessionStore(root / "runtime")
    session = store.create_session(goal_id="loopx-manager", agent_id="codex",
                                   adapter_kind="codex_app_server", upstream_thread_id="research-owner",
                                   channel_id="manager")
    turn, _ = store.create_turn(session["session_id"], client_turn_id="initial",
                                message="研究并产出自动电商客服系统终案", origin="web")
    brief = {
        "schema_version": "collaboration_brief_v0",
        "purpose": "Research and produce the final executable plan for our automatic "
                   "e-commerce customer service system, upgrading reference/v4.1.md with "
                   "2026 landscape findings.",
        "context": BRIEF[:1500],
        "constraints": ["Chinese deliverables", "Cite sources for landscape claims",
                        "Judge against our real constraints, not generic best practice"],
        "inputs": [{"ref": "REQUIREMENTS.md", "description": "Research brief with real constraints"}],
        "acceptance": ["research.md with sources", "architecture.md", "independent review.md",
                       "final-plan.md execution-ready"],
        "return_requirement": "Return actual documents and remaining gaps",
    }
    receipt = deliver(root / "runtime", root / "registry.json", session=session, turn=turn,
                      request={"goal_id": GOAL, "agent_id": "builder", "brief": brief})
    store.update_turn(session["session_id"], turn["turn_id"], status="completing",
                      response={"message": "Delegation saved.", "context_handoff_receipt": receipt})
    store.finalize_managed_turn_completion(session["session_id"], turn["turn_id"])
    write(root / "demo.json", {"schema": "research_run_v1", "session_id": session["session_id"],
                               "requests": [receipt["request_id"]]})
    print("Prepared research fixture; no model call has run.")


def stage_inputs(root, phase):
    """Controller-side artifact routing: copy prior outputs into the actor's inputs/."""
    routing = {
        "analyst-1": [("builder", "outputs/research.md", "inputs/research.md")],
        "reviewer-1": [("builder", "outputs/research.md", "inputs/research.md"),
                       ("analyst", "outputs/architecture.md", "inputs/architecture.md")],
        "builder-final": [("builder", "outputs/research.md", "inputs/research.md"),
                          ("analyst", "outputs/architecture.md", "inputs/architecture.md"),
                          ("reviewer", "outputs/review.md", "inputs/review.md")],
    }
    actor = ARTIFACT[phase][0]
    ws = root / "agents" / actor
    (ws / "inputs").mkdir(exist_ok=True)
    for src_actor, src_ref, dst_ref in routing.get(phase, []):
        src = root / "agents" / src_actor / src_ref
        if src.exists():
            shutil.copy(src, ws / dst_ref)


def validate(root, phase):
    actor, ref = ARTIFACT[phase]
    p = root / "agents" / actor / ref
    assert p.stat().st_size > 200, f"{ref} 太小或缺失"
    print(f"validated: {ref} ({p.stat().st_size} bytes)")


def run(root, phase, model, execute, attempt):
    if not execute or not os.environ.get("DEEPSEEK_API_KEY"):
        raise SystemExit("Model execution requires --execute and DEEPSEEK_API_KEY")
    actor, ref = ARTIFACT[phase]
    route = PEER_ROUTE.get(phase)
    if route:
        from loopx.control_plane.collaboration import peers as _peers
        _peers.request(
            root / "runtime", root / "registry.json", GOAL,
            source_agent_id=route[0], target_agent_id=route[1],
            operation_id=f"{phase}-handoff",
            brief={
                "schema_version": "collaboration_brief_v0",
                "purpose": f"Phase handoff: perform {phase}. See tasks/{phase}.md and staged inputs/.",
                "context": "Controller-routed research chain; artifacts staged under inputs/.",
                "constraints": ["Chinese deliverables", "Cite sources"],
                "inputs": [{"ref": "REQUIREMENTS.md", "description": "Research brief"}],
                "acceptance": ["The phase output file named in tasks/"],
                "return_requirement": "Return actual documents and remaining gaps",
            },
        )
    instance = phase if attempt == 1 else f"{phase}-attempt-{attempt}"
    workspace = root / "agents" / actor
    meta = json.loads((root / "demo.json").read_text(encoding="utf-8"))
    (workspace / "OPERATING.md").write_text(
        f"Your identity is {actor}. Scoped loopx_collaboration MCP tools are available. "
        "Host quirk: shell tools (pwsh/bash) are BROKEN on this host (every call fails with "
        "'--profile <name> is required'); do NOT call them — use read/write/edit/glob and "
        "web_search/web_fetch instead. Use file_sha256 whenever you cite a digest. "
        f"Owner request ids: {', '.join(meta['requests'])}.\n", encoding="utf-8")
    stage_inputs(root, phase)
    (workspace / "tasks" / f"{phase}.md").write_text(TASKS[phase] + "\n", encoding="utf-8")
    todos = cli(root, "todo", "list", "--goal-id", GOAL)["todos"]
    owned = next((t for t in todos if t.get("claimed_by") == actor and t.get("status") == "open"), None)
    text = f"Read OPERATING.md and tasks/{phase}.md and perform that bounded research phase."
    if owned:
        cli(root, "todo", "update", "--goal-id", GOAL, "--todo-id", owned["todo_id"],
            "--agent-id", actor, "--text", text)
    else:
        cli(root, "todo", "add", "--goal-id", GOAL, "--role", "agent", "--claimed-by", actor,
            "--text", text, "--action-kind", "implement")
    validator = [sys.executable, str(HERE / "research_run.py"), "validate",
                 "--root", str(root), "--phase", phase]
    turn_args = (
        "turn", "run-once",
        "--goal-id", GOAL, "--agent-id", actor, "--turn-instance-id", instance,
        "--host", "dsh", "--execution-mode", "isolated-headless",
        "--project", str(workspace),
        "--dsh-home", str(root / f"home-{instance}"),
        "--dsh-cordis", str(root / f"{actor}-cordis.yml"),
        "--dsh-model", model, "--dsh-reasoning-effort", "high",
        "--dsh-max-tokens", "32768",
        "--validation-command-json", json.dumps(validator),
        "--validation-failure-kind", "repair_required",
        "--scan-root", str(workspace), "--no-global-sync",
        "--timeout-seconds", "900", "--execute",
    )
    result = cli(root, *turn_args, cwd=str(workspace))
    write(root / f"{instance}.json", result)
    print(json.dumps({k: result.get(k) for k in ("ok", "status", "result_kind", "validation")}))


def main():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", type=Path, default=ROOT)
    parser = argparse.ArgumentParser(parents=[common])
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("prepare", parents=[common])
    p_run = sub.add_parser("run", parents=[common])
    p_run.add_argument("--phase", choices=list(TASKS), required=True)
    p_run.add_argument("--model", default="deepseek-chat")
    p_run.add_argument("--execute", action="store_true")
    p_run.add_argument("--attempt", type=int, default=1)
    p_val = sub.add_parser("validate", parents=[common])
    p_val.add_argument("--phase", choices=list(TASKS), required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    if args.cmd == "prepare":
        prepare(root)
    elif args.cmd == "run":
        run(root, args.phase, args.model, args.execute, args.attempt)
    elif args.cmd == "validate":
        validate(root, args.phase)


if __name__ == "__main__":
    main()
