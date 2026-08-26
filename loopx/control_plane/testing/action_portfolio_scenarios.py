from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..quota.cli_projection import compact_quota_should_run_cli_payload
from ..quota.should_run import build_quota_should_run
from ..quota.turn_envelope import quota_action_signature_document
from .quota_fixtures import quota_status_payload, quota_todo_item


ACTUAL_DEFAULT_MODEL_BEHAVIOR_FIXTURE_GOAL_ID = "portfolio-goal"
ACTUAL_DEFAULT_MODEL_BEHAVIOR_FIXTURE_AGENT_ID = "codex-portfolio"


def future_primary_fallback_scenario_source() -> dict[str, Any]:
    future_primary = quota_todo_item(
        todo_id="todo_future_primary",
        index=1,
        priority="P0",
        title="Poll the primary target at its next due window.",
        claimed_by=ACTUAL_DEFAULT_MODEL_BEHAVIOR_FIXTURE_AGENT_ID,
        task_class="continuous_monitor",
        action_kind="monitor",
        target_key="public-fixture-primary",
        cadence="daily",
        next_due_at="2099-01-01T00:00:00Z",
        watch_only=True,
    )
    ready_fallback = quota_todo_item(
        todo_id="todo_ready_fallback",
        index=2,
        priority="P1",
        title="Advance the ready bounded fallback slice.",
        claimed_by=ACTUAL_DEFAULT_MODEL_BEHAVIOR_FIXTURE_AGENT_ID,
    )
    status = quota_status_payload(
        goal_id=ACTUAL_DEFAULT_MODEL_BEHAVIOR_FIXTURE_GOAL_ID,
        status="active",
        agent_todo_items=[future_primary, ready_fallback],
        recommended_action=future_primary["text"],
        next_action=future_primary["text"],
        coordination={
            "agent_model": "peer_v1",
            "registered_agents": [ACTUAL_DEFAULT_MODEL_BEHAVIOR_FIXTURE_AGENT_ID],
        },
        claim_scope_agent_id=ACTUAL_DEFAULT_MODEL_BEHAVIOR_FIXTURE_AGENT_ID,
    )
    return build_quota_should_run(
        status,
        goal_id=ACTUAL_DEFAULT_MODEL_BEHAVIOR_FIXTURE_GOAL_ID,
        agent_id=ACTUAL_DEFAULT_MODEL_BEHAVIOR_FIXTURE_AGENT_ID,
    )


def external_wait_fallback_scenario_source() -> dict[str, Any]:
    waiting_primary = quota_todo_item(
        todo_id="todo_external_wait_primary",
        index=1,
        priority="P0",
        title="Resume the validated primary slice after external state changes.",
        claimed_by=ACTUAL_DEFAULT_MODEL_BEHAVIOR_FIXTURE_AGENT_ID,
        resume_when="monitor_changed:todo_external_wait_monitor",
        resume_monitor_generation=4,
        successor_todo_ids=["todo_external_wait_fallback"],
        note="Do not poll this Todo; its typed monitor condition is still pending.",
    )
    ready_fallback = quota_todo_item(
        todo_id="todo_external_wait_fallback",
        index=2,
        priority="P1",
        title="Advance the independent bounded fallback slice.",
        claimed_by=ACTUAL_DEFAULT_MODEL_BEHAVIOR_FIXTURE_AGENT_ID,
        note="Implement the fallback and run its focused validation.",
    )
    monitor = quota_todo_item(
        todo_id="todo_external_wait_monitor",
        index=3,
        priority="P2",
        title="Observe the external lifecycle for a material change.",
        claimed_by=ACTUAL_DEFAULT_MODEL_BEHAVIOR_FIXTURE_AGENT_ID,
        task_class="continuous_monitor",
        action_kind="monitor",
        target_key="public-fixture-external-lifecycle",
        cadence="daily",
        next_due_at="2099-01-01T00:00:00Z",
        watch_only=True,
        material_change_generation=4,
    )
    status = quota_status_payload(
        goal_id=ACTUAL_DEFAULT_MODEL_BEHAVIOR_FIXTURE_GOAL_ID,
        status="active",
        agent_todo_items=[waiting_primary, ready_fallback, monitor],
        recommended_action=waiting_primary["text"],
        next_action=waiting_primary["text"],
        coordination={
            "agent_model": "peer_v1",
            "registered_agents": [ACTUAL_DEFAULT_MODEL_BEHAVIOR_FIXTURE_AGENT_ID],
        },
        claim_scope_agent_id=ACTUAL_DEFAULT_MODEL_BEHAVIOR_FIXTURE_AGENT_ID,
    )
    return build_quota_should_run(
        status,
        goal_id=ACTUAL_DEFAULT_MODEL_BEHAVIOR_FIXTURE_GOAL_ID,
        agent_id=ACTUAL_DEFAULT_MODEL_BEHAVIOR_FIXTURE_AGENT_ID,
    )


