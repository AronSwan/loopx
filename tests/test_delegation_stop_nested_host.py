"""Hard-lease stop must account for the real nested Host before safe handoff."""
from __future__ import annotations

# Imported fixtures are parameterized over real File and SQLite authorities.
# ruff: noqa: F811
import os
import signal

import pytest

from test_local_delegation import HOST, process_gone, service, until  # noqa: F401
from test_delegation_lease_lifetime import inspect, prepare_lease
from loopx.collaboration_mcp import Delegations
from loopx.control_plane.collaboration.inbox import _read
from loopx.control_plane.collaboration.peers import returns


@pytest.mark.skipif(os.name == "nt", reason="POSIX nested supervisor interruption")
@pytest.mark.parametrize("pause_supervisor", [False, True])
def test_stop_waits_for_actual_nested_host_before_releasing_lease(service, monkeypatch, pause_supervisor):
    root, runner = service
    operation = "nested-stop"
    with monkeypatch.context() as setup:
        original = prepare_lease(root, runner, setup, operation_id=operation, renew=False)
    # Identify the actual supervisor from its child, independently of the
    # implementation's recorded process attribution.
    host = HOST.replace("counter = workspace / 'host-invocations'", """
(root / 'supervisor-pid').write_text(str(os.getppid()))
(root / 'host-record-env').write_text(str(os.environ.get('LOOPX_HOST_PROCESS_RECORD')))
counter = workspace / 'host-invocations'""")
    (root / "fixture-host.py").write_text(host)
    (root / "hold").touch()
    (root / "ignore-term").touch()
    runner._spawn(operation)
    host_pid = child_pid = supervisor = None
    try:
        assert until(lambda: (root / "host-started").exists()), _read(runner.path(operation))
        host_pid = int((root / "host-pid").read_text())
        child_pid = int((root / "host-child-pid").read_text())
        supervisor = int((root / "supervisor-pid").read_text())
        assert not process_gone(host_pid) and not process_gone(child_pid)
        assert (root / "host-record-env").read_text() == "None"
        if pause_supervisor:
            os.kill(supervisor, signal.SIGSTOP)
        receipt = runner.stop(operation, execute=True)
        if pause_supervisor:
            assert receipt["phase"] == "acknowledged", receipt
            assert receipt["reason"] == "host_process_still_running", receipt
            assert not process_gone(host_pid) and not process_gone(child_pid)
            lease = inspect(runner)
            assert lease["active"] and lease["lease"]["idempotency_key"] == original["idempotency_key"]
            # A fresh requester must preserve the same receipt and lease while
            # the unavailable supervisor leaves actual execution alive.
            fresh = Delegations(runner.root, runner.registry, runner.goal_id, runner.agent_id, runner.config)
            repeated = fresh.stop(operation, execute=True)
            assert repeated["phase"] == "acknowledged"
            assert repeated["stop"]["stop_id"] == receipt["stop"]["stop_id"]
            assert inspect(runner)["active"]
            # Cleanup only the independently identified fixture group. The
            # product readback must observe this, never signal unrelated groups.
            os.killpg(host_pid, signal.SIGKILL)
            assert until(lambda: process_gone(host_pid) and process_gone(child_pid))
            receipt = fresh.stop(operation, execute=True)
        assert receipt["phase"] == "settled", receipt
        assert process_gone(host_pid) and process_gone(child_pid), receipt
        assert inspect(runner)["lease"]["status"] == "released"
        assert runner.stop(operation, execute=True) == receipt
        assert runner.read(operation)["stop"]["phase"] == "settled"
        with pytest.raises(ValueError, match="start a new operation id"):
            runner.resume(operation)
        assert (root / "analyst" / "initial" / "host-invocations").read_text() == "1"
        assert returns(runner.root, runner.goal_id, "lead")["items"] == []
        assert runner.operations()["page_readback_complete"]
    finally:
        for pid, group in ((host_pid, True), (supervisor, False)):
            if pid is not None:
                try:
                    os.killpg(pid, signal.SIGKILL) if group else os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group attribution")
@pytest.mark.parametrize("legacy_record", [True, False])
def test_missing_or_unreadable_nested_attribution_cannot_release_a_lease(service, monkeypatch, legacy_record):
    """Outer-only historical evidence or a corrupt inner record is not drain."""
    import json
    import subprocess

    from loopx.control_plane.turn_driver.host_process_transport import HOST_PROCESS_RECORD_SCHEMA_VERSION
    from loopx.file_lock import lock_holder_host_label

    root, runner = service
    operation = "unproven-nested-stop"
    prepare_lease(root, runner, monkeypatch, operation_id=operation, renew=False)
    dead = subprocess.Popen(["true"])
    dead.wait(timeout=5)
    record = runner._host_process_record(runner.path(operation))
    outer = {"schema_version": HOST_PROCESS_RECORD_SCHEMA_VERSION,
             "host": lock_holder_host_label(), "phase": "finished",
             "bridge_pid": dead.pid, "process_group": dead.pid}
    if legacy_record:
        record.write_text(json.dumps(outer))
    else:
        record.with_suffix(".cli.host.json").write_text(json.dumps(outer))
        record.write_text("{corrupt nested attribution")
    evidence = record.read_bytes()
    stopped = runner.stop(operation, execute=True)
    assert stopped["phase"] == "acknowledged"
    assert stopped["reason"] == "host_process_drain_unproven"
    assert inspect(runner)["active"]
    assert record.read_bytes() == evidence
