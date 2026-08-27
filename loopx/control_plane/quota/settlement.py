from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..effect_runtime import EffectRuntimeRejected, effect_runtime_result
from ..settlement_driver import decode_settlement_result
from .effect_program import (
    SETTLEMENT_IDENTITY_SCHEMA_VERSION,
    SETTLEMENT_PLAN_SCHEMA_VERSION,
    SETTLEMENT_RECEIPT_SCHEMA_VERSION,
    SettlementFailure,
    SettlementFailureKind,
    SettlementIdentity,
    SettlementPlan,
    SettlementReceipt,
    SettlementResult,
    SettlementStep,
    SettlementStepKind,
    ReceiptBoundMonitorPhase,
    ReceiptBoundReplayPhase,
    ReceiptBoundTerminalPhase,
    build_codex_app_settlement_plan,
    build_turn_scoped_cli_settlement_plan,
    settlement_binding_args,
    settlement_result_payload,
    settlement_step_command,
)


QUOTA_SETTLEMENT_READBACK_REQUEST_SCHEMA = (
    "loopx_quota_settlement_readback_request_v0"
)
QUOTA_SETTLEMENT_READBACK_RESULT_SCHEMA = (
    "loopx_quota_settlement_readback_result_v0"
)


@dataclass(frozen=True, slots=True)
class QuotaSettlementReadback:
    identity: SettlementResult[SettlementIdentity]
    writeback: SettlementResult[dict[str, Any]]
    spend: SettlementResult[dict[str, Any]]
    delivery: SettlementResult[dict[str, Any]]
    settlement: SettlementResult[dict[str, Any]]
    terminal_closeout: SettlementResult[dict[str, Any]]
    terminal_settlement: SettlementResult[dict[str, Any]]
    workspace_causality: dict[str, str] | None
    writeback_run: dict[str, Any] | None
    spend_run: dict[str, Any] | None
    heartbeat_receipt: dict[str, Any] | None
    writeback_event: dict[str, Any] | None
    spend_event: dict[str, Any] | None
    completion_event: dict[str, Any] | None
    monitor_phase: ReceiptBoundMonitorPhase | None
    replay_phase: ReceiptBoundReplayPhase | None

__all__ = [
    "SETTLEMENT_IDENTITY_SCHEMA_VERSION",
    "SETTLEMENT_PLAN_SCHEMA_VERSION",
    "SETTLEMENT_RECEIPT_SCHEMA_VERSION",
    "SettlementFailure",
    "SettlementFailureKind",
    "SettlementIdentity",
    "SettlementPlan",
    "SettlementReceipt",
    "SettlementResult",
    "SettlementStep",
    "SettlementStepKind",
    "build_codex_app_settlement_plan",
    "build_turn_scoped_cli_settlement_plan",
    "find_quota_spend_run_by_effect_ref",
    "find_settlement_spend_run",
    "find_settlement_step_event",
    "find_settlement_writeback",
    "infer_persisted_heartbeat_settlement_identity",
    "read_heartbeat_settlement",
    "receipt_bound_monitor_settlement_phase",
    "receipt_bound_replay_settlement_phase",
    "receipt_bound_terminal_settlement_phase",
    "require_settlement_spend",
    "require_settlement_terminal_closeout",
    "require_settlement_writeback",
    "resolve_heartbeat_settlement_identity",
    "resolve_settlement_delivery_workspace_causality",
    "settlement_binding_args",
    "settlement_result_payload",
    "settlement_step_command",
]


def _readback_result(
    payload: Any,
    *,
    identity: bool = False,
) -> SettlementResult[Any]:
    if not isinstance(payload, Mapping):
        raise RuntimeError("TypeScript quota settlement readback result shape mismatch")
    result = payload.get("result")
    projection = payload.get("payload")
    if not isinstance(result, Mapping) or not isinstance(projection, Mapping):
        raise RuntimeError("TypeScript quota settlement readback result shape mismatch")
    return decode_settlement_result(
        result,
        value_decoder=(
            SettlementIdentity.from_runtime_payload if identity else None
        ),
        projection_payload=projection,
    )


