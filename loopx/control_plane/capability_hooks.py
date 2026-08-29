from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..file_lock import exclusive_file_lock
from .effect_runtime import EffectRuntimeRejected, effect_runtime_result


CAPABILITY_HOOK_REGISTRATION_SCHEMA_VERSION = "loopx_capability_hook_registration_v0"
INTERACTION_PROJECTION_HOOK_RESULT_SCHEMA_VERSION = (
    "loopx_interaction_projection_hook_result_v0"
)
INTERACTION_PROJECTION_HOOK_DISPATCH_SCHEMA_VERSION = (
    "loopx_interaction_projection_hook_dispatch_v0"
)
TURN_START_HOOK_REGISTRATION_SCHEMA_VERSION = (
    "loopx_turn_start_capability_hook_registration_v0"
)
TURN_START_HOOK_RESULT_SCHEMA_VERSION = "loopx_turn_start_capability_hook_result_v0"
TURN_START_HOOK_DISPATCH_SCHEMA_VERSION = "loopx_turn_start_capability_hook_dispatch_v0"
POST_WRITEBACK_HOOK_REGISTRATION_SCHEMA_VERSION = (
    "loopx_post_writeback_capability_hook_registration_v0"
)
POST_WRITEBACK_HOOK_INPUT_SCHEMA_VERSION = (
    "loopx_post_writeback_capability_hook_input_v0"
)
POST_WRITEBACK_HOOK_RESULT_SCHEMA_VERSION = (
    "loopx_post_writeback_capability_hook_result_v0"
)
POST_WRITEBACK_HOOK_DISPATCH_SCHEMA_VERSION = (
    "loopx_post_writeback_capability_hook_dispatch_v0"
)
POST_WRITEBACK_HOOK_RECEIPT_SCHEMA_VERSION = (
    "loopx_post_writeback_capability_hook_receipt_v0"
)

