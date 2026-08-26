from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from loopx.control_plane.todos.contract import encode_metadata_value
from loopx.todos import list_goal_todos

GOAL_ID = "todo-list-thin-goal"
AGENT_ID = "codex-thin-output"
REPO_ROOT = Path(__file__).resolve().parents[2]


def _todo_line(*, text: str, metadata: str) -> list[str]:
    return [
        f"- [ ] {text}",
        f"  <!-- loopx:todo {metadata} -->",
    ]


def _write_fixture(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    runtime = tmp_path / "runtime"
    state_relative = Path(".local/goals") / GOAL_ID / "ACTIVE_GOAL_STATE.md"
    state_file = project / state_relative
    state_file.parent.mkdir(parents=True)
    lines = [
        "---",
        "status: active",
        "updated_at: 2026-01-01T00:00:00+00:00",
        "---",
        "",
        "# Todo List Thin Fixture",
        "",
        "## User Todo",
        "",
        *_todo_line(
            text="Approve the public output contract.",
            metadata=(
                "todo_id=todo_user_gate status=open priority=P0 "
                "task_class=user_gate action_kind=approve_output "
                f"blocks_agent={AGENT_ID} "
                "decision_scope=direction:action:output-contract "
                f"note={encode_metadata_value('Public fixture review detail.')}"
            ),
        ),
        "",
        "## Agent Todo",
        "",
        *_todo_line(
            text="Observe the public output budget.",
            metadata=(
                "todo_id=todo_agent_monitor status=open priority=P1 "
                "task_class=continuous_monitor action_kind=observe_budget "
                f"claimed_by={AGENT_ID} target_key=public-output "
                "cadence=PT5M next_due_at=2026-01-01T00:05:00Z "
                f"note={encode_metadata_value('Public fixture monitor detail.')} "
                f"evidence={encode_metadata_value('Public fixture evidence.')}"
            ),
        ),
    ]
    state_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    registry_path = project / ".loopx/registry.json"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "common_runtime_root": str(runtime),
                "goals": [
                    {
                        "id": GOAL_ID,
                        "status": "active",
                        "repo": str(project),
                        "state_file": str(state_relative),
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return registry_path


def _run_cli(
    registry_path: Path,
    *extra: str,
    output_format: str = "json",
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "loopx.cli",
            "--format",
            output_format,
            "todo",
            "list",
            "--goal-id",
            GOAL_ID,
            *extra,
        ],
        cwd=REPO_ROOT,
        env={**os.environ, "LOOPX_REGISTRY": str(registry_path)},
        check=False,
        capture_output=True,
        text=True,
    )


def test_thin_projects_actionable_identity_and_omits_detail(tmp_path: Path) -> None:
    registry_path = _write_fixture(tmp_path)

    payload = list_goal_todos(
        registry_path=registry_path,
        goal_id=GOAL_ID,
        thin=True,
    )

    assert payload["thin"] is True
    assert payload["todo_count"] == len(payload["todos"]) == 2
    assert "state_file" not in payload
    assert "project" not in payload
    assert payload["todo_list_field_projection"] == {
        "schema_version": "todo_list_thin_projection_v0",
        "view": "thin_explicit_view",
        "item_container": "todos",
        "item_fields": [
            "todo_id",
            "role",
            "status",
            "priority",
            "text",
            "title",
            "task_class",
            "action_kind",
            "claimed_by",
            "bound_agent",
            "goal_bound",
            "blocks_agent",
            "global_gate",
            "unblocks_todo_id",
            "decision_scope",
            "required_decision_scopes",
            "resume_when",
            "resume_ready",
            "target_key",
            "cadence",
            "next_due_at",
            "expires_at",
            "watch_only",
        ],
        "item_text_limit": 180,
        "full_detail_cold_paths": [
            "todo list without --thin",
            "todo list --todo-id <id> without --thin",
            "active state",
        ],
    }

    user_item, agent_item = payload["todos"]
    assert user_item["todo_id"] == "todo_user_gate"
    assert user_item["blocks_agent"] == AGENT_ID
    assert user_item["decision_scope"] == {
        "schema_version": "decision_scope_v0",
        "kind": "direction",
        "granularity": "action",
        "scope_key": "output-contract",
    }
    assert agent_item["todo_id"] == "todo_agent_monitor"
    assert agent_item["claimed_by"] == AGENT_ID
    assert agent_item["target_key"] == "public-output"
    assert agent_item["next_due_at"] == "2026-01-01T00:05:00Z"
    for item in payload["todos"]:
        assert "note" not in item
        assert "evidence" not in item
        assert "reason" not in item
        assert "updated_at" not in item

    for summary in (payload["user_todos"], payload["agent_todos"]):
        assert summary["payload_compaction"]["view"] == "thin_explicit_view"
        assert summary["payload_compaction"]["items_projected_to"] == "todos"
        assert [
            key
            for key, value in summary.items()
            if isinstance(value, list)
        ] == []


def test_thin_is_opt_in_and_composes_with_limit(tmp_path: Path) -> None:
    registry_path = _write_fixture(tmp_path)

    default = list_goal_todos(registry_path=registry_path, goal_id=GOAL_ID)
    limited = list_goal_todos(
        registry_path=registry_path,
        goal_id=GOAL_ID,
        thin=True,
        limit=1,
    )

    assert "thin" not in default
    assert "todo_list_field_projection" not in default
    assert default["state_file"]
    assert default["project"]
    assert any("note" in item for item in default["todos"])

    assert limited["thin"] is True
    assert limited["explicit_limit"] == 1
    assert limited["returned_todo_count"] == 2
    assert limited["todo_list_projection"]["view"] == "explicit_limit_cold_path"
    assert limited["user_todos"]["payload_compaction"]["source_view"] == (
        "explicit_limit_cold_path"
    )
    assert limited["agent_todos"]["payload_compaction"]["source_view"] == (
        "explicit_limit_cold_path"
    )


def test_cli_thin_round_trips_json_and_markdown(tmp_path: Path) -> None:
    registry_path = _write_fixture(tmp_path)

    json_result = _run_cli(registry_path, "--thin")
    assert json_result.returncode == 0, json_result.stdout
    payload = json.loads(json_result.stdout)
    assert payload["thin"] is True
    assert "state_file" not in payload

    markdown_result = _run_cli(
        registry_path,
        "--thin",
        output_format="markdown",
    )
    assert markdown_result.returncode == 0, markdown_result.stdout
    assert "# LoopX Todo List" in markdown_result.stdout
    assert "- view: `thin_explicit_view`" in markdown_result.stdout
    assert "state_file" not in markdown_result.stdout
    assert "Public fixture review detail" not in markdown_result.stdout
    assert len(markdown_result.stdout.splitlines()) <= 18


def test_cli_rejects_thin_outside_todo_list(tmp_path: Path) -> None:
    registry_path = _write_fixture(tmp_path)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "loopx.cli",
            "--format",
            "json",
            "todo",
            "add",
            "--goal-id",
            GOAL_ID,
            "--role",
            "agent",
            "--text",
            "Do not write this rejected fixture todo.",
            "--thin",
        ],
        cwd=REPO_ROOT,
        env={**os.environ, "LOOPX_REGISTRY": str(registry_path)},
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1, result.stdout
    payload = json.loads(result.stdout)
    assert payload["error"] == "--thin is supported only by todo list"
