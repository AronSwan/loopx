"""Canonical owner-confirmed deletion for stopped Goals."""

from __future__ import annotations

from contextlib import ExitStack
import hashlib
import os
from pathlib import Path
import re
import shutil
from typing import Any
import uuid

from ...file_lock import exclusive_file_lock
from ...history import load_registry
from ...registry import atomic_write_json
from ...registry_writability import probe_registry_write_path
from ..runtime.time import now_local_iso
from .activation import GoalActivationState, goal_activation_state
from .activation_service import (
    GoalActivationAuthorityRouteMode,
    _goal_or_none,
    _same_path,
    _source_and_target,
)


GOAL_DELETION_SCHEMA_VERSION = "loopx_goal_deletion_v1"
_BACKUP_TOKEN_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _registry_fingerprint(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _backup_path(path: Path, timestamp: str, goal_id: str, nonce: str) -> Path:
    compact_timestamp = timestamp.replace(":", "").replace("-", "")
    safe_goal_id = _BACKUP_TOKEN_RE.sub("-", goal_id).strip("-") or "goal"
    return path.with_name(
        f"{path.name}.goal-delete-{compact_timestamp}-{safe_goal_id}-{nonce}.bak"
    )


def _create_backup(path: Path, *, timestamp: str, goal_id: str) -> Path:
    """Create an independent snapshot without ever overwriting an old backup."""

    for _ in range(8):
        backup = _backup_path(path, timestamp, goal_id, uuid.uuid4().hex)
        try:
            descriptor = os.open(
                backup,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
        except FileExistsError:
            continue
        try:
            with path.open("rb") as source, os.fdopen(descriptor, "wb") as target:
                shutil.copyfileobj(source, target)
                target.flush()
                os.fsync(target.fileno())
            shutil.copystat(path, backup)
        except Exception:
            backup.unlink(missing_ok=True)
            raise
        return backup
    raise FileExistsError(f"could not allocate a unique Goal deletion backup for {path}")


def _remove_goal(payload: dict[str, Any], goal_id: str) -> tuple[dict[str, Any], bool]:
    goals = payload.get("goals")
    if not isinstance(goals, list):
        raise ValueError("registry goals must be a list")
    retained = [
        goal
        for goal in goals
        if not (isinstance(goal, dict) and str(goal.get("id") or "") == goal_id)
    ]
    changed = len(retained) != len(goals)
    updated = dict(payload)
    updated["goals"] = retained
    if changed:
        updated["updated_at"] = now_local_iso()
    return updated, changed


def delete_stopped_goal(
    *,
    registry_path: Path,
    goal_id: str,
    execute: bool = False,
    expected_state_fingerprint: str | None = None,
) -> dict[str, Any]:
    """Preview or permanently remove one stopped Goal from its registries.

    Goal data such as state files and project files is intentionally retained;
    deletion removes only the registry entries that make the Goal visible to
    the LoopX control plane. When an expected fingerprint is supplied, the
    target registry is checked again while both registry locks are held.
    """

    normalized_goal_id = str(goal_id or "").strip()
    if not normalized_goal_id:
        raise ValueError("goal id is required")

    route = _source_and_target(
        registry_path=Path(registry_path),
        goal_id=normalized_goal_id,
        target_state=GoalActivationState.STOPPED,
        runtime_root_override=None,
    )
    source_registry = route.source_registry
    target_registry = route.target_registry
    source_available = route.mode is not GoalActivationAuthorityRouteMode.ORPHANED_GLOBAL_STOP_FALLBACK
    source_payload = load_registry(source_registry) if source_available else None
    target_payload = load_registry(target_registry)
    source_goal = _goal_or_none(source_payload, normalized_goal_id) if source_payload else None
    target_goal = _goal_or_none(target_payload, normalized_goal_id)
    goal = source_goal or target_goal
    if goal is None:
        raise ValueError(f"goal id not found in registry: {normalized_goal_id}")
    if goal_activation_state(goal) is not GoalActivationState.STOPPED:
        raise ValueError("stop the Goal before deleting it")
    if target_goal is None:
        raise ValueError("global registry does not contain the Goal projection")

    same_registry = _same_path(source_registry, target_registry)
    payload: dict[str, Any] = {
        "ok": True,
        "schema_version": GOAL_DELETION_SCHEMA_VERSION,
        "dry_run": not execute,
        "execute": execute,
        "goal_id": normalized_goal_id,
        "source_registry": str(source_registry),
        "target_global_registry": str(target_registry),
        "source_registry_present": source_goal is not None,
        "global_registry_present": target_goal is not None,
        "written": False,
        "partial_write": False,
        "backup_paths": [],
        "readback": {
            "source_missing": source_goal is None,
            "global_missing": False,
            "verified": False,
        },
    }
    if not execute:
        return payload

    paths = [target_registry] if same_registry else [source_registry, target_registry]
    writability = [
        probe_registry_write_path(path, create_parent=False) for path in paths
    ]
    denied = next((item for item in writability if not item.get("ok")), None)
    if denied is not None:
        payload.update(
            {
                "ok": False,
                "error_kind": "goal_registry_write_denied",
                "error": str(denied.get("error") or "Goal registry is not writable"),
                "recommended_action": denied.get("recommended_action"),
                "registry_writability": writability,
            }
        )
        return payload

    original_payloads: dict[Path, dict[str, Any]] = {}
    written_paths: list[Path] = []
    with ExitStack() as stack:
        for path in sorted(paths, key=lambda item: str(item)):
            stack.enter_context(
                exclusive_file_lock(path, operation="delete_stopped_goal")
            )
        current_source = load_registry(source_registry) if source_available else None
        current_target = load_registry(target_registry)
        if expected_state_fingerprint is not None:
            current_fingerprint = _registry_fingerprint(target_registry)
            if current_fingerprint != expected_state_fingerprint:
                payload.update(
                    {
                        "ok": False,
                        "stale": True,
                        "error_kind": "goal_registry_changed",
                        "error": "Goal registry changed after preview; regenerate the deletion preview",
                        "current_state_fingerprint": current_fingerprint,
                    }
                )
                return payload

        locked_source_goal = (
            _goal_or_none(current_source, normalized_goal_id)
            if current_source is not None
            else None
        )
        locked_target_goal = _goal_or_none(current_target, normalized_goal_id)
        locked_goal = locked_source_goal or locked_target_goal
        if locked_goal is None or locked_target_goal is None:
            raise ValueError("Goal disappeared before deletion; refresh and retry")
        if goal_activation_state(locked_goal) is not GoalActivationState.STOPPED:
            raise ValueError("Goal activation changed; stop the Goal before deleting it")

        current_payloads = {target_registry: current_target}
        if source_available and not same_registry:
            if current_source is None or locked_source_goal is None:
                raise ValueError("Goal source registry changed; refresh and retry")
            current_payloads[source_registry] = current_source
        original_payloads = current_payloads
        updated_payloads: dict[Path, dict[str, Any]] = {}
        for path, current in current_payloads.items():
            updated, changed = _remove_goal(current, normalized_goal_id)
            if not changed:
                raise ValueError("Goal disappeared before deletion; refresh and retry")
            updated_payloads[path] = updated

        try:
            timestamp = now_local_iso()
            for path in current_payloads:
                backup = _create_backup(
                    path,
                    timestamp=timestamp,
                    goal_id=normalized_goal_id,
                )
                payload["backup_paths"].append(str(backup))
            for path in sorted(updated_payloads, key=lambda item: str(item)):
                atomic_write_json(path, updated_payloads[path], preserve_mode=True)
                written_paths.append(path)

            source_after = load_registry(source_registry) if source_available else None
            target_after = load_registry(target_registry)
            source_missing = (
                _goal_or_none(source_after, normalized_goal_id) is None
                if source_after is not None
                else True
            )
            global_missing = _goal_or_none(target_after, normalized_goal_id) is None
            payload["readback"] = {
                "source_missing": source_missing,
                "global_missing": global_missing,
                "verified": source_missing and global_missing,
            }
            payload["written"] = bool(written_paths)
            payload["ok"] = bool(payload["readback"]["verified"])
            payload["partial_write"] = bool(payload["written"] and not payload["ok"])
            if not payload["ok"]:
                payload["error"] = "Goal deletion readback did not verify"
        except Exception:
            for path in written_paths:
                original = original_payloads.get(path)
                if original is not None:
                    atomic_write_json(path, original, preserve_mode=True)
            raise
    return payload
