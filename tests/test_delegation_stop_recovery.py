"""Stop ordering against native completion of a validated, unsettled Turn."""

import sys
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from contextlib import contextmanager
from threading import Event, get_ident

import pytest

from test_local_delegation import brief, demo, service as service
from loopx import collaboration_mcp as delegation
from loopx.control_plane.collaboration.inbox import _read
from loopx.control_plane.collaboration.peers import returns
from loopx.file_lock import exclusive_file_lock


def recoverable_boundary(service, monkeypatch):
    root, runner = service
    # The Host adopts and supplies an artifact, but only delegation publishes
    # the result. Keep that effect independently observable in this fixture.
    host = root / "fixture-host.py"
    host.write_text("\n".join(line for line in host.read_text().splitlines()
                              if not line.startswith("    return_result(")))
    monkeypatch.setattr(runner, "_spawn", lambda _: None)
    runner.start("analysis", "analysis-recovery", brief())
    module_command = delegation._python_module_command
    # Exit the real native CLI after its validated checkpoint is persisted,
    # before any settlement callback runs. Host output and task validation are
    # real; completion, settlement and authority are never replaced.
    interruption = """
import os, runpy
from loopx.control_plane.turn_driver import executor
persist = executor._write_journal
def checkpoint(path, snapshot, **kwargs):
    persist(path, snapshot, **kwargs)
    if snapshot.get('completed_phases') == ['host_execute', 'typed_result', 'validation']:
        os._exit(86)
executor._write_journal = checkpoint
runpy.run_module('loopx.cli', run_name='__main__')
"""
    with monkeypatch.context() as setup:
        setup.setattr(delegation, "_python_module_command", lambda module:
                      [sys.executable, "-c", interruption] if module == "loopx.cli"
                      else module_command(module))
        runner.execute("analysis-recovery")
    path = runner.path("analysis-recovery")
    row = _read(path)
    assert row["status"] == "running" and row.get("error")
    # The interrupted CLI did not return an accepted result. Record that
    # observation through the owner, then use public same-operation resume;
    # the typed recovery transition accepts only a rejected observation.
    runner._observe(path, row, "rejected")
    assert runner.resume("analysis-recovery")["status"] == "turn_returned"
    row = _read(path)
    journal = runner._validated_turn_journal(row, runner.binding("analysis"))
    assert journal["task_validation"]["ok"] is True
    assert journal["host_result"]["result_kind"] == "validated_progress"
    assert not demo.canonical_tasks(root)["todo_analyst-initial"]["done"]
    assert returns(runner.root, runner.goal_id, "lead")["items"] == []
    # The test process owns the operation; it must never signal its own group.
    monkeypatch.setattr(runner, "_signal_worker", lambda *_: None)
    return root, runner


def test_stop_wins_before_recovered_completion(service, monkeypatch):
    root, runner = recoverable_boundary(service, monkeypatch)
    validated = runner._validated_turn_journal
    receipts = []

    def stop_after_validation(row, binding):
        journal = validated(row, binding)
        assert journal is not None
        receipts.append(runner.stop("analysis-recovery", execute=True))
        return journal

    monkeypatch.setattr(runner, "_validated_turn_journal", stop_after_validation)
    runner.execute("analysis-recovery")
    assert len(receipts) == 1 and receipts[0]["phase"] == "requested"
    receipt = runner.stop("analysis-recovery", execute=True)
    assert receipt["phase"] == "settled" and receipt["status"] == "stopped"
    assert not demo.canonical_tasks(root)["todo_analyst-initial"]["done"]
    assert returns(runner.root, runner.goal_id, "lead")["items"] == []
    assert (root / "analyst" / "initial" / "host-invocations").read_text() == "1"
    with pytest.raises(ValueError, match="start a new operation id"):
        runner.resume("analysis-recovery")


def test_recovered_completion_wins_over_a_concurrent_stop(service, monkeypatch):
    root, runner = recoverable_boundary(service, monkeypatch)
    complete = runner._complete_delegated_todo
    main_thread = get_ident()
    attempted = Event()
    dispatch = runner._dispatch_lock(runner.path("analysis-recovery"))
    futures = []

    @contextmanager
    def observed_lock(target, **kwargs):
        if target == dispatch and get_ident() != main_thread:
            attempted.set()
            kwargs["timeout_seconds"] = 30
        with exclusive_file_lock(target, **kwargs) as held:
            yield held

    monkeypatch.setattr(delegation, "exclusive_file_lock", observed_lock)
    with ThreadPoolExecutor(max_workers=1) as pool:
        def concurrent_stop(row, binding):
            future = pool.submit(runner.stop, "analysis-recovery", execute=True)
            futures.append(future)
            assert attempted.wait(10)
            # Give stop the chance to persist if completion has no fence.
            # Do not assert the lock implementation: run native completion and
            # judge the final canonical state and public receipt instead.
            try:
                future.result(timeout=0.3)
            except FutureTimeout:
                pass
            complete(row, binding)

        monkeypatch.setattr(runner, "_complete_delegated_todo", concurrent_stop)
        runner.execute("analysis-recovery")
        assert len(futures) == 1
        receipt = futures[0].result(timeout=30)
    receipt = runner.stop("analysis-recovery", execute=True)
    assert demo.canonical_tasks(root)["todo_analyst-initial"]["done"]
    assert receipt["phase"] == "noop" and receipt["status"] == "accepted", receipt
    assert runner.read("analysis-recovery")["status"] == "accepted"
    assert len(returns(runner.root, runner.goal_id, "lead")["items"]) == 1
    assert not runner._stop_path(runner.path("analysis-recovery")).exists()
    assert (root / "analyst" / "initial" / "host-invocations").read_text() == "1"
