from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from pathlib import Path

from ..capabilities.explore.composition_frontier import (
    project_live_explore_composition_frontier,
)
from ..capabilities.repository_change_window import (
    repository_delivery_interaction_hook,
)
from ..control_plane.quota.heartbeat_receipt import (
    find_heartbeat_receipt,
    heartbeat_receipt_settlement_replan_obligation_id,
    heartbeat_receipt_settlement_todo_id,
)
from ..control_plane.quota.live_decision import build_live_quota_should_run_decision
from ..control_plane.quota.scheduler_ack import (
    record_quota_scheduler_failure_for_decision,
)
from ..control_plane.scheduler.execution_context import (
    SchedulerExecutionContextResolution,
)
from ..quota import record_quota_scheduler_ack
from ..upgrade import resolve_codex_app_automation_rrule


def _receipt_bound_action_bindings(
    *,
    runtime_root: Path,
    args: argparse.Namespace,
    turn_instance_id: str | None,
) -> tuple[str | None, str | None]:
    if not turn_instance_id:
        return None, None
    receipt = find_heartbeat_receipt(
        runtime_root,
        goal_id=args.goal_id,
        agent_id=args.agent_id,
        turn_instance_id=turn_instance_id,
    )
    if not receipt:
        return None, None
    return (
        heartbeat_receipt_settlement_todo_id(receipt),
        heartbeat_receipt_settlement_replan_obligation_id(receipt),
    )


def _build_scheduler_followup_decision(
    status_payload: dict[str, object],
    args: argparse.Namespace,
    *,
    registry_path: Path,
    runtime_root: Path,
    turn_instance_id: str | None,
    codex_app_current_rrule: str | None,
    scheduler_context: Mapping[str, object]
    | SchedulerExecutionContextResolution
    | None,
    operator_inbox_urgency_projector: Callable[..., dict[str, object]],
) -> dict[str, object]:
    """Rebuild a scheduler follow-up from the originating receipt-bound Turn."""

    receipt_todo_id, receipt_replan_id = _receipt_bound_action_bindings(
        runtime_root=runtime_root,
        args=args,
        turn_instance_id=turn_instance_id,
    )
    return build_live_quota_should_run_decision(
        status_payload,
        goal_id=args.goal_id,
        agent_id=args.agent_id,
        available_capabilities=args.available_capabilities,
        include_scheduler_detail=False,
        codex_app_current_rrule=codex_app_current_rrule,
        registry_path=registry_path,
        runtime_root=runtime_root,
        host_observation_resolver=resolve_codex_app_automation_rrule,
        scheduler_execution_context=scheduler_context,
        operator_inbox_urgency_projector=operator_inbox_urgency_projector,
        bounded_research_frontier_projector=project_live_explore_composition_frontier,
        receipt_bound_todo_id=receipt_todo_id,
        receipt_bound_replan_obligation_id=receipt_replan_id,
        turn_instance_id=turn_instance_id,
        interaction_projection_hooks=(
            repository_delivery_interaction_hook(repo_path=Path.cwd()),
        ),
    )


def build_scheduler_followup_payload(
    status_payload: dict[str, object],
    args: argparse.Namespace,
    *,
    registry_path: Path,
    runtime_root: Path,
    turn_instance_id: str | None,
    scheduler_context: Mapping[str, object]
    | SchedulerExecutionContextResolution
    | None,
    operator_inbox_urgency_projector: Callable[..., dict[str, object]],
) -> dict[str, object]:
    """Execute one scheduler ACK/failure command against its live decision."""

    observed_rrule = str(args.codex_app_current_rrule or "").strip()
    if args.quota_command == "scheduler-fail-current" and not observed_rrule:
        host_observation = resolve_codex_app_automation_rrule(
            goal_id=args.goal_id,
            agent_id=args.agent_id,
        )
        if host_observation.get("available") is True:
            observed_rrule = str(host_observation.get("rrule") or "")

    before_decision = _build_scheduler_followup_decision(
        status_payload,
        args,
        registry_path=registry_path,
        runtime_root=runtime_root,
        turn_instance_id=turn_instance_id,
        codex_app_current_rrule=(
            args.applied_rrule
            if bool(getattr(args, "host_match_observed", False))
            else observed_rrule
        ),
        scheduler_context=scheduler_context,
        operator_inbox_urgency_projector=operator_inbox_urgency_projector,
    )
    if args.quota_command == "scheduler-fail-current":
        return record_quota_scheduler_failure_for_decision(
            before_decision,
            runtime_root=runtime_root,
            goal_id=args.goal_id,
            agent_id=args.agent_id,
            execute=bool(args.execute),
            surface=args.surface,
            state_key=args.state_key,
            failed_rrule=args.failed_rrule,
            observed_host_rrule=observed_rrule,
            failure_kind=args.failure_kind,
        )
    return record_quota_scheduler_ack(
        status_payload,
        goal_id=args.goal_id,
        execute=bool(args.execute),
        agent_id=args.agent_id,
        available_capabilities=args.available_capabilities,
        surface=args.surface,
        state_key=args.state_key,
        applied_rrule=args.applied_rrule,
        reset_token=args.reset_token,
        identity_signature=args.identity_signature,
        reason_summary=args.reason_summary,
        use_current_hint=bool(
            args.use_current_hint or args.quota_command == "scheduler-ack-current"
        ),
        host_match_observed=bool(getattr(args, "host_match_observed", False)),
        scheduler_execution_context=scheduler_context,
        operator_inbox_urgency_projector=operator_inbox_urgency_projector,
        before_decision=before_decision,
    )
