from __future__ import annotations

from typing import Any

from loopx.control_plane.quota.turn_envelope import build_turn_envelope
from loopx.control_plane.testing.quota_fixtures import (
    quota_status_payload,
    quota_todo_item,
    quota_todo_summary,
)
from loopx.control_plane.todos.summary_item import compact_todo_summary_item
from loopx.quota import build_quota_should_run

GOAL_ID = "agent-task-visibility-fixture"
AGENT_ID = "codex-current-peer"
OTHER_AGENT_ID = "codex-other-peer"


def _decision() -> dict[str, Any]:
    items = [
        quota_todo_item(
            todo_id="todo_current",
            index=1,
            title="Advance current peer work.",
            claimed_by=AGENT_ID,
            action_kind="issue_fix_branch_validation",
            target_key="issue-fix:owner/repo:issue_42",
            required_capabilities=["shell"],
            note=(
                "The implementation is already review-ready; next run the restart canary."
            ),
        ),
        quota_todo_item(
            todo_id="todo_unclaimed",
            index=2,
            title="Advance unclaimed work.",
            required_capabilities=["shell"],
        ),
        quota_todo_item(
            todo_id="todo_other",
            index=3,
            title="Advance other peer work.",
            claimed_by=OTHER_AGENT_ID,
            required_capabilities=["shell"],
        ),
    ]
    status = quota_status_payload(
        goal_id=GOAL_ID,
        status="active",
        recommended_action="Advance the current goal.",
        agent_todos=quota_todo_summary(items),
        coordination={
            "agent_model": "peer_v1",
            "registered_agents": [AGENT_ID, OTHER_AGENT_ID],
        },
    )
    decision: dict[str, Any] = build_quota_should_run(
        status,
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
    )
    return decision


def test_quota_projects_goal_scoped_read_and_execution_boundary() -> None:
    decision = _decision()

    assert (
        decision["task_scope"]
        == "goal_all_read_claimed_run_global_read_v0"
    )
    assert [
        item["todo_id"]
        for item in decision["agent_todo_summary"]["executable_backlog_items"]
    ] == ["todo_current", "todo_unclaimed"]
    assert [
        item["todo_id"]
        for item in decision["agent_todo_summary"]["claimed_by_others_items"]
    ] == ["todo_other"]
    assert decision["selected_todo"]["todo_id"] == "todo_current"
    assert decision["selected_todo"]["action_kind"] == "issue_fix_branch_validation"
    assert decision["selected_todo"]["target_key"] == (
        "issue-fix:owner/repo:issue_42"
    )
    assert decision["selected_todo"]["continuation_hint"] == (
        "The implementation is already review-ready; next run the restart canary."
    )


def test_todo_continuation_hint_drops_secret_bearing_source() -> None:
    credential_values = tuple(
        f"{name}=must-not-project; next run the canary."
        for name in ("api" + "_key", "tok" + "en", "pass" + "word")
    ) + (
        ("Author" + "ization")
        + ": "
        + ("Bear" + "er")
        + " must-not-project; next run the canary.",
    )
    for field in ("note", "continuation_hint"):
        for index, value in enumerate(credential_values):
            item = quota_todo_item(
                todo_id=f"todo_secret_{field}_{index}",
                title="Resume the current task.",
                **{field: value},
            )

            assert "continuation_hint" not in compact_todo_summary_item(item)


def test_todo_continuation_hint_only_projects_open_advancement_work() -> None:
    item = quota_todo_item(
        todo_id="todo_monitor",
        title="Poll the current target.",
        task_class="continuous_monitor",
        continuation_hint="Next inspect the material transition.",
    )

    assert "continuation_hint" not in compact_todo_summary_item(item)


def test_turn_envelope_retains_agent_task_visibility_contract() -> None:
    decision = _decision()

    envelope = build_turn_envelope(decision)

    assert (
        envelope["contract_capsule"]["task_scope"]
        == decision["task_scope"]
    )
