"""Host wake of a Chat LoopX lead after a delegated result is accepted.

Expectations follow the wake contract, not the implementation: an accepted
result with a pending intent continues its requester's lead at most once, the
existing Chat LoopX owner decides admission, and every other state leaves a
distinct receipt without starting a Turn.
"""

import json

import pytest

import loopx.collaboration_mcp as collaboration_mcp
from loopx.chat_loopx_mode import pump_delegation_wakes
from loopx.chat_runtime import ChatRuntimeController
from loopx.collaboration_mcp import execution_row_path
from test_chat_loopx_mode import apply, mode  # noqa: F401
from test_chat_project_coordination import project  # noqa: F401

INTENT_ID = "a" * 64
OPERATION_ID = "review-1"


def _runtime_root(service):
    return service.store.root.parent


def _write_record(service, *, status="accepted", agent_id="coordinator",
                  stored_as=None, operation_id=OPERATION_ID, session_id=None):
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
            # The conversation whose Turn started the operation; the only wake target.
            **({"conversation": {"session_id": session_id, "turn_id": "lead-turn"}}
               if session_id else {}),
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
    path = _write_record(service, session_id=sid)

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


def test_lost_receipt_after_the_turn_started_records_it_once(mode):  # noqa: F811
    service, sid, calls = _idle_resumable_lead(mode)
    repo = mode[2]
    turn, _ = service.store.create_turn(
        sid, client_turn_id="wake-" + INTENT_ID[:32], message="/goal resume"
    )
    # A started Turn is dispatch evidence; a merely persisted one is not.
    service.store.update_turn(
        sid, turn["turn_id"], loopx_execution=True, status="completed",
        started_at="2026-09-30T00:00:00Z", completed_at="2026-09-30T00:01:00Z",
        loopx_request={"operation": "wake", "wake": {"intent_id": INTENT_ID}},
    )
    service.store.update_session(sid, active_turn_id=None)
    path = _write_record(service, session_id=sid)

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
    path = _write_record(service, session_id=sid)

    _pump(service, repo)

    assert _wake(path)["state"] == "refused"
    assert _wake(path)["reason"] == "wake_identity_conflict" and calls == []


def test_active_lead_turn_keeps_the_intent_pending_without_churn(mode):  # noqa: F811
    service, sid, _, settings, calls = mode
    repo = mode[2]
    apply(mode, "start", settings=settings)
    calls.clear()
    assert service.store.load_session(sid)["active_turn_id"]
    path = _write_record(service, session_id=sid)

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
    path = _write_record(service, session_id=sid)

    _pump(service, repo)

    assert _wake(path)["state"] == "pending" and _wake(path)["reason"] == "lead_paused"
    assert service.store.load_session(sid)["loopx_mode"]["paused"] is True
    assert calls == []


def test_stopped_goal_refuses_the_wake(mode):  # noqa: F811
    service, sid, calls = _idle_resumable_lead(mode)
    repo = mode[2]
    registry = service.controller.registry_path
    payload = json.loads(registry.read_text())
    next(goal for goal in payload["goals"] if goal["id"] == "research")["status"] = "stopped"
    registry.write_text(json.dumps(payload))
    path = _write_record(service, session_id=sid)

    _pump(service, repo)

    assert _wake(path)["state"] == "refused" and _wake(path)["reason"] == "goal_stopped"
    assert calls == []


def test_intent_without_an_originating_conversation_wakes_nobody(mode):  # noqa: F811
    """An operation started outside a Chat conversation has no wake target;
    a same-identity conversation is never selected in its place."""
    service, sid, calls = _idle_resumable_lead(mode)
    repo = mode[2]
    path = _write_record(service)

    _pump(service, repo)

    assert _wake(path)["state"] == "refused" and _wake(path)["reason"] == "no_wake_owner"
    assert calls == []


def test_pinned_conversation_rebound_to_another_requester_is_refused(mode):  # noqa: F811
    service, sid, calls = _idle_resumable_lead(mode)
    repo = mode[2]
    path = _write_record(service, agent_id="someone-else", session_id=sid)

    _pump(service, repo)

    assert _wake(path)["state"] == "refused"
    assert _wake(path)["reason"] == "wake_identity_conflict" and calls == []


