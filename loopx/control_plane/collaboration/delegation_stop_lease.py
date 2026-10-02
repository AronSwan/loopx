"""Release the hard lease a stopped delegation acquired, by its own execution identity.

A stop owes the release of the lease its execution acquired; it never owns a
lease another execution holds. The identity comes from the operation record
and the version from the canonical lease, so a renewed or unannotated lease is
still released exactly, and the native lifecycle remains the only writer.
"""
from __future__ import annotations

from .inbox import _write
from ..coordination.local_authority import local_authority_is_promoted
from ..effect_runtime import EffectRuntimeRemoteError
from ..todos.handoff_mode import show_goal_handoff_mode
from ..work_items.task_lease import inspect_task_lease, release_task_lease

_AUTHORITY_ERRORS = (ValueError, OSError, RuntimeError, EffectRuntimeRemoteError)


def obligation(service, row):
    """The hard lease this operation may hold, named by its own execution identity.

    `_acquire_delegation_lease` only accepts a lease whose key is
    `_turn_instance_id(row)`, and that key survives in the operation record, so
    the identity never depends on the annotation's shape or on the in-memory
    row that acquired it. A native claim commits before the annotation is
    saved, so a missing annotation is an absent fact, not proof that nothing is
    owed: under a promoted hard-lease authority the obligation stands until the
    canonical lease shows this execution no longer holds it. The recorded
    epoch, when there is one, fences the release against another generation
    under the same key.
    """

    recorded = row.get("task_lease")
    if isinstance(recorded, dict) and recorded.get("required") is not True:
        return None
    if not (isinstance(recorded, dict) and recorded.get("required") is True):
        if not local_authority_is_promoted(runtime_root=service.root, goal_id=service.goal_id):
            return None
        if show_goal_handoff_mode(
            registry_path=service.registry, runtime_root_arg=str(service.root), goal_id=service.goal_id,
        )["handoff_mode"] != "hard_lease":
            return None
        recorded = {}
    acquired = recorded.get("lease") if isinstance(recorded.get("lease"), dict) else {}
    return {"idempotency_key": service._turn_instance_id(row),
            "lease_epoch": acquired.get("lease_epoch")}


def release(service, row, binding):
    """Release the lease only while this execution still holds it, at its current version.

    Renewal advances the version, so the acquisition's version is no CAS for a
    later release. The canonical lease is read first: the exact owner, key and
    (when recorded) epoch must match before its current version is released.
    A lease another execution holds, or none at all, is reported `held: false`:
    it is not this stop's to release and blocks nothing on its behalf.
    """

    try:
        owed = obligation(service, row)
    except _AUTHORITY_ERRORS as exc:
        return {"required": True, "released": False,
                "error": ("lease obligation unreadable: " + str(exc))[:180]}
    if owed is None:
        return {"required": False, "released": None}
    key = owed["idempotency_key"]
    try:
        inspection = inspect_task_lease(
            registry_path=service.registry, runtime_root=service.root,
            goal_id=service.goal_id, todo_id=binding["todo_id"],
        )
        if inspection.get("ok") is not True:
            raise RuntimeError(str(inspection.get("error") or "lease inspection unavailable"))
    except _AUTHORITY_ERRORS as exc:
        return {"required": True, "released": False, "idempotency_key": key,
                "error": ("lease obligation unreadable: " + str(exc))[:180]}
    held = inspection.get("lease")
    if (not isinstance(held, dict)
            or held.get("owner") != binding["agent_id"]
            or held.get("idempotency_key") != key
            or (owed.get("lease_epoch") is not None
                and held.get("lease_epoch") != owed["lease_epoch"])):
        return {"required": True, "released": None, "held": False, "idempotency_key": key}
    if held.get("status") == "released":
        return {"required": True, "released": True, "idempotency_key": key,
                "version": held.get("version")}
    try:
        result = release_task_lease(
            runtime_root=service.root, goal_id=service.goal_id, todo_id=binding["todo_id"],
            owner=binding["agent_id"], idempotency_key=key,
            expected_version=held.get("version"), registry_path=service.registry,
        )
    except _AUTHORITY_ERRORS as exc:
        return {"required": True, "released": False, "idempotency_key": key,
                "error": str(exc)[:180]}
    return {"required": True, "released": result.get("released") is True,
            "idempotency_key": key, "version": held.get("version"),
            "missing": result.get("missing") is True}


def settle(service, path, row, binding, stop):
    """Try the required release once and record what it proved on the stop receipt.

    Returns the `lease_released` fact, or `None` when the operation owed no
    required lease at all, or this execution no longer holds the lease it
    acquired. `None` keeps the typed planner's `undefined` meaning instead of
    claiming a release that was never owed. A release already proven on the
    receipt is not attempted again. Callers hold the operation's dispatch lock.
    """

    recorded = stop.get("lease") if isinstance(stop.get("lease"), dict) else {}
    if recorded.get("released") is True:
        return True
    released = release(service, row, binding)
    if released != stop.get("lease"):
        stop["lease"] = released
        _write(service._stop_path(path), stop)
    if released.get("required") is not True:
        return None  # preserve the no-obligation receipt, but add no release fact
    return None if released.get("held") is False else released.get("released") is True
