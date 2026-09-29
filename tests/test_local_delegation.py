"""Production delegation/Turn/TS completion with an explicit fixture model host."""
import json
import asyncio
import os
from pathlib import Path
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from contextlib import contextmanager
from threading import Event, get_ident

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples" / "managed-research-team"))
import research_team as demo  # noqa: E402
from test_managed_research_scenario import fixture  # noqa: E402
from loopx.collaboration_mcp import DelegationFenced, Delegations  # noqa: E402
from loopx.control_plane.collaboration.peers import returns  # noqa: E402
from loopx.control_plane.collaboration.inbox import _read  # noqa: E402
from loopx.file_lock import exclusive_file_lock, try_exclusive_file_lock  # noqa: E402


HOST = '''import json, os, sys, time
from pathlib import Path
from loopx.control_plane.turn_driver.host_candidate import build_result
from loopx.control_plane.collaboration.inbox import acknowledge
from loopx.control_plane.collaboration.peers import return_result
request = json.load(sys.stdin)
workspace = Path.cwd()
root = Path(sys.argv[1])
envelope = request['turn_envelope']
actor = envelope['agent_id']
counter = workspace / 'host-invocations'
counter.write_text(str(int(counter.read_text()) + 1 if counter.exists() else 1))
if (root / 'hold').exists():
    (root / 'host-pid').write_text(str(os.getpid()))
    (root / 'host-started').touch()
    while not (root / 'release').exists(): time.sleep(0.1)
delegation = json.loads((workspace / 'DELEGATION.json').read_text())
if not (root / 'skip-adoption').exists():
    acknowledge(root / 'runtime', envelope['goal_id'], actor, delegation['request_id'], 'adopt', 'Independently checked the requested scope.')
    return_result(root / 'runtime', envelope['goal_id'], actor, delegation['request_id'], 'Independent member conclusion; host acceptance is separate.')
print(json.dumps(build_result(request, {'result_kind':'validated_progress', 'classification':'artifact_written', 'summary':'Fixture host supplied output for independent verification.', 'next_action':'Return verified evidence.'}, host_name='Fixture')))
'''


@pytest.fixture(params=["file", "sqlite"])
def service(tmp_path, request, monkeypatch):
    for name in ("TMPDIR", "TEMP", "TMP"):
        monkeypatch.setenv(name, str(tmp_path))
    root = tmp_path / "team"
    demo.prepare(root, provider=request.param)
    fixture(root)
    host = root / "fixture-host.py"
    host.write_text(HOST)
    config = root / "delegations.json"
    config.write_text(json.dumps({"schema_version": "loopx_local_delegation_v0", "bindings": [{
        "id": "analysis", "agent_id": "analyst", "todo_id": "todo_analyst-initial", "requesters": ["lead"],
        "workspace": str(root / "analyst" / "initial"), "timeout_seconds": 60, "output_refs": ["output.json"],
        "host_args": ["--host", "generic-cli", "--iteration-context", "fresh", "--host-command-json",
                      json.dumps([sys.executable, str(host), str(root)])],
    }]}))
    return root, Delegations(root / "runtime", root / "registry.json", demo.GOAL, "lead", config)


def brief():
    return {"schema_version": "collaboration_brief_v0", "purpose": "Review synthetic cash flow",
            "context": "Use the initial filing and preserve the period distinction.",
            "constraints": ["No external actions"], "inputs": [], "acceptance": ["Pinned task validation"],
            "return_requirement": "Return the independently checked artifact"}


@pytest.mark.parametrize("operation", ["--help", "x y", "x\ny", "x;echo", "x/../y"])
def test_worker_rejects_unbounded_operation_arguments(tmp_path, monkeypatch, operation):
    from loopx import collaboration_mcp as delegation

    runner = Delegations(tmp_path, tmp_path / "registry.json", "goal", "lead", tmp_path / "config.json")
    calls = []
    monkeypatch.setattr(delegation.subprocess, "Popen", lambda *args, **kwargs: calls.append(args))
    with pytest.raises(ValueError, match="stable peer operation id"):
        runner._spawn(operation)
    assert calls == []


