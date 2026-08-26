from __future__ import annotations

import pytest

from loopx.control_plane.capability_hooks import (
    POST_WRITEBACK_HOOK_RESULT_SCHEMA_VERSION,
    POST_WRITEBACK_RECEIPT_SCHEMA_VERSION,
    PostWritebackHookRegistration,
    dispatch_post_writeback_hooks,
)


def _receipt(**overrides: object) -> dict[str, object]:
    return {
        "schema_version": POST_WRITEBACK_RECEIPT_SCHEMA_VERSION,
        "goal_id": "long-research",
        "event_id": "evt-0001",
        "event_kind": "todo_complete",
        "recorded_at": "2026-08-24T12:00:00Z",
        "appended": True,
        **overrides,
    }


def _result(**overrides: object) -> dict[str, object]:
    return {
        "schema_version": POST_WRITEBACK_HOOK_RESULT_SCHEMA_VERSION,
        "hook_id": "periodic_report.post_writeback_trigger",
        "capability_id": "periodic-report",
        "phase": "post_writeback",
        "status": "intent_ready",
        "intent_kind": "periodic_report_trigger_evaluation",
        "idempotency_key": "sha256:" + "0" * 64,
        "intent": {"report_kind": "milestone_update"},
        "error_code": None,
        **overrides,
    }


def _hook(producer: object | None = None) -> PostWritebackHookRegistration:
    return PostWritebackHookRegistration(
        hook_id="periodic_report.post_writeback_trigger",
        capability_id="periodic-report",
        subscribed_event_kinds=("refresh_state", "todo_complete"),
        requested_read_scope=("durable_rollout_events",),
        producer=producer or (lambda receipt: _result()),  # type: ignore[arg-type]
    )


def test_post_writeback_hook_returns_validated_intent() -> None:
    dispatch = dispatch_post_writeback_hooks([_hook()], _receipt())

    assert dispatch["failures"] == []
    assert dispatch["invoked_count"] == 1
    assert dispatch["results"][0]["intent_kind"] == (
        "periodic_report_trigger_evaluation"
    )
    assert dispatch["primary_writeback_affected"] is False


def test_replayed_receipt_dispatches_nothing() -> None:
    calls: list[dict[str, object]] = []

    def produce(receipt: dict[str, object]) -> dict[str, object]:
        calls.append(receipt)
        return _result()

    dispatch = dispatch_post_writeback_hooks(
        [_hook(produce)], _receipt(appended=False)
    )

    assert calls == []
    assert dispatch["invoked_count"] == 0
    assert dispatch["results"] == []
    assert dispatch["failures"] == []
    assert dispatch["skipped_hooks"] == [
        {
            "hook_id": "periodic_report.post_writeback_trigger",
            "capability_id": "periodic-report",
            "reason": "replayed_receipt",
        }
    ]


def test_unsubscribed_event_kind_is_never_invoked() -> None:
    calls: list[dict[str, object]] = []

    def produce(receipt: dict[str, object]) -> dict[str, object]:
        calls.append(receipt)
        return _result()

    dispatch = dispatch_post_writeback_hooks(
        [_hook(produce)], _receipt(event_kind="goal_closed")
    )

    assert calls == []
    assert dispatch["invoked_count"] == 0
    assert dispatch["skipped_hooks"][0]["reason"] == "event_kind_not_subscribed"


def test_incomplete_intent_is_contract_rejected() -> None:
    dispatch = dispatch_post_writeback_hooks(
        [_hook(lambda receipt: _result(intent=None))], _receipt()
    )

    assert dispatch["results"] == []
    assert dispatch["failures"] == [
        {
            "hook_id": "periodic_report.post_writeback_trigger",
            "capability_id": "periodic-report",
            "error_code": "contract_rejected",
        }
    ]


def test_not_applicable_result_must_stay_empty() -> None:
    dispatch = dispatch_post_writeback_hooks(
        [_hook(lambda receipt: _result(status="not_applicable"))], _receipt()
    )

    assert dispatch["results"] == []
    assert dispatch["failures"][0]["error_code"] == "contract_rejected"


def test_producer_failure_is_isolated() -> None:
    def broken(receipt: dict[str, object]) -> dict[str, object]:
        raise RuntimeError("capability exploded")

    dispatch = dispatch_post_writeback_hooks([_hook(broken)], _receipt())

    assert dispatch["results"] == []
    assert dispatch["failures"] == [
        {
            "hook_id": "periodic_report.post_writeback_trigger",
            "capability_id": "periodic-report",
            "error_code": "producer_failed",
        }
    ]
    assert dispatch["primary_writeback_affected"] is False


def test_post_writeback_hooks_are_single_flight_by_identity() -> None:
    hook = _hook()

    dispatch = dispatch_post_writeback_hooks([hook, hook], _receipt())

    assert dispatch["invoked_count"] == 1
    assert dispatch["failures"][0]["error_code"] == "duplicate_hook_id"


def test_receipt_schema_mismatch_is_rejected() -> None:
    with pytest.raises(ValueError):
        dispatch_post_writeback_hooks(
            [_hook()], _receipt(schema_version="loopx_writeback_receipt_v0")
        )


def test_unknown_receipt_field_is_rejected() -> None:
    with pytest.raises(ValueError):
        dispatch_post_writeback_hooks(
            [_hook()], _receipt(raw_task_text="secret")
        )
