"""Python transport for the TS-owned managed Host process lifecycle."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from ...file_lock import lock_holder_host_label
from ..effect_runtime import _node_executable

# Keep Python's Windows executable/batch launcher compatibility. No timeout,
# buffering or lifecycle decision lives in this transport-only child.
_WINDOWS_COMMAND_RELAY = "import subprocess,sys;sys.exit(subprocess.call(sys.argv[1:]))"


# A launching owner that must later prove its Host drained names a record path
# here. The transport consumes it: the Host never inherits it, so a nested
# LoopX run inside the Host cannot overwrite its parent's record.
HOST_PROCESS_RECORD_ENV = "LOOPX_HOST_PROCESS_RECORD"
HOST_PROCESS_RECORD_SCHEMA_VERSION = "loopx_host_process_record_v0"
# Drain facts read back from a record; the caller's typed decision interprets them.
HOST_PROCESS_NOT_LAUNCHED = "not_launched"
HOST_PROCESS_DRAINED = "drained"
HOST_PROCESS_DRAINING = "draining"
HOST_PROCESS_UNATTRIBUTABLE = "unattributable"
HOST_PROCESS_UNSUPPORTED_PLATFORM = "unsupported_platform"


def host_process_drain_supported() -> bool:
    """Whether this platform can prove an owned Host group has exited.

    The TS supervisor cleans up a process group on POSIX and a process tree
    best-effort on Windows. Only the group gives the stop a fact it can prove,
    so the caller must say so rather than reporting a settlement it cannot
    support.
    """

    return hasattr(os, "killpg")


def _write_host_process_record(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(record, handle, separators=(",", ":"))
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _process_group_present(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # it exists; it is simply not ours to signal
    return True


def host_process_drain(record_path: Path) -> str:
    """Read whether the Host a record names, and its process group, have exited.

    Read-only: nothing is signalled, and the TS-owned supervisor keeps cleanup.
    No record means no Host was launched under it. ``draining`` while the
    supervising bridge or the Host's group still has a member. A record from
    another machine, one without a reported group whose supervisor is gone,
    or a platform without process groups proves nothing: ``unattributable``.
    """

    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return HOST_PROCESS_NOT_LAUNCHED
    except (OSError, ValueError):
        return HOST_PROCESS_UNATTRIBUTABLE
    if (not isinstance(record, dict) or record.get("schema_version") != HOST_PROCESS_RECORD_SCHEMA_VERSION
            or record.get("host") != lock_holder_host_label()):
        return HOST_PROCESS_UNATTRIBUTABLE
    if not hasattr(os, "killpg"):
        # A launched Host on a platform without process groups is never proven
        # drained. This is a platform boundary, not an attribution failure.
        return HOST_PROCESS_UNSUPPORTED_PLATFORM
    bridge, group = record.get("bridge_pid"), record.get("process_group")
    if record.get("phase") != "finished":
        if not isinstance(bridge, int) or bridge <= 1:
            return HOST_PROCESS_UNATTRIBUTABLE
        if _process_group_present(bridge):  # the bridge leads its own session
            return HOST_PROCESS_DRAINING
    if group is None:
        # The supervisor left before reporting a group it may already have spawned.
        return HOST_PROCESS_UNATTRIBUTABLE if record.get("phase") == "launching" else HOST_PROCESS_DRAINED
    if not isinstance(group, int) or group <= 1:
        return HOST_PROCESS_UNATTRIBUTABLE
    return HOST_PROCESS_DRAINING if _process_group_present(group) else HOST_PROCESS_DRAINED


class HostOutputLines:
    """Frame LF records without retaining raw trajectories or an unbounded line."""

    def __init__(self, consume: Callable[[str], None], max_chars: int = 1_048_576):
        self.consume = consume
        self.max_chars = max_chars
        self.pending = ""
        self.dropping = False
        self.complete = True

    def feed(self, text: str) -> None:
        pieces = text.split("\n")
        for index, piece in enumerate(pieces):
            if not self.dropping:
                if len(self.pending) + len(piece) > self.max_chars:
                    self.complete = False
                    self.pending = ""
                    self.dropping = True
                else:
                    self.pending += piece
            if index < len(pieces) - 1:
                if not self.dropping:
                    self.consume(self.pending)
                self.pending = ""
                self.dropping = False

    def finish(self) -> None:
        if self.pending and not self.dropping:
            self.consume(self.pending)
        self.pending = ""


def run_host_process(
    argv: Sequence[str],
    *,
    project: Path,
    input_text: str,
    timeout_seconds: float,
    stdout_limit_bytes: int | None = None,
    drain_timeout_seconds: float = 2,
    on_stdout: Callable[[str], None] | None = None,
    on_stderr: Callable[[str], None] | None = None,
    delegated_lease: dict[str, Any] | None = None,
    environment: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Keep the control pipe open until exit; EOF cancels the owned process group.

    Callbacks observe transient chunks. They must not persist raw Host output.
    TS owns deadlines, byte budgets, termination and the final observation.
    """
    command = list(argv)
    if sys.platform == "win32":
        command = [sys.executable, "-c", _WINDOWS_COMMAND_RELAY, *command]
    request = {
        "argv": command,
        "cwd": str(project),
        "input": input_text,
        "timeout_ms": max(1.0, timeout_seconds) * 1000,
        "drain_timeout_ms": drain_timeout_seconds * 1000,
        "stdout_limit_bytes": stdout_limit_bytes,
    }
    if delegated_lease is not None:
        request["delegated_lease"] = delegated_lease
    bridge = Path(__file__).with_name("host_process_bridge.ts")
    environment = os.environ.copy()
    record_value = environment.pop(HOST_PROCESS_RECORD_ENV, "")
    record_path = Path(record_value) if record_value else None
    with subprocess.Popen(
        [
            _node_executable(),
            "--no-warnings",
            "--experimental-strip-types",
            str(bridge),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="strict",
        start_new_session=True,
        env=environment,
    ) as proc:
        assert proc.stdin is not None and proc.stdout is not None
        result = None
        record = None
        try:
            if record_path is not None:
                # Written before the request, so no Host exists that the record
                # does not name; a record that cannot be written launches nothing.
                record = {"schema_version": HOST_PROCESS_RECORD_SCHEMA_VERSION,
                          "host": lock_holder_host_label(), "owner_pid": os.getpid(),
                          "bridge_pid": proc.pid, "phase": "launching", "process_group": None}
                _write_host_process_record(record_path, record)
            proc.stdin.write(
                json.dumps(request, ensure_ascii=False, separators=(",", ":")) + "\n"
            )
            proc.stdin.flush()
            for line in proc.stdout:
                event = json.loads(line)
                kind = event.get("kind")
                if kind == "spawned" and isinstance(event.get("pid"), int):
                    if record is not None:
                        group = event.get("process_group")
                        record.update(phase="spawned", host_pid=event["pid"],
                                      process_group=group if isinstance(group, int) else None)
                        _write_host_process_record(record_path, record)
                elif kind in {"stdout", "stderr"} and isinstance(event.get("text"), str):
                    consume = on_stdout if kind == "stdout" else on_stderr
                    if consume is not None:
                        consume(event["text"])
                elif kind == "result" and event.get("outcome") in {
                    "exited",
                    "timeout",
                    "cancelled",
                    "output_limit",
                    "spawn_failed",
                }:
                    result = event
                else:
                    raise RuntimeError("Invalid managed Host process observation")
        finally:
            # Also runs on callback failure / Ctrl-C. Do not kill the supervisor
            # before it has had a chance to terminate its owned Host group.
            proc.stdin.close()
            try:
                # The leased CLI gets six seconds to acknowledge nested Host
                # cleanup. Keep this control transport alive through its forced
                # group kill as well, including callback failure / Ctrl-C.
                proc.wait(timeout=8 if delegated_lease is not None else 5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        if record is not None and result is not None and proc.returncode == 0:
            # The supervisor returned only after cleaning its group; the group is still re-read.
            record["phase"] = "finished"
            _write_host_process_record(record_path, record)
        if proc.returncode != 0 or result is None:
            raise RuntimeError("Managed Host process supervision returned no result")
        return result
