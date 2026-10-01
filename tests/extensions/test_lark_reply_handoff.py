"""Exact reply context survives the real Chat→inbox→original-return path."""

import json
import runpy
import stat
from pathlib import Path

import pytest

from loopx.capabilities.manager_context import (
    POLICY_SCHEMA, _root, _write, acknowledge, pending,
)
from loopx.capabilities.manager_context.roundtrip import drain, report, reply_status
from loopx.chat_runtime import ChatRuntimeController
from loopx.chat_store import ChatSessionStore
from loopx.extensions.lark.goal_topic_runtime import answer_lark_goal_topic


@pytest.mark.parametrize("context_state", ["available", "truncated", "missing", "wrong_room", "not_a_reply", "thread"])
def test_short_reply_handoff_preserves_source_and_returns_once(
    tmp_path: Path, monkeypatch, context_state: str,
) -> None:
    # Model/provider and portfolio evidence are fixtures; ingress, protocol subprocess,
    # source provenance, request publication, receiver assessment and return run.
    target = {"goal_id": "research", "agent_id": "worker"}
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"goals": [{
        "id": "research", "repo": str(tmp_path),
        "coordination": {"registered_agents": ["worker"]},
    }]}))
    fixture = runpy.run_path(str(Path(__file__).parents[2] / "examples/loopx-chat-runtime-smoke.py"))
    executable = tmp_path / "codex"
    executable.write_text(fixture["FAKE_CODEX"].replace(
        '"message": "Runtime response.",',
        '"message": "Preparing handoff.", "context_handoff": ' + repr(target) + ',',
    ))
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    store = ChatSessionStore(tmp_path)
    controller = ChatRuntimeController(
        store=store, codex_bin=str(executable), registry_path=registry,
        manager_scope_resolver=lambda _session: ["research"],
    )
    monkeypatch.setattr("loopx.chat_manager_context.collect_manager_turn_context",
                        lambda *_args, **_kwargs: {
                            "coverage": {}, "goals": [], "authorization_scope_id": "fixture-research",
                        })
    try:
        session, _ = controller.open_session(
            goal_id="loopx-manager", agent_id="codex", work_dir=tmp_path,
            objective="Inspect the referenced material.", mode="resume_latest",
            channel_id="manager.external.public_fixture",
        )
        _write(_root(tmp_path) / "policy.json", {
            "schema_version": POLICY_SCHEMA,
            "sources": {session["channel_id"]: {"sender_ids": ["owner"], "targets": [target]}},
        })
        parent_text = "Public cash-flow draft: separate cash payments from finance leases."
        quoted = {"message_id": "om_parent", "conversation_id": "room", "content": parent_text}
        if context_state == "truncated":
            quoted["content"] += "x" * 4000
        elif context_state == "wrong_room":
            quoted["conversation_id"] = "other-room"
        route = {
            "goal_id": "loopx-manager", "session_id": session["session_id"],
            "conversation_kind": "manager", "manager_channel_id": session["channel_id"],
            "ingress_mode": "session_queue", "source_sender_id": "owner",
            "message_id": "om_current", "parent_id": "om_parent", "source_conversation_id": "room",
            "topic_root_message_id": "om_topic",
            "reply_context": None if context_state == "missing" else quoted,
            "context_materials": [{"content": "Unrelated recent material must not be forwarded."}],
        }
        if context_state == "not_a_reply":
            route.pop("parent_id")
        if context_state == "thread":
            route.pop("parent_id")
            route.update(root_id="om_root", thread_id="thread", thread_context={
                "root_message_id": "om_root", "conversation_id": "room", "thread_id": "thread",
                "messages": [{"message_id": mid, "position": pos, "content": content,
                              "conversation_id": "room", "thread_id": "thread"}
                             for mid, pos, content in [
                                 ("om_root", -1, "Review version 1."),
                                 ("om_revision", 0, "Version 3 is ready; publication still separate."),
                                 ("om_current", 1, "Approved."),
                             ]],
            })
        options = dict(route=route, text="Ask the researcher to check this.",
                       work_dir=tmp_path, objective="Inspect the draft.", runtime_controller=controller)
        answer = answer_lark_goal_topic(**options)
        assert "worker" in answer
        entry, = pending(tmp_path, **target)["items"]
        forwarded = entry["message"]
        if context_state == "not_a_reply":
            assert forwarded == "Ask the researcher to check this."
        elif context_state == "thread":
            assert "Earlier messages in this same thread" in forwarded
            assert "Version 3" in forwarded
            assert "not an exact reply target" in forwarded
        else:
            assert "Referenced message" in forwarded
        assert forwarded.endswith("Ask the researcher to check this.")
        assert "Unrelated recent material" not in forwarded
        assert "context_handoff" not in forwarded  # Provider's operating prompt is not source context.
        if context_state in {"available", "truncated"}:
            assert parent_text in forwarded
            source = json.loads(forwarded.splitlines()[1])
            assert source["complete"] is (context_state == "available")
            assert len(source["content"]) <= 4000
        elif context_state not in {"not_a_reply", "thread"}:
            assert parent_text not in forwarded
            assert "referent remains unknown" in forwarded
        assert entry["source_id"] == "lark:om_current"
        # Replayed ingress neither republishes the request nor starts a second Turn.
        assert answer_lark_goal_topic(**options) == answer
        assert len(pending(tmp_path, **target)["items"]) == 1
        turn_files = list((store.root / "sessions" / session["session_id"] / "turns").glob("*.json"))
        assert len(turn_files) == 1
        turn = json.loads(turn_files[0].read_text())
        receipt = turn["response"]["context_handoff_receipt"]
        acknowledge(tmp_path, **target, request_id=entry["request_id"], decision="adopt",
                    reason="Assess the exact quote without granting new effects.")
        report(tmp_path, "research", "worker", entry["request_id"], "conclusion",
               "Checked the referenced draft; missing source remains unknown. No publication performed.")
        sends = []

        def sender(original, returned_session, returned_turn, text):
            assert original["source_id"] == "lark:om_current"
            assert returned_session["session_id"] == session["session_id"]
            assert returned_turn["turn_id"] == turn["turn_id"]
            sends.append(text)
            return {"ok": True, "reply_verified": True}

        for _ in range(2):
            drain(tmp_path, registry, ChatSessionStore(tmp_path), sender)
        assert len(sends) == 1
        assert reply_status(tmp_path, receipt)[0]["status"] == "delivered"
        returned = [row for row in store.messages(session["session_id"])
                    if row.get("origin") == "manager_followup"]
        assert len(returned) == 1 and "Checked the referenced draft" in returned[0]["text"]
    finally:
        controller.close()
