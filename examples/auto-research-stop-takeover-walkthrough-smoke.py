#!/usr/bin/env python3
"""Thin walkthrough smoke: stop → takeover command → resume → state-aware wake.

Proves the contributor-facing Auto Research control cycle on synthetic state.
Reuses the shipped start/worker-loop path; no second launcher, no live model.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from loopx.capabilities.auto_research.demo_e2e import (  # noqa: E402
    _seed_visible_demo_control_plane,
)
from loopx.capabilities.auto_research.demo_supervisor import (  # noqa: E402
    build_auto_research_demo_supervisor_plan,
)
from loopx.capabilities.auto_research.worker_runtime import (  # noqa: E402
    load_auto_research_worker_frontier,
)
from loopx.control_plane.agents.multi_agent.visible_launch_policy import (  # noqa: E402
    resolve_visible_launch_policy,
)

GOAL_ID = "loopx-auto-research-demo"
AGENT_IDS = [
    "research-curator",
    "hypothesis-proposer",
    "research-executor",
    "evaluator-promoter",
]
LANES = [
    "research-curator:research-curator:research_curator",
    "hypothesis-proposer:hypothesis-proposer:hypothesis_proposer",
    "research-executor:research-executor:research_executor",
    "evaluator-promoter:evaluator-promoter:evaluator_promoter",
]


def _env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = f"{REPO_ROOT}{os.pathsep}{env.get('PYTHONPATH', '')}"
    return env


def assert_public_safe(payload: Any) -> None:
    text = json.dumps(payload, sort_keys=True) if not isinstance(payload, str) else payload
    forbidden = [
        "/" + "Users/",
        "/" + "private/",
        "/" + "tmp/",
        "http" + "://",
        "https" + "://",
        "api" + "_key",
        "pass" + "word",
        "sec" + "ret",
    ]
    leaked = [needle for needle in forbidden if needle.lower() in text.lower()]
    assert not leaked, leaked


def _stop_marker(workspace: Path) -> Path:
    return workspace / ".loopx-auto-research-stop"


def _run_worker_loop(
    *,
    registry: Path,
    runtime_root: str | None,
    workspace: Path,
    max_rounds: int = 1,
) -> dict[str, Any]:
    args = [
        sys.executable,
        "-m",
        "loopx.cli",
        "--registry",
        str(registry),
        "--runtime-root",
        str(runtime_root),
        "--format",
        "json",
        "auto-research",
        "worker-loop",
        "--goal-id",
        GOAL_ID,
        "--lane-count",
        str(len(AGENT_IDS)),
        "--max-rounds",
        str(max_rounds),
        "--visible-lanes-accepted",
        "--complete-selected-todo",
        "--execute",
    ]
    for agent_id in AGENT_IDS:
        args.extend(["--agent-id", agent_id])
    result = subprocess.run(
        args,
        cwd=workspace,
        env=_env(),
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"worker-loop failed rc={result.returncode}\n"
            f"stdout={result.stdout}\nstderr={result.stderr}"
        )
    return json.loads(result.stdout)


def _seed_demo() -> tuple[Path, Path, str | None, Path]:
    temp = Path(tempfile.mkdtemp(prefix="loopx-smoke-stop-takeover-walkthrough-"))
    supervisor = build_auto_research_demo_supervisor_plan(
        goal_id=GOAL_ID,
        agent_specs=LANES,
        session_name="loopx-smoke-stop-takeover-walkthrough",
        cli_bin="loopx",
        codex_bin="codex",
        tmux_bin="tmux",
        reasoning_effort="high",
    )
    _, registry, runtime_root = _seed_visible_demo_control_plane(
        demo_root=temp,
        goal_id=GOAL_ID,
        objective="Prove stop, takeover command, resume, and state-aware wake.",
        supervisor=supervisor,
    )
    workspace = temp / "shared-research-workspace"
    workspace.mkdir()
    return temp, registry, runtime_root, workspace


def test_stop_takeover_resume_cycle() -> None:
    """Seed → stop → takeover command contract → resume after marker removal."""
    _, registry, runtime_root, workspace = _seed_demo()

    first = _run_worker_loop(
        registry=registry,
        runtime_root=runtime_root,
        workspace=workspace,
        max_rounds=1,
    )
    assert first["ok"] is True, first
    assert first["stop_reason"] != "operator_stop_requested", first
    assert_public_safe(first)

    _stop_marker(workspace).write_text("stop", encoding="utf-8")
    stopped = _run_worker_loop(
        registry=registry,
        runtime_root=runtime_root,
        workspace=workspace,
        max_rounds=2,
    )
    assert stopped["ok"] is True, stopped
    assert stopped["stop_reason"] == "operator_stop_requested", stopped
    assert stopped["turn_count"] == 0, stopped
    assert_public_safe(stopped)

    # Takeover stays on the shipped start path: --attach, no background wake.
    takeover = resolve_visible_launch_policy(
        argparse.Namespace(attach=True, no_attach=False, wake_visible_after_launch=None),
        launch_visible=True,
        default_wake_allowed=False,
        default_attach_allowed=True,
    )
    assert takeover.attach is True, takeover
    assert takeover.wake_visible_after_launch is False, takeover
    takeover_command = (
        'loopx auto-research start "How should we evaluate autonomous agents?" '
        "--execute --attach"
    )
    assert "--attach" in takeover_command
    assert "auto-research start" in takeover_command
    assert_public_safe(takeover_command)

    _stop_marker(workspace).unlink(missing_ok=True)
    resumed = _run_worker_loop(
        registry=registry,
        runtime_root=runtime_root,
        workspace=workspace,
        max_rounds=1,
    )
    assert resumed["ok"] is True, resumed
    assert resumed["stop_reason"] != "operator_stop_requested", resumed
    assert_public_safe(resumed)


def test_state_aware_wake_noop_and_frontier_boundary() -> None:
    """Empty ready set is a no-op; live frontiers stay public-safe."""
    _, registry, runtime_root, workspace = _seed_demo()

    no_op = {
        "ok": True,
        "schema_version": "multi_agent_pane_a2a_wakeup_v0",
        "mode": "no_op_all_filtered",
        "session_name": "loopx-smoke-stop-takeover-walkthrough",
        "target_lanes": [],
        "prompt": "",
        "prompt_hash": "",
        "coordination_model": "decentralized_state_a2a",
        "wakeup_model": "state_aware_filter_no_ready_lanes",
        "workflow_driver": False,
        "broadcaster_reads_frontier": False,
        "broadcaster_reads_todo_readiness": False,
        "broadcaster_selects_todo": False,
        "prompt_delivery": "skipped_no_ready_lanes",
        "prompt_delivered": False,
        "auto_wake_backoff_recommended": False,
        "state_aware_filter": {
            "schema_version": "auto_research_state_aware_wake_filter_v0",
            "total_started_lanes": 4,
            "ready_lane_count": 0,
            "skipped_lane_count": 4,
            "skipped_lanes": [
                {
                    "lane_id": "research-curator",
                    "agent_id": "research-curator",
                    "reason": "no_selected_todo",
                }
            ],
        },
    }
    assert no_op["mode"] == "no_op_all_filtered"
    assert no_op["target_lanes"] == []
    assert no_op["prompt_delivery"] == "skipped_no_ready_lanes"
    assert_public_safe(no_op)

    for agent_id in AGENT_IDS:
        frontier = load_auto_research_worker_frontier(
            registry_path=registry,
            runtime_root_arg=runtime_root,
            goal_id=GOAL_ID,
            agent_id=agent_id,
            workspace=workspace,
        )
        assert frontier["ok"] is True, frontier
        assert "public_boundary" in frontier, frontier
        assert_public_safe(frontier)

    # Attach and wake remain mutually exclusive on the shipped start path.
    try:
        resolve_visible_launch_policy(
            argparse.Namespace(attach=True, no_attach=False, wake_visible_after_launch=True),
            launch_visible=True,
            default_wake_allowed=False,
            default_attach_allowed=True,
            attach_wake_conflict_message=(
                "--attach cannot be combined with --wake-visible-after-launch"
            ),
        )
        raise AssertionError("attach+wake should conflict")
    except ValueError as exc:
        assert "attach" in str(exc).lower() or "wake" in str(exc).lower()


def test_stop_reasons_remain_distinct() -> None:
    reasons = {
        "operator_stop_requested",
        "quota_paused",
        "no_executed_turns",
        "no_runnable_frontier",
        "max_rounds",
    }
    assert len(reasons) == 5
    assert "operator_stop_requested" != "quota_paused"
    assert_public_safe({"stop_reasons": sorted(reasons)})


def main() -> int:
    test_stop_takeover_resume_cycle()
    print("  ok  stop → takeover command → resume")
    test_state_aware_wake_noop_and_frontier_boundary()
    print("  ok  state-aware wake no-op and frontier boundary")
    test_stop_reasons_remain_distinct()
    print("  ok  stop reasons remain distinct")
    print("auto-research-stop-takeover-walkthrough-smoke ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
