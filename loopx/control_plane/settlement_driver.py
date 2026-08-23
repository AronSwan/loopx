"""Python callback adapter for the TS-owned Effect settlement runtime.

The TypeScript runtime owns identity, receipt, replay, ordering, phase advance,
and failure classification. Python remains only where an existing bounded
context still supplies an external callback; it submits the callback result to
the TS reducer before checkpointing it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from .effect_program import (
    SettlementIdentity,
    SettlementReceipt,
    SettlementResult,
    SettlementStepKind,
    decode_settlement_receipt_payload,
    decode_settlement_result_payload,
)
from .effect_runtime import effect_runtime_result


def _identity_payload(identity: SettlementIdentity) -> dict[str, Any]:
    return identity.as_dict()


def decode_settlement_result(
    payload: Any,
    *,
    value_decoder: Callable[[Any], Any] | None = None,
    projection_payload: Mapping[str, Any] | None = None,
) -> SettlementResult[Any]:
    value, receipts, failure = decode_settlement_result_payload(payload)
    if value_decoder is not None and value is not None:
        value = value_decoder(value)
    return SettlementResult(
        value=value,
        receipts=receipts,
        failure=failure,
        _runtime_payload=(
            dict(projection_payload)
            if isinstance(projection_payload, Mapping)
            else None
        ),
    )


def effect_ids_match(
    committed_effect_id: str | None,
    expected_effect_id: str,
) -> bool:
    """Return whether committed receipts prove the expected effect id."""

    return bool(
        effect_runtime_result(
            "settlement.effect_ids_match",
            {
                "committed_effect_id": committed_effect_id,
                "expected_effect_id": expected_effect_id,
            },
        )
    )


def settlement_receipt(
    identity: SettlementIdentity,
    *,
    step_kind: SettlementStepKind,
    source_ref: str | None = None,
) -> SettlementReceipt:
    """Build one committed receipt for a settlement identity and step."""

    payload = effect_runtime_result(
        "settlement.receipt",
        {
            "identity": _identity_payload(identity),
            "step_kind": step_kind.value,
            "source_ref": source_ref,
        },
    )
    if not isinstance(payload, Mapping):
        raise RuntimeError("TypeScript settlement receipt shape mismatch")
    return decode_settlement_receipt_payload(payload)
