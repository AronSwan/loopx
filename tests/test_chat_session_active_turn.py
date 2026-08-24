from pathlib import Path
import threading
import time

import loopx.chat_store as chat_store
from loopx.chat_store import ChatSessionStore


def test_concurrent_managed_turn_creation_claims_active_once(
    tmp_path: Path,
    monkeypatch,
) -> None:
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
    original_atomic_write = chat_store._atomic_write_json
    turn_write_threads: set[str] = set()
    condition = threading.Condition()

    def slow_new_turn_write(
        path: Path,
        payload: dict[str, object],
        *,
        preserve_mode: bool = False,
    ) -> None:
        is_new_turn_file = (
            path.parent.name == "turns"
            and path.name.endswith(".json")
            and not path.name.endswith(".events.json")
            and not preserve_mode
        )
        if is_new_turn_file and threading.current_thread().name.startswith("creator-"):
            with condition:
                turn_write_threads.add(threading.current_thread().name)
                condition.notify_all()
                deadline = time.monotonic() + 0.25
                while len(turn_write_threads) < 2 and time.monotonic() < deadline:
                    condition.wait(timeout=deadline - time.monotonic())
        original_atomic_write(path, payload, preserve_mode=preserve_mode)

    monkeypatch.setattr(chat_store, "_atomic_write_json", slow_new_turn_write)
    results: list[tuple[str, str, bool]] = []
    errors: list[str] = []

    def create(client_turn_id: str) -> None:
        try:
            turn, created = store.create_turn(
                session_id,
                client_turn_id=client_turn_id,
                message=f"message from {client_turn_id}",
            )
            results.append((client_turn_id, str(turn["turn_id"]), created))
        except RuntimeError as exc:
            errors.append(str(exc))

    threads = [
        threading.Thread(
            target=create,
            args=(f"client-{index}",),
            name=f"creator-{index}",
        )
        for index in (1, 2)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=3)

    assert not any(thread.is_alive() for thread in threads)
    assert len(results) == 1
    assert len(errors) == 1
    active_turn_id = results[0][1]
    assert errors == [active_turn_id]
    assert len(turn_write_threads) == 1
    assert [
        item["text"] for item in store.messages(session_id) if item["role"] == "user"
    ] == [f"message from {results[0][0]}"]
    current = store.load_session(session_id)
    assert current is not None
    assert current["status"] == "busy"
    assert current["active_turn_id"] == active_turn_id


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