def test_intent_stored_under_another_requester_is_not_decided(mode):  # noqa: F811
    service, sid, calls = _idle_resumable_lead(mode)
    repo = mode[2]
    path = _write_record(service, stored_as=("research", "reviewer"), session_id=sid)

    assert _pump(service, repo) == []
    assert _wake(path)["state"] == "pending" and calls == []


@pytest.mark.parametrize("status", ["rejected", "running", "stopped"])
def test_only_an_accepted_result_can_wake(mode, status):  # noqa: F811
    service, sid, calls = _idle_resumable_lead(mode)
    repo = mode[2]
    path = _write_record(service, status=status, session_id=sid)

    assert _pump(service, repo) == []
    assert _wake(path)["state"] == "pending" and calls == []


# Native dispatch recovery and conversation pinning.
#
# These run the real ChatRuntimeController.submit_turn, TS turn acceptance and
# the durable Chat store.  Only the adapter and worker transport are replaced,
# so no model runs; "dispatch" below is a request to start the worker.

class Transport:
    """Adapter/worker boundary with injectable faults."""

    def __init__(self, service, *, adapter_failures=0, start_turns=False):
        self.service = service
        self.adapter_failures = adapter_failures
        self.start_turns = start_turns
        self.adapter_attempts = []
        self.dispatches = []

    def ensure_adapter(self, session, **kwargs):
        self.adapter_attempts.append(session["session_id"])
        if len(self.adapter_attempts) <= self.adapter_failures:
            raise RuntimeError("adapter initialization failed")
        return object()

    def start_worker(self, *, session_id, turn_id, **kwargs):
        self.dispatches.append((session_id, turn_id))
        if self.start_turns:  # the worker's first durable step
            self.service.store.update_turn(
                session_id, turn_id, expected_statuses={"queued"},
                status="starting", started_at="2026-09-30T00:00:00Z",
            )
        return True


def _native(mode, monkeypatch, **faults):  # noqa: F811
    service, sid, repo, settings, _ = mode
    apply(mode, "start", settings=settings)
    store = service.store
    start_turn = store.load_session(sid)["active_turn_id"]
    store.update_turn(sid, start_turn, status="completed", started_at="2026-09-30T00:00:00Z",
                      completed_at="2026-09-30T00:00:01Z")
    store.update_session(sid, active_turn_id=None, status="ready", loopx_tools=True,
                         native_goal={"status": "paused", "tokensUsed": 0})
    controller = service.controller
    transport = Transport(service, **faults)
    monkeypatch.setattr(controller, "submit_turn",
                        ChatRuntimeController.submit_turn.__get__(controller))
    monkeypatch.setattr(controller, "_ensure_adapter_locked", transport.ensure_adapter)
    monkeypatch.setattr(controller, "_start_accepted_turn_worker", transport.start_worker)
    return service, sid, repo, transport


def _wake_turns(service, sid):
    turns = service.store.root / "sessions" / sid / "turns"
    return [
        row for row in (json.loads(p.read_text()) for p in turns.glob("*.json")
                        if not p.name.endswith(".events.json"))
        if str(row.get("client_turn_id", "")).startswith("wake-")
    ]


def _second_lead(service, sid, settings):
    """Another enabled conversation for the same Goal and coordinator identity."""
    store = service.store
    other = store.create_session(
        goal_id="research", agent_id="codex", channel_id="goal.research",
        upstream_thread_id="fixture-2", upstream_mode="chat", adapter_kind="codex_app_server",
    )["session_id"]
    mode_state = store.load_session(sid)["loopx_mode"]
    store.update_session(other, loopx_mode={**mode_state, "enabled": True, "paused": False},
                         loopx_tools=True, status="ready",
                         native_goal={"status": "paused", "tokensUsed": 0})
    return other