def _optional_readback_record(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise RuntimeError("TypeScript quota settlement readback result shape mismatch")
    return dict(value)


def read_heartbeat_settlement(
    runtime_root: Path,
    *,
    goal_id: str,
    agent_id: str | None,
    todo_id: str | None,
    turn_instance_id: str | None,
    replan_obligation_id: str | None = None,
    infer_turn_instance_id: bool = False,
    allow_unbound_binding: bool = False,
) -> QuotaSettlementReadback | None:
    """Read one complete heartbeat settlement through the TS domain owner."""

    try:
        payload = effect_runtime_result(
            "quota.settlement.read",
            {
                "schema_version": QUOTA_SETTLEMENT_READBACK_REQUEST_SCHEMA,
                "runtime_root": str(runtime_root.expanduser()),
                "goal_id": goal_id,
                "agent_id": agent_id,
                "todo_id": todo_id,
                "turn_instance_id": turn_instance_id,
                "replan_obligation_id": replan_obligation_id,
                "infer_turn_instance_id": infer_turn_instance_id,
                "allow_unbound_binding": allow_unbound_binding,
            },
        )
    except EffectRuntimeRejected as exc:
        raise ValueError(str(exc)) from None
    if not isinstance(payload, Mapping) or (
        payload.get("schema_version")
        != QUOTA_SETTLEMENT_READBACK_RESULT_SCHEMA
    ):
        raise RuntimeError("TypeScript quota settlement readback result shape mismatch")
    if payload.get("found") is False:
        if set(payload) != {"schema_version", "found"}:
            raise RuntimeError(
                "TypeScript quota settlement readback result shape mismatch"
            )
        return None
    if payload.get("found") is not True:
        raise RuntimeError("TypeScript quota settlement readback result shape mismatch")
    workspace_causality = _optional_readback_record(
        payload.get("workspace_causality")
    )
    monitor_phase = payload.get("monitor_phase")
    replay_phase = payload.get("replay_phase")
    if monitor_phase not in {None, "poll_due", "settlement_pending", "settled"} or (
        replay_phase not in {None, "open", "settlement_pending", "settled"}
    ):
        raise RuntimeError("TypeScript quota settlement readback result shape mismatch")
    return QuotaSettlementReadback(
        identity=_readback_result(payload.get("identity"), identity=True),
        writeback=_readback_result(payload.get("writeback")),
        spend=_readback_result(payload.get("spend")),
        delivery=_readback_result(payload.get("delivery")),
        settlement=_readback_result(payload.get("settlement")),
        terminal_closeout=_readback_result(payload.get("terminal_closeout")),
        terminal_settlement=_readback_result(payload.get("terminal_settlement")),
        workspace_causality=(
            {str(key): str(value) for key, value in workspace_causality.items()}
            if workspace_causality is not None
            else None
        ),
        writeback_run=_optional_readback_record(payload.get("writeback_run")),
        spend_run=_optional_readback_record(payload.get("spend_run")),
        heartbeat_receipt=_optional_readback_record(payload.get("heartbeat_receipt")),
        writeback_event=_optional_readback_record(payload.get("writeback_event")),
        spend_event=_optional_readback_record(payload.get("spend_event")),
        completion_event=_optional_readback_record(payload.get("completion_event")),
        monitor_phase=(
            ReceiptBoundMonitorPhase(str(monitor_phase))
            if monitor_phase is not None
            else None
        ),
        replay_phase=(
            ReceiptBoundReplayPhase(str(replay_phase))
            if replay_phase is not None
            else None
        ),
    )


def receipt_bound_monitor_settlement_phase(
    runtime_root: Path,
    *,
    goal_id: str,
    agent_id: str | None,
    todo_id: str | None,
    turn_instance_id: str | None,
) -> ReceiptBoundMonitorPhase | None:
    """Resolve the typed phase for one receipt-bound monitor turn.

    A missing matching poll remains explicitly ``poll_due`` even when mutable
    Todo scheduling metadata has moved into the future.  An unchanged poll is
    terminal by itself.  A material poll is terminal only after the exact
    heartbeat identity has both durable writeback and quota-spend receipts.
    ``None`` is reserved for an invalid receipt identity or runtime failure.
    """

    readback = read_heartbeat_settlement(
        runtime_root,
        goal_id=goal_id,
        agent_id=agent_id,
        todo_id=todo_id,
        turn_instance_id=turn_instance_id,
    )
    if readback is None or readback.monitor_phase is None:
        return None
    return ReceiptBoundMonitorPhase(readback.monitor_phase)


def receipt_bound_replay_settlement_phase(
    runtime_root: Path,
    *,
    goal_id: str,
    agent_id: str | None,
    todo_id: str | None,
    turn_instance_id: str | None,
    replan_obligation_id: str | None = None,
) -> ReceiptBoundReplayPhase | None:
    """Resolve settled replay for the exact persisted receipt identity.

    Replay is complete only after the original Todo has a matching completion,
    durable writeback, and quota-spend receipt. The completion may establish an
    ordinary successor or close the goal terminally; either way that successor
    belongs to a fresh turn. A partial chain remains pending and cannot suppress
    live work selection.
    """

    readback = read_heartbeat_settlement(
        runtime_root,
        goal_id=goal_id,
        agent_id=agent_id,
        todo_id=todo_id,
        turn_instance_id=turn_instance_id,
        replan_obligation_id=replan_obligation_id,
    )
    if readback is None or readback.replay_phase is None:
        return None
    return ReceiptBoundReplayPhase(readback.replay_phase)


def receipt_bound_terminal_settlement_phase(
    runtime_root: Path,
    *,
    goal_id: str,
    agent_id: str | None,
    todo_id: str | None,
    turn_instance_id: str | None,
    replan_obligation_id: str | None = None,
) -> ReceiptBoundTerminalPhase | None:
    """Compatibility alias for the pre-successor replay resolver."""

    return receipt_bound_replay_settlement_phase(
        runtime_root,
        goal_id=goal_id,
        agent_id=agent_id,
        todo_id=todo_id,
        turn_instance_id=turn_instance_id,
        replan_obligation_id=replan_obligation_id,
    )


def resolve_settlement_delivery_workspace_causality(
    runtime_root: Path,
    identity: SettlementIdentity,
) -> dict[str, str] | None:
    readback = read_heartbeat_settlement(
        runtime_root,
        goal_id=identity.goal_id,
        agent_id=identity.agent_id,
        todo_id=identity.todo_id,
        turn_instance_id=identity.turn_instance_id,
        replan_obligation_id=identity.replan_obligation_id,
    )
    return readback.workspace_causality if readback is not None else None


def resolve_heartbeat_settlement_identity(
    runtime_root: Path,
    *,
    goal_id: str,
    agent_id: str | None,
    todo_id: str | None,
    turn_instance_id: str | None,
    replan_obligation_id: str | None = None,
) -> SettlementResult[SettlementIdentity]:
    readback = read_heartbeat_settlement(
        runtime_root,
        goal_id=goal_id,
        agent_id=agent_id,
        todo_id=todo_id,
        turn_instance_id=turn_instance_id,
        replan_obligation_id=replan_obligation_id,
    )
    if readback is None:
        raise RuntimeError("exact settlement readback unexpectedly returned not-found")
    return readback.identity


def _run_index_records(runtime_root: Path, goal_id: str) -> list[dict[str, Any]]:
    index_path = runtime_root / "goals" / goal_id / "runs" / "index.jsonl"
    if not index_path.exists():
        return []
    records: list[dict[str, Any]] = []
    try:
        lines = index_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def infer_persisted_heartbeat_settlement_identity(
    runtime_root: Path,
    *,
    goal_id: str,
    agent_id: str | None,
    todo_id: str | None,
    allow_unbound_binding: bool = False,
) -> SettlementResult[SettlementIdentity] | None:
    """Recover the latest typed heartbeat identity when a caller omits identity fields.

    This is a compatibility recovery seam, not a second source of truth. It
    considers only the newest same-agent accountable writeback or spend, and
    then revalidates that candidate against the original heartbeat guard.
    Callers normally supply the Todo binding and omit only the Turn. A visible
    Goal delivery-completion path may opt into recovering both binding and Turn
    from a fully typed persisted run after the frontier has already replanned.
    Unrelated lineages and legacy untyped runs fall back to the existing
    frontier binding rules.
    """
    readback = read_heartbeat_settlement(
        runtime_root,
        goal_id=goal_id,
        agent_id=agent_id,
        todo_id=todo_id,
        turn_instance_id=None,
        infer_turn_instance_id=True,
        allow_unbound_binding=allow_unbound_binding,
    )
    return readback.identity if readback is not None else None


def find_settlement_writeback(
    runtime_root: Path,
    identity: SettlementIdentity,
) -> dict[str, Any] | None:
    readback = _readback_for_identity(runtime_root, identity)
    return readback.writeback_run


def _readback_for_identity(
    runtime_root: Path,
    identity: SettlementIdentity,
) -> QuotaSettlementReadback:
    readback = read_heartbeat_settlement(
        runtime_root,
        goal_id=identity.goal_id,
        agent_id=identity.agent_id,
        todo_id=identity.todo_id,
        turn_instance_id=identity.turn_instance_id,
        replan_obligation_id=identity.replan_obligation_id,
    )
    if readback is None:
        raise RuntimeError("exact settlement readback unexpectedly returned not-found")
    return readback


def find_settlement_step_event(
    runtime_root: Path,
    identity: SettlementIdentity,
    *,
    event_kind: str,
) -> dict[str, Any] | None:
    readback = _readback_for_identity(runtime_root, identity)
    return {
        "refresh_state": readback.writeback_event,
        "quota_spend": readback.spend_event,
        "todo_complete": readback.completion_event,
    }.get(event_kind)


def require_settlement_terminal_closeout(
    runtime_root: Path,
    identity: SettlementIdentity,
) -> SettlementResult[dict[str, Any]]:
    return _readback_for_identity(runtime_root, identity).terminal_closeout


def require_settlement_writeback(
    runtime_root: Path,
    identity: SettlementIdentity,
) -> SettlementResult[dict[str, Any]]:
    return _readback_for_identity(runtime_root, identity).writeback


def find_settlement_spend_run(
    runtime_root: Path,
    identity: SettlementIdentity,
) -> dict[str, Any] | None:
    return _readback_for_identity(runtime_root, identity).spend_run


def find_quota_spend_run_by_effect_ref(
    runtime_root: Path,
    *,
    goal_id: str,
    effect_ref: str,
) -> dict[str, Any] | None:
    """Return the durable quota run for one provider-owned effect attempt."""

    normalized_effect_ref = str(effect_ref or "").strip()
    if not normalized_effect_ref:
        return None
    for run in reversed(_run_index_records(runtime_root, goal_id)):
        if str(run.get("classification") or "") != "quota_slot_spent":
            continue
        if str(run.get("effect_ref") or "") == normalized_effect_ref:
            return run
    return None


def require_settlement_spend(
    runtime_root: Path,
    identity: SettlementIdentity,
) -> SettlementResult[dict[str, Any]]:
    return _readback_for_identity(runtime_root, identity).spend
