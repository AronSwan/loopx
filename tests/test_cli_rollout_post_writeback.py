from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from loopx.cli_rollout import append_cli_rollout_event
from loopx.control_plane.capability_hooks import (
    POST_WRITEBACK_HOOK_RESULT_SCHEMA_VERSION,
    PostWritebackHookRegistration,
)

_HOOK_ID = "fixture.post_writeback_probe"
_CAPABILITY_ID = "fixture-probe"
_SUBSCRIBED_KINDS = ("todo_complete",)


def _registration(
    *,
    producer: Any | None = None,
    subscribed: tuple[str, ...] = _SUBSCRIBED_KINDS,
) -> PostWritebackHookRegistration:
    def default_producer(receipt: Any) -> dict[str, Any]:
        return {
            "schema_version": POST_WRITEBACK_HOOK_RESULT_SCHEMA_VERSION,
            "hook_id": _HOOK_ID,
            "capability_id": _CAPABILITY_ID,
            "phase": "post_writeback",
            "status": "not_applicable",
            "intent_kind": None,
            "idempotency_key": None,
            "intent": None,
            "error_code": None,
        }

    return PostWritebackHookRegistration(
        hook_id=_HOOK_ID,
        capability_id=_CAPABILITY_ID,
        subscribed_event_kinds=subscribed,
        requested_read_scope=("durable_rollout_events",),
        producer=producer or default_producer,
        max_result_bytes=2048,
    )


def _append(
    tmp_path: Path,
    payload: dict[str, object],
    *,
    event_kind: str = "todo_complete",
    hooks: Any = None,
    idempotency_fields: list[str] | None = None,
    agent_id: str | None = "fixture-agent",
    todo_id: str | None = "todo_fixture0001",
) -> dict[str, object]:
    payload = dict(payload)
    payload.setdefault("runtime_root", str(tmp_path / "runtime"))
    return append_cli_rollout_event(
        payload,
        registry_path=tmp_path / "registry.json",
        runtime_root_arg=None,
        event_kind=event_kind,
        agent_id=agent_id,
        todo_id=todo_id,
        idempotency_fields=idempotency_fields,
        post_writeback_hooks=hooks,
    )


def _ok_payload() -> dict[str, object]:
    return {"ok": True, "goal_id": "fixture-goal"}


def test_newly_appended_event_dispatches_hook_once(tmp_path: Path) -> None:
    seen: list[dict[str, Any]] = []

    def producer(receipt: Any) -> dict[str, Any]:
        seen.append(dict(receipt))
        result = _registration().producer(receipt)
        result["status"] = "intent_ready"
        result["intent_kind"] = "fixture_probe_intent"
        result["idempotency_key"] = "sha256:0123456789abcdef0123456789abcdef"
        result["intent"] = {"probe": "typed"}
        return result

    hook = _registration(producer=producer)
    payload = _append(
        tmp_path,
        _ok_payload(),
        hooks=(hook,),
        idempotency_fields=["goal_id", "event_kind", "agent_id", "todo_id"],
    )

    assert len(seen) == 1
    receipt = seen[0]
    assert receipt["schema_version"] == "loopx_post_writeback_receipt_v0"
    assert receipt["appended"] is True
    assert receipt["goal_id"] == "fixture-goal"
    assert receipt["event_kind"] == "todo_complete"
    assert receipt["event_id"]
    assert receipt["recorded_at"]
    assert receipt["todo_id"] == "todo_fixture0001"

    summary = payload.get("post_writeback_hooks")
    assert isinstance(summary, dict)
    assert summary["phase"] == "post_writeback"
    assert summary["registered_count"] == 1
    results = summary["results"]
    assert isinstance(results, list) and len(results) == 1
    assert results[0]["hook_id"] == _HOOK_ID
    assert results[0]["status"] == "intent_ready"