def _fail_next_wake_receipt(monkeypatch):
    real = collaboration_mcp._write
    failed = []

    def write(path, row):
        if not failed and (row.get("wake") or {}).get("state") == "woken":
            failed.append(path)
            raise OSError("receipt write lost")
        return real(path, row)

    monkeypatch.setattr(collaboration_mcp, "_write", write)
    return failed


def test_adapter_failure_after_acceptance_is_redispatched_not_recorded(mode, monkeypatch):  # noqa: F811
    service, sid, repo, transport = _native(mode, monkeypatch, adapter_failures=1)
    path = _write_record(service, session_id=sid)

    assert _pump(service, repo) == []
    [queued] = _wake_turns(service, sid)
    assert queued["status"] == "queued" and queued["started_at"] is None
    assert _wake(path)["state"] == "pending" and transport.dispatches == []

    _pump(service, repo)

    # The native acceptance owner re-dispatches the same Turn; no second Turn.
    assert len(transport.adapter_attempts) == 2
    assert transport.dispatches == [(sid, queued["turn_id"])]
    assert [row["turn_id"] for row in _wake_turns(service, sid)] == [queued["turn_id"]]
    receipt = _wake(path)
    assert receipt["state"] == "woken" and receipt["turn_id"] == queued["turn_id"]
    assert receipt["created"] is False


def test_failure_after_the_prepared_capsule_is_repaired_and_dispatched(mode, monkeypatch):  # noqa: F811
    service, sid, repo, transport = _native(mode, monkeypatch)
    path = _write_record(service, session_id=sid)
    real = service.store.append_message
    failed = []

    def append_message(*args, **kwargs):
        if not failed:
            failed.append(True)
            raise OSError("transcript unavailable")
        return real(*args, **kwargs)

    monkeypatch.setattr(service.store, "append_message", append_message)
    assert _pump(service, repo) == []
    [prepared] = _wake_turns(service, sid)
    assert "_acceptance" in prepared and transport.dispatches == []
    assert _wake(path)["state"] == "pending"

    _pump(service, repo)

    [settled] = _wake_turns(service, sid)
    assert settled["turn_id"] == prepared["turn_id"] and "_acceptance" not in settled
    assert transport.dispatches == [(sid, prepared["turn_id"])]
    assert _wake(path)["state"] == "woken"


@pytest.mark.parametrize("started", [False, True])
def test_lost_receipt_replays_only_the_original_turn(mode, monkeypatch, started):  # noqa: F811
    service, sid, repo, transport = _native(mode, monkeypatch, start_turns=started)
    path = _write_record(service, session_id=sid)
    lost = _fail_next_wake_receipt(monkeypatch)

    assert _pump(service, repo) == [] and lost
    assert _wake(path)["state"] == "pending" and len(transport.dispatches) == 1

    _pump(service, repo)

    [turn] = _wake_turns(service, sid)
    receipt = _wake(path)
    assert receipt["state"] == "woken" and receipt["turn_id"] == turn["turn_id"]
    # A started Turn is recorded without another dispatch; a still-queued one
    # is handed to the native owner again for the same Turn.
    expected = 1 if started else 2
    assert transport.dispatches == [(sid, turn["turn_id"])] * expected


def test_wake_turn_cancelled_before_it_started_is_not_woken(mode, monkeypatch):  # noqa: F811
    service, sid, repo, transport = _native(mode, monkeypatch, adapter_failures=1)
    path = _write_record(service, session_id=sid)
    _pump(service, repo)
    [queued] = _wake_turns(service, sid)
    service.store.update_turn(sid, queued["turn_id"], status="interrupted",
                              completed_at="2026-09-30T00:00:02Z")
    service.store.update_session(sid, active_turn_id=None, status="ready")

    _pump(service, repo)

    receipt = _wake(path)
    assert receipt["state"] == "refused" and receipt["reason"] == "wake_turn_not_started"
    assert transport.dispatches == []


