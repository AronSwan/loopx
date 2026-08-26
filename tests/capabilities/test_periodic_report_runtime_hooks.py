from __future__ import annotations

from typing import Any

from loopx.capabilities.periodic_report.runtime_hooks import (
    build_periodic_report_post_writeback_hook,
)
from loopx.control_plane.capability_hooks import (
    POST_WRITEBACK_RECEIPT_SCHEMA_VERSION,
    dispatch_post_writeback_hooks,
)
from loopx.rollout_event_log import build_rollout_event


_PROFILE: dict[str, Any] = {
    "profile_id": "weekly_progress",
    "profile_version": "v1",
}


def _policy(*, threshold: int = 2, promote_replan: bool = True) -> dict[str, Any]:
    return {
        "enabled_kinds": ["bounded_segment_milestone"],
        "minimum_interval_seconds": 0,
        "aggregation": {
            "window_seconds": 604800,
            "todo_completed_threshold": threshold,
            "promote_replan": promote_replan,
        },
    }


def _receipt(**overrides: Any) -> dict[str, Any]:
    return {
        "schema_version": POST_WRITEBACK_RECEIPT_SCHEMA_VERSION,
        "goal_id": "long-research",
        "event_id": "evt-0002",
        "event_kind": "todo_complete",
        "recorded_at": "2026-08-24T12:00:00Z",
        "appended": True,
        **overrides,
    }


def _event(
    kind: str,
    *,
    event_at: str,
    todo_id: str | None = None,
    replan: bool = False,
) -> dict[str, Any]:
    return build_rollout_event(
        goal_id="long-research",
        event_kind=kind,
        todo_id=todo_id,
        recorded_at=event_at,
        details={"autonomous_replan_recorded": replan},
    )


def _hook(
    events: list[dict[str, Any]],
    *,
    policy: dict[str, Any] | None = None,
    reader_raises: bool = False,
):
    def reader(goal_id: str, start_at: str, end_at: str):
        if reader_raises:
            raise RuntimeError("durable log unavailable")
        return list(events)

    return build_periodic_report_post_writeback_hook(
        profile=_PROFILE,
        trigger_policy=policy if policy is not None else _policy(),
        rollout_event_reader=reader,
        remaining_todo_count=12,
    )


def test_todo_completion_receipt_promotes_trigger_intent() -> None:
    events = [
        _event("todo_complete", event_at="2026-08-20T09:00:00Z", todo_id="todo-1"),
        _event("todo_complete", event_at="2026-08-21T10:00:00Z", todo_id="todo-2"),
    ]

    dispatch = dispatch_post_writeback_hooks([_hook(events)], _receipt())

    assert dispatch["failures"] == []
    assert dispatch["invoked_count"] == 1
    result = dispatch["results"][0]
    assert result["status"] == "intent_ready"
    assert result["intent_kind"] == "periodic_report_trigger_evaluation"
    assert result["idempotency_key"].startswith("sha256:")
    intent = result["intent"]
    assert intent["report_kind"] == "milestone_update"
    assert intent["selected_trigger_kind"] == "bounded_segment_milestone"
    assert intent["producer_receipt"]["transition"] == "segment_completed"
    assert intent["producer_receipt"]["contributing_event_count"] == 2
    assert intent["producer_receipt"]["boundary"]["external_writes_performed"] is False


def test_replan_receipt_promotes_replan_entered() -> None:
    events = [
        _event("todo_complete", event_at="2026-08-20T09:00:00Z", todo_id="todo-1"),
        _event(
            "refresh_state",
            event_at="2026-08-21T10:00:00Z",
            replan=True,
        ),
    ]

    dispatch = dispatch_post_writeback_hooks(
        [_hook(events)], _receipt(event_kind="refresh_state")
    )

    assert dispatch["failures"] == []
    intent = dispatch["results"][0]["intent"]
    assert intent["producer_receipt"]["transition"] == "replan_entered"
    assert intent["producer_receipt"]["reason"] == "durable_replan_observed"


def test_below_threshold_stays_not_applicable() -> None:
    events = [
        _event("todo_complete", event_at="2026-08-20T09:00:00Z", todo_id="todo-1"),
    ]

    dispatch = dispatch_post_writeback_hooks([_hook(events)], _receipt())

    assert dispatch["failures"] == []
    assert dispatch["results"][0]["status"] == "not_applicable"
    assert dispatch["results"][0]["intent"] is None


def test_missing_aggregation_is_not_applicable_without_reads() -> None:
    calls: list[tuple[str, str, str]] = []

    def reader(goal_id: str, start_at: str, end_at: str):
        calls.append((goal_id, start_at, end_at))
        return []

    hook = build_periodic_report_post_writeback_hook(
        profile=_PROFILE,
        trigger_policy={"enabled_kinds": ["bounded_segment_milestone"]},
        rollout_event_reader=reader,
    )

    dispatch = dispatch_post_writeback_hooks([hook], _receipt())

    assert calls == []
    assert dispatch["failures"] == []
    assert dispatch["results"][0]["status"] == "not_applicable"


def test_reader_failure_returns_isolated_failed_intent() -> None:
    dispatch = dispatch_post_writeback_hooks(
        [_hook([], reader_raises=True)], _receipt()
    )

    assert dispatch["failures"] == []
    result = dispatch["results"][0]
    assert result["status"] == "failed"
    assert result["error_code"] == "trigger_evaluation_failed"
    assert result["intent"] is None
    assert dispatch["primary_writeback_affected"] is False


def test_replayed_receipt_never_reaches_the_producer() -> None:
    calls: list[tuple[str, str, str]] = []

    def reader(goal_id: str, start_at: str, end_at: str):
        calls.append((goal_id, start_at, end_at))
        return []

    hook = build_periodic_report_post_writeback_hook(
        profile=_PROFILE,
        trigger_policy=_policy(),
        rollout_event_reader=reader,
    )

    dispatch = dispatch_post_writeback_hooks([hook], _receipt(appended=False))

    assert calls == []
    assert dispatch["invoked_count"] == 0
    assert dispatch["results"] == []