def test_replayed_idempotent_append_dispatches_nothing(tmp_path: Path) -> None:
    seen: list[dict[str, Any]] = []

    def producer(receipt: Any) -> dict[str, Any]:
        seen.append(dict(receipt))
        return _registration().producer(receipt)

    hook = _registration(producer=producer)
    fields = ["goal_id", "event_kind", "agent_id", "todo_id"]
    first = _append(
        tmp_path,
        _ok_payload(),
        hooks=(hook,),
        idempotency_fields=fields,
    )
    assert "post_writeback_hooks" in first
    assert len(seen) == 1

    replay = _append(
        tmp_path,
        _ok_payload(),
        hooks=(hook,),
        idempotency_fields=fields,
    )
    assert len(seen) == 1, "a replayed writeback must not re-dispatch hooks"
    assert "post_writeback_hooks" not in replay
    rollout_event = replay.get("rollout_event")
    assert isinstance(rollout_event, dict)
    assert rollout_event.get("appended") is False


def test_unsubscribed_event_kind_is_skipped_not_invoked(tmp_path: Path) -> None:
    seen: list[dict[str, Any]] = []

    def producer(receipt: Any) -> dict[str, Any]:
        seen.append(dict(receipt))
        return _registration().producer(receipt)

    hook = _registration(producer=producer)
    payload = _append(
        tmp_path,
        _ok_payload(),
        event_kind="evidence_log_read",
        hooks=(hook,),
    )

    assert seen == []
    summary = payload.get("post_writeback_hooks")
    assert isinstance(summary, dict)
    assert summary["results"] == []
    skipped = summary.get("skipped_hooks")
    assert isinstance(skipped, list) and len(skipped) == 1
    assert skipped[0]["hook_id"] == _HOOK_ID
    assert skipped[0]["reason"] == "event_kind_not_subscribed"


def test_hook_failure_is_isolated_from_primary_writeback(tmp_path: Path) -> None:
    def exploding_producer(receipt: Any) -> dict[str, Any]:
        raise RuntimeError("capability probe exploded")

    hook = _registration(producer=exploding_producer)
    payload = _append(
        tmp_path,
        _ok_payload(),
        hooks=(hook,),
    )

    rollout_event = payload.get("rollout_event")
    assert isinstance(rollout_event, dict) and rollout_event.get("event_id")
    assert payload.get("ok") is True
    summary = payload.get("post_writeback_hooks")
    assert isinstance(summary, dict)
    failures = summary.get("failures")
    assert isinstance(failures, list) and len(failures) == 1
    assert failures[0]["hook_id"] == _HOOK_ID
    assert "post_writeback_hooks_error" not in payload


def test_failed_primary_payload_never_appends_or_dispatches(tmp_path: Path) -> None:
    seen: list[dict[str, Any]] = []

    def producer(receipt: Any) -> dict[str, Any]:
        seen.append(dict(receipt))
        return _registration().producer(receipt)

    hook = _registration(producer=producer)
    payload = _append(
        tmp_path,
        {"ok": False, "goal_id": "fixture-goal"},
        hooks=(hook,),
    )

    assert seen == []
    assert "rollout_event" not in payload
    assert "post_writeback_hooks" not in payload


def test_no_hooks_leaves_payload_untouched(tmp_path: Path) -> None:
    payload = _append(tmp_path, _ok_payload(), hooks=None)
    assert isinstance(payload.get("rollout_event"), dict)
    assert "post_writeback_hooks" not in payload
    assert "post_writeback_hooks_error" not in payload


def test_rollout_log_survives_hook_side_effects(tmp_path: Path) -> None:
    """The dispatch summary must not leak into the durable event log."""

    hook = _registration()
    runtime_root = tmp_path / "runtime"
    _append(
        tmp_path,
        _ok_payload(),
        hooks=(hook,),
        idempotency_fields=["goal_id", "event_kind"],
    )
    log_path = runtime_root / "goals" / "fixture-goal" / "rollout-event-log.jsonl"
    lines = [
        json.loads(line)
        for line in log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(lines) == 1
    assert "post_writeback_hooks" not in lines[0]
