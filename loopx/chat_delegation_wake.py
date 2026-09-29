"""Continue a Chat LoopX lead once a delegated result is accepted.

The accepted transition leaves a pending wake intent beside the result.  This
pump maps the intent to the conversation that observed the operation (its
``loopx_deliveries``) and asks the existing Chat LoopX owner for one bounded
Turn.  It never unpauses a lead, never starts a native Goal and never settles
canonical work.  Refusals are terminal facts; pending intents wait for a later
tick.  Stopping the pump leaves intents pending, so disabling it is a complete
rollback.  Requesters outside a Chat LoopX conversation are never visited: their
intent stays pending and the scheduler deadline recheck remains their fallback.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, Callable

from .collaboration_mcp import execution_row_path
from .control_plane.collaboration.inbox import _read
from .file_lock import LockAcquireTimeoutError

WAKE_INTERVAL_SECONDS = 3.0


def default_goal_context(controller, session: dict[str, Any]) -> dict[str, Any]:
    """Project and objective for a host-initiated Turn when no richer reader exists."""
    from .agent_registry import load_goal_from_registry

    goal = load_goal_from_registry(controller.registry_path, session["goal_id"]) or {}
    return {
        "project": Path(str(goal.get("repo") or ".")).expanduser().resolve(),
        "objective": str(goal.get("domain") or session["goal_id"]),
    }


def _pending_owner(sessions: list[dict[str, Any]]) -> dict[str, Any]:
    """Prefer a conversation that can still be continued over one that exited."""
    return next(
        (row for row in sessions if (row.get("loopx_mode") or {}).get("enabled") is True),
        sessions[0],
    )


def pump_delegation_wakes(
    controller,
    *,
    goal_context: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    cancelled: Callable[[], bool] = lambda: False,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """One restart-safe tick; returns the receipts it changed."""
    store = controller.store
    context_for = goal_context or (lambda session: default_goal_context(controller, session))
    owners: dict[Path, list[dict[str, Any]]] = {}
    for path in sorted(store.sessions_root.glob("*/session.json")):
        if cancelled():
            return []
        session = store.load_session(path.parent.name)
        if not session:
            continue
        settings = (session.get("loopx_mode") or {}).get("settings") or {}
        agent_id = settings.get("agent_id")
        if not isinstance(agent_id, str) or not agent_id:
            continue
        for delivery in session.get("loopx_deliveries") or []:
            operation_id = delivery.get("operation_id")
            if not isinstance(operation_id, str) or not operation_id:
                continue
            record = execution_row_path(
                store.root.parent, str(session["goal_id"]), agent_id, operation_id
            )
            owners.setdefault(record, []).append(session)
    changed: list[dict[str, Any]] = []
    for record, sessions in owners.items():
        if cancelled() or len(changed) >= limit:
            break
        try:
            wake = _read(record).get("wake") if record.exists() else None
        except (OSError, ValueError):
            continue
        if not isinstance(wake, dict) or wake.get("state") != "pending":
            continue  # unlocked pre-check; record_wake re-reads under the lock
        session = _pending_owner(sessions)
        context = context_for(session)
        try:
            receipt = controller.loopx_mode.wake(
                session["session_id"],
                record,
                work_dir=context["project"],
                objective=context["objective"],
            )
        except LockAcquireTimeoutError:
            continue  # a worker or decision holds the record; retry next tick
        if receipt is not None:
            changed.append({"operation_id": wake.get("operation_id"), **receipt})
    return changed


class DelegationWakeService:
    """Cheap local pump hosted by the existing Chat server, beside the return service."""

    def __init__(self, controller, *, goal_context=None, interval=WAKE_INTERVAL_SECONDS):
        self.controller = controller
        self.goal_context = goal_context
        self.interval = interval
        self.stop = threading.Event()
        self.thread = threading.Thread(
            target=self.run, daemon=True, name="loopx-delegation-wakes"
        )

    def start(self):
        self.thread.start()
        return self

    def run(self):
        while not self.stop.is_set():
            try:
                pump_delegation_wakes(
                    self.controller,
                    goal_context=self.goal_context,
                    cancelled=self.stop.is_set,
                )
            except (OSError, ValueError, KeyError, TypeError, RuntimeError):
                logging.getLogger(__name__).warning(
                    "Delegation wake receipts unavailable; retrying"
                )
            self.stop.wait(self.interval)

    def close(self):
        self.stop.set()
        self.thread.join(timeout=3)
