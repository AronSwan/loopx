"""End-to-end coverage for the post-writeback capability hook (issue #3479).

The Turn CLI composition root registers the periodic-report post-writeback
hook; after a validated completion writes its durable ``todo_complete``
receipt, the core boundary dispatches the hook exactly once and the typed
trigger-evaluation intent surfaces in the command payload without gaining
any write authority. This file mirrors the fake-scheduler run-once fixture
from ``test_loopx_turn_driver.py``: the generic host adapter and independent
validator are inline Python fixtures.
"""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
from typing import Any

from loopx.cli import main as cli_main
from test_loopx_turn_driver import (
    _completion_host_and_validation_scripts,
    _turn_run_once_completion_argv,
    _write_live_fixture,
)

_PROFILE: dict[str, Any] = {
    "schema_version": "periodic_report_profile_v0",
    "profile_id": "weekly_progress",
    "profile_version": "v1",
    "trigger_policy": {
        "enabled_kinds": ["bounded_segment_milestone"],
        "minimum_interval_seconds": 0,
        "aggregation": {
            "window_seconds": 604800,
            "todo_completed_threshold": 1,
            "promote_replan": True,
        },
    },
}


def _write_profile(tmp_path: Path) -> Path:
    profile_path = tmp_path / "periodic-report-profile.json"
    profile_path.write_text(json.dumps(_PROFILE), encoding="utf-8")
    return profile_path


def _run_cli(argv: list[str]) -> tuple[int, dict[str, Any]]:
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        exit_code = cli_main(argv)
    return exit_code, json.loads(output.getvalue())


def test_disabled_capability_makes_zero_hook_calls(tmp_path: Path) -> None:
    project, runtime, registry = _write_live_fixture(tmp_path)
    host_project = tmp_path / "isolated-host-workspace"
    host_project.mkdir()
    host_script, validation_script = _completion_host_and_validation_scripts()
    argv = _turn_run_once_completion_argv(
        host_project,
        runtime,
        registry,
        host_script,
        validation_script,
    )

    exit_code, payload = _run_cli([*argv[:-1], "--scan-root", str(project), "--execute"])

    assert exit_code == 0, payload
    assert payload["status"] == "committed"
    assert "post_writeback_hooks" not in payload


def test_validated_completion_auto_promotes_report_intent(tmp_path: Path) -> None:
    project, runtime, registry = _write_live_fixture(tmp_path)
    host_project = tmp_path / "isolated-host-workspace"
    host_project.mkdir()
    profile_path = _write_profile(tmp_path)
    host_script, validation_script = _completion_host_and_validation_scripts()
    argv = _turn_run_once_completion_argv(
        host_project,
        runtime,
        registry,
        host_script,
        validation_script,
    )

    exit_code, payload = _run_cli(
        [
            *argv[:-1],
            "--scan-root",
            str(project),
            "--post-writeback-periodic-report",
            str(profile_path),
            "--execute",
        ]
    )

    assert exit_code == 0, payload
    assert payload["status"] == "committed"
    assert payload["effects"]["state_written"] is True

    observed = payload.get("post_writeback_hooks")
    assert isinstance(observed, dict), payload.get("error")
    completion_lane = observed.get("todo_complete")
    assert isinstance(completion_lane, list) and len(completion_lane) == 1
    summary = completion_lane[0]
    assert summary["phase"] == "post_writeback"
    assert summary["primary_writeback_affected"] is False
    receipt = summary["receipt"]
    assert receipt["event_kind"] == "todo_complete"
    assert receipt["appended"] is True
    assert receipt["goal_id"] == "loopx-turn-fixture"
    assert receipt["todo_id"] == "todo_fixture0001"

    results = summary["results"]
    assert len(results) == 1
    result = results[0]
    assert result["hook_id"] == "periodic_report.post_writeback_trigger"
    assert result["capability_id"] == "periodic-report"
    assert result["status"] == "intent_ready"
    assert result["intent_kind"] == "periodic_report_trigger_evaluation"
    assert isinstance(result["idempotency_key"], str)
    intent = result["intent"]
    assert isinstance(intent, dict)
    producer_receipt = intent["producer_receipt"]
    assert producer_receipt["status"] == "promoted"
    assert producer_receipt["todo_completed_count"] >= 1
    assert producer_receipt["contributing_event_count"] >= 1
    assert summary["failures"] == []

    # The typed intent carries no sink authority: the capability-owned
    # compose-run/renderer/sink boundary stays the only route to effects.
    assert "sink" not in intent
    assert "requested_write_scope" not in intent


def test_replayed_turn_does_not_redispatch_hooks(tmp_path: Path) -> None:
    project, runtime, registry = _write_live_fixture(tmp_path)
    host_project = tmp_path / "isolated-host-workspace"
    host_project.mkdir()
    profile_path = _write_profile(tmp_path)
    host_script, validation_script = _completion_host_and_validation_scripts()
    argv = _turn_run_once_completion_argv(
        host_project,
        runtime,
        registry,
        host_script,
        validation_script,
    )
    base_argv = [
        *argv[:-1],
        "--scan-root",
        str(project),
        "--post-writeback-periodic-report",
        str(profile_path),
        "--execute",
    ]

    exit_code, payload = _run_cli(base_argv)
    assert exit_code == 0, payload
    observed = payload["post_writeback_hooks"]
    assert isinstance(observed.get("todo_complete"), list)

    replay_exit_code, replayed = _run_cli(
        [*base_argv[:-1], "--resume-turn-key", str(payload["resume_turn_key"]), "--execute"]
    )
    assert replay_exit_code == 0, replayed
    assert replayed["replayed"] is True
    assert not any(replayed["effects"].values())
    assert "post_writeback_hooks" not in replayed


def test_invalid_profile_fails_fast_before_any_writeback(tmp_path: Path) -> None:
    project, runtime, registry = _write_live_fixture(tmp_path)
    host_project = tmp_path / "isolated-host-workspace"
    host_project.mkdir()
    bad_profile = tmp_path / "bad-profile.json"
    bad_profile.write_text(json.dumps({"profile_id": "broken"}), encoding="utf-8")
    host_script, validation_script = _completion_host_and_validation_scripts()
    argv = _turn_run_once_completion_argv(
        host_project,
        runtime,
        registry,
        host_script,
        validation_script,
    )

    exit_code, payload = _run_cli(
        [
            *argv[:-1],
            "--scan-root",
            str(project),
            "--post-writeback-periodic-report",
            str(bad_profile),
            "--execute",
        ]
    )

    assert exit_code != 0, payload
    assert payload.get("ok") is False
    assert "profile" in str(payload.get("error", ""))
    # Composition fails before the host runs: no journal, no rollout event.
    turns_dir = runtime / "goals" / "loopx-turn-fixture" / "turns"
    assert not turns_dir.exists()
