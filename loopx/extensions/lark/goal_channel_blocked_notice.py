"""Authorized Lark delivery for typed blocked Todo notices."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ...control_plane.quota.blocked_transition_notice import (
    blocked_transition_notice_owner_reason,
    build_blocked_transition_notice,
)
from .goal_channel_contracts import (
    binding_for_goal,
    blocked_notice_auto_notify_enabled,
    now_iso,
    provider_idempotency_key,
    read_goal_channel_binding,
    save_goal_binding,
    semantic_key,
    serialize_goal_binding_mutation,
)
from .goal_channel_transport import (
    APP_ID_PATTERN,
    CHAT_ID_PATTERN,
    MESSAGE_ID_PATTERN,
    auth_verified,
    call,
    chat_verified,
    find_first_string,
    json_payload,
    lark_args,
    message_readback_verified,
    verified_app_id,
)
from .presentation.kanban import (
    DEFAULT_CLI_BIN,
    CommandRunner,
    default_subprocess_runner,
)


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _active_notices(
    status: Mapping[str, Any], goal_id: str, quota_packet: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    fallback = _mapping(quota_packet.get("blocked_priority_fallback"))
    selected = _mapping(fallback.get("selected_executable"))
    notices = [
        dict(value)
        for value in fallback.get("blocked_transition_notices", [])
        if isinstance(value, Mapping)
    ]
    observed: dict[str, dict[str, Any]] = {}
    queue = _mapping(status.get("attention_queue"))
    for goal in queue.get("items", []):
        if not isinstance(goal, Mapping) or str(goal.get("goal_id") or "") != goal_id:
            continue
        for lane in ("agent_todos", "user_todos"):
            group = _mapping(goal.get(lane))
            for item in group.get("items", []):
                if not isinstance(item, Mapping):
                    continue
                todo_id = str(item.get("todo_id") or "")
                if todo_id:
                    observed[f"todo:{todo_id}"] = dict(item)
                notice = build_blocked_transition_notice(
                    item, selected_executable=selected or None
                )
                if notice is not None:
                    notices.append(notice)
    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for notice in notices:
        identity = str(notice.get("blocker_identity") or "")
        revision = str(notice.get("blocker_revision") or "")
        if identity and revision:
            unique[(identity, revision)] = notice
    return list(unique.values())[:8], observed


def _notice_message(goal_id: str, notice: Mapping[str, Any]) -> str:
    reason = blocked_transition_notice_owner_reason(notice) or "A Goal task is blocked."
    evidence = notice.get("evidence")
    evidence_text = (
        "; ".join(str(value) for value in evidence[:4])
        if isinstance(evidence, list)
        else ""
    )
    responsible = str(notice.get("responsible_party") or "unknown")
    recovery = _mapping(notice.get("recovery_condition"))
    return "\n".join(
        filter(
            None,
            (
                f"LoopX Goal {goal_id}: blocked task",
                reason,
                f"Evidence: {evidence_text}" if evidence_text else "",
                f"Responsible: {responsible}",
                f"Recovery: {recovery.get('description') or 'clear the blocker'}",
                "Owner action required."
                if notice.get("owner_must_act") is True
                else "No owner action required.",
            ),
        )
    )


@serialize_goal_binding_mutation
def deliver_blocked_notices(
    *,
    goal_id: str,
    binding_path: Path,
    status: Mapping[str, Any],
    quota_packet: Mapping[str, Any],
    provider_target: Mapping[str, Any] | None = None,
    external_sink_delivery_authorized: bool,
    runner: CommandRunner = default_subprocess_runner,
) -> dict[str, Any]:
    payload = read_goal_channel_binding(binding_path)
    raw_binding = binding_for_goal(payload, goal_id)
    binding = binding_for_goal(payload, goal_id, provider_target=provider_target)
    enabled = blocked_notice_auto_notify_enabled(raw_binding)
    notices, observed = _active_notices(status, goal_id, quota_packet)
    result: dict[str, Any] = {
        "schema_version": "loopx_goal_channel_blocked_notice_delivery_v0",
        "ok": True,
        "enabled": enabled,
        "status": "not_configured" if raw_binding is None else "disabled",
        "notice_count": len(notices),
        "delivered_count": 0,
        "pending_count": len(notices),
        "external_write_performed": False,
        "readback_verified": False,
        "delivery_postcondition": {"satisfied": True, "blocks_delivery": False},
    }
    if not enabled:
        return result
    if not external_sink_delivery_authorized:
        result["status"] = "external_sink_suppressed"
        return result
    if binding is None or binding.get("enabled") is not True:
        result.update(
            ok=False,
            status="channel_binding_incomplete",
            blocker="channel_binding_incomplete",
        )
        return result
    if raw_binding.get("target_ref") and provider_target is None:
        result.update(
            ok=False,
            status="provider_target_missing",
            blocker="provider_target_missing",
        )
        return result
    channel = _mapping(binding.get("channel"))
    identity_config = _mapping(binding.get("identity"))
    chat_id = str(channel.get("chat_id") or "")
    cli_bin = str(identity_config.get("cli_bin") or DEFAULT_CLI_BIN)
    profile = str(identity_config.get("sender_profile") or "") or None
    app_id = str(identity_config.get("bot_app_id") or "")
    if notices and not (
        identity_config.get("sender_identity") == "bot"
        and APP_ID_PATTERN.fullmatch(app_id)
        and auth_verified(
            runner=runner,
            cli_bin=cli_bin,
            profile=profile,
            identity="bot",
            expected_bot_name=str(identity_config.get("bot_display_name") or "")
            or None,
        )
        and verified_app_id(runner=runner, cli_bin=cli_bin, profile=profile) == app_id
    ):
        result.update(
            ok=False,
            status="provider_identity_unverified",
            blocker="provider_identity_unverified",
        )
        return result
    if notices and (
        not CHAT_ID_PATTERN.fullmatch(chat_id)
        or not chat_verified(
            runner=runner,
            cli_bin=cli_bin,
            profile=profile,
            identity="bot",
            chat_id=chat_id,
        )
    ):
        result.update(
            ok=False,
            status="channel_membership_unverified",
            blocker="channel_membership_unverified",
        )
        return result
    receipts = _mapping(raw_binding.get("receipts"))
    delivered = 0
    for notice in notices:
        identity = str(notice["blocker_identity"])
        revision = str(notice["blocker_revision"])
        previous = [
            (receipt_key, receipt)
            for receipt_key, receipt in receipts.items()
            if isinstance(receipt, Mapping)
            and receipt.get("kind") == "blocked_notice"
            and receipt.get("blocker_identity") == identity
            and receipt.get("blocker_revision") == revision
        ]
        latest_key, latest = previous[-1] if previous else ("", {})
        key = (
            semantic_key(
                goal_id,
                "lark",
                "blocked_notice",
                identity,
                revision,
                chat_id,
                "reopened",
                str(latest.get("reconciled_at") or ""),
            )
            if latest.get("state") in {"resolved", "superseded"}
            else latest_key
            or semantic_key(
                goal_id, "lark", "blocked_notice", identity, revision, chat_id
            )
        )
        existing = _mapping(receipts.get(key))
        if (
            existing.get("readback_verified") is True
            and existing.get("state") == "delivered"
        ):
            delivered += 1
            continue
        message = _notice_message(goal_id, notice)
        send = call(
            runner,
            lark_args(
                cli_bin=cli_bin,
                profile=profile,
                tail=[
                    "im",
                    "+messages-send",
                    "--chat-id",
                    chat_id,
                    "--text",
                    message,
                    "--idempotency-key",
                    provider_idempotency_key(key),
                    "--as",
                    "bot",
                    "--format",
                    "json",
                ],
            ),
        )
        message_id = (
            find_first_string(json_payload(send), {"message_id"}, MESSAGE_ID_PATTERN)
            or ""
        )
        if send.get("returncode") != 0 or not message_id:
            receipts[key] = {
                "kind": "blocked_notice",
                "blocker_identity": identity,
                "blocker_revision": revision,
                "state": "pending",
                "readback_verified": False,
                "failure_code": "provider_api_failed",
            }
            mutable = dict(raw_binding)
            mutable["receipts"] = receipts
            save_goal_binding(
                binding_path=binding_path,
                payload=payload,
                goal_id=goal_id,
                binding=mutable,
            )
            result.update(
                ok=False, status="provider_api_failed", blocker="provider_api_failed"
            )
            break
        result["external_write_performed"] = True
        verified = message_readback_verified(
            runner=runner,
            cli_bin=cli_bin,
            profile=profile,
            identity="bot",
            message_id=message_id,
            expected_text=message,
        )
        sent_at = now_iso()
        receipts[key] = {
            "kind": "blocked_notice",
            "blocker_identity": identity,
            "blocker_revision": revision,
            "message_id": message_id,
            "sent_at": sent_at,
            "verified_at": sent_at if verified else None,
            "readback_verified": verified,
            "state": "delivered" if verified else "sent_unverified",
        }
        mutable = dict(raw_binding)
        mutable["receipts"] = receipts
        save_goal_binding(
            binding_path=binding_path, payload=payload, goal_id=goal_id, binding=mutable
        )
        payload = read_goal_channel_binding(binding_path)
        raw_binding = binding_for_goal(payload, goal_id) or mutable
        if not verified:
            result.update(
                ok=False, status="sent_unverified", blocker="readback_mismatch"
            )
            break
        delivered += 1
    # Reconcile only explicit terminal/superseding source facts. Missing rows
    # alone do not prove recovery and must not silently close a blocker.
    changed = False
    for key, receipt in receipts.items():
        if not isinstance(receipt, Mapping) or receipt.get("kind") != "blocked_notice":
            continue
        item = observed.get(str(receipt.get("blocker_identity") or ""))
        if item is None:
            continue
        terminal = str(item.get("status") or "") in {"done", "completed", "cancelled"}
        superseded = bool(item.get("superseded_by"))
        new_state = "superseded" if superseded else "resolved" if terminal else None
        if new_state and receipt.get("state") != new_state:
            receipts[key] = {
                **dict(receipt),
                "state": new_state,
                "reconciled_at": now_iso(),
            }
            changed = True
    if changed:
        mutable = dict(raw_binding)
        mutable["receipts"] = receipts
        save_goal_binding(
            binding_path=binding_path, payload=payload, goal_id=goal_id, binding=mutable
        )
    result["delivered_count"] = delivered
    result["pending_count"] = max(0, len(notices) - delivered)
    result["readback_verified"] = bool(notices and delivered == len(notices))
    if result["ok"]:
        result["status"] = "sent_verified" if notices else "no_active_blocker"
    return result
