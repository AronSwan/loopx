from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from loopx import goal_mode_mcp
from loopx.claude_goal_mode.hooks.goal_state import goal_context as claude_context
from loopx.goal_mode_mcp import GoalModeMCPConfig, GoalModeMCPControlPlane
from loopx.kunluncode_goal_mode import cli
from loopx.kunluncode_goal_mode.context import (
    goal_context as kunluncode_context,
    write_binding,
)


def _registry(project: Path) -> Path:
    path = project / ".loopx" / "registry.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": "0.1",
                "goals": [
                    {
                        "id": "shared-goal",
                        "repo": str(project),
                        "coordination": {
                            "agent_model": "peer_v1",
                            "registered_agents": ["cc", "kunlun"],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_claude_and_kunluncode_bind_distinct_agents(tmp_path: Path) -> None:
    _registry(tmp_path)
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    claude_dir.joinpath("loop.md").write_text(
        '<!-- loopx:armed {"goal_id":"shared-goal","agent_id":"cc"} -->\n',
        encoding="utf-8",
    )
    write_binding(tmp_path, goal_id="shared-goal", agent_id="kunlun")

    claude = claude_context(tmp_path)
    kunlun = kunluncode_context(tmp_path)

    assert claude and claude["agent_id"] == "cc"
    assert kunlun and kunlun["agent_id"] == "kunlun"
    assert claude["goal_id"] == kunlun["goal_id"] == "shared-goal"


def test_kunluncode_binding_fails_closed_for_unregistered_agent(tmp_path: Path) -> None:
    _registry(tmp_path)
    write_binding(tmp_path, goal_id="shared-goal", agent_id="not-registered")

    assert kunluncode_context(tmp_path) is None


def test_mcp_uses_kunluncode_profile_and_rejects_agent_impersonation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    control = GoalModeMCPControlPlane(
        GoalModeMCPConfig(
            server_name="loopx-kunluncode",
            runtime_profile="kunluncode",
            legacy_host_surface="kunluncode",
        ),
        lambda: {
            "goal_id": "shared-goal",
            "registry": "/project/.loopx/registry.json",
            "agent_id": "kunlun",
        },
    )
    commands: list[list[str]] = []
    control.command_prefix = lambda: ["loopx"]

    def capture(command: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, '{"ok": true}', "")

    monkeypatch.setattr(goal_mode_mcp.subprocess, "run", capture)

    assert json.loads(control.claim_task("todo-1", "cc"))["ok"] is False
    assert commands == []

    assert json.loads(control.should_run())["ok"] is True
    assert commands[-1][-2:] == ["--runtime-profile", "kunluncode"]

    assert json.loads(control.claim_task("todo-1", "kunlun"))["ok"] is True
    assert commands[-1][-4:] == ["--claimed-by", "kunlun", "--agent-id", "kunlun"]

    output = control.complete_task(
        "todo-1",
        "kunlun",
        "focused check passed",
        no_follow_up=True,
    )
    assert "spend-slot" in output
    assert "--no-follow-up" in commands[-2]
    assert commands[-1][-2:] == ["--agent-id", "kunlun"]


def test_installer_registers_only_the_owned_global_mcp_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(cli.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(cli, "_compatible_python", lambda _python: True)
    monkeypatch.setattr(cli, "_configured_mcp_servers", lambda _binary: [])

    def capture(command: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(cli, "_run", capture)

    selected = cli.install_mcp(
        python="/managed/.venv/bin/python",
        dry_run=False,
        replace=False,
    )

    assert selected == "/managed/.venv/bin/python"
    assert calls == [
        [
            "/usr/bin/kunluncode",
            "mcp",
            "add",
            "loopx-kunluncode",
            "--command",
            "/managed/.venv/bin/python",
            "--args",
            str(cli.MCP_SCRIPT),
        ]
    ]


def test_installer_refuses_to_replace_a_foreign_named_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(cli, "_compatible_python", lambda _python: True)
    monkeypatch.setattr(
        cli,
        "_configured_mcp_servers",
        lambda _binary: [
            {
                "name": "loopx-kunluncode",
                "command": "/user/custom-server",
                "args": [],
            }
        ],
    )

    with pytest.raises(RuntimeError, match="user-owned"):
        cli.install_mcp(
            python="/managed/.venv/bin/python",
            dry_run=False,
            replace=False,
        )


def test_installer_normalizes_relative_python_to_an_absolute_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    interpreter = tmp_path / ".venv" / "bin" / "python"
    calls: list[list[str]] = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(cli, "_compatible_python", lambda _python: True)
    monkeypatch.setattr(cli, "_configured_mcp_servers", lambda _binary: [])

    def capture(command: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(cli, "_run", capture)

    selected = cli.install_mcp(
        python=".venv/bin/python",
        dry_run=False,
        replace=False,
    )

    assert selected == str(interpreter)
    assert str(interpreter) in calls[0]


def test_connect_preserves_existing_registered_agents(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry = _registry(tmp_path)
    commands: list[list[str]] = []
    monkeypatch.setattr(cli, "_loopx_prefix", lambda: ["loopx"])

    def capture(command: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, '{"ok": true}', "")

    monkeypatch.setattr(cli, "_run", capture)

    result = cli.connect_project(
        project=tmp_path,
        goal_id="shared-goal",
        agent_id="kunlun-next",
        objective=None,
        python=None,
        skip_mcp=True,
        replace=False,
        dry_run=False,
    )

    configure = commands[0]
    registered = [
        configure[index + 1]
        for index, argument in enumerate(configure)
        if argument == "--registered-agent"
    ]
    assert registered == ["cc", "kunlun", "kunlun-next"]
    assert result["agent_id"] == "kunlun-next"
    assert json.loads(registry.read_text(encoding="utf-8"))["agent_backends"] == [
        "kunluncode"
    ]


def test_worker_prompt_closes_each_bounded_lifecycle_segment() -> None:
    prompt = cli.worker_prompt("kunlun")

    assert "should_run first" in prompt
    assert "claim exactly the selected todo" in prompt
    assert "complete_task" in prompt
    assert "no_follow_up=true" in prompt
    assert "never reuse the completed todo_id" in prompt
    assert "Re-check should_run once and stop" in prompt


def test_worker_prepends_the_adapter_environment_to_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        cli,
        "goal_context",
        lambda _project: {"goal_id": "g", "agent_id": "kunlun"},
    )
    monkeypatch.setattr(cli.shutil, "which", lambda _name: "/usr/bin/kunluncode")

    def capture(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        captured["command"] = command
        captured.update(kwargs)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(cli.subprocess, "run", capture)

    assert cli.run_worker(
        tmp_path,
        permission_mode="auto",
        max_duration_secs=60,
        json_output=True,
        dry_run=False,
    ) == 0

    environment = captured["env"]
    assert isinstance(environment, dict)
    assert environment["PATH"].split(":", 1)[0] == str(
        Path(cli.sys.executable).absolute().parent
    )
