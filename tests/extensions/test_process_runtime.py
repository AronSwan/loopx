from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time

import pytest

from loopx.extensions.process_runtime import run_capped_process


@pytest.mark.skipif(os.name != "posix", reason="POSIX process-group regression")
def test_timeout_terminates_provider_descendants(tmp_path: Path) -> None:
    marker = tmp_path / "descendant-effect"
    child_code = (
        "from pathlib import Path; import time; "
        "time.sleep(1.2); "
        f"Path({str(marker)!r}).write_text('effect', encoding='utf-8')"
    )
    provider_code = (
        "import subprocess, sys, time; "
        f"subprocess.Popen([sys.executable, '-c', {child_code!r}]); "
        "time.sleep(5)"
    )

    result = run_capped_process(
        [sys.executable, "-c", provider_code],
        stdin=json.dumps({"schema_version": "request_v0"}).encode(),
        timeout_seconds=1,
        output_limit_bytes=1024,
    )

    assert result.failure_kind == "timeout"
    time.sleep(0.5)
    assert not marker.exists()


@pytest.mark.skipif(os.name != "posix", reason="POSIX process-group regression")
def test_output_overflow_terminates_provider_descendants(tmp_path: Path) -> None:
    marker = tmp_path / "descendant-effect"
    child_code = (
        "from pathlib import Path; import time; "
        "time.sleep(0.6); "
        f"Path({str(marker)!r}).write_text('effect', encoding='utf-8')"
    )
    provider_code = (
        "import subprocess, sys, time; "
        f"subprocess.Popen([sys.executable, '-c', {child_code!r}]); "
        "sys.stdout.buffer.write(b'x' * 1025); sys.stdout.flush(); time.sleep(5)"
    )

    result = run_capped_process(
        [sys.executable, "-c", provider_code],
        stdin=b"{}",
        timeout_seconds=5,
        output_limit_bytes=1024,
    )

    assert result.failure_kind == "response_too_large"
    time.sleep(0.8)
    assert not marker.exists()


def test_a_provider_response_returns_byte_for_byte() -> None:
    response = '{"verdict": "巡检通过"}\n'.encode("utf-8")

    result = run_capped_process(
        [
            sys.executable,
            "-c",
            "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())",
        ],
        stdin=response,
        timeout_seconds=30,
        output_limit_bytes=1024,
    )

    assert result.failure_kind is None
    assert result.returncode == 0
    assert result.stdout == response


def test_a_provider_declining_is_not_reported_as_a_runtime_failure() -> None:
    result = run_capped_process(
        [sys.executable, "-c", "import sys; sys.stdout.write('declined'); sys.exit(3)"],
        stdin=b"{}",
        timeout_seconds=30,
        output_limit_bytes=1024,
    )

    assert result.failure_kind is None
    assert result.returncode == 3
    assert result.stdout == b"declined"


def test_a_response_of_exactly_the_limit_is_kept() -> None:
    limit = 4096

    result = run_capped_process(
        [sys.executable, "-c", f"import sys; sys.stdout.buffer.write(b'x' * {limit})"],
        stdin=b"{}",
        timeout_seconds=30,
        output_limit_bytes=limit,
    )

    assert result.failure_kind is None
    assert result.returncode == 0
    assert len(result.stdout) == limit


def test_a_spewing_provider_is_stopped_instead_of_drained() -> None:
    limit = 4096
    started = time.monotonic()

    result = run_capped_process(
        [
            sys.executable,
            "-c",
            "import sys, time\n"
            "while True:\n"
            "    sys.stdout.buffer.write(b'x' * 65536)\n"
            "    sys.stdout.flush()\n"
            "    time.sleep(30)\n",
        ],
        stdin=b"{}",
        timeout_seconds=30,
        output_limit_bytes=limit,
    )

    elapsed = time.monotonic() - started
    assert result.failure_kind == "response_too_large"
    # One byte past the limit is the caller's truncation signal, and the bound
    # must hold against a provider that never stops writing.
    assert len(result.stdout) == limit + 1
    assert elapsed < 20, (
        f"the capture drained the provider instead of stopping it: {elapsed:.1f}s"
    )


def test_a_spewing_provider_on_stderr_is_its_own_failure() -> None:
    result = run_capped_process(
        [
            sys.executable,
            "-c",
            "import sys, time\n"
            "sys.stderr.buffer.write(b'e' * 262144)\n"
            "sys.stderr.flush()\n"
            "time.sleep(30)\n",
        ],
        stdin=b"{}",
        timeout_seconds=30,
        output_limit_bytes=1024,
    )

    assert result.failure_kind == "stderr_too_large"
    assert result.stdout == b""
