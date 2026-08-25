from collections.abc import Callable
from pathlib import Path
import threading
import time

import loopx.chat_store as chat_store
from loopx.chat_store import ChatSessionStore, SESSION_QUEUE_MAX_PENDING


def _slow_new_turn_writes(monkeypatch) -> set[str]:
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
    return turn_write_threads


def _run_two_client_turn_creators(
    create_turn: Callable[[str], tuple[dict[str, object], bool]],
) -> tuple[list[tuple[str, str, bool]], list[str]]:
    results: list[tuple[str, str, bool]] = []
    errors: list[str] = []

    def create(client_turn_id: str) -> None:
        try:
            turn, created = create_turn(client_turn_id)
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
    return results, errors


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
    turn_write_threads = _slow_new_turn_writes(monkeypatch)
    results, errors = _run_two_client_turn_creators(
        lambda client_turn_id: store.create_turn(
            session_id,
            client_turn_id=client_turn_id,
            message=f"message from {client_turn_id}",
        )
    )

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


def test_concurrent_queued_turn_creation_is_atomic(
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
    for index in range(SESSION_QUEUE_MAX_PENDING - 1):
        queued, created = store.create_queued_turn(
            session_id,
            client_turn_id=f"prefill-{index}",
            message=f"prefill message {index}",
        )
        assert created
        assert queued["status"] == "queued"
    turn_write_threads = _slow_new_turn_writes(monkeypatch)
    results, errors = _run_two_client_turn_creators(
        lambda client_turn_id: store.create_queued_turn(
            session_id,
            client_turn_id=client_turn_id,
            message=f"message from {client_turn_id}",
        )
    )

    assert len(results) == 1
    assert len(errors) == 1
    assert errors == ["session_queue_full"]
    assert len(turn_write_threads) == 1
    assert [
        item["text"] for item in store.messages(session_id) if item["role"] == "user"
    ][-2:] == [f"prefill message {SESSION_QUEUE_MAX_PENDING - 2}", f"message from {results[0][0]}"]
    current = store.load_session(session_id)
    assert current is not None
    assert current["status"] == "ready"
    assert current["active_turn_id"] is None


def test_concurrent_queued_turn_creation_is_idempotent(
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
    turn_write_threads = _slow_new_turn_writes(monkeypatch)
    results: list[tuple[str, str, bool]] = []

    def create() -> None:
        turn, created = store.create_queued_turn(
            session_id,
            client_turn_id="shared-client",
            message="same message",
        )
        results.append((str(turn["turn_id"]), created))

    threads = [
        threading.Thread(target=create, name=f"creator-{index}")
        for index in (1, 2)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=3)

    assert not any(thread.is_alive() for thread in threads)
    assert len(results) == 2
    assert {created for _turn_id, created in results} == {True, False}
    assert len({turn_id for turn_id, _created in results}) == 1
    assert len(turn_write_threads) == 1
    assert [
        item["text"] for item in store.messages(session_id) if item["role"] == "user"
    ] == ["same message"]
    current = store.load_session(session_id)
    assert current is not None
    assert current["status"] == "ready"
    assert current["active_turn_id"] is None


def test_queued_turn_rejects_closed_session(tmp_path: Path) -> None:
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
    store.update_session(session_id, status="closed", active_turn_id=None)

    try:
        store.create_queued_turn(
            session_id,
            client_turn_id="closed-session",
            message="should not queue",
        )
    except KeyError as exc:
        assert str(exc) == "'chat session was not found'"
    else:  # pragma: no cover - safety net for unexpected passes.
        raise AssertionError("closed session should not accept queued turns")
