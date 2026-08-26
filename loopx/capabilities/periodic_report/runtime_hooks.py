from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from ...control_plane.capability_hooks import (
    POST_WRITEBACK_HOOK_RESULT_SCHEMA_VERSION,
    PostWritebackHookRegistration,
)
from ...rollout_event_log import iter_rollout_events, rollout_event_log_path
from .runtime_producer import (
    RUNTIME_TRIGGER_REQUEST_SCHEMA,
    build_periodic_report_runtime_trigger_decision,
)


PERIODIC_REPORT_POST_WRITEBACK_HOOK_ID = "periodic_report.post_writeback_trigger"
PERIODIC_REPORT_POST_WRITEBACK_CAPABILITY_ID = "periodic-report"
PERIODIC_REPORT_TRIGGER_INTENT_KIND = "periodic_report_trigger_evaluation"

_SUBSCRIBED_EVENT_KINDS = ("refresh_state", "todo_complete")
_DEFAULT_WINDOW_SECONDS = 7 * 24 * 60 * 60
_MAX_INTENT_EVENT_COUNT = 4096

RolloutEventReader = Callable[[str, str, str], Iterable[Mapping[str, Any]]]


def _empty_result() -> dict[str, Any]:
    return {
        "schema_version": POST_WRITEBACK_HOOK_RESULT_SCHEMA_VERSION,
        "hook_id": PERIODIC_REPORT_POST_WRITEBACK_HOOK_ID,
        "capability_id": PERIODIC_REPORT_POST_WRITEBACK_CAPABILITY_ID,
        "phase": "post_writeback",
        "status": "not_applicable",
        "intent_kind": None,
        "idempotency_key": None,
        "intent": None,
        "error_code": None,
    }


def _failure_result(error_code: str) -> dict[str, Any]:
    return {
        "schema_version": POST_WRITEBACK_HOOK_RESULT_SCHEMA_VERSION,
        "hook_id": PERIODIC_REPORT_POST_WRITEBACK_HOOK_ID,
        "capability_id": PERIODIC_REPORT_POST_WRITEBACK_CAPABILITY_ID,
        "phase": "post_writeback",
        "status": "failed",
        "intent_kind": None,
        "idempotency_key": None,
        "intent": None,
        "error_code": error_code,
    }


def _iso_z(value: datetime, *, receipt_text: str) -> str:
    encoded = value.isoformat()
    if receipt_text.endswith("Z"):
        return encoded.replace("+00:00", "Z")
    return encoded


def _intent_idempotency_key(
    *, event_id: str, segment_ref: str, evaluated_at: str
) -> str:
    digest = hashlib.sha256(
        "\n".join(
            (
                PERIODIC_REPORT_POST_WRITEBACK_HOOK_ID,
                event_id,
                segment_ref,
                evaluated_at,
            )
        ).encode("utf-8")
    ).hexdigest()
    return f"sha256:{digest}"


