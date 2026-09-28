from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

import pytest

from loopx.chat_action_store import ActionConflictError, ChatActionStore
from loopx.chat_actions import ChatActionService, ProtectedActionGate


GOAL_ID = "goal-operation-fixture"
OPERATOR_ID = "ou_authorized_fixture"


def _digest(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _service(tmp_path: Path) -> tuple[ChatActionService, ChatActionStore]:
    project = tmp_path / "project"
    project.mkdir()
    (project / "ACTIVE_GOAL_STATE.md").write_text(
        f"---\ngoal_id: {GOAL_ID}\n---\n\n## User Todo\n\n## Agent Todo\n",
        encoding="utf-8",
    )
    registry = project / ".loopx" / "registry.json"
    registry.parent.mkdir()
    registry.write_text(
        json.dumps(
            {
                "goals": [
                    {
                        "id": GOAL_ID,
                        "repo": str(project),
                        "state_file": "ACTIVE_GOAL_STATE.md",
                        "coordination": {
                            "registered_agents": ["finance-fixture-agent"]
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    store = ChatActionStore(tmp_path / "runtime" / "chat" / "actions")
    return ChatActionService(store=store, registry_path=registry), store


def _request(*, payload: dict[str, object] | None = None) -> dict[str, object]:
    operation_payload = payload or {
        "schema_version": "finance_order_intent_v0",
        "side": "buy",
        "asset": "SYNTH",
        "quantity": "1.00",
        "order_type": "limit",
        "limit_price": "10.00",
        "time_in_force": "GTC",
        "reduce_only": False,
    }
    return {
        "action_kind": "operation.execute",
        "summary": "Confirm one simulated finance order",
        "idempotency_key": "operation-fixture-v1",
        "context": {"kind": "goal", "goal_id": GOAL_ID},
        "normalized_parameters": {
            "schema_version": "loopx_operation_request_v0",
            "goal_id": GOAL_ID,
            "agent_id": "finance-fixture-agent",
            "domain": "finance",
            "operation_kind": "finance.order.simulate",
            "operation_schema": "finance_order_intent_v0",
            "payload_ref": "finance-order:synthetic-1",
            "payload": operation_payload,
            "payload_digest": _digest(operation_payload),
            "projection": {
                "schema_version": "loopx_operation_projection_v0",
                "title": "Simulated trade request",
                "subtitle": "Synthetic fixture · no venue call",
                "focus": "BUY 1.00 SYNTH @ 10.00",
                "fields": [
                    {"label": "Order type", "value": "Limit · GTC"},
                    {"label": "Maximum notional", "value": "10.00 TEST"},
                ],
                "warning": "Simulation only. This cannot submit, sign, or transfer.",
                "simulated": True,
            },
            "destination_account_ref": "account:simulation",
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            "authorized_principals": [f"lark:{OPERATOR_ID}"],
            "executor": {
                "extension_id": "loopx-finance-execution",
                "protocol": "finance_operation_executor_v0",
                "permission": "finance.operation.simulate",
                "revision": "simulator-v0",
            },
        },
    }


def _delivery(proposal: dict[str, object]) -> dict[str, str]:
    operation = proposal["operation"]
    assert isinstance(operation, dict)
    return {
        "provider": "lark",
        "message_id": "om_operation_fixture",
        "chat_id": "oc_operation_fixture",
        "app_id": "cli_operation_fixture",
        "binding_digest": "a" * 64,
        "card_digest": "b" * 64,
        "delivered_at": datetime.now(timezone.utc).isoformat(),
    }


def _confirmation(
    proposal: dict[str, object], *, event_id: str = "evt-operation-1"
) -> dict[str, str]:
    operation = proposal["operation"]
    assert isinstance(operation, dict)
    delivery = operation["delivery"]
    assert isinstance(delivery, dict)
    return {
        "provider": "lark",
        "event_id": event_id,
        "principal": f"lark:{OPERATOR_ID}",
        "message_id": str(delivery["message_id"]),
        "chat_id": str(delivery["chat_id"]),
        "app_id": str(delivery["app_id"]),
        "surface_kind": "group_message_card",
        "interaction_kind": "button_callback",
        "confirmation_digest": str(operation["confirmation_digest"]),
        "card_digest": str(delivery["card_digest"]),
        "confirmed_at": datetime.now(timezone.utc).isoformat(),
    }


def test_operation_preview_arms_one_canonical_gate_and_local_apply_cannot_claim(
    tmp_path: Path,
) -> None:
    service, store = _service(tmp_path)

    proposal = service.preview(_request())

    assert proposal["status"] == "gated"
    assert proposal["available_transitions"] == ["cancel"]
    assert proposal["operation"]["lifecycle_state"] == "awaiting_confirmation"
    assert proposal["gate"]["kind"] == "human_operation_confirmation"
    with pytest.raises(ProtectedActionGate, match="local apply"):
        service.apply(str(proposal["proposal_id"]))
    assert store.load(str(proposal["proposal_id"]))["status"] == "gated"


def test_operation_digest_change_cannot_reuse_idempotency_key(tmp_path: Path) -> None:
    service, _store = _service(tmp_path)
    service.preview(_request())
    changed = _request(
        payload={
            "schema_version": "finance_order_intent_v0",
            "side": "buy",
            "asset": "SYNTH",
            "quantity": "2.00",
        }
    )

    with pytest.raises(ActionConflictError, match="idempotency key"):
        service.preview(changed)


def test_operation_rejects_non_finite_payload_numbers(tmp_path: Path) -> None:
    service, _store = _service(tmp_path)
    request = _request(payload={"schema_version": "fixture", "price": float("nan")})

    with pytest.raises(ValueError, match="JSON"):
        service.preview(request)


def test_lark_decision_claims_once_and_restart_preserves_outcome(
    tmp_path: Path,
) -> None:
    service, store = _service(tmp_path)
    proposal = service.preview(_request())
    proposal_id = str(proposal["proposal_id"])
    delivered = store.record_operation_delivery(
        proposal_id, delivery=_delivery(proposal)
    )
    confirmation = _confirmation(delivered)

    forged = {**confirmation, "principal": "lark:ou_untrusted_fixture"}
    with pytest.raises(ActionConflictError, match="not authorized"):
        store.decide_operation(proposal_id, decision="confirm", confirmation=forged)

    claimed = store.decide_operation(
        proposal_id, decision="confirm", confirmation=confirmation
    )
    replay = store.decide_operation(
        proposal_id, decision="confirm", confirmation=confirmation
    )
    assert claimed["operation"]["lifecycle_state"] == "claimed"
    assert replay["operation"]["claim"] == claimed["operation"]["claim"]
    with pytest.raises(ActionConflictError, match="already consumed"):
        store.decide_operation(
            proposal_id,
            decision="confirm",
            confirmation={**confirmation, "event_id": "evt-operation-2"},
        )

    outcome = {
        "schema_version": "loopx_operation_outcome_v0",
        "outcome": "simulated_filled",
        "projection_verified": True,
        "operation_id": proposal_id,
        "payload_digest": claimed["operation"]["payload_digest"],
        "summary": "Simulation completed without an external write.",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "external_write_performed": False,
    }
    observed = store.observe_operation_outcome(proposal_id, outcome=outcome)
    restarted = ChatActionStore(store.root)

    assert observed["status"] == "applied"
    assert restarted.load(proposal_id)["operation"]["outcome"] == outcome
    assert restarted.observe_operation_outcome(proposal_id, outcome=outcome) == observed


def test_reject_is_terminal_without_executor_claim(tmp_path: Path) -> None:
    service, store = _service(tmp_path)
    proposal = service.preview(_request())
    proposal_id = str(proposal["proposal_id"])
    delivered = store.record_operation_delivery(
        proposal_id, delivery=_delivery(proposal)
    )

    rejected = store.decide_operation(
        proposal_id,
        decision="reject",
        confirmation=_confirmation(delivered),
    )

    assert rejected["status"] == "rejected"
    assert rejected["operation"]["claim"] is None
    assert rejected["operation"]["outcome"]["outcome"] == "rejected_by_operator"
