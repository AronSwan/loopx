from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .control_plane.capability_hooks import (
    POST_WRITEBACK_RECEIPT_SCHEMA_VERSION,
    PostWritebackHookRegistration,
    dispatch_post_writeback_hooks,
)
from .history import load_registry
from .paths import resolve_runtime_root
from .rollout_event_log import (
    append_rollout_event,
    append_rollout_event_once,
    build_rollout_event,
    rollout_event_log_path,
)


def _run_post_writeback_hooks(
    payload: dict[str, object],
    *,
    hooks: Sequence[PostWritebackHookRegistration],
    appended_event: dict[str, Any],
) -> dict[str, object]:
    """Dispatch intent-only hooks once, after one newly appended writeback.

    The dispatch happens at this CLI orchestration boundary on purpose: the
    low-level append helpers stay capability-free, and the receipt handed to
    hooks is the public-safe event identity only. Dispatch is best-effort and
    isolated; a hook-side failure is recorded for observation but never rolls
    back or fails the primary writeback.
    """

    receipt: dict[str, object] = {
        "schema_version": POST_WRITEBACK_RECEIPT_SCHEMA_VERSION,
        "goal_id": str(appended_event.get("goal_id") or ""),
        "event_id": str(appended_event.get("event_id") or ""),
        "event_kind": str(appended_event.get("event_kind") or ""),
        "recorded_at": str(appended_event.get("recorded_at") or ""),
        "appended": True,
    }
    for optional in ("agent_id", "todo_id"):
        value = appended_event.get(optional)
        if value:
            receipt[optional] = str(value)
    try:
        payload["post_writeback_hooks"] = dispatch_post_writeback_hooks(
            hooks, receipt
        )
    except Exception as exc:
        payload["post_writeback_hooks_error"] = {
            "dispatched": False,
            "error_type": type(exc).__name__,
            "message": (
                "post-writeback hook dispatch failed; primary writeback "
                "remains authoritative"
            ),
        }
    return payload


def append_cli_rollout_event(
    payload: dict[str, object],
    *,
    registry_path: Path,
    runtime_root_arg: str | None,
    event_kind: str,
    agent_id: str | None = None,
    todo_id: str | None = None,
    case_id: str | None = None,
    run_id: str | None = None,
    status: str | None = None,
    summary: str | None = None,
    labels: list[str] | None = None,
    artifact_refs: list[str] | None = None,
    details: dict[str, object] | None = None,
    allow_failed: bool = False,
    idempotency_fields: list[str] | None = None,
    post_writeback_hooks: Sequence[PostWritebackHookRegistration] | None = None,
) -> dict[str, object]:
    """Append a compact rollout event for core CLI lifecycle commands.

    Rollout logging is intentionally best-effort so the diagnostic log cannot
    turn a successful state transition into a failed CLI command. Failures are
    surfaced in the command payload as compact metadata.

    When ``post_writeback_hooks`` is supplied and this call newly appended the
    durable event, the hooks are dispatched exactly once with the public-safe
    receipt. A replayed (idempotent) append dispatches nothing, and the
    dispatch itself is isolated from the primary writeback.
    """

    if not payload.get("ok") and not allow_failed:
        return payload
    goal_id = str(payload.get("goal_id") or "").strip()
    if not goal_id:
        return payload
    try:
        runtime_root_value = payload.get("runtime_root")
        if runtime_root_value:
            runtime_root = Path(str(runtime_root_value)).expanduser()
        else:
            registry = load_registry(registry_path)
            runtime_root = resolve_runtime_root(registry, runtime_root_arg)
        event = build_rollout_event(
            goal_id=goal_id,
            event_kind=event_kind,
            agent_id=agent_id or str(payload.get("agent_id") or "").strip() or None,
            todo_id=todo_id or str(payload.get("todo_id") or "").strip() or None,
            case_id=case_id,
            run_id=run_id,
            status=status,
            classification=str(payload.get("classification") or "").strip() or None,
            delivery_outcome=str(payload.get("delivery_outcome") or "").strip() or None,
            labels=labels,
            summary=summary,
            artifact_refs=artifact_refs,
            details=details,
        )
        log_path = rollout_event_log_path(runtime_root, goal_id)
        if idempotency_fields:
            appended, newly_appended = append_rollout_event_once(
                log_path,
                event,
                identity_fields=idempotency_fields,
            )
        else:
            appended = append_rollout_event(log_path, event)
            newly_appended = True
        rollout_event_view = {
            "schema_version": appended["schema_version"],
            "event_id": appended["event_id"],
            "event_kind": appended["event_kind"],
            "recorded_at": appended["recorded_at"],
            "status": appended.get("status"),
        }
        if idempotency_fields:
            rollout_event_view["appended"] = newly_appended
        payload["rollout_event"] = rollout_event_view
    except Exception as exc:
        payload["rollout_event_log_error"] = {
            "recorded": False,
            "error_type": type(exc).__name__,
            "message": "rollout event append failed; primary command payload remains authoritative",
        }
        return payload
    if post_writeback_hooks and newly_appended:
        payload = _run_post_writeback_hooks(
            payload,
            hooks=post_writeback_hooks,
            appended_event=appended,
        )
    return payload