def build_periodic_report_post_writeback_hook(
    *,
    profile: Mapping[str, Any],
    trigger_policy: Mapping[str, Any],
    rollout_event_reader: RolloutEventReader,
    remaining_todo_count: int = 0,
    last_report: Mapping[str, Any] | None = None,
    max_result_bytes: int = 16 * 1024,
) -> PostWritebackHookRegistration:
    """Compose the runtime trigger producer behind the post-writeback phase.

    The composition root supplies the durable rollout event reader and the
    project-owned profile/policy; the hook itself only receives the
    public-safe writeback receipt and returns a typed trigger-evaluation
    intent without performing any external writes.
    """

    def produce(receipt: Mapping[str, Any]) -> dict[str, Any]:
        event_kind = str(receipt.get("event_kind") or "")
        if event_kind not in _SUBSCRIBED_EVENT_KINDS:
            return _empty_result()
        aggregation = None
        if isinstance(trigger_policy, Mapping):
            candidate = trigger_policy.get("aggregation")
            if isinstance(candidate, Mapping):
                aggregation = candidate
        if aggregation is None:
            return _empty_result()
        try:
            window_seconds = int(
                aggregation.get("window_seconds", _DEFAULT_WINDOW_SECONDS)
            )
        except (TypeError, ValueError):
            return _failure_result("aggregation_window_invalid")
        goal_id = str(receipt.get("goal_id") or "")
        event_id = str(receipt.get("event_id") or "")
        recorded_at = str(receipt.get("recorded_at") or "")
        try:
            end_value = datetime.fromisoformat(recorded_at.replace("Z", "+00:00"))
        except ValueError:
            return _failure_result("receipt_timestamp_invalid")
        start_value = end_value - timedelta(seconds=window_seconds)
        start_at = _iso_z(start_value, receipt_text=recorded_at)
        segment_ref = (
            "post_writeback."
            + hashlib.sha256(f"{event_id}\n{recorded_at}".encode("utf-8")).hexdigest()
        )
        try:
            request: dict[str, Any] = {
                "schema_version": RUNTIME_TRIGGER_REQUEST_SCHEMA,
                "evaluated_at": recorded_at,
                "goal_id": goal_id,
                "profile": dict(profile),
                "trigger_policy": dict(trigger_policy),
                "segment": {
                    "segment_ref": segment_ref,
                    "start_at": start_at,
                    "end_at": recorded_at,
                    "remaining_todo_count": remaining_todo_count,
                },
            }
            if last_report is not None:
                request["last_report"] = dict(last_report)
            events = list(rollout_event_reader(goal_id, start_at, recorded_at))
            decision = build_periodic_report_runtime_trigger_decision(
                request,
                rollout_events=events,
            )
        except Exception:  # noqa: BLE001 - capability failures stay isolated.
            return _failure_result("trigger_evaluation_failed")
        producer_receipt = decision.get("producer_receipt")
        if not isinstance(producer_receipt, Mapping):
            return _failure_result("producer_receipt_missing")
        if producer_receipt.get("status") != "promoted":
            return _empty_result()
        contributing = producer_receipt.get("contributing_event_ids")
        contributing_count = (
            len(contributing) if isinstance(contributing, list) else 0
        )
        if contributing_count > _MAX_INTENT_EVENT_COUNT:
            return _failure_result("intent_evidence_too_large")
        intent = {
            "report_kind": decision.get("report_kind"),
            "report_key": decision.get("report_key"),
            "selected_trigger_id": decision.get("selected_trigger_id"),
            "selected_trigger_kind": decision.get("selected_trigger_kind"),
            "producer_receipt": {
                "schema_version": producer_receipt.get("schema_version"),
                "status": producer_receipt.get("status"),
                "reason": producer_receipt.get("reason"),
                "goal_id": producer_receipt.get("goal_id"),
                "segment_ref": producer_receipt.get("segment_ref"),
                "window": dict(producer_receipt.get("window") or {}),
                "todo_completed_count": producer_receipt.get("todo_completed_count"),
                "replan_event_count": producer_receipt.get("replan_event_count"),
                "contributing_event_count": contributing_count,
                "transition": producer_receipt.get("transition"),
                "boundary": dict(producer_receipt.get("boundary") or {}),
            },
        }
        return {
            "schema_version": POST_WRITEBACK_HOOK_RESULT_SCHEMA_VERSION,
            "hook_id": PERIODIC_REPORT_POST_WRITEBACK_HOOK_ID,
            "capability_id": PERIODIC_REPORT_POST_WRITEBACK_CAPABILITY_ID,
            "phase": "post_writeback",
            "status": "intent_ready",
            "intent_kind": PERIODIC_REPORT_TRIGGER_INTENT_KIND,
            "idempotency_key": _intent_idempotency_key(
                event_id=event_id,
                segment_ref=segment_ref,
                evaluated_at=recorded_at,
            ),
            "intent": intent,
            "error_code": None,
        }

    return PostWritebackHookRegistration(
        hook_id=PERIODIC_REPORT_POST_WRITEBACK_HOOK_ID,
        capability_id=PERIODIC_REPORT_POST_WRITEBACK_CAPABILITY_ID,
        subscribed_event_kinds=_SUBSCRIBED_EVENT_KINDS,
        requested_read_scope=("durable_rollout_events",),
        producer=produce,
        max_result_bytes=max_result_bytes,
    )


def runtime_rollout_event_reader(runtime_root: Path) -> RolloutEventReader:
    """Read durable rollout events for one goal inside a bounded window.

    ``recorded_at`` values are emitted by the control plane in a single
    UTC ``Z``-suffixed format, so lexicographic comparison matches the
    chronological window the producer asked for.
    """

    def reader(goal_id: str, start_at: str, end_at: str) -> Iterable[Mapping[str, Any]]:
        log_path = rollout_event_log_path(runtime_root, goal_id)
        for event in iter_rollout_events(log_path):
            recorded_at = str(event.get("recorded_at") or "")
            if recorded_at and start_at <= recorded_at <= end_at:
                yield event

    return reader
