from __future__ import annotations


def render_loopx_turn_plan_markdown(payload: dict[str, object]) -> str:
    if not payload.get("ok"):
        error = payload.get("error") or "invalid TurnEnvelope contract"
        return f"LoopX Turn plan failed: {error}"
    host = payload.get("host") if isinstance(payload.get("host"), dict) else {}
    route = payload.get("route") if isinstance(payload.get("route"), dict) else {}
    return "\n".join(
        [
            "# LoopX Turn Plan",
            f"- host: {host.get('kind')}",
            f"- execution_mode: {host.get('execution_mode')}",
            f"- route: {route.get('kind')}",
            f"- would_invoke_host: {route.get('would_invoke_host')}",
            "- side_effects: none",
        ]
    )


def render_loopx_turn_execution_markdown(payload: dict[str, object]) -> str:
    effects = payload.get("effects") if isinstance(payload.get("effects"), dict) else {}
    receipt = payload.get("receipt") if isinstance(payload.get("receipt"), dict) else {}
    validation = (
        payload.get("validation") if isinstance(payload.get("validation"), dict) else {}
    )
    return "\n".join(
        [
            "# LoopX Turn Run Once",
            f"- status: {payload.get('status')}",
            f"- result_kind: {payload.get('result_kind')}",
            f"- validation: {validation.get('status')}",
            f"- recovery_kind: {validation.get('recovery_kind')}",
            f"- next_phase: {receipt.get('next_phase')}",
            f"- host_invoked: {effects.get('host_invoked')}",
            f"- state_written: {effects.get('state_written')}",
            f"- quota_spent: {effects.get('quota_spent')}",
        ]
    )


def render_loopx_turn_journal_inspection_markdown(
    payload: dict[str, object],
) -> str:
    if not payload.get("ok"):
        error = payload.get("error") or "Turn journal inspection failed"
        return f"LoopX Turn journal inspection failed: {error}"
    completed_phases = payload.get("completed_phases")
    violations = payload.get("violations")
    return "\n".join(
        [
            "# LoopX Turn Journal Inspection",
            f"- decision: {payload.get('decision')}",
            f"- journal_status: {payload.get('journal_status')}",
            f"- replay_legal: {payload.get('replay_legal')}",
            f"- goal_matches: {payload.get('goal_matches')}",
            f"- owner_matches: {payload.get('owner_matches')}",
            f"- turn_key_matches: {payload.get('turn_key_matches')}",
            (
                "- phases_form_ordered_prefix: "
                f"{payload.get('phases_form_ordered_prefix')}"
            ),
            "- completed_phases: "
            + (
                ", ".join(str(value) for value in completed_phases)
                if isinstance(completed_phases, list) and completed_phases
                else "none"
            ),
            f"- tombstone_retained: {payload.get('tombstone_retained')}",
            "- violations: "
            + (
                ", ".join(str(value) for value in violations)
                if isinstance(violations, list) and violations
                else "none"
            ),
            "- effects: none",
        ]
    )