def test_queued_wake_turn_keeps_the_pause_boundary(mode, monkeypatch):  # noqa: F811
    service, sid, repo, transport = _native(mode, monkeypatch, adapter_failures=1)
    path = _write_record(service, session_id=sid)
    _pump(service, repo)
    session = service.store.load_session(sid)
    service.store.update_session(sid, loopx_mode={**session["loopx_mode"], "paused": True})

    _pump(service, repo)

    assert _wake(path)["state"] == "pending" and _wake(path)["reason"] == "lead_paused"
    assert transport.dispatches == [] and len(transport.adapter_attempts) == 1


def test_wake_never_moves_to_another_conversation_after_exit(mode, monkeypatch):  # noqa: F811
    service, sid, repo, transport = _native(mode, monkeypatch)
    other = _second_lead(service, sid, mode[3])
    session = service.store.load_session(sid)
    service.store.update_session(sid, loopx_mode={**session["loopx_mode"], "enabled": False})
    path = _write_record(service, session_id=sid)

    _pump(service, repo)

    assert _wake(path)["state"] == "refused" and _wake(path)["reason"] == "no_wake_owner"
    assert transport.dispatches == [] and _wake_turns(service, other) == []


def test_closed_origin_conversation_is_refused_without_a_substitute(mode, monkeypatch):  # noqa: F811
    service, sid, repo, transport = _native(mode, monkeypatch)
    other = _second_lead(service, sid, mode[3])
    service.store.update_session(sid, status="closed")
    path = _write_record(service, session_id=sid)

    _pump(service, repo)

    assert _wake(path)["state"] == "refused" and _wake(path)["reason"] == "no_wake_owner"
    assert transport.dispatches == [] and _wake_turns(service, other) == []


def test_lost_receipt_then_new_conversation_cannot_dispatch_twice(mode, monkeypatch):  # noqa: F811
    service, sid, repo, transport = _native(mode, monkeypatch, start_turns=True)
    path = _write_record(service, session_id=sid)
    _fail_next_wake_receipt(monkeypatch)
    _pump(service, repo)
    assert len(transport.dispatches) == 1 and _wake(path)["state"] == "pending"
    [turn] = _wake_turns(service, sid)
    # The original conversation leaves the mode; a new one takes the same identity.
    service.store.update_turn(sid, turn["turn_id"], status="completed",
                              completed_at="2026-09-30T00:00:03Z")
    session = service.store.load_session(sid)
    service.store.update_session(sid, active_turn_id=None, status="ready",
                                 loopx_mode={**session["loopx_mode"], "enabled": False})
    other = _second_lead(service, sid, mode[3])

    _pump(service, repo)

    receipt = _wake(path)
    assert receipt["state"] == "woken" and receipt["session_id"] == sid
    assert receipt["turn_id"] == turn["turn_id"] and receipt["created"] is False
    assert len(transport.dispatches) == 1 and _wake_turns(service, other) == []

def test_the_in_turn_tool_pins_the_conversation_it_runs_in(mode, monkeypatch):  # noqa: F811
    """The model supplies the brief, never the wake routing: the host fixes it."""
    from loopx.collaboration_mcp import Delegations

    pinned = []

    def start(self, binding_id, operation_id, brief, parent_request_id=None, *, conversation=None):
        pinned.append(conversation)
        return {"operation_id": operation_id, "status": "prepared"}

    monkeypatch.setattr(Delegations, "start", start)
    service, sid, _, settings, _ = mode
    apply(mode, "start", settings=settings)
    adapter = type("A", (), {})()
    adapter.session = type("S", (), {})()
    adapter.goal_driver = type("D", (), {
        "turn_start_handler": None, "stopped": __import__("threading").Event()})()
    turn_id = service.store.load_session(sid)["active_turn_id"]
    service.prepare(sid, turn_id, adapter, lambda name, arguments: {"ok": True}, lambda *a, **k: None)

    adapter.session.read_tool_handler("loopx_collaboration", {
        "action": "start", "binding_id": "review", "operation_id": "op-1",
        "brief": {"schema_version": "collaboration_brief_v0"}})

    assert pinned == [{"session_id": sid, "turn_id": turn_id}]
