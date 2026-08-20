from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from ..control_plane.goals.path_resolution import resolve_goal_local_path
from ..control_plane.quota.goal_boundary import registry_goal_by_id
from ..control_plane.quota.host_poll_receipts import record_host_poll_receipt


def attach_host_poll_receipt(
    status_payload: dict[str, object],
    args: argparse.Namespace,
    payload: dict[str, Any],
    *,
    registry_path: Path,
) -> None:
    if not bool(getattr(args, "record_host_poll", False)) or not bool(
        payload.get("ok")
    ):
        return
    try:
        receipt_view = _record_host_poll_for_should_run(
            status_payload,
            args,
            payload,
            registry_path=registry_path,
        )
        if receipt_view is not None:
            payload["host_poll_receipt"] = receipt_view
    except Exception as exc:  # noqa: BLE001 - receipt must never break the quota decision.
        payload["host_poll_receipt"] = {
            "recorded": False,
            "error": str(exc)[:200],
        }


def _record_host_poll_for_should_run(
    status_payload: dict[str, object],
    args: argparse.Namespace,
    payload: dict[str, Any],
    *,
    registry_path: Path,
) -> dict[str, Any] | None:
    goal = registry_goal_by_id(status_payload).get(str(args.goal_id or ""))
    if not goal:
        return None
    state_path = resolve_goal_local_path(
        goal.get("state_file"),
        goal,
        fallback_base=registry_path.parent,
    )
    receipt = record_host_poll_receipt(
        goal,
        state_path,
        agent_id=args.agent_id,
        decision=payload,
    )
    if receipt is None:
        return None
    return {
        "recorded": True,
        "poll_count": receipt.get("poll_count"),
        "last_poll_at": receipt.get("last_poll_at"),
        "expected_continuation": receipt.get("expected_continuation"),
    }
