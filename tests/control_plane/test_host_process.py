"""Real managed Host boundaries: no paid model, no external side effects."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from loopx.control_plane.turn_driver.executor import _run_host
from loopx.control_plane.turn_driver.host_process_transport import (
    HostOutputLines,
    run_host_process,
)


def test_host_output_lines_bound_storage_and_use_lf() -> None:
    rows: list[str] = []
    lines = HostOutputLines(rows.append, max_chars=20)
    lines.feed("one\u2028two\n" + "x" * 100)
    assert lines.pending == ""
    lines.feed("tail\nlast")
    lines.finish()
    assert rows == ["one\u2028two", "last"]
    assert not lines.complete


def test_real_generic_host_roundtrip_and_stream_budget(tmp_path: Path) -> None:
    request = {"message": "one private local request"}
    result = _run_host(
        request,
        argv=[
            sys.executable,
            "-c",
            "import sys,json;print(json.dumps(json.load(sys.stdin)))",
        ],
        project=tmp_path,
        timeout_seconds=5,
    )
    assert result == {"ok": True, "value": request, "returncode": 0}
    overflow = _run_host(
        request,
        argv=[
            sys.executable,
            "-c",
            "import sys,time;sys.stdout.write('x'*1000000);sys.stdout.flush();time.sleep(30)",
        ],
        project=tmp_path,
        timeout_seconds=5,
    )
    assert overflow["ok"] is False
    assert overflow["reason"] == "host stdout exceeded the result budget"


def test_callback_failure_waits_for_owned_host_cleanup(tmp_path: Path) -> None:
    def reject(_text: str) -> None:
        raise ValueError("consumer stopped")

    started = time.monotonic()
    with pytest.raises(ValueError, match="consumer stopped"):
        run_host_process(
            [
                sys.executable,
                "-c",
                "import time;print('ready',flush=True);time.sleep(30)",
            ],
            project=tmp_path,
            input_text="",
            timeout_seconds=20,
            on_stdout=reject,
        )
    assert time.monotonic() - started < 8


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group cancellation contract")
def test_disappearing_python_owner_cancels_real_host(tmp_path: Path) -> None:
    marker = tmp_path / "counter"
    pid_path = tmp_path / "pid"
    host = f"""
import os,time,signal
from pathlib import Path
signal.signal(signal.SIGTERM, signal.SIG_IGN)
Path({str(pid_path)!r}).write_text(str(os.getpid()))
i=0
while True:
 Path({str(marker)!r}).write_text(str(i));i+=1;time.sleep(.02)
"""
    launcher = f"""
from pathlib import Path
from loopx.control_plane.turn_driver.host_process_transport import run_host_process
run_host_process({[sys.executable, "-c", host]!r}, project=Path({str(tmp_path)!r}), input_text='', timeout_seconds=30)
"""
    owner = subprocess.Popen(
        [sys.executable, "-c", launcher],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 10
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert marker.exists(), "Host never started"
        owner.kill()
        owner.wait(timeout=5)
        time.sleep(1)
        before = marker.read_text()
        time.sleep(0.15)
        assert marker.read_text() == before, "Host survived loss of its owner"
    finally:
        if owner.poll() is None:
            owner.kill()
            owner.wait(timeout=5)
        if pid_path.exists():
            try:
                os.kill(int(pid_path.read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group cancellation contract")
def test_generic_host_timeout_stops_real_descendant(tmp_path: Path) -> None:
    marker = tmp_path / "child-work"
    pid_path = tmp_path / "child-pid"
    child = f"""
import os,time,signal
from pathlib import Path
signal.signal(signal.SIGTERM, signal.SIG_IGN)
Path({str(pid_path)!r}).write_text(str(os.getpid()))
i=0
while True:
 Path({str(marker)!r}).write_text(str(i));i+=1;time.sleep(.02)
