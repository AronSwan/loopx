"""Real refresh/status transactions on disposable Goal state."""
from concurrent.futures import ThreadPoolExecutor
import json
import subprocess
import sys

import pytest

import loopx.state_refresh as refresh
from loopx.control_plane.work_items.next_action_writeback_io import (
    NextActionWritebackRejected, next_action_writeback_context,
)
from loopx.status import collect_status
from loopx.control_plane.coordination.local_authority import read_canonical_todos_if_promoted
from tests.control_plane import test_todo_projection_concurrency as projection_fixtures

canonical_projection = projection_fixtures.canonical_projection

STATE = """# Active Goal State

## Agent Todo

- [ ] [P1] Inspect the parser.
  <!-- loopx:todo todo_id=todo_parser status=open task_class=advancement_task claimed_by=agent-a -->
- [ ] [P1] Evaluate the current artifact.
  <!-- loopx:todo todo_id=todo_evaluate status=open task_class=advancement_task claimed_by=agent-b -->

## Next Action

- Preserve the current shared route.
"""
VISION = {"state": "vision_patch_proposed", "vision_patch": {
    "vision_summary": "Inspect current evidence before the next experiment.",
    "acceptance_summary": "Validated evidence and scoped next work remain required.",
}}


def fixture(tmp_path, agents=("agent-a",)):
    state = tmp_path / "state.md"
    state.write_text(STATE)
    registry = tmp_path / "registry.json"
    goal = {"id": "next-action-goal", "status": "active", "repo": str(tmp_path),
            "state_file": state.name, "coordination": {"registered_agents": list(agents)}}
    runtime = tmp_path / "runtime"
    registry.write_text(json.dumps({"common_runtime_root": str(runtime), "goals": [goal]}))
    return registry, state, runtime, goal


def write(registry, runtime, **kwargs):
    options = dict(
        registry_path=registry, runtime_root_override=str(runtime), goal_id="next-action-goal",
        project=None, state_file=None, classification="state_refreshed", recommended_action=None,
        agent_id="agent-a", next_action="Evaluate the new artifact; preserve the incumbent.",
        agent_vision_packet=VISION, dry_run=False, sync_global=False,
    )
    options.update(kwargs)
    return refresh.refresh_state_run(**options)


def test_sole_peer_write_keeps_attribution_scope_and_task_owners(tmp_path):
    registry, state, runtime, _ = fixture(tmp_path)
    payload = write(registry, runtime)
    assert payload["progress_scope"] == "agent_lane"
    assert payload["agent_id"] == "agent-a"
    assert payload["vision_checkpoint"]["satisfied"] is True
    assert payload["active_state_next_action_update"]["agent_id"] == "agent-a"
    assert "Evaluate the new artifact; preserve the incumbent." in state.read_text()
    assert state.read_text().split("## Next Action")[0] == STATE.split("## Next Action")[0]
    run = json.loads((runtime / "goals/next-action-goal/runs/index.jsonl").read_text())
    assert run["progress_scope"] == "agent_lane"
    assert run["agent_id"] == "agent-a"


@pytest.mark.parametrize("agents,scope,basis,code", [
    ([], None, None, "next_action_shared_scope_required"),
    (["agent-b"], None, None, None),
    (["agent-a", "offline-peer"], None, None, "next_action_shared_scope_required"),
    (["agent-a", "agent-b"], "goal", None, "next_action_basis_required"),
    (["agent-a"], None, "sha256:" + "0" * 64, "next_action_basis_conflict"),
])
def test_rejections_do_not_write_state_or_append_runs(tmp_path, agents, scope, basis, code):
    registry, state, runtime, _ = fixture(tmp_path, agents)
    with pytest.raises(ValueError) as caught:
        write(registry, runtime, progress_scope=scope, next_action_basis=basis)
    if code:
        assert caught.value.code == code
    assert state.read_text() == STATE
    assert not (runtime / "goals/next-action-goal/runs/index.jsonl").exists()


def test_shared_write_uses_status_basis_and_preserves_both_routes(tmp_path):
    registry, state, runtime, _ = fixture(tmp_path, ("agent-a", "agent-b"))
    status = collect_status(registry_path=registry, runtime_root_override=str(runtime), scan_roots=[tmp_path], limit=5, include_task_graph=True)
    item = next(item for item in status["attention_queue"]["items"] if item["goal_id"] == "next-action-goal")
    assert {r["agent_id"] for r in item["agent_next_actions"]} == {"agent-a", "agent-b"}
    basis = item["next_action_basis"]
    result = write(registry, runtime, progress_scope="goal", next_action_basis=basis)
    assert result["active_state_next_action_update"]["read_basis"] == basis
    assert result["active_state_next_action_update"]["applied_basis"] != basis
    after = collect_status(registry_path=registry, runtime_root_override=str(runtime), scan_roots=[tmp_path], limit=5, include_task_graph=True)
    item_after = next(item for item in after["attention_queue"]["items"] if item["goal_id"] == "next-action-goal")
    assert [(r["agent_id"], r["todo_id"]) for r in item_after["agent_next_actions"]] == [("agent-a", "todo_parser"), ("agent-b", "todo_evaluate")]
    assert state.read_text().split("## Next Action")[0] == STATE.split("## Next Action")[0]


