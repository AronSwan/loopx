from __future__ import annotations

import pytest

from loopx.control_plane.quota.settlement_workspace_causality import (
    build_delivery_workspace_causality,
    delivery_workspace_causality_event_fields,
    delivery_workspace_causality_from_event_details,
    missing_delivery_workspace_resolution,
)


@pytest.mark.parametrize(
    ("contract", "reason"),
    [
        (
            {"task_repository": "git:github.com/example/loopx"},
            "declared_repository_or_write_contract",
        ),
        (
            {"required_write_scopes": ["loopx/**"]},
            "declared_repository_or_write_contract",
        ),
        (
            {"required_capabilities": ["filesystem_write"]},
            "declared_repository_or_write_contract",
        ),
    ],
)
def test_declared_repository_write_contract_requires_workspace(
    contract: dict[str, object],
    reason: str,
) -> None:
    causality = build_delivery_workspace_causality(
        {"todo_id": "todo_write", **contract}
    )

    assert causality is not None
    assert causality["requirement"] == "required"
    assert causality["reason"] == reason


def test_explicit_non_delivery_contract_does_not_require_workspace() -> None:
    causality = build_delivery_workspace_causality(
        {
            "todo_id": "todo_read_only",
            "continuation_policy": "same_agent_non_delivery",
            "required_capabilities": ["shell", "filesystem_read"],
        }
    )

    assert causality == {
        "schema_version": "delivery_workspace_causality_v0",
        "todo_id": "todo_read_only",
        "requirement": "not_required",
        "source": "selected_todo_contract",
        "reason": "explicit_non_delivery_without_repository_writes",
    }


@pytest.mark.parametrize(
    "write_contract",
    [
        {"task_repository": "git:github.com/example/loopx"},
        {"required_write_scopes": ["loopx/**"]},
        {"required_capabilities": ["filesystem_write"]},
    ],
)
def test_non_delivery_policy_cannot_override_repository_write_contract(
    write_contract: dict[str, object],
) -> None:
    causality = build_delivery_workspace_causality(
        {
            "todo_id": "todo_write",
            "continuation_policy": "same_agent_non_delivery",
            **write_contract,
        }
    )

    assert causality is not None
    assert causality["requirement"] == "required"
    assert causality["reason"] == "declared_repository_or_write_contract"


def test_underspecified_current_todo_keeps_workspace_guard_fail_closed() -> None:
    causality = build_delivery_workspace_causality(
        {"todo_id": "todo_legacy", "action_kind": "inspect"}
    )

    assert causality is not None
    assert causality["requirement"] == "unknown"
    assert causality["reason"] == "todo_write_contract_not_explicit"


def test_unknown_causality_projects_typed_contract_repair() -> None:
    causality = build_delivery_workspace_causality({"todo_id": "todo_unknown"})

    assert causality is not None
    assert missing_delivery_workspace_resolution(causality) == {
        "schema_version": "delivery_workspace_resolution_v0",
        "todo_id": "todo_unknown",
        "decision": "repair_contract",
        "requirement": "unknown",
        "reason": "todo_delivery_contract_not_explicit",
        "accepted_resolutions": [
            "declare_repository_or_write_contract",
            "declare_explicit_non_delivery_contract",
        ],
    }


def test_event_fields_round_trip_without_nested_rollout_details() -> None:
    causality = build_delivery_workspace_causality(
        {
            "todo_id": "todo_read_only",
            "continuation_policy": "same_agent_non_delivery",
        }
    )
    details = delivery_workspace_causality_event_fields(causality)

    assert "delivery_workspace_causality" not in details
    assert delivery_workspace_causality_from_event_details(
        details,
        todo_id="todo_read_only",
    ) == causality


def test_event_causality_rejects_cross_todo_replay() -> None:
    causality = build_delivery_workspace_causality(
        {
            "todo_id": "todo_original",
            "continuation_policy": "same_agent_non_delivery",
        }
    )
    details = delivery_workspace_causality_event_fields(causality)

    assert (
        delivery_workspace_causality_from_event_details(
            details,
            todo_id="todo_successor",
        )
        is None
    )
