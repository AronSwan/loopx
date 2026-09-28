"""A due monitor poll is only advertised when this Turn can actually poll it."""

from __future__ import annotations

from loopx.control_plane.work_items.interaction_contract import (
    build_interaction_contract,
)

DUE_MONITOR_TODO_ID = "todo_due_monitor_fixture"


def _payload(*, portfolio_requires_explicit_binding: bool) -> dict[str, object]:
    payload: dict[str, object] = {
        "goal_id": "auxiliary-monitor-availability-fixture",
        "effective_action": "normal_run",
        "should_run": True,
        "normal_delivery_allowed": True,
        "reason": "advance the first executable agent todo",
        "agent_identity": {"agent_id": "agent-fixture"},
        "execution_obligation": {
            "must_attempt_work": True,
            "kind": "work_lane_contract",
        },
        "heartbeat_recommendation": {
            "notify": "DONT_NOTIFY",
            "recommended_mode": "normal_run",
        },
        "work_lane_contract": {
            "schema_version": "work_lane_contract_v1",
            "lane": "advancement_task",
            "auxiliary_monitor_poll": {
                "schema_version": "auxiliary_monitor_poll_v0",
                "required": False,
                "preempts_advancement": False,
                "spend_policy": "no_spend",
                "continuation": "advancement_remains_primary",
                "monitor_due_count": 1,
                "selected_todo_id": DUE_MONITOR_TODO_ID,
                "selected_next_due_at": "2026-09-22T10:30:28Z",
            },
        },
    }
    if portfolio_requires_explicit_binding:
        payload["action_portfolio"] = {
            "schema_version": "action_portfolio_v0",
            "selection_policy": {
                "mode": "explicit_turn_binding",
                "requires_explicit_turn_binding": True,
            },
        }
    return payload


def _poll_projection(payload: dict[str, object]) -> dict[str, object]:
    contract = build_interaction_contract(
        payload,
        available_capabilities=["network", "external_evidence_poll"],
        turn_instance_id="turn-auxiliary-monitor-availability",
        runtime_root="/tmp/auxiliary-monitor-availability-runtime",
    )
    cli_channel = contract["cli_channel"]
    assert isinstance(cli_channel, dict)
    projection = cli_channel["auxiliary_monitor_poll"]
    assert isinstance(projection, dict)
    return projection


def test_identity_less_turn_names_the_missing_receipt_binding() -> None:
    """The offered command could only fail on identity, so it is not offered."""

    projection = _poll_projection(_payload(portfolio_requires_explicit_binding=True))

    assert projection["availability"] == "receipt_binding_required"
    assert projection["reason_code"] == "auxiliary_monitor_receipt_not_bound"
    assert projection["selected_todo_id"] == DUE_MONITOR_TODO_ID
    assert "command" not in projection
    assert "material_change_command" not in projection
    assert "bind the Turn to a claimed Todo" in str(projection["next_step"])


def test_turn_with_a_settlement_binding_still_offers_the_poll_command() -> None:
    """Parity: a Turn that can carry the observation keeps the ready command."""

    projection = _poll_projection(_payload(portfolio_requires_explicit_binding=False))

    assert projection["availability"] == "ready"
    assert projection["turn_instance_id"] == "turn-auxiliary-monitor-availability"
    assert "quota monitor-poll" in str(projection["command"])
    assert DUE_MONITOR_TODO_ID in str(projection["command"])
    assert "--use-current-task-lease" in str(projection["command"])
    assert projection["input_contract"]["task_lease_proof"]["source"] == "canonical_lease_or_same_turn_receipt"