@pytest.mark.parametrize("change_membership", [False, True])
def test_final_commit_rechecks_state_and_membership(tmp_path, monkeypatch, change_membership):
    registry, state, runtime, _ = fixture(tmp_path)
    original = refresh.qualify_refresh_replan_writeback
    def concurrent_change(**kwargs):
        result = original(**kwargs)
        if change_membership:
            data = json.loads(registry.read_text())
            data["goals"][0]["coordination"]["registered_agents"].append("offline-peer")
            registry.write_text(json.dumps(data))
        else:
            state.write_text(STATE.replace("Preserve the current shared route.", "A newer session chose this route."))
        return result
    monkeypatch.setattr(refresh, "qualify_refresh_replan_writeback", concurrent_change)
    with pytest.raises(NextActionWritebackRejected) as caught:
        write(registry, runtime)
    assert caught.value.code == "next_action_basis_conflict"
    assert caught.value.payload["next_action_writeback"]["next_action_entries"]
    assert "Evaluate the new artifact; preserve the incumbent." not in state.read_text()
    assert not (runtime / "goals/next-action-goal/runs/index.jsonl").exists()


def test_same_actor_concurrent_cli_writers_cannot_commit_the_same_old_basis(tmp_path):
    registry, state, runtime, goal = fixture(tmp_path)
    basis = next_action_writeback_context(goal, STATE, source_registry=registry)["basis"]
    vision_path = tmp_path / "vision.json"
    vision_path.write_text(json.dumps(VISION))
    def run(action):
        command = [sys.executable, "-m", "loopx.cli", "--format", "json", "--registry", str(registry),
                   "--runtime-root", str(runtime), "refresh-state", "--goal-id", goal["id"],
                   "--agent-id", "agent-a", "--next-action", action, "--next-action-basis", basis,
                   "--agent-vision-json", str(vision_path), "--no-global-sync"]
        result = subprocess.run(command, text=True, capture_output=True, timeout=30)
        assert result.stdout, result.stderr
        return result.returncode, json.loads(result.stdout)
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(run, ["Inspect new parser evidence.", "Evaluate the new artifact."]))
    assert sorted(code for code, _ in results) == [0, 1], results
    failure = next(payload for code, payload in results if code)
    assert failure["error_code"] == "next_action_basis_conflict"
    assert len((runtime / "goals/next-action-goal/runs/index.jsonl").read_text().splitlines()) == 1


def test_basis_covers_untruncated_state_and_legacy_roster_sources(tmp_path):
    _, _, _, goal = fixture(tmp_path)
    first = next_action_writeback_context(goal, STATE + "\n" + "x" * 500)
    second = next_action_writeback_context(goal, STATE + "\n" + "x" * 501)
    assert first["basis"] != second["basis"]
    goal["spawn_policy"] = {"registered_agents": ["offline-peer"]}
    assert next_action_writeback_context(goal, STATE)["registered_agents"] == ["agent-a", "offline-peer"]


def test_dry_run_checks_admission_without_writing_or_appending(tmp_path):
    registry, state, runtime, goal = fixture(tmp_path)
    result = write(registry, runtime, dry_run=True)
    assert result["active_state_next_action_update"]["would_update"] is True
    assert result["active_state_next_action_update"]["updated"] is False
    assert state.read_text() == STATE
    assert not (runtime / "goals/next-action-goal/runs/index.jsonl").exists()
    goal["coordination"]["registered_agents"].append("offline-peer")
    registry.write_text(json.dumps({"goals": [goal]}))
    with pytest.raises(NextActionWritebackRejected):
        write(registry, runtime, dry_run=True)


def test_single_peer_permission_does_not_bypass_vision_continuity_rules(tmp_path):
    registry, state, runtime, _ = fixture(tmp_path)
    with pytest.raises(ValueError, match="in_flight_continuation"):
        write(registry, runtime, delivery_boundary="in_flight_continuation", delivery_outcome="outcome_progress")
    assert state.read_text() == STATE
    assert not (runtime / "goals/next-action-goal/runs/index.jsonl").exists()


@pytest.mark.parametrize("field,value", [
    ("goal_instance_id", "new-instance"), ("status", "paused"), ("state_file", "other-state.md"),
])
def test_basis_fences_goal_identity_lifecycle_and_route_changes(tmp_path, field, value):
    registry, state, runtime, goal = fixture(tmp_path)
    basis = next_action_writeback_context(goal, STATE)["basis"]
    goal[field] = value
    assert next_action_writeback_context(goal, STATE)["basis"] != basis
    # A bounded status projection must not introduce a new revision.
    enriched = {**goal, "latest_runs": [{"classification": "state_refreshed"}], "quota": {"remaining": 1}}
    assert next_action_writeback_context(enriched, STATE)["basis"] == next_action_writeback_context(goal, STATE)["basis"]