def test_delegation_captures_goal_ref_after_registry_becomes_available(tmp_path, monkeypatch):
    from loopx import collaboration_mcp as delegation

    runner = Delegations(
        tmp_path,
        tmp_path / "registry.json",
        "goal",
        "lead",
        tmp_path / "config.json",
    )
    captured = {"goal_id": "goal", "goal_instance_id": "instance-a"}
    calls = []
    monkeypatch.setattr(
        delegation,
        "capture_collaboration_goal_ref",
        lambda *args, **kwargs: calls.append((args, kwargs)) or captured,
    )

    assert runner._caller_goal_ref() == captured
    assert runner._caller_goal_ref() == captured
    assert len(calls) == 1


def test_worker_waits_for_a_transient_status_probe(service, monkeypatch):
    """A reader temporarily holding the lock must not discard admitted work."""
    from loopx import collaboration_mcp as delegation

    _, runner = service
    monkeypatch.setattr(runner, "_spawn", lambda _: None)
    runner.start("analysis", "analysis-1", brief())
    path = runner.path("analysis-1")
    attempted = Event()
    main_thread = get_ident()
    executed = []

    @contextmanager
    def observed_lock(target, **kwargs):
        if target == path and get_ident() != main_thread:
            attempted.set()
        with exclusive_file_lock(target, **kwargs) as held:
            yield held

    monkeypatch.setattr(delegation, "exclusive_file_lock", observed_lock)
    monkeypatch.setattr(runner, "_execute", lambda *args: executed.append("ran"))
    with ThreadPoolExecutor(max_workers=1) as pool:
        with exclusive_file_lock(path):
            future = pool.submit(runner.execute, "analysis-1")
            assert attempted.wait(5)
            with pytest.raises(FutureTimeout):
                future.result(timeout=0.2)
        future.result(timeout=10)
    assert executed == ["ran"]


def wait(service, operation="analysis-1"):
    deadline = time.monotonic() + 100
    while time.monotonic() < deadline:
        result = service.read(operation)
        if result["status"] in {"accepted", "rejected"}:
            return result
        if result.get("error"):
            pytest.fail(str(result))
        time.sleep(0.25)
    pytest.fail(str(service.read(operation)))