InteractionProjectionProducer = Callable[[], Mapping[str, Any]]
TurnStartProducer = Callable[[], Mapping[str, Any]]
PostWritebackProducer = Callable[[Mapping[str, Any]], Mapping[str, Any]]
_SAFE_PATH_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(
                dict(payload),
                handle,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        if os.name == "posix":
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


@dataclass(frozen=True, slots=True)
class InteractionProjectionHookRegistration:
    """One read-only capability contribution to an interaction contract."""

    hook_id: str
    capability_id: str
    projection_slots: tuple[str, ...]
    requested_read_scope: tuple[str, ...]
    producer: InteractionProjectionProducer
    max_result_bytes: int = 16 * 1024

    def contract(self) -> dict[str, Any]:
        return {
            "schema_version": CAPABILITY_HOOK_REGISTRATION_SCHEMA_VERSION,
            "hook_id": self.hook_id,
            "capability_id": self.capability_id,
            "phase": "interaction_projection",
            "projection_slots": list(self.projection_slots),
            "budget": {
                "max_invocations_per_dispatch": 1,
                "max_result_bytes": self.max_result_bytes,
            },
            "failure_policy": "isolate",
            "requested_read_scope": list(self.requested_read_scope),
            "requested_write_scope": [],
        }


@dataclass(frozen=True, slots=True)
class TurnStartHookRegistration:
    """One bounded provider observation before a LoopX turn is selected."""

    hook_id: str
    capability_id: str
    requested_read_scope: tuple[str, ...]
    requested_write_scope: tuple[str, ...]
    producer: TurnStartProducer
    max_result_bytes: int = 16 * 1024

    def contract(self) -> dict[str, Any]:
        return {
            "schema_version": TURN_START_HOOK_REGISTRATION_SCHEMA_VERSION,
            "hook_id": self.hook_id,
            "capability_id": self.capability_id,
            "phase": "turn_start",
            "budget": {
                "max_invocations_per_dispatch": 1,
                "max_result_bytes": self.max_result_bytes,
            },
            "failure_policy": "isolate",
            "requested_read_scope": list(self.requested_read_scope),
            "requested_write_scope": list(self.requested_write_scope),
        }


@dataclass(frozen=True, slots=True)
class PostWritebackHookRegistration:
    """One effect-free capability observer of a committed primary writeback."""

    hook_id: str
    capability_id: str
    event_kinds: tuple[str, ...]
    intent_kinds: tuple[str, ...]
    requested_read_scope: tuple[str, ...]
    producer: PostWritebackProducer
    policy_version: str = "v0"
    max_input_bytes: int = 64 * 1024
    max_result_bytes: int = 16 * 1024

    def contract(self) -> dict[str, Any]:
        return {
            "schema_version": POST_WRITEBACK_HOOK_REGISTRATION_SCHEMA_VERSION,
            "hook_id": self.hook_id,
            "capability_id": self.capability_id,
            "policy_version": self.policy_version,
            "phase": "post_writeback",
            "event_kinds": list(self.event_kinds),
            "intent_kinds": list(self.intent_kinds),
            "budget": {
                "max_invocations_per_dispatch": 1,
                "max_input_bytes": self.max_input_bytes,
                "max_result_bytes": self.max_result_bytes,
            },
            "failure_policy": "isolate",
            "requested_read_scope": list(self.requested_read_scope),
            "requested_write_scope": [],
        }


@dataclass(frozen=True, slots=True)
class PostWritebackHookReceiptJournal:
    """Core-owned sidecar checkpoint for replay-safe hook dispatch."""

    runtime_root: Path
    goal_id: str

    def __post_init__(self) -> None:
        if not _SAFE_PATH_SEGMENT_RE.fullmatch(self.goal_id):
            raise ValueError(
                "post-writeback journal goal_id is not a safe path segment"
            )

    def _path(self, dispatch_id: str) -> Path:
        if not re.fullmatch(r"pwh_[0-9a-f]{64}", dispatch_id):
            raise ValueError("post-writeback dispatch_id is invalid")
        return (
            self.runtime_root
            / "goals"
            / self.goal_id
            / "post_writeback_hooks"
            / f"{dispatch_id}.json"
        )

    def load(self, dispatch_id: str) -> dict[str, Any] | None:
        path = self._path(dispatch_id)
        with exclusive_file_lock(path, operation="post_writeback_hook_read"):
            if not path.exists():
                return None
            value = json.loads(path.read_text(encoding="utf-8"))
        if (
            not isinstance(value, dict)
            or value.get("schema_version") != POST_WRITEBACK_HOOK_RECEIPT_SCHEMA_VERSION
            or value.get("dispatch_id") != dispatch_id
        ):
            raise ValueError("post-writeback hook receipt is invalid")
        return value

    def store(self, receipt: Mapping[str, Any]) -> dict[str, Any]:
        dispatch_id = str(receipt.get("dispatch_id") or "").strip()
        path = self._path(dispatch_id)
        normalized = dict(receipt)
        if (
            normalized.get("schema_version")
            != POST_WRITEBACK_HOOK_RECEIPT_SCHEMA_VERSION
        ):
            raise ValueError("post-writeback hook receipt schema is invalid")
        path.parent.mkdir(parents=True, exist_ok=True)
        with exclusive_file_lock(path, operation="post_writeback_hook_write"):
            if path.exists():
                existing = json.loads(path.read_text(encoding="utf-8"))
                if existing == normalized:
                    return existing
                stable_fields = {
                    "schema_version",
                    "dispatch_id",
                    "hook_id",
                    "capability_id",
                    "source_receipt_id",
                    "recorded_at",
                }
                stable_identity_matches = all(
                    existing.get(field) == normalized.get(field)
                    for field in stable_fields
                )
                previous_attempt = existing.get("attempt_count")
                next_attempt = normalized.get("attempt_count")
                retry_transition = bool(
                    existing.get("status") == "retryable_failure"
                    and stable_identity_matches
                    and type(previous_attempt) is int
                    and type(next_attempt) is int
                    and next_attempt == previous_attempt + 1
                )
                if not retry_transition:
                    raise ValueError(
                        "post-writeback dispatch receipt conflicts with replay"
                    )
            _atomic_write_json(path, normalized)
        return normalized


def _post_writeback_dispatch_id(
    registration: PostWritebackHookRegistration,
    hook_input: Mapping[str, Any],
) -> str:
    receipt = hook_input.get("receipt")
    if not isinstance(receipt, Mapping):
        raise ValueError("post-writeback hook input has no receipt")
    identity = {
        "source_receipt_id": str(receipt.get("event_id") or "").strip(),
        "event_kind": str(receipt.get("event_kind") or "").strip(),
        "hook_id": registration.hook_id,
        "capability_id": registration.capability_id,
        "registration_schema": POST_WRITEBACK_HOOK_REGISTRATION_SCHEMA_VERSION,
        "policy_version": registration.policy_version,
    }
    if not all(identity.values()):
        raise ValueError("post-writeback dispatch identity is incomplete")
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return f"pwh_{digest}"


def _validated_post_writeback_receipt(
    *,
    registration: PostWritebackHookRegistration,
    hook_input: Mapping[str, Any],
    receipt: Mapping[str, Any],
) -> dict[str, Any]:
    normalized = effect_runtime_result(
        "capability_hook.post_writeback.validate_receipt",
        {
            "registration": registration.contract(),
            "hook_input": dict(hook_input),
            "receipt": dict(receipt),
        },
    )
    if not isinstance(normalized, Mapping):
        raise ValueError("post-writeback receipt runtime result is invalid")
    return dict(normalized)


def _post_writeback_sidecar_receipt(
    *,
    registration: PostWritebackHookRegistration,
    hook_input: Mapping[str, Any],
    dispatch_id: str,
    status: str,
    intent: Mapping[str, Any] | None,
    error_code: str | None,
    attempt_count: int,
) -> dict[str, Any]:
    source_receipt = hook_input.get("receipt")
    if not isinstance(source_receipt, Mapping):
        raise ValueError("post-writeback hook input has no source receipt")
    return {
        "schema_version": POST_WRITEBACK_HOOK_RECEIPT_SCHEMA_VERSION,
        "dispatch_id": dispatch_id,
        "hook_id": registration.hook_id,
        "capability_id": registration.capability_id,
        "source_receipt_id": str(source_receipt.get("event_id") or ""),
        "status": status,
        "intent": dict(intent) if intent is not None else None,
        "error_code": error_code,
        "attempt_count": attempt_count,
        "recorded_at": str(source_receipt.get("recorded_at") or ""),
    }


def _store_post_writeback_sidecar(
    *,
    journal: PostWritebackHookReceiptJournal,
    registration: PostWritebackHookRegistration,
    hook_input: Mapping[str, Any],
    dispatch_id: str,
    status: str,
    intent: Mapping[str, Any] | None,
    error_code: str | None,
    attempt_count: int,
) -> dict[str, Any]:
    receipt = _post_writeback_sidecar_receipt(
        registration=registration,
        hook_input=hook_input,
        dispatch_id=dispatch_id,
        status=status,
        intent=intent,
        error_code=error_code,
        attempt_count=attempt_count,
    )
    validated = _validated_post_writeback_receipt(
        registration=registration,
        hook_input=hook_input,
        receipt=receipt,
    )
    return journal.store(validated)


def _record_retryable_post_writeback_failure(
    *,
    journal: PostWritebackHookReceiptJournal | None,
    registration: PostWritebackHookRegistration,
    hook_input: Mapping[str, Any],
    dispatch_id: str,
    error_code: str,
    attempt_count: int,
) -> dict[str, str]:
    if journal is None:
        return _hook_failure(registration, error_code=error_code)
    try:
        _store_post_writeback_sidecar(
            journal=journal,
            registration=registration,
            hook_input=hook_input,
            dispatch_id=dispatch_id,
            status="retryable_failure",
            intent=None,
            error_code=error_code,
            attempt_count=attempt_count,
        )
    except (EffectRuntimeRejected, OSError, RuntimeError, TypeError, ValueError):
        return _hook_failure(registration, error_code="journal_write_failed")
    return _hook_failure(
        registration,
        error_code=error_code,
        durable_receipt_ref=f"post-writeback-hook:{dispatch_id}",
    )


def build_post_writeback_hook_input(
    *,
    event_kind: str,
    goal_id: str,
    agent_id: str,
    todo_id: str,
    turn_instance_id: str,
    effect_id: str,
    state_version: str,
    committed_at: str,
    projection: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the compact source packet from a committed primary writeback.

    This packet deliberately does not use the best-effort rollout-event log as
    authority. Its identity is reconstructible from the durable state-refresh
    receipt facts and contains no task prose, paths, logs, or provider data.
    """

    identity = {
        "goal_id": str(goal_id or "").strip(),
        "agent_id": str(agent_id or "").strip(),
        "todo_id": str(todo_id or "").strip(),
        "turn_instance_id": str(turn_instance_id or "").strip(),
        "effect_id": str(effect_id or "").strip(),
    }
    normalized_event_kind = str(event_kind or "").strip()
    normalized_state_version = str(state_version or "").strip()
    normalized_committed_at = str(committed_at or "").strip()
    if (
        not all(identity.values())
        or not normalized_event_kind
        or not normalized_state_version
        or not normalized_committed_at
    ):
        raise ValueError(
            "post-writeback hooks require committed goal/agent/todo/turn/effect identity"
        )
    receipt_facts = {
        "event_kind": normalized_event_kind,
        "identity": identity,
        "state_version": normalized_state_version,
        "committed_at": normalized_committed_at,
    }
    digest = hashlib.sha256(
        json.dumps(receipt_facts, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:24]
    return {
        "schema_version": POST_WRITEBACK_HOOK_INPUT_SCHEMA_VERSION,
        "receipt": {
            "schema_version": "loopx_primary_writeback_receipt_v0",
            "event_id": f"pwr_{digest}",
            "event_kind": normalized_event_kind,
            "status": "committed",
            "recorded_at": normalized_committed_at,
            "durable": True,
        },
        "identity": identity,
        "state_version": normalized_state_version,
        "projection": dict(projection),
    }


def dispatch_interaction_projection_hooks(
    registrations: Sequence[InteractionProjectionHookRegistration] | None,
) -> dict[str, Any]:
    """Validate and combine read-only projections without granting effects."""

    projections: dict[str, Any] = {}
    failures: list[dict[str, str]] = []
    projected_hooks: list[str] = []
    for registration in registrations or ():
        try:
            effect_runtime_result(
                "capability_hook.interaction_projection.validate_registration",
                {"registration": registration.contract()},
            )
        except (EffectRuntimeRejected, RuntimeError, TypeError, ValueError):
            failures.append(
                _hook_failure(registration, error_code="registration_rejected")
            )
            continue
        try:
            result = dict(registration.producer())
        except Exception:  # Capability failures are isolated by contract.
            failures.append(_hook_failure(registration, error_code="producer_failed"))
            continue
        try:
            normalized = effect_runtime_result(
                "capability_hook.interaction_projection.validate",
                {
                    "registration": registration.contract(),
                    "result": result,
                },
            )
        except (EffectRuntimeRejected, RuntimeError, TypeError, ValueError):
            failures.append(_hook_failure(registration, error_code="contract_rejected"))
            continue
        if not isinstance(normalized, Mapping):
            failures.append(
                _hook_failure(registration, error_code="runtime_result_invalid")
            )
            continue
        if normalized.get("status") != "projected":
            continue
        slot = normalized.get("projection_slot")
        projection = normalized.get("projection")
        if not isinstance(slot, str) or not isinstance(projection, Mapping):
            failures.append(
                _hook_failure(registration, error_code="runtime_result_invalid")
            )
            continue
        if slot in projections:
            failures.append(
                _hook_failure(registration, error_code="projection_slot_conflict")
            )
            continue
        projections[slot] = dict(projection)
        projected_hooks.append(registration.hook_id)
    return {
        "schema_version": INTERACTION_PROJECTION_HOOK_DISPATCH_SCHEMA_VERSION,
        "phase": "interaction_projection",
        "registered_count": len(registrations or ()),
        "projected_hooks": projected_hooks,
        "projections": projections,
        "failures": failures,
    }


def dispatch_turn_start_hooks(
    registrations: Sequence[TurnStartHookRegistration] | None,
) -> dict[str, Any]:
    """Run bounded pre-turn observations without exposing provider payloads."""

    results: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    seen_hook_ids: set[str] = set()
    ordered = sorted(registrations or (), key=lambda item: item.hook_id)
    for registration in ordered:
        if registration.hook_id in seen_hook_ids:
            failures.append(_hook_failure(registration, error_code="duplicate_hook_id"))
            continue
        seen_hook_ids.add(registration.hook_id)
        try:
            effect_runtime_result(
                "capability_hook.turn_start.validate_registration",
                {"registration": registration.contract()},
            )
        except (EffectRuntimeRejected, RuntimeError, TypeError, ValueError):
            failures.append(
                _hook_failure(registration, error_code="registration_rejected")
            )
            continue
        try:
            result = dict(registration.producer())
        except Exception:  # noqa: BLE001 - capability failures are isolated.
            failures.append(_hook_failure(registration, error_code="producer_failed"))
            continue
        try:
            normalized = effect_runtime_result(
                "capability_hook.turn_start.validate",
                {
                    "registration": registration.contract(),
                    "result": result,
                },
            )
        except (EffectRuntimeRejected, RuntimeError, TypeError, ValueError):
            failures.append(_hook_failure(registration, error_code="contract_rejected"))
            continue
        if not isinstance(normalized, Mapping):
            failures.append(
                _hook_failure(registration, error_code="runtime_result_invalid")
            )
            continue
        results.append(dict(normalized))
    return {
        "schema_version": TURN_START_HOOK_DISPATCH_SCHEMA_VERSION,
        "phase": "turn_start",
        "registered_count": len(registrations or ()),
        "invoked_count": len(results),
        "results": results,
        "failures": failures,
    }


def dispatch_post_writeback_hooks(
    registrations: Sequence[PostWritebackHookRegistration] | None,
    *,
    hook_input: Mapping[str, Any],
    journal: PostWritebackHookReceiptJournal | None = None,
) -> dict[str, Any]:
    """Dispatch typed intents after, never inside, the primary writeback."""

    intents: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    seen_hook_ids: set[str] = set()
    seen_intent_keys: set[str] = set()
    replayed_hooks: list[str] = []
    retried_hooks: list[str] = []
    invoked_count = 0
    ordered = sorted(registrations or (), key=lambda item: item.hook_id)
    for registration in ordered:
        if registration.hook_id in seen_hook_ids:
            failures.append(_hook_failure(registration, error_code="duplicate_hook_id"))
            continue
        seen_hook_ids.add(registration.hook_id)
        try:
            dispatch_id = _post_writeback_dispatch_id(registration, hook_input)
            existing = journal.load(dispatch_id) if journal is not None else None
        except (OSError, TypeError, ValueError):
            failures.append(
                _hook_failure(registration, error_code="journal_read_failed")
            )
            continue
        previous_attempt_count = 0
        if existing is not None:
            try:
                existing = _validated_post_writeback_receipt(
                    registration=registration,
                    hook_input=hook_input,
                    receipt=existing,
                )
            except (EffectRuntimeRejected, RuntimeError, TypeError, ValueError):
                failures.append(
                    _hook_failure(registration, error_code="receipt_conflict")
                )
                continue
            if existing.get("status") == "retryable_failure":
                previous_attempt_count = int(existing["attempt_count"])
                retried_hooks.append(registration.hook_id)
            else:
                existing_intent = existing.get("intent")
                if isinstance(existing_intent, Mapping):
                    idempotency_key = str(existing_intent.get("idempotency_key") or "")
                    if idempotency_key in seen_intent_keys:
                        failures.append(
                            _hook_failure(
                                registration, error_code="intent_key_conflict"
                            )
                        )
                        continue
                    seen_intent_keys.add(idempotency_key)
                    intents.append(dict(existing_intent))
                replayed_hooks.append(registration.hook_id)
                continue
        try:
            effect_runtime_result(
                "capability_hook.post_writeback.validate_registration",
                {"registration": registration.contract()},
            )
            admitted_input = effect_runtime_result(
                "capability_hook.post_writeback.validate_input",
                {
                    "registration": registration.contract(),
                    "hook_input": dict(hook_input),
                },
            )
        except (EffectRuntimeRejected, RuntimeError, TypeError, ValueError):
            failures.append(
                _hook_failure(registration, error_code="registration_or_input_rejected")
            )
            continue
        if not isinstance(admitted_input, Mapping):
            failures.append(
                _hook_failure(registration, error_code="runtime_input_invalid")
            )
            continue
        attempt_count = previous_attempt_count + 1
        try:
            invoked_count += 1
            result = dict(registration.producer(dict(admitted_input)))
        except Exception:  # noqa: BLE001 - optional capability failures are isolated.
            failures.append(
                _record_retryable_post_writeback_failure(
                    journal=journal,
                    registration=registration,
                    hook_input=admitted_input,
                    dispatch_id=dispatch_id,
                    error_code="producer_failed",
                    attempt_count=attempt_count,
                )
            )
            continue
        try:
            normalized = effect_runtime_result(
                "capability_hook.post_writeback.validate",
                {
                    "registration": registration.contract(),
                    "hook_input": dict(admitted_input),
                    "result": result,
                },
            )
        except (EffectRuntimeRejected, RuntimeError, TypeError, ValueError):
            failures.append(
                _record_retryable_post_writeback_failure(
                    journal=journal,
                    registration=registration,
                    hook_input=admitted_input,
                    dispatch_id=dispatch_id,
                    error_code="contract_rejected",
                    attempt_count=attempt_count,
                )
            )
            continue
        if not isinstance(normalized, Mapping):
            failures.append(
                _record_retryable_post_writeback_failure(
                    journal=journal,
                    registration=registration,
                    hook_input=admitted_input,
                    dispatch_id=dispatch_id,
                    error_code="runtime_result_invalid",
                    attempt_count=attempt_count,
                )
            )
            continue
        if normalized.get("status") != "intent":
            if journal is not None:
                try:
                    _store_post_writeback_sidecar(
                        journal=journal,
                        registration=registration,
                        hook_input=admitted_input,
                        dispatch_id=dispatch_id,
                        status="not_applicable",
                        intent=None,
                        error_code=None,
                        attempt_count=attempt_count,
                    )
                except (
                    EffectRuntimeRejected,
                    OSError,
                    RuntimeError,
                    TypeError,
                    ValueError,
                ):
                    failures.append(
                        _hook_failure(registration, error_code="journal_write_failed")
                    )
            continue
        intent = normalized.get("intent")
        if not isinstance(intent, Mapping):
            failures.append(
                _hook_failure(registration, error_code="runtime_result_invalid")
            )
            continue
        idempotency_key = str(intent.get("idempotency_key") or "")
        if idempotency_key in seen_intent_keys:
            failures.append(
                _record_retryable_post_writeback_failure(
                    journal=journal,
                    registration=registration,
                    hook_input=admitted_input,
                    dispatch_id=dispatch_id,
                    error_code="intent_key_conflict",
                    attempt_count=attempt_count,
                )
            )
            continue
        seen_intent_keys.add(idempotency_key)
        normalized_intent = dict(intent)
        if journal is not None:
            try:
                _store_post_writeback_sidecar(
                    journal=journal,
                    registration=registration,
                    hook_input=admitted_input,
                    dispatch_id=dispatch_id,
                    status="intent_recorded",
                    intent=normalized_intent,
                    error_code=None,
                    attempt_count=attempt_count,
                )
            except (
                EffectRuntimeRejected,
                OSError,
                RuntimeError,
                TypeError,
                ValueError,
            ):
                failures.append(
                    _hook_failure(registration, error_code="journal_write_failed")
                )
                continue
        intents.append(normalized_intent)
    return {
        "schema_version": POST_WRITEBACK_HOOK_DISPATCH_SCHEMA_VERSION,
        "phase": "post_writeback",
        "registered_count": len(registrations or ()),
        "invoked_count": invoked_count,
        "replayed_hooks": replayed_hooks,
        "retried_hooks": retried_hooks,
        "intent_count": len(intents),
        "intents": intents,
        "failures": failures,
        "primary_writeback_preserved": True,
        "external_writes_performed": False,
    }


def _hook_failure(
    registration: (
        InteractionProjectionHookRegistration
        | TurnStartHookRegistration
        | PostWritebackHookRegistration
    ),
    *,
    error_code: str,
    durable_receipt_ref: str | None = None,
) -> dict[str, str]:
    failure = {
        "hook_id": registration.hook_id,
        "capability_id": registration.capability_id,
        "error_code": error_code,
    }
    if durable_receipt_ref is not None:
        failure["durable_receipt_ref"] = durable_receipt_ref
    return failure