"""
    host = f"import subprocess,sys,time;subprocess.Popen({[sys.executable, '-c', child]!r});time.sleep(30)"
    try:
        result = _run_host(
            {}, argv=[sys.executable, "-c", host], project=tmp_path, timeout_seconds=1
        )
        assert result["ok"] is False
        assert result["reason"] == "host process timeout"
        before = marker.read_text()
        time.sleep(0.15)
        assert marker.read_text() == before
    finally:
        if pid_path.exists():
            try:
                os.kill(int(pid_path.read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass


def test_windows_transport_relay_preserves_argv_and_stdin(tmp_path: Path) -> None:
    from loopx.control_plane.turn_driver.host_process_transport import _WINDOWS_COMMAND_RELAY

    # The relay is tested here on any OS; real .cmd resolution remains a Windows
    # integration obligation. All args stay argv entries, not interpolated code.
    values = ["two words", "a&b", "%NAME%", 'one"quote', "界"]
    result = _run_host(
        {},
        argv=[
            sys.executable,
            "-c",
            _WINDOWS_COMMAND_RELAY,
            sys.executable,
            "-c",
            "import json,sys;print(json.dumps({'args':sys.argv[1:],'input':json.load(sys.stdin)}))",
            *values,
        ],
        project=tmp_path,
        timeout_seconds=5,
    )
    assert result["ok"] is True
    assert result["value"] == {"args": values, "input": {}}


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group drain readback")
def test_host_process_record_names_the_owned_group_and_is_not_inherited(tmp_path: Path, monkeypatch) -> None:
    from loopx.control_plane.turn_driver.host_process_transport import (
        HOST_PROCESS_RECORD_ENV, host_process_drain,
    )

    record_path = tmp_path / "op.host.json"
    assert host_process_drain(record_path) == "not_launched"
    monkeypatch.setenv(HOST_PROCESS_RECORD_ENV, str(record_path))
    host = ("import json,os,sys;print(json.dumps({'env': os.environ.get(%r), 'pid': os.getpid(),"
            " 'pgid': os.getpgid(0)}))" % HOST_PROCESS_RECORD_ENV)
    result = _run_host({}, argv=[sys.executable, "-c", host], project=tmp_path, timeout_seconds=5)
    assert result["ok"] is True
    # A nested LoopX run inside the Host cannot overwrite its parent's record.
    assert result["value"]["env"] is None
    record = json.loads(record_path.read_text())
    assert record["phase"] == "finished"
    assert record["host_pid"] == result["value"]["pid"] == record["process_group"] == result["value"]["pgid"]
    assert host_process_drain(record_path) == "drained"


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group drain readback")
def test_host_process_drain_reads_live_groups_and_refuses_unattributable_records(tmp_path: Path) -> None:
    from loopx.control_plane.turn_driver.host_process_transport import (
        HOST_PROCESS_RECORD_SCHEMA_VERSION, host_process_drain,
    )
    from loopx.file_lock import lock_holder_host_label

    path = tmp_path / "op.host.json"
    live = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(60)"], start_new_session=True)
    gone = subprocess.Popen([sys.executable, "-c", "pass"], start_new_session=True)
    gone.wait(timeout=10)

    def drain(**fields):
        path.write_text(json.dumps({"schema_version": HOST_PROCESS_RECORD_SCHEMA_VERSION,
                                    "host": lock_holder_host_label(), "owner_pid": 1, **fields}))
        return host_process_drain(path)

    try:
        # A live supervisor or a live Host group is still draining.
        assert drain(phase="launching", bridge_pid=live.pid, process_group=None) == "draining"
        assert drain(phase="spawned", bridge_pid=gone.pid, process_group=live.pid) == "draining"
        assert drain(phase="finished", bridge_pid=gone.pid, process_group=live.pid) == "draining"
        assert drain(phase="spawned", bridge_pid=gone.pid, process_group=gone.pid) == "drained"
        # A supervisor gone before it reported a group may have spawned one anyway.
        assert drain(phase="launching", bridge_pid=gone.pid, process_group=None) == "unattributable"
        assert drain(phase="finished", bridge_pid=gone.pid, process_group=None) == "drained"
        for fields in ({"phase": "spawned", "bridge_pid": None, "process_group": gone.pid},
                       {"phase": "spawned", "bridge_pid": gone.pid, "process_group": "1"},
                       {"phase": "spawned", "bridge_pid": gone.pid, "process_group": 1},
                       {"phase": "spawned", "bridge_pid": gone.pid, "process_group": gone.pid,
                        "host": "another-machine"},
                       {"phase": "spawned", "bridge_pid": gone.pid, "process_group": gone.pid,
                        "schema_version": "other"}):
            assert drain(**fields) == "unattributable", fields
        path.write_text("{not json")
        assert host_process_drain(path) == "unattributable"
    finally:
        live.kill()
        live.wait(timeout=10)