def test_detached_result_reconnects_without_duplicate_execution(service):
    root, original = service
    (root / "hold").touch()
    async def disconnect_requester():
        params = StdioServerParameters(command=sys.executable, args=[
            "-m", "loopx.collaboration_mcp", "--registry", str(original.registry),
            "--runtime-root", str(original.root), "--goal-id", original.goal_id,
            "--agent-id", original.agent_id, "--workspace", str(root / "lead"),
            "--execution-config", str(original.config)])
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                inspection = await session.call_tool("inspect_execution_binding", {"binding_id": "analysis"})
                assert not inspection.isError
                preflight = json.loads(inspection.content[0].text)
                assert preflight["state"] == "runtime_unverified"
                assert not any(preflight["effects"].values())
                assert not (root / "host-started").exists()
                inventory = await session.call_tool("list_delegations", {})
                assert not inventory.isError and json.loads(inventory.content[0].text)["items"] == []
                assert "stop_delegation" in {tool.name for tool in (await session.list_tools()).tools}
                result = await session.call_tool("start_delegation", {
                    "binding_id": "analysis", "operation_id": "analysis-1", "brief": brief()})
                assert not result.isError
                inventory = await session.call_tool("list_delegations", {})
                assert not inventory.isError
                assert json.loads(inventory.content[0].text)["items"][0]["operation_id"] == "analysis-1"
                return json.loads(result.content[0].text)
        # Exiting the real stdio session closes the requesting MCP process.
    first = asyncio.run(disconnect_requester())
    deadline = time.monotonic() + 45
    while not (root / "host-started").exists() and time.monotonic() < deadline:
        time.sleep(0.1)
    assert (root / "host-started").exists(), _read(original.path("analysis-1"))
    # Replace the requesting context. The original worker remains independent;
    # retry/resume cannot start another model call while its lock is held.
    reconnected = Delegations(original.root, original.registry, original.goal_id, original.agent_id, original.config)
    assert reconnected.start("analysis", "analysis-1", brief())["request_id"] == first["request_id"]
    reconnected.resume("analysis-1")
    (root / "release").touch()
    result = wait(reconnected)
    assert result["status"] == "accepted", result
    assert (root / "analyst" / "initial" / "host-invocations").read_text() == "1"
    assert not (root / "analyst" / "initial" / "DELEGATION.json").exists()
    assert demo.canonical_tasks(root)["todo_analyst-initial"]["done"]
    returned = returns(original.root, original.goal_id, "lead")["items"]
    assert len(returned) == 1
    assert returned[0]["decision"] == "adopt"
    assert wait(reconnected)["artifacts"] == result["artifacts"]
    # Accepted work cannot be stopped: nothing is written and the receipt repeats exactly.
    noop = reconnected.stop("analysis-1", execute=True)
    assert noop["phase"] == "noop" and noop["status"] == "accepted" and noop["stop"] is None
    assert reconnected.stop("analysis-1", execute=True) == noop
    assert not reconnected._stop_path(reconnected.path("analysis-1")).exists()
    assert wait(reconnected)["artifacts"] == result["artifacts"]
    assert "stop" not in reconnected.read("analysis-1")
    changed_brief = {**brief(), "purpose": "Changed instruction"}
    with pytest.raises(ValueError, match="identity conflict"):
        reconnected.start("analysis", "analysis-1", changed_brief)
    ungranted = Delegations(original.root, original.registry, original.goal_id, "reviewer", original.config)
    original_brief = brief()
    with pytest.raises(Exception, match="no delegation grant"):
        ungranted.start("analysis", "other", original_brief)
    registry = json.loads(original.registry.read_text())
    registry["goals"][0]["status"] = "stopped"
    original.registry.write_text(json.dumps(registry))
    assert reconnected.read("analysis-1")["status"] == "accepted"
    with pytest.raises(ValueError, match="stopped"):
        reconnected.start("analysis", "new-operation", original_brief)
    registry["goals"][0]["status"] = "active"
    original.registry.write_text(json.dumps(registry))
    output = root / "analyst" / "initial" / "output.json"
    output.write_text("{}")
    with pytest.raises(ValueError, match="acceptance rejected"):
        reconnected.read("analysis-1")


def test_host_timeout_removes_private_delegation_bootstrap(service, monkeypatch):
    root, runner = service
    monkeypatch.setattr(runner, "_spawn", lambda _operation_id: None)
    runner.start("analysis", "analysis-timeout", brief())

    def timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired("loopx turn", 1)

    monkeypatch.setattr(runner, "_cli", timeout)
    runner.execute("analysis-timeout")

    workspace = root / "analyst" / "initial"
    assert not (workspace / "DELEGATION.json").exists()
    assert runner.read("analysis-timeout")["error"] == "TimeoutExpired"


def test_model_success_without_receiver_adoption_cannot_complete(service):
    root, runner = service
    (root / "skip-adoption").touch()
    runner.start("analysis", "analysis-1", brief())
    result = wait(runner)
    assert result["status"] == "rejected"
    assert "did not adopt" in result["error"]
    assert not demo.canonical_tasks(root)["todo_analyst-initial"]["done"]


def test_rejected_operation_publishes_reason_with_terminal_state(service, monkeypatch):
    """A reader may stop polling as soon as it sees a terminal observation."""
    root, runner = service
    (root / "skip-adoption").touch()
    monkeypatch.setattr(runner, "_spawn", lambda _: None)
    runner.start("analysis", "analysis-1", brief())
    observe = runner._observe
    terminal_reads = []

    def read_on_publish(path, row, status, **facts):
        observe(path, row, status, **facts)
        if status == "rejected":
            result = runner.read("analysis-1")
            terminal_reads.append(result)
            assert "did not adopt" in result.get("error", "")

    monkeypatch.setattr(runner, "_observe", read_on_publish)
    runner.execute("analysis-1")
    assert len(terminal_reads) == 1
    assert not demo.canonical_tasks(root)["todo_analyst-initial"]["done"]
    assert returns(runner.root, runner.goal_id, "lead")["items"] == []