def test_missing_goal_fails_at_the_next_action_boundary(tmp_path):
    registry, state, runtime, _ = fixture(tmp_path)
    registry.write_text(json.dumps({"goals": []}))
    with pytest.raises(ValueError, match="requires a registry Goal"):
        write(registry, runtime, project=tmp_path, state_file=state)
    assert state.read_text() == STATE


def shared_fixture(tmp_path):
    registry, state, runtime, goal = fixture(tmp_path, ("agent-a", "agent-b"))
    mirror = tmp_path / "shared-registry.json"
    stale = {**goal, "source_registry": str(registry), "state_file": "stale-state.md",
             "coordination": {"registered_agents": ["agent-a"]}}
    (tmp_path / "stale-state.md").write_text(STATE.replace("current shared route", "stale mirror route"))
    mirror.write_text(json.dumps({"registry_role": "global-local", "common_runtime_root": str(runtime), "goals": [stale]}))
    return registry, mirror, state, runtime, goal


def test_stale_shared_roster_cannot_grant_sole_peer_authority(tmp_path):
    registry, mirror, state, runtime, goal = shared_fixture(tmp_path)
    with pytest.raises(NextActionWritebackRejected) as caught:
        write(mirror, runtime)
    assert caught.value.code == "next_action_shared_scope_required"
    assert state.read_text() == STATE
    status = collect_status(registry_path=mirror, runtime_root_override=str(runtime), scan_roots=[tmp_path], limit=5, include_task_graph=True)
    item = next(item for item in status["attention_queue"]["items"] if item["goal_id"] == goal["id"])
    basis = next_action_writeback_context(goal, STATE, source_registry=registry)["basis"]
    assert item["next_action_basis"] == basis
    assert {route["agent_id"] for route in item["agent_next_actions"]} == {"agent-a", "agent-b"}
    result = write(mirror, runtime, progress_scope="goal", next_action_basis=basis)
    assert result["agent_id"] == "agent-a"
    assert result["active_state_next_action_update"]["read_basis"] == basis
    assert "Evaluate the new artifact" in state.read_text()
    assert "stale mirror route" in (tmp_path / "stale-state.md").read_text()


def test_missing_shared_source_never_mints_a_basis_or_allows_write(tmp_path):
    registry, mirror, state, runtime, _ = shared_fixture(tmp_path)
    registry.unlink()
    with pytest.raises(ValueError, match="source_registry is missing"):
        write(mirror, runtime)
    assert state.read_text() == STATE
    status = collect_status(registry_path=mirror, runtime_root_override=str(runtime), scan_roots=[tmp_path], limit=5, include_task_graph=True)
    assert all("next_action_basis" not in item for item in status["attention_queue"]["items"])


@pytest.mark.parametrize("change_route", [False, True])
def test_shared_source_is_rechecked_before_commit(tmp_path, monkeypatch, change_route):
    registry, mirror, state, runtime, goal = shared_fixture(tmp_path)
    basis = next_action_writeback_context(goal, STATE, source_registry=registry)["basis"]
    original = refresh.qualify_refresh_replan_writeback
    def concurrent_change(**kwargs):
        result = original(**kwargs)
        if change_route:
            successor = tmp_path / "successor-registry.json"
            successor.write_text(registry.read_text())
            data = json.loads(mirror.read_text())
            data["goals"][0]["source_registry"] = str(successor)
            mirror.write_text(json.dumps(data))
        else:
            data = json.loads(registry.read_text())
            data["goals"][0]["coordination"]["registered_agents"].append("offline-peer")
            registry.write_text(json.dumps(data))
        return result
    monkeypatch.setattr(refresh, "qualify_refresh_replan_writeback", concurrent_change)
    with pytest.raises(ValueError, match="source registry changed|read basis changed"):
        write(mirror, runtime, progress_scope="goal", next_action_basis=basis)
    assert state.read_text() == STATE
    assert not (runtime / "goals/next-action-goal/runs/index.jsonl").exists()


def test_sole_peer_prose_write_preserves_real_canonical_authority(canonical_projection):
    args, state, _, _ = canonical_projection
    registry = args["registry_path"]
    data = json.loads(registry.read_text())
    data["goals"][0]["coordination"] = {"registered_agents": ["agent-a"]}
    registry.write_text(json.dumps(data))
    before = read_canonical_todos_if_promoted(runtime_root=args["runtime_root"], goal_id=args["goal_id"])
    result = refresh.refresh_state_run(
        registry_path=registry, runtime_root_override=str(args["runtime_root"]), goal_id=args["goal_id"],
        project=None, state_file=None, classification="state_refreshed", recommended_action=None,
        agent_id="agent-a", agent_vision_packet=VISION, next_action="Validate the canonical work.",
        dry_run=False, sync_global=False,
    )
    assert result["progress_scope"] == "agent_lane"
    assert result["projection_delivery"] == "delivered"
    assert "Validate the canonical work." in state.read_text()
    assert "Canonical work" in state.read_text()
    assert "Human narrative." in state.read_text()
    after = read_canonical_todos_if_promoted(runtime_root=args["runtime_root"], goal_id=args["goal_id"])
    assert (after["provider_revision"], after["cursor"], after["todos"]) == (
        before["provider_revision"], before["cursor"], before["todos"],
    )