def validate_future_primary_fallback_scenario(
    source_packet: Mapping[str, Any],
) -> None:
    signature = quota_action_signature_document(source_packet)
    action = dict(signature.get("action") or {})
    selected = dict(action.get("selected_todo") or {})
    portfolio = dict(action.get("action_portfolio") or {})
    primary = dict(portfolio.get("primary") or {})
    unavailable = list(portfolio.get("unavailable_higher_priority") or [])
    first_unavailable = dict(unavailable[0]) if unavailable else {}
    if not (
        selected.get("todo_id") == "todo_ready_fallback"
        and primary.get("todo_id") == "todo_ready_fallback"
        and first_unavailable.get("todo_id") == "todo_future_primary"
        and first_unavailable.get("availability_reason") == "scheduled_for_future"
    ):
        raise ValueError(
            "future-primary scenario must execute the ready fallback while "
            "preserving the unavailable higher-priority monitor"
        )


def validate_external_wait_fallback_scenario(
    source_packet: Mapping[str, Any],
) -> None:
    signature = quota_action_signature_document(source_packet)
    action = dict(signature.get("action") or {})
    selected = dict(action.get("selected_todo") or {})
    portfolio = dict(action.get("action_portfolio") or {})
    unavailable = list(portfolio.get("unavailable_higher_priority") or [])
    first_unavailable = dict(unavailable[0]) if unavailable else {}
    summary = dict(source_packet.get("agent_todo_summary") or {})
    resume_blocked = list(summary.get("resume_blocked_items") or [])
    first_resume_blocked = dict(resume_blocked[0]) if resume_blocked else {}
    condition = dict(first_resume_blocked.get("resume_condition") or {})
    compact = compact_quota_should_run_cli_payload(dict(source_packet))
    compact_portfolio = dict(compact.get("action_portfolio") or {})
    suggested = list(compact_portfolio.get("suggested_actions") or [])
    first_suggested = dict(suggested[0]) if suggested else {}
    if not (
        selected.get("todo_id") == "todo_external_wait_fallback"
        and source_packet.get("recommended_action")
        == "[P1] Advance the independent bounded fallback slice."
        and portfolio.get("schema_version") == "quota_action_portfolio_v2"
        and first_unavailable.get("todo_id") == "todo_external_wait_primary"
        and first_unavailable.get("availability_reason")
        == "resume_condition_pending"
        and first_resume_blocked.get("todo_id") == "todo_external_wait_primary"
        and first_resume_blocked.get("resume_ready") is False
        and condition.get("kind") == "monitor_changed"
        and condition.get("baseline_generation") == 4
        and condition.get("material_change_generation") == 4
        and first_suggested.get("todo_id") == "todo_external_wait_fallback"
        and first_suggested.get("continuation_hint")
        == "Implement the fallback and run its focused validation."
    ):
        raise ValueError(
            "external-wait scenario must expose the pending P0 condition while "
            "executing the bounded fallback from the compact default packet"
        )