def until(predicate, timeout=45):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.1)
    return predicate()


def process_gone(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    try:
        return "State:\tZ" in Path(f"/proc/{pid}/status").read_text()
    except OSError:
        return True


def start_held_worker(service, operation="analysis-stop"):
    root, runner = service
    (root / "hold").touch()
    runner.start("analysis", operation, brief())
    assert until(lambda: (root / "host-started").exists()), _read(runner.path(operation))
    return int((root / "host-pid").read_text())


def test_stop_while_executing_is_acknowledged_by_the_worker_and_settles(service, monkeypatch):
    """The detached worker acknowledges SIGTERM under its own lock; time proves nothing."""
    root, runner = service
    host_pid = start_held_worker(service)
    path = runner.path("analysis-stop")
    before = _read(path)
    assert before["status"] == "running" and before["worker"]["pid"] == before["worker"]["pgid"]
    receipt = runner.stop("analysis-stop", execute=True)
    assert receipt["phase"] == "settled" and receipt["status"] == "stopped", receipt
    stop = receipt["stop"]
    assert stop["requested_by"] == "lead" and stop["requested_status"] == "running"
    assert stop["worker"]["pid"] == before["worker"]["pid"]
    assert stop["ack"]["pid"] == before["worker"]["pid"] and stop["ack"]["source"] == "SIGTERM"
    assert stop["ack"]["observed_status"] == "running" and stop["ack"]["turn_key"]
    assert stop["settled"]["operation_lock_free"] and stop["settled"]["lane_lock_free"]
    assert stop["settled"]["turn_journal_status"] == "in_progress"
    assert stop["lease"] == {"required": False, "released": None}
    # The acknowledged record is final: nobody writes it again, the Todo stays open,
    # the host process group is gone and the member's Turn lane can be taken.
    frozen = path.read_bytes()
    assert until(lambda: process_gone(host_pid), timeout=20)
    assert until(lambda: process_gone(before["worker"]["pid"]), timeout=20)
    binding = runner.binding("analysis")
    with try_exclusive_file_lock(runner._lane_target(binding)) as held:
        assert held is not None
    assert not demo.canonical_tasks(root)["todo_analyst-initial"]["done"]
    assert not (root / "analyst" / "initial" / "DELEGATION.json").exists()
    assert path.read_bytes() == frozen
    assert runner.stop("analysis-stop", execute=True) == receipt
    observed = runner.read("analysis-stop")
    assert observed["status"] == "stopped" and not observed["recovery_required"]
    assert observed["stop"] == {"stop_id": stop["stop_id"], "phase": "settled"}
    assert runner.wait("analysis-stop")["status"] == "stopped"
    monkeypatch.setattr(runner, "_spawn", lambda _: pytest.fail("stopped work must not respawn"))
    with pytest.raises(ValueError, match="start a new operation id"):
        runner.resume("analysis-stop")
    assert path.read_bytes() == frozen
    page = runner.operations()
    assert page["page_readback_complete"] and page["items"][0]["status"] == "stopped"
    assert returns(runner.root, runner.goal_id, "lead")["items"] == []


def test_stop_without_a_holder_is_acknowledged_by_the_requester(service, monkeypatch):
    root, runner = service
    monkeypatch.setattr(runner, "_spawn", lambda _: None)
    runner.start("analysis", "analysis-idle", brief())
    receipt = runner.stop("analysis-idle", execute=True)
    assert receipt["phase"] == "settled" and receipt["status"] == "stopped"
    assert receipt["stop"]["worker"] is None and receipt["stop"]["requested_status"] == "prepared"
    assert receipt["stop"]["ack"]["pid"] == os.getpid() and receipt["stop"]["ack"]["source"] == "requester"
    assert receipt["stop"]["settled"]["turn_journal_status"] is None
    frozen = runner.path("analysis-idle").read_bytes()
    with pytest.raises(ValueError, match="start a new operation id"):
        runner.resume("analysis-idle")
    runner.execute("analysis-idle")  # a late worker finds terminal work and launches nothing
    assert runner.path("analysis-idle").read_bytes() == frozen
    assert not (root / "host-started").exists()
    assert runner.stop("analysis-idle", execute=True) == receipt
    with pytest.raises(ValueError, match="requires execute"):
        runner.stop("analysis-idle", execute=False)
    with pytest.raises(ValueError, match="unknown delegation operation"):
        runner.stop("never-started", execute=True)


def test_worker_killed_before_acknowledging_is_unknown_not_settled(service, monkeypatch):
    """A vanished holder never becomes a settlement; the stop still fences resume."""
    import signal

    root, runner = service
    host_pid = start_held_worker(service)
    path = runner.path("analysis-stop")
    worker = _read(path)["worker"]

    def kill_without_grace(target, stop):
        assert stop["worker"]["pgid"] == worker["pgid"] != os.getpgid(0)
        os.killpg(worker["pgid"], signal.SIGKILL)
        assert until(lambda: runner._operation_lock_free(target), timeout=20)

    monkeypatch.setattr(runner, "_signal_worker", kill_without_grace)
    receipt = runner.stop("analysis-stop", execute=True)
    assert receipt["phase"] == "unknown" and receipt["status"] == "running", receipt
    assert receipt["stop"]["ack"] is None and receipt["stop"]["settled"]["operation_lock_free"]
    assert receipt["stop"]["settled"]["turn_journal_status"] == "in_progress"
    assert until(lambda: process_gone(host_pid), timeout=20)
    assert runner.stop("analysis-stop", execute=True) == receipt
    with pytest.raises(ValueError, match="start a new operation id"):
        runner.resume("analysis-stop")
    assert runner.read("analysis-stop")["stop"]["phase"] == "unknown"
    assert not demo.canonical_tasks(root)["todo_analyst-initial"]["done"]


def test_fenced_write_after_another_process_stop_writes_nothing(service, monkeypatch):
    root, runner = service
    monkeypatch.setattr(runner, "_spawn", lambda _: None)
    runner.start("analysis", "analysis-fenced", brief())
    path = runner.path("analysis-fenced")
    row = _read(path)
    foreign = runner._new_stop_record(row, requested_by="other-host-lead", worker=None)
    foreign.update(phase="acknowledged", ack={"pid": 1, "host": "elsewhere", "at": 0.0,
                                              "source": "requester", "observed_status": "running",
                                              "turn_key": None})
    from loopx.control_plane.collaboration.inbox import _write

    _write(runner._stop_path(path), foreign)
    frozen = path.read_bytes()
    with pytest.raises(DelegationFenced):
        runner._fenced_write(path, {**row, "status": "running"})
    with pytest.raises(DelegationFenced):
        runner._observe(path, dict(row), "running")
    with pytest.raises(DelegationFenced):
        runner._record_turn_result(path, {**row, "status": "running"},
                                   {"status": "committed", "result_kind": "validated_progress"})
    runner.execute("analysis-fenced")  # the foreign acknowledgement stands; nothing is rewritten
    assert path.read_bytes() == frozen
    assert _read(runner._stop_path(path)) == foreign
    assert not (root / "host-started").exists()
    assert not demo.canonical_tasks(root)["todo_analyst-initial"]["done"]
    # A stop this process may acknowledge is taken from under the lock at entry.
    runner.start("analysis", "analysis-entry", brief())
    entry = runner.path("analysis-entry")
    _write(runner._stop_path(entry), runner._new_stop_record(_read(entry), requested_by="lead", worker=None))
    runner.execute("analysis-entry")
    assert _read(entry)["status"] == "stopped"
    acknowledged = _read(runner._stop_path(entry))
    assert acknowledged["phase"] == "acknowledged" and acknowledged["ack"]["source"] == "worker_entry"
    assert runner.stop("analysis-entry", execute=True)["phase"] == "settled"
