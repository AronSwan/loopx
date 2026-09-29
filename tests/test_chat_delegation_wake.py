"""Host wake of a Chat LoopX lead after a delegated result is accepted.

Expectations follow the wake contract, not the implementation: an accepted
result with a pending intent continues its requester's lead at most once, the
existing Chat LoopX owner decides admission, and every other state leaves a
distinct receipt without starting a Turn.
"""

import json

import pytest

from loopx.chat_loopx_mode import pump_delegation_wakes
from loopx.collaboration_mcp import execution_row_path
from test_chat_loopx_mode import apply, mode  # noqa: F401
from test_chat_project_coordination import project  # noqa: F401

INTENT_ID = "a" * 64
OPERATION_ID = "review-1"


def _runtime_root(service):
    return service.store.root.parent


def _write_record(service, *, status="accepted", agent_id="coordinator",
                  stored_as=None, operation_id=OPERATION_ID):
    root = _runtime_root(service)
    owner_goal, owner_agent = stored_as or ("research", agent_id)
    path = execution_row_path(root, owner_goal, owner_agent, operation_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "operation_id": operation_id,
        "status": status,
        "wake": {
            "schema_version": "loopx_delegation_wake_intent_v0",
            "intent_id": INTENT_ID,
            "requester": {"goal_id": "research", "agent_id": agent_id, "goal_ref": None},
            "operation_id": operation_id,
            "request_id": "request-1",
            "state": "pending",
        },
    }))
    return path


def _wake(path):
    return json.loads(path.read_text())["wake"]


def _idle_resumable_lead(mode):  # noqa: F811
    """Enable the mode, then leave the lead idle on a resumable native Goal."""
    service, sid, _, settings, calls = mode
    apply(mode, "start", settings=settings)
    service.store.update_session(
        sid, active_turn_id=None, native_goal={"status": "paused", "tokensUsed": 0}
    )
    calls.clear()
    return service, sid, calls


def _pump(service, repo):
    return pump_delegation_wakes(
        service.controller,
        goal_context=lambda session: {"project": repo, "objective": "Continue"},
    )


def test_accepted_result_wakes_the_lead_exactly_once(mode):  # noqa: F811
    service, sid, calls = _idle_resumable_lead(mode)
    repo = mode[2]
    path = _write_record(service)

    changed = _pump(service, repo)

    assert len(calls) == 1
    assert calls[0]["client_turn_id"] == "wake-" + INTENT_ID[:32]
    assert calls[0]["loopx_request"]["operation"] == "wake"
    assert calls[0]["loopx_request"]["wake"]["intent_id"] == INTENT_ID
    receipt = _wake(path)
    assert receipt["state"] == "woken" and receipt["created"] is True
    assert receipt["session_id"] == sid and changed == [receipt]

    # A second tick finds no pending intent: no second Turn, receipt unchanged.
    assert _pump(service, repo) == []
    assert len(calls) == 1 and _wake(path) == receipt


def test_crash_after_submit_records_the_existing_turn_once(mode):  # noqa: F811
    service, sid, calls = _idle_resumable_lead(mode)
    repo = mode[2]
    turn, _ = service.store.create_turn(
        sid, client_turn_id="wake-" + INTENT_ID[:32], message="/goal resume"
    )
    service.store.update_turn(
        sid, turn["turn_id"], loopx_execution=True,
        loopx_request={"operation": "wake", "wake": {"intent_id": INTENT_ID}},
    )
    service.store.update_session(sid, active_turn_id=None)
    path = _write_record(service)

    _pump(service, repo)

    receipt = _wake(path)
    assert receipt["state"] == "woken" and receipt["created"] is False
    assert receipt["turn_id"] == turn["turn_id"] and calls == []


def test_client_id_owned_by_another_turn_is_not_claimed(mode):  # noqa: F811
    service, sid, calls = _idle_resumable_lead(mode)
    repo = mode[2]
    service.store.create_turn(
        sid, client_turn_id="wake-" + INTENT_ID[:32], message="unrelated"
    )
    service.store.update_session(sid, active_turn_id=None)
    path = _write_record(service)

    _pump(service, repo)

    assert _wake(path)["state"] == "refused"
    assert _wake(path)["reason"] == "wake_identity_conflict" and calls == []


def test_active_lead_turn_keeps_the_intent_pending_without_churn(mode):  # noqa: F811
    service, sid, _, settings, calls = mode
    repo = mode[2]
    apply(mode, "start", settings=settings)
    calls.clear()
    assert service.store.load_session(sid)["active_turn_id"]
    path = _write_record(service)

    _pump(service, repo)
    first = _wake(path)
    assert first["state"] == "pending" and first["reason"] == "lead_turn_active"
    before = path.read_bytes()
    _pump(service, repo)
    assert path.read_bytes() == before and calls == []


def test_paused_lead_stays_pending_and_is_not_unpaused(mode):  # noqa: F811
    service, sid, calls = _idle_resumable_lead(mode)
    repo = mode[2]
    session = service.store.load_session(sid)
    service.store.update_session(
        sid, loopx_mode={**session["loopx_mode"], "paused": True}
    )
    path = _write_record(service)

    _pump(service, repo)

    assert _wake(path)["state"] == "pending" and _wake(path)["reason"] == "lead_paused"
    assert service.store.load_session(sid)["loopx_mode"]["paused"] is True
    assert calls == []


def test_stopped_goal_refuses_the_wake(mode):  # noqa: F811
    service, _, calls = _idle_resumable_lead(mode)
    repo = mode[2]
    registry = service.controller.registry_path
    payload = json.loads(registry.read_text())
    next(goal for goal in payload["goals"] if goal["id"] == "research")["status"] = "stopped"
    registry.write_text(json.dumps(payload))
    path = _write_record(service)

    _pump(service, repo)

    assert _wake(path)["state"] == "refused" and _wake(path)["reason"] == "goal_stopped"
    assert calls == []


def test_requester_without_a_lead_conversation_is_refused(mode):  # noqa: F811
    service, _, calls = _idle_resumable_lead(mode)
    repo = mode[2]
    path = _write_record(service, agent_id="someone-else")

    _pump(service, repo)

    assert _wake(path)["state"] == "refused" and _wake(path)["reason"] == "no_wake_owner"
    assert calls == []


def test_intent_stored_under_another_requester_is_not_decided(mode):  # noqa: F811
    service, _, calls = _idle_resumable_lead(mode)
    repo = mode[2]
    path = _write_record(service, stored_as=("research", "reviewer"))

    assert _pump(service, repo) == []
    assert _wake(path)["state"] == "pending" and calls == []


@pytest.mark.parametrize("status", ["rejected", "running", "stopped"])
def test_only_an_accepted_result_can_wake(mode, status):  # noqa: F811
    service, _, calls = _idle_resumable_lead(mode)
    repo = mode[2]
    path = _write_record(service, status=status)

    assert _pump(service, repo) == []
    assert _wake(path)["state"] == "pending" and calls == []
