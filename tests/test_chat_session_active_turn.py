from pathlib import Path

from loopx.chat_store import ChatSessionStore


def test_completed_turn_cannot_release_a_newer_active_turn(tmp_path: Path) -> None:
    store = ChatSessionStore(tmp_path)
    session = store.create_session(
        goal_id="goal-one",
        agent_id="codex",
        executor_endpoint_id="codex",
        adapter_kind="codex_app_server",
        upstream_thread_id="thread-one",
        upstream_mode="chat",
    )
    session_id = str(session["session_id"])
    first, _ = store.create_turn(
        session_id,
        client_turn_id="first-turn",
        message="first",
    )
    store.update_turn(
        session_id,
        str(first["turn_id"]),
        status="completed",
        completed_at="2026-08-23T00:00:00Z",
    )
    second, _ = store.create_turn(
        session_id,
        client_turn_id="second-turn",
        message="second",
    )

    released = store.release_active_turn(
        session_id,
        str(first["turn_id"]),
        last_activity_at="2026-08-23T00:00:01Z",
        last_error_code=None,
    )

    assert released is False
    current = store.load_session(session_id)
    assert current is not None
    assert current["status"] == "busy"
    assert current["active_turn_id"] == second["turn_id"]

    assert store.release_active_turn(
        session_id,
        str(second["turn_id"]),
        last_activity_at="2026-08-23T00:00:02Z",
        last_error_code=None,
    )
    current = store.load_session(session_id)
    assert current is not None
    assert current["status"] == "ready"
    assert current["active_turn_id"] is None
