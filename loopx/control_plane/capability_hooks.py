from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .effect_runtime import EffectRuntimeRejected, effect_runtime_result


CAPABILITY_HOOK_REGISTRATION_SCHEMA_VERSION = (
    "loopx_capability_hook_registration_v0"
)
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
POST_WRITEBACK_HOOK_RESULT_SCHEMA_VERSION = (
    "loopx_post_writeback_capability_hook_result_v0"
)
POST_WRITEBACK_HOOK_DISPATCH_SCHEMA_VERSION = (
    "loopx_post_writeback_capability_hook_dispatch_v0"
)
POST_WRITEBACK_RECEIPT_SCHEMA_VERSION = "loopx_post_writeback_receipt_v0"

InteractionProjectionProducer = Callable[[], Mapping[str, Any]]
TurnStartProducer = Callable[[], Mapping[str, Any]]
PostWritebackProducer = Callable[[Mapping[str, Any]], Mapping[str, Any]]


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
    """One intent-only capability observation after a durable writeback.

    The hook receives only the public-safe writeback receipt, subscribes to
    the durable event kinds it cares about, and returns a typed intent.
    It is never granted a write scope: effects stay behind the existing
    authorized boundaries and the primary writeback is never rolled back.
    """

    hook_id: str
    capability_id: str
    subscribed_event_kinds: tuple[str, ...]
    requested_read_scope: tuple[str, ...]
    producer: PostWritebackProducer
    max_result_bytes: int = 16 * 1024

    def contract(self) -> dict[str, Any]:
        return {
            "schema_version": POST_WRITEBACK_HOOK_REGISTRATION_SCHEMA_VERSION,
            "hook_id": self.hook_id,
            "capability_id": self.capability_id,
            "phase": "post_writeback",
            "subscribed_event_kinds": list(self.subscribed_event_kinds),
            "budget": {
                "max_invocations_per_dispatch": 1,
                "max_result_bytes": self.max_result_bytes,
            },
            "failure_policy": "isolate",
            "requested_read_scope": list(self.requested_read_scope),
            "requested_write_scope": [],
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
            failures.append(
                _hook_failure(registration, error_code="producer_failed")
            )
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
            failures.append(
                _hook_failure(registration, error_code="contract_rejected")
            )
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


def _hook_failure(
    registration: (
        InteractionProjectionHookRegistration
        | TurnStartHookRegistration
        | PostWritebackHookRegistration
    ),
    *,
    error_code: str,
) -> dict[str, str]:
    return {
        "hook_id": registration.hook_id,
        "capability_id": registration.capability_id,
        "error_code": error_code,
    }


def _receipt_token(value: object, label: str, *, maximum: int = 128) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be text")
    token = value.strip()
    if not token or len(token) > maximum:
        raise ValueError(f"{label} is invalid")
    return token


def _writeback_receipt(raw: object) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise ValueError("writeback_receipt must be an object")
    allowed = {
        "schema_version",
        "goal_id",
        "event_id",
        "event_kind",
        "recorded_at",
        "appended",
        "agent_id",
        "todo_id",
        "state_version",
    }
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ValueError(
            "writeback_receipt contains unsupported fields: " + ", ".join(unknown)
        )
    if raw.get("schema_version") != POST_WRITEBACK_RECEIPT_SCHEMA_VERSION:
        raise ValueError(
            f"writeback_receipt.schema_version must be {POST_WRITEBACK_RECEIPT_SCHEMA_VERSION!r}"
        )
    appended = raw.get("appended")
    if not isinstance(appended, bool):
        raise ValueError("writeback_receipt.appended must be boolean")
    receipt: dict[str, Any] = {
        "schema_version": POST_WRITEBACK_RECEIPT_SCHEMA_VERSION,
        "goal_id": _receipt_token(raw.get("goal_id"), "writeback_receipt.goal_id"),
        "event_id": _receipt_token(raw.get("event_id"), "writeback_receipt.event_id"),
        "event_kind": _receipt_token(
            raw.get("event_kind"), "writeback_receipt.event_kind", maximum=64
        ),
        "recorded_at": _receipt_token(
            raw.get("recorded_at"), "writeback_receipt.recorded_at", maximum=64
        ),
        "appended": appended,
    }
    for optional in ("agent_id", "todo_id", "state_version"):
        value = raw.get(optional)
        if value is not None:
            receipt[optional] = _receipt_token(
                value, f"writeback_receipt.{optional}"
            )
    return receipt


def dispatch_post_writeback_hooks(
    registrations: Sequence[PostWritebackHookRegistration] | None,
    writeback_receipt: Mapping[str, Any],
) -> dict[str, Any]:
    """Run subscribed intent hooks after one successful durable writeback.

    Dispatch is composition-owned: it must only be invoked once the primary
    durable writeback succeeded and its public-safe event receipt exists.
    A replayed (not newly appended) receipt dispatches nothing, hooks whose
    subscribed event kinds do not cover the receipt are never invoked, and
    every hook failure is isolated so the primary writeback is never
    affected.
    """

    receipt = _writeback_receipt(writeback_receipt)
    results: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    seen_hook_ids: set[str] = set()
    ordered = sorted(registrations or (), key=lambda item: item.hook_id)
    if not receipt["appended"]:
        return {
            "schema_version": POST_WRITEBACK_HOOK_DISPATCH_SCHEMA_VERSION,
            "phase": "post_writeback",
            "receipt": dict(receipt),
            "registered_count": len(ordered),
            "invoked_count": 0,
            "results": results,
            "failures": failures,
            "skipped_hooks": sorted(
                (
                    {
                        "hook_id": registration.hook_id,
                        "capability_id": registration.capability_id,
                        "reason": "replayed_receipt",
                    }
                    for registration in ordered
                ),
                key=lambda item: (item["hook_id"], item["capability_id"]),
            ),
            "primary_writeback_affected": False,
        }
    for registration in ordered:
        if registration.hook_id in seen_hook_ids:
            failures.append(_hook_failure(registration, error_code="duplicate_hook_id"))
            continue
        seen_hook_ids.add(registration.hook_id)
        if receipt["event_kind"] not in registration.subscribed_event_kinds:
            skipped.append(
                {
                    "hook_id": registration.hook_id,
                    "capability_id": registration.capability_id,
                    "reason": "event_kind_not_subscribed",
                }
            )
            continue
        try:
            effect_runtime_result(
                "capability_hook.post_writeback.validate_registration",
                {"registration": registration.contract()},
            )
        except (EffectRuntimeRejected, RuntimeError, TypeError, ValueError):
            failures.append(
                _hook_failure(registration, error_code="registration_rejected")
            )
            continue
        try:
            result = dict(registration.producer(dict(receipt)))
        except Exception:  # noqa: BLE001 - capability failures are isolated.
            failures.append(_hook_failure(registration, error_code="producer_failed"))
            continue
        try:
            normalized = effect_runtime_result(
                "capability_hook.post_writeback.validate",
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
        "schema_version": POST_WRITEBACK_HOOK_DISPATCH_SCHEMA_VERSION,
        "phase": "post_writeback",
        "receipt": dict(receipt),
        "registered_count": len(ordered),
        "invoked_count": len(results),
        "results": results,
        "failures": failures,
        "skipped_hooks": sorted(
            skipped, key=lambda item: (item["hook_id"], item["capability_id"])
        ),
        "primary_writeback_affected": False,
    }
