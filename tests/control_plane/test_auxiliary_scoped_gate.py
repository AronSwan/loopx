"""Auxiliary observation must use its own scoped gate and fixed primary Turn."""
from __future__ import annotations

import json
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from canonical_authority_fixture import initialize_canonical_authority, isolate_sqlite_runtime
from tests.control_plane.test_quota_settlement_cli import (
    AGENT_ID, DUE_MONITOR_TODO_ID, GOAL_ID, TODO_ID,
    _append_newly_due_monitor, _run_cli, _spend_run_count, _write_fixture,
)
from loopx.control_plane.coordination.runtime_shadow import build_todo_runtime_shadow_projection
from loopx.todos import add_goal_todo, list_goal_todos, update_goal_todo


@pytest.mark.parametrize("provider", ["legacy", "file", "sqlite"])
@pytest.mark.parametrize("route", ["source", "global"])
@pytest.mark.parametrize("gate_change", ["none", "targets_monitor", "unknown_scope", "global_gate", "primary_blocked"])
def test_emitted_auxiliary_command_honors_an_unrelated_gate(tmp_path, monkeypatch, provider, route, gate_change):
    isolate_sqlite_runtime(tmp_path, monkeypatch)
    project, runtime, source = _write_fixture(tmp_path)
    update_goal_todo(registry_path=source, goal_id=GOAL_ID, todo_id=TODO_ID,
        claimed_by=AGENT_ID, agent_id=AGENT_ID, priority="P0")
    gated = add_goal_todo(registry_path=source, goal_id=GOAL_ID, role="agent",
        text="Work awaiting owner input", status="blocked", task_class="advancement_task", claimed_by=AGENT_ID)
    gate = add_goal_todo(registry_path=source, goal_id=GOAL_ID, role="user",
        text="Decide the gated work", task_class="user_gate", bound_agent=AGENT_ID,
        blocks_agent=AGENT_ID, unblocks_todo_id=gated["todo_id"], agent_id=AGENT_ID)
    _append_newly_due_monitor(project, priority="P1", watch_only=True)
    if provider != "legacy":
        todos = list_goal_todos(registry_path=source, goal_id=GOAL_ID)["todos"]
        projection = build_todo_runtime_shadow_projection(goal_id=GOAL_ID, todos=todos, handoff_mode="soft_claim")
        initialize_canonical_authority(runtime, GOAL_ID, projection,
            state_path=project / f".codex/goals/{GOAL_ID}/ACTIVE_GOAL_STATE.md", provider=provider)
    registry = source
    if route == "global":
        registry = runtime / "registry.global.json"
        payload = json.loads(source.read_text(encoding="utf-8"))
        payload["registry_role"] = "global-local"
        payload["goals"][0]["source_registry"] = str(source)
        registry.write_text(json.dumps(payload), encoding="utf-8")
    turn = "auxiliary-scoped-gate-turn"
    guard_args = ["quota", "should-run", "--codex-app", "--goal-id", GOAL_ID,
        "--agent-id", AGENT_ID, "--turn-instance-id", turn,
        "--available-capability", "network", "--available-capability", "external_evidence_poll",
        "--scan-path", str(project)]
    rc, guard = _run_cli(registry, runtime, *guard_args)
    assert rc == 0, json.dumps(guard, ensure_ascii=False)
    assert guard["heartbeat_receipt"]["settlement_identity"]["todo_id"] == TODO_ID
    assert guard["requires_user_action"] is True
    projection = guard["interaction_contract"]["cli_channel"]["auxiliary_monitor_poll"]
    assert projection["availability"] == "ready"
    args = shlex.split(projection["command"])[1:]
    assert args[args.index("--registry") + 1] == str(registry)
    assert args[args.index("--target-key") + 1] == "due-monitor-fixture"
    args = tuple("observed-target" if x == "${LOOPX_MONITOR_RESULT_HASH:?}" else x for x in args)
    def emitted():
        result = subprocess.run([sys.executable, "-m", "loopx.cli", "--format", "json", *args, "--scan-path", str(project)],
            cwd=Path(__file__).resolve().parents[2], text=True, capture_output=True)
        return result.returncode, json.loads(result.stdout)
    if gate_change != "none":
        if gate_change == "targets_monitor":
            update_goal_todo(registry_path=source, goal_id=GOAL_ID, todo_id=gate["todo_id"],
                agent_id=AGENT_ID, unblocks_todo_id=DUE_MONITOR_TODO_ID)
        elif gate_change == "global_gate":
            update_goal_todo(registry_path=source, goal_id=GOAL_ID, todo_id=gate["todo_id"],
                agent_id=AGENT_ID, global_gate=True, clear_blocks_agent=True)
        elif gate_change == "primary_blocked":
            update_goal_todo(registry_path=source, goal_id=GOAL_ID, todo_id=TODO_ID,
                agent_id=AGENT_ID, status="blocked")
        else:
            add_goal_todo(registry_path=source, goal_id=GOAL_ID, role="user", task_class="user_gate",
                text="Decide an unspecified dependency", bound_agent=AGENT_ID,
                blocks_agent=AGENT_ID, agent_id=AGENT_ID)
        rc, current = _run_cli(registry, runtime, *guard_args)
        if gate_change == "primary_blocked":
            assert rc == 1 and current["error_code"] == "heartbeat_receipt_identity_conflict", current
        else:
            assert rc == 0, current
            offered = current["interaction_contract"]["cli_channel"].get("auxiliary_monitor_poll", {})
            assert offered.get("availability") != "ready"
            assert "command" not in offered
        rc, denied = emitted()
        expected = ("heartbeat_receipt_identity_conflict" if gate_change == "primary_blocked"
            else "monitor_poll_admission_rejected")
        assert rc == 1 and denied["error_code"] == expected, denied
        assert _spend_run_count(runtime) == 0
        rows = list_goal_todos(registry_path=source, goal_id=GOAL_ID, todo_id=DUE_MONITOR_TODO_ID)["todos"]
        assert rows[0].get("result_hash") is None
        return
    rc, observed = emitted()
    assert rc == 0, observed
    assert observed["settlement_todo_id"] == TODO_ID
    assert observed["todo_id"] == DUE_MONITOR_TODO_ID
    assert observed["turn_continuation"]["current_turn_settled"] is False
    assert observed["turn_continuation"]["next_turn_required"] is False
    rc, replay = emitted()
    assert rc == 0 and replay["replayed"] is True, replay
    assert _spend_run_count(runtime) == 0
    rc, after = _run_cli(registry, runtime, *guard_args)
    assert rc == 0 and after["selected_todo"]["todo_id"] == TODO_ID, after
