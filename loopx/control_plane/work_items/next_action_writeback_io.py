"""Source I/O for TS-owned Next Action admission; no task/intent write authority."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Any

from ...agent_registry import load_goal_from_registry, registered_agent_ids_for_goal
from ...file_lock import exclusive_cross_runtime_file_lock
from ...state_projection import active_state_next_action_entries
from ..effect_runtime import EffectRuntimeRejected, effect_runtime_result
from ..runtime.local_state_write_correctness import active_state_revision, stable_write_digest
from ..runtime.runtime_projection_route import resolve_goal_source_runtime_route


class NextActionWritebackRejected(ValueError):
    def __init__(self, result: dict[str, Any]) -> None:
        super().__init__(result["error"])
        self.code = result["error_code"]
        self.payload = {"next_action_writeback": result}


def next_action_writeback_context(
    goal: dict[str, Any] | None, state_text: str, *, goal_id: str | None = None,
    source_registry: Path | None = None,
    write: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source = goal if goal is not None else {"id": goal_id}
    request = {
        "goal_id": source["id"],
        # Bind registry identity/lifecycle/routing facts, not status's derived
        # run history, projections or display defaults.
        "goal_revision": "sha256:" + stable_write_digest({
            "registered_goal_present": goal is not None,
            "source_registry": str(source_registry.resolve()) if source_registry is not None else None,
            "facts": {key: source.get(key) for key in ("id", "goal_instance_id", "status", "repo", "state_file")},
        }),
        "registered_agents": registered_agent_ids_for_goal(goal),
        "state_revision": active_state_revision(state_text)["value"],
        # A bounded readback, but the revision above covers the complete bytes.
        "next_action_entries": active_state_next_action_entries(state_text, limit=3, text_limit=500),
        "write": write,
    }
    try:
        result = effect_runtime_result("work_item.next_action_writeback.resolve", request)
    except EffectRuntimeRejected as error:
        raise ValueError(str(error)) from error
    if not isinstance(result, dict) or not isinstance(result.get("basis"), str):
        raise RuntimeError("invalid TypeScript Next Action admission result")
    if write is not None and result.get("admitted") is not True:
        raise NextActionWritebackRejected(result)
    return result


def load_next_action_source_goal(registry_path: Path, goal_id: str) -> tuple[Path, dict[str, Any] | None]:
    # Runtime overrides choose execution/projection, never roster authority.
    route = resolve_goal_source_runtime_route(registry_path=registry_path, goal_id=goal_id)
    source_registry = Path(route["source_registry"]).resolve()
    return source_registry, load_goal_from_registry(source_registry, goal_id)


def project_agent_next_actions(goal: dict[str, Any], todo_fields: dict[str, Any]) -> list[dict[str, Any]]:
    """Compose independent existing lane selectors; never infer a new owner."""
    from ..agents.agent_lane_recommendation import build_agent_lane_next_action

    agents = registered_agent_ids_for_goal(goal)
    if len(agents) < 2:
        return []
    routes = []
    for agent in agents:
        route = build_agent_lane_next_action(
            agent_identity={"agent_id": agent}, agent_todo_summary=todo_fields.get("agent_todos"),
            capability_gate=None, active_next_action=[],
        )
        if route:
            routes.append({key: route[key] for key in ("agent_id", "todo_id", "text") if key in route})
    return routes


@contextmanager
def next_action_source_guard(
    registry_path: Path, state_path: Path, goal_id: str,
    *, source_registry: Path,
) -> Iterator[tuple[dict[str, Any] | None, str]]:
    # Registration/configuration use the same registry lock. Quota's outer
    # index/source guard precedes this short registry -> state critical section.
    # Release before projection/global sync to avoid recursive registry locking.
    # Configuration locks source before its shared projection. Keep that order,
    # and revalidate the projection's route under both locks before using it.
    with ExitStack() as stack:
        stack.enter_context(exclusive_cross_runtime_file_lock(source_registry, operation="next-action-writeback"))
        if registry_path.resolve() != source_registry.resolve():
            stack.enter_context(exclusive_cross_runtime_file_lock(registry_path, operation="next-action-writeback"))
        current_source, goal = load_next_action_source_goal(registry_path, goal_id)
        if current_source != source_registry.resolve():
            raise ValueError("Next Action source registry changed; read current status and rejudge before retrying")
        stack.enter_context(exclusive_cross_runtime_file_lock(state_path, operation="next-action-writeback"))
        yield goal, state_path.read_text(encoding="utf-8")
