from __future__ import annotations

import json
from pathlib import Path

from loopx.cli_commands import lark_inbox
from loopx.configure_goal import configure_goal
from loopx.control_plane.quota.goal_boundary import goal_boundary


def _goal(project: Path) -> dict[str, object]:
    return {
        "id": "lark-urgency-fixture",
        "repo": str(project),
        "control_plane": {
            "lark_event_inbox": {
                "enabled": True,
                "config_path": ".loopx/config/lark/event-inbox.json",
            }
        },
    }


def test_lark_urgency_projection_checks_activation_before_private_config(
    tmp_path: Path,
    monkeypatch,
) -> None:
    events: list[str] = []

    def resolve(command: str, *, runtime_root_arg: str | None) -> dict[str, object]:
        events.append(f"activate:{command}:{runtime_root_arg}")
        return {"enabled": True}

    def project(**_kwargs: object) -> dict[str, object]:
        events.append("project")
        return {"schema_version": "lark_event_inbox_urgency_v0"}

    monkeypatch.setattr(lark_inbox, "_resolve_lark_activation", resolve)
    monkeypatch.setattr(lark_inbox, "project_lark_event_inbox_urgency", project)

    projector = lark_inbox.build_lark_operator_inbox_urgency_projector(
        runtime_root_arg=tmp_path / "runtime"
    )
    result = projector(project=tmp_path, config_path="private.json")

    assert result["schema_version"] == "lark_event_inbox_urgency_v0"
    assert events == [f"activate:drain:{tmp_path / 'runtime'}", "project"]


def test_disabled_lark_extension_cannot_schedule_from_private_config(
    tmp_path: Path,
    monkeypatch,
) -> None:
    projected = False

    def disabled(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise ValueError("extension `loopx-lark` is disabled")

    def project(**_kwargs: object) -> dict[str, object]:
        nonlocal projected
        projected = True
        return {}

    monkeypatch.setattr(lark_inbox, "_resolve_lark_activation", disabled)
    monkeypatch.setattr(lark_inbox, "project_lark_event_inbox_urgency", project)

    boundary = goal_boundary(
        _goal(tmp_path),
        operator_inbox_urgency_projector=(
            lark_inbox.build_lark_operator_inbox_urgency_projector(
                runtime_root_arg=tmp_path / "runtime"
            )
        ),
    )
    urgency = boundary["capabilities"]["lark_event_inbox"]["urgency"]

    assert urgency["projection_status"] == "unavailable"
    assert urgency["local_private_content_returned"] is False
    assert projected is False


def test_agent_scoped_inbox_is_registered_and_projected_only_for_its_agent(
    tmp_path: Path,
) -> None:
    registry_path = tmp_path / ".loopx" / "registry.json"
    registry_path.parent.mkdir()
    registry_path.write_text(
        json.dumps(
            {
                "goals": [
                    {
                        "id": "goal-alpha",
                        "repo": str(tmp_path),
                        "coordination": {
                            "registered_agents": ["agent-alpha", "agent-beta"]
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    configured = configure_goal(
        registry_path=registry_path,
        goal_id="goal-alpha",
        lark_event_inbox_config=".loopx/config/lark/agent-alpha.json",
        lark_event_inbox_agent_id="agent-alpha",
        execute=True,
    )

    assert configured["written"] is True
    goal = json.loads(registry_path.read_text(encoding="utf-8"))["goals"][0]
    assert (
        lark_inbox._goal_inbox_config(goal, agent_id="agent-alpha")
        == ".loopx/config/lark/agent-alpha.json"
    )
    assert lark_inbox._goal_inbox_config(goal, agent_id="agent-beta") is None
    alpha = goal_boundary(goal, agent_id="agent-alpha", registry_path=registry_path)
    beta = goal_boundary(goal, agent_id="agent-beta", registry_path=registry_path)
    assert "--agent-id agent-alpha" in alpha["capabilities"]["lark_event_inbox"]["drain_command"]
    assert beta is None or "lark_event_inbox" not in beta.get("capabilities", {})
