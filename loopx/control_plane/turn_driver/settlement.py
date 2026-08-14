"""Turn-driver adapter for the shared typed settlement receipt-chain driver."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ..effect_program import (
    SettlementResult,
    SettlementStepKind,
)
from ..settlement_driver import (
    commit_step_effect,
    require_matching_effect_id,
    seed_committed_steps,
    settlement_identity_from_plan,
)


TurnEffect = Callable[[], Mapping[str, Any]]
TurnSettlementCheckpoint = Callable[
    [SettlementStepKind, Mapping[str, Any], tuple[str, ...]],
    None,
]


@dataclass(frozen=True, slots=True)
class TurnSettlementState:
    completed_phases: tuple[str, ...]
    writeback: Mapping[str, Any] | None = None
    quota_spend: Mapping[str, Any] | None = None


SETTLEMENT_STEPS = (
    SettlementStepKind.VALIDATION,
    SettlementStepKind.DURABLE_WRITEBACK,
    SettlementStepKind.QUOTA_SPEND,
)


def execute_turn_driver_settlement(
    transaction_plan: Mapping[str, Any],
    *,
    transaction_phases: tuple[str, ...],
    completed_phases: Sequence[str],
    writeback_payload: Mapping[str, Any] | None,
    quota_spend_payload: Mapping[str, Any] | None,
    writeback: TurnEffect,
    spend: TurnEffect,
    checkpoint: TurnSettlementCheckpoint,
    committed_effect_id: str | None = None,
) -> SettlementResult[TurnSettlementState]:
    """Bind validation -> writeback -> spend for the isolated Turn adapter.

    ``committed_effect_id`` is the settlement effect id under which an
    existing journal committed its receipts. When a journal is present, a
    caller must prove that the committed receipts belong to the current plan's
    settlement identity; otherwise a key/owner-mismatched replay would
    re-attribute the committed validation/writeback/spend receipts to a
    different effect while skipping its effects. A ``None`` provenance
    keeps legacy plans and direct callers that have no journal readback
    unchanged.
    """

    identity_result = settlement_identity_from_plan(transaction_plan)
    if identity_result.failure is not None:
        return identity_result
    identity = identity_result.value
    assert identity is not None
    matched = require_matching_effect_id(committed_effect_id, identity.effect_id)
    if matched.failure is not None:
        return SettlementResult.failed(
            kind=matched.failure.kind,
            step_kind=matched.failure.step_kind,
            reason=matched.failure.reason,
        )
    phases = tuple(str(phase) for phase in completed_phases)
    committed_payloads: dict[SettlementStepKind, Mapping[str, Any] | None] = {
        SettlementStepKind.VALIDATION: {},
        SettlementStepKind.DURABLE_WRITEBACK: writeback_payload,
        SettlementStepKind.QUOTA_SPEND: quota_spend_payload,
    }
    seeded = seed_committed_steps(
        identity,
        ordered_steps=SETTLEMENT_STEPS,
        committed_payloads=committed_payloads,
        completed_phases=phases,
        transaction_phases=transaction_phases,
        require_validation=True,
        source_ref_prefix="turn_journal",
    )
    if seeded.failure is not None:
        return SettlementResult.failed(
            kind=seeded.failure.kind,
            step_kind=seeded.failure.step_kind,
            reason=seeded.failure.reason,
            receipts=seeded.receipts,
        )
    state = TurnSettlementState(
        completed_phases=phases,
        writeback=writeback_payload,
        quota_spend=quota_spend_payload,
    )
    receipts = list(seeded.receipts)
    if "durable_writeback" not in phases:
        step_result = commit_step_effect(
            identity,
            step_kind=SettlementStepKind.DURABLE_WRITEBACK,
            transaction_phases=transaction_phases,
            effect=writeback,
            checkpoint=checkpoint,
        )
        if step_result.failure is not None:
            return SettlementResult.failed(
                kind=step_result.failure.kind,
                step_kind=step_result.failure.step_kind,
                reason=step_result.failure.reason,
                receipts=tuple(receipts),
            )
        receipts.extend(step_result.receipts)
        phase_index = transaction_phases.index(
            SettlementStepKind.DURABLE_WRITEBACK.value
        )
        state = TurnSettlementState(
            completed_phases=tuple(transaction_phases[: phase_index + 1]),
            writeback=step_result.value,
            quota_spend=state.quota_spend,
        )
    if "quota_spend" not in phases:
        step_result = commit_step_effect(
            identity,
            step_kind=SettlementStepKind.QUOTA_SPEND,
            transaction_phases=transaction_phases,
            effect=spend,
            checkpoint=checkpoint,
        )
        if step_result.failure is not None:
            return SettlementResult.failed(
                kind=step_result.failure.kind,
                step_kind=step_result.failure.step_kind,
                reason=step_result.failure.reason,
                receipts=tuple(receipts),
            )
        receipts.extend(step_result.receipts)
        phase_index = transaction_phases.index(SettlementStepKind.QUOTA_SPEND.value)
        state = TurnSettlementState(
            completed_phases=tuple(transaction_phases[: phase_index + 1]),
            writeback=state.writeback,
            quota_spend=step_result.value,
        )
    return SettlementResult.pure(state, receipts=tuple(receipts))
