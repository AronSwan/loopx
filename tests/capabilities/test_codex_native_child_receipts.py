from __future__ import annotations

import json
from pathlib import Path

import pytest

from loopx.control_plane.turn_driver.codex_native_child import (
    configured_native_child_limit, CodexNativeChildObserver, native_child_observer,
)
from loopx.capabilities.multi_subagent.native_child_receipts import load_native_child_activity, record_native_child
from loopx.rollout_event_log import load_rollout_events, rollout_event_log_path
from tests.capabilities.test_native_child_receipts import _admit, GOAL, AGENT, TURN


def _turn():
    return {"id": "host-turn-1", "itemsView": "full", "status": "completed", "items": [
        {"type": "collabAgentToolCall", "id": "call-1", "senderThreadId": "parent-1",
         "tool": "spawnAgent", "status": "completed", "receiverThreadIds": ["child-1"],
         "prompt": "private child instructions", "agentsStates": {"child-1": {"status": "running"}}},
        {"type": "collabAgentToolCall", "id": "wait-1", "senderThreadId": "parent-1",
         "tool": "wait", "status": "completed", "agentsStates": {
             "child-1": {"status": "completed", "message": "private child result"}}},
    ]}


def _observe(root, items, session_id="parent-1"):
    observer = CodexNativeChildObserver(runtime_root=root,
        lineage={"goal_id": GOAL, "agent_id": AGENT},
        turn_instance_id=TURN, configured_limit=3)
    for item in items:
        observer.observe(item, session_id=session_id)


def test_host_spawn_result_parent_review_and_restart(tmp_path: Path):
    _admit(tmp_path)
    _observe(tmp_path, _turn()["items"])
    _observe(tmp_path, _turn()["items"])
    activity = load_native_child_activity(tmp_path, goal_id=GOAL, agent_id=AGENT,
        turn_instance_id=TURN, configured_limit=3)
    assert activity["observation"] == "host_observed"
    assert activity["host_attested"] is True
    assert activity["launched_count"] == 1
    assert activity["parent_accepted_count"] == 0
    [operation] = activity["operations"]
    assert operation["result"] == "completed"
    record_native_child(runtime_root=tmp_path, goal_id=GOAL, agent_id=AGENT,
        turn_instance_id=TURN, configured_limit=3, operation_id=operation["operation_id"],
        stage="review", outcome="accepted", evidence_ref="evidence-1",
        validation_ref="validation-1", execute=True)
    readback = load_native_child_activity(tmp_path, goal_id=GOAL, agent_id=AGENT,
        turn_instance_id=TURN, configured_limit=3)
    assert readback["parent_accepted_count"] == 1
    assert readback["host_attested"] is True
    events = load_rollout_events(rollout_event_log_path(tmp_path, GOAL))
    assert len(events) == 4
    assert "private child" not in json.dumps(events)
    assert all(event.get("event_kind") != "quota_spend" for event in events)


@pytest.mark.parametrize("items", [[], [{"type": "agentMessage", "text": "I spawned three children"}],
    [{**_turn()["items"][0], "status": "inProgress"}],
    [{**_turn()["items"][0], "senderThreadId": "historical-parent"}]])
def test_missing_or_unrelated_host_events_stay_unknown(tmp_path: Path, items):
    _admit(tmp_path)
    _observe(tmp_path, items)
    activity = load_native_child_activity(tmp_path, goal_id=GOAL, agent_id=AGENT,
        turn_instance_id=TURN, configured_limit=3)
    assert activity["observation"] == "unknown"
    assert activity["launched_count"] == 0


def test_exec_casing_and_display_counter_replay_do_not_duplicate_spawn(tmp_path: Path):
    _admit(tmp_path)
    snake = {"type": "collab_tool_call", "id": "item_1", "sender_thread_id": "parent-1",
        "tool": "spawn_agent", "status": "completed", "receiver_thread_ids": ["child-1"],
        "agents_states": {"child-1": {"status": "completed", "message": "private content"}}}
    _observe(tmp_path, [snake, {**snake, "id": "item_7"}])
    activity = load_native_child_activity(tmp_path, goal_id=GOAL, agent_id=AGENT,
        turn_instance_id=TURN, configured_limit=3)
    assert activity["host_attested"] is True
    assert activity["launched_count"] == 1
    assert activity["operations"][0]["result"] == "completed"
    assert len(load_rollout_events(rollout_event_log_path(tmp_path, GOAL))) == 3


def test_host_failure_does_not_infer_capacity_from_prose(tmp_path: Path):
    _admit(tmp_path)
    failed = {**_turn()["items"][0], "status": "failed", "receiverThreadIds": [],
        "agentsStates": {"child-1": {"status": "errored", "message": "agent_thread_limit_reached"}}}
    _observe(tmp_path, [failed])
    activity = load_native_child_activity(tmp_path, goal_id=GOAL, agent_id=AGENT,
        turn_instance_id=TURN, configured_limit=3)
    assert activity["host_attested"] is True
    assert activity["host_failed_count"] == 1
    assert activity["capacity_rejected_count"] == 0
    assert activity["retry_same_turn"] is False


def test_feature_off_has_no_observer_and_reports_cannot_attest_reviews(tmp_path: Path):
    assert native_child_observer({"turn_envelope": {}}, runtime_root=tmp_path,
        lineage={"goal_id": GOAL, "agent_id": AGENT}) is None
    assert configured_native_child_limit({"turn_envelope": {}}) is None
    assert configured_native_child_limit({"turn_envelope": {"agent_context": {
        "contributions": [{"capability_id": "multi_subagent", "facts": {"max_children": 0}}]}}}) is None
    with pytest.raises(ValueError, match="cannot attest"):
        record_native_child(runtime_root=tmp_path, goal_id=GOAL, agent_id=AGENT,
            turn_instance_id=TURN, configured_limit=3, operation_id="review-1", stage="review",
            outcome="accepted", evidence_ref="evidence-1", validation_ref="validation-1",
            execute=True, _host_observed=True)


def test_cli_host_collects_native_items_before_returning_parent_result(tmp_path: Path, monkeypatch):
    import sys
    from loopx.control_plane.turn_driver import codex_cli
    from tests.test_loopx_turn_codex_cli import _request

    _admit(tmp_path)
    request = _request()
    request["turn_instance_id"] = TURN
    request["turn_envelope"].update(goal_id=GOAL, agent_id=AGENT, agent_context={
        "contributions": [{"capability_id": "multi_subagent", "facts": {"max_children": 3}}]})
    request["turn_envelope"]["action"]["selected_todo"]["todo_id"] = "todo_native_1"

    def host(command, **kwargs):
        kwargs["on_stdout"](json.dumps({"type": "thread.started", "thread_id": "parent-1"}) + "\n")
        for item in _turn()["items"]:
            kwargs["on_stdout"](json.dumps({"type": "item.completed", "item": item}) + "\n")
        Path(command[command.index("--output-last-message") + 1]).write_text(json.dumps({"parent_work": "preserved"}))
        return {"returncode": 0, "outcome": "exited", "output_complete": True}

    monkeypatch.setattr(codex_cli, "run_host_process", host)
    assert codex_cli.run_codex_cli_host(request, runtime_root=tmp_path, project=tmp_path,
        codex_bin=sys.executable) == {"parent_work": "preserved"}
    activity = load_native_child_activity(tmp_path, goal_id=GOAL, agent_id=AGENT,
        turn_instance_id=TURN, configured_limit=3)
    assert activity["host_attested"] is True
    assert activity["launched_count"] == 1
    assert activity["operations"][0]["result"] == "completed"
