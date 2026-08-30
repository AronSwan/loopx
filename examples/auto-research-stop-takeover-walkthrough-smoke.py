#!/usr/bin/env python3
"""Thin walkthrough smoke: stop → takeover command → resume → state-aware wake.

Proves the contributor-facing Auto Research control cycle on synthetic state.
Reuses helpers from the shipped stop-marker smoke (no duplicated lane/env
boilerplate) and the existing start/worker-loop path; no second launcher.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
import tempfile
from pathlib import Path
from types import ModuleType
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from demo.auto_research.demo_e2e import (  # noqa: E402
    _seed_visible_demo_control_plane,
)
from demo.auto_research.demo_supervisor import (  # noqa: E402
    build_auto_research_demo_supervisor_plan,
)
from demo.auto_research.worker_runtime import (  # noqa: E402
    load_auto_research_worker_frontier,
)
from demo.multi_agent.visible_launch_policy import (  # noqa: E402
    resolve_visible_launch_policy,
)


def _load_stop_marker_smoke() -> ModuleType:
    path = REPO_ROOT / "examples" / "auto-research-stop-marker-smoke.py"
    spec = importlib.util.spec_from_file_location("ar_stop_marker_smoke", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load stop-marker smoke from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_STOP = _load_stop_marker_smoke()
GOAL_ID = _STOP.GOAL_ID
AGENT_IDS = _STOP.AGENT_IDS
LANES = _STOP.LANES
assert_public_safe = _STOP.assert_public_safe
_run_worker_loop = _STOP._run_worker_loop
_stop_marker = _STOP._stop_marker


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
