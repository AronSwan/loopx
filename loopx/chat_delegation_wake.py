"""Continue a Chat LoopX lead once a delegated result is accepted.

The accepted transition leaves a pending wake intent beside the result.  Each
tick scans this runtime's operation records for pending intents and resolves
the owner from the intent's requester: a Chat LoopX conversation configured
with that coordinator identity, preferring one that can still continue and,
among those, the one that observed the operation.  The existing Chat LoopX
owner decides and records the receipt.  A requester without such a
conversation is refused with ``no_wake_owner``; the scheduler deadline recheck
remains its continuation.  The pump never unpauses a lead, never starts a
native Goal and never settles canonical work.  Stopping it leaves intents
pending, which is its rollback.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any, Callable

from .chat_runtime import ChatTurnAcceptanceUnavailableError
from .collaboration_mcp import execution_row_path, record_wake, wake_receipt
from .control_plane.collaboration.inbox import _read, _root
from .file_lock import LockAcquireTimeoutError

WAKE_INTERVAL_SECONDS = 3.0
_LOG = logging.getLogger(__name__)


def default_goal_context(controller, session: dict[str, Any]) -> dict[str, Any]:
    """Project and objective for a host-initiated Turn when no richer reader exists."""
    from .agent_registry import load_goal_from_registry

    goal = load_goal_from_registry(controller.registry_path, session["goal_id"])
    if not goal:
        raise ValueError("Goal unavailable")
    return {
        "project": Path(str(goal.get("repo") or ".")).expanduser().resolve(),
        "objective": str(goal.get("domain") or session["goal_id"]),
    }


def _owners(store) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """Chat conversations by their configured coordinator (requester) identity."""
    owners: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for path in sorted(store.sessions_root.glob("*/session.json")):
        session = store.load_session(path.parent.name)
        settings = ((session or {}).get("loopx_mode") or {}).get("settings") or {}
        agent_id = settings.get("agent_id")
        if session and isinstance(agent_id, str) and agent_id:
            owners.setdefault((str(session.get("goal_id") or ""), agent_id), []).append(session)
    return owners


def _select_owner(sessions: list[dict[str, Any]], operation_id: str) -> dict[str, Any]:
    def rank(session):
        usable = session.get("status") != "closed" and (
            (session.get("loopx_mode") or {}).get("enabled") is True
        )
        observed = any(
            row.get("operation_id") == operation_id
            for row in session.get("loopx_deliveries") or []
        )
        return (usable, observed, str(session.get("updated_at") or ""))

    return max(sessions, key=rank)


def _pending_identity(record: Path) -> tuple[str, str, str] | None:
    """Requester and operation of a pending intent; an unlocked pre-check only."""
    row = _read(record)
    wake = row.get("wake")
    if row.get("status") != "accepted" or not isinstance(wake, dict) or wake.get("state") != "pending":
        return None
    requester = wake.get("requester") or {}
    identity = (requester.get("goal_id"), requester.get("agent_id"), wake.get("operation_id"))
    if not all(isinstance(value, str) and value for value in identity):
        return None
    return identity  # type: ignore[return-value]


def pump_delegation_wakes(
    controller,
    *,
    goal_context: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    cancelled: Callable[[], bool] = lambda: False,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """One restart-safe tick; returns the receipts it changed."""
    store = controller.store
    root = store.root.parent
    context_for = goal_context or (lambda session: default_goal_context(controller, session))
    owners = _owners(store)
    changed: list[dict[str, Any]] = []
    for record in sorted((_root(root) / "executions").glob("*/*.json")):
        if cancelled() or len(changed) >= limit:
            break
        try:
            identity = _pending_identity(record)
            if identity is None:
                continue
            goal_id, agent_id, operation_id = identity
            if execution_row_path(root, goal_id, agent_id, operation_id) != record:
                continue  # an intent must name the requester that owns its storage address
            sessions = owners.get((goal_id, agent_id))
            if not sessions:
                receipt = record_wake(record, lambda wake: wake_receipt(
                    wake, "refused", reason="no_wake_owner", refused_at=time.time()))
            else:
                session = _select_owner(sessions, operation_id)
                receipt = controller.loopx_mode.wake(
                    session["session_id"],
                    record,
                    goal_context=lambda session=session: context_for(session),
                )
        except LockAcquireTimeoutError:
            continue  # a worker or decision holds the record; retry next tick
        except (OSError, ValueError, KeyError, TypeError, RuntimeError,
                ChatTurnAcceptanceUnavailableError) as exc:
            # Isolate one record; the others still progress this tick.
            _LOG.warning("Delegation wake unavailable for one operation (%s); retrying", type(exc).__name__)
            continue
        if receipt is not None:
            changed.append(receipt)
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
                _LOG.warning("Delegation wake receipts unavailable; retrying")
            self.stop.wait(self.interval)

    def close(self):
        self.stop.set()
        self.thread.join(timeout=3)
