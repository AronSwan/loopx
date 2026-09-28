import assert from "node:assert/strict";
import test from "node:test";
import { projectVisionWaitCoverage } from "../../loopx/control_plane/goals/vision_wait_coverage.ts";

const facts = (extra: Record<string, unknown> = {}) => ({
  causal_todo_ids: ["todo_a", "todo_b"], waiting_todo_ids: ["todo_a"],
  blocker_todo_ids: [], edges: [], ...extra,
});

test("one waiting path cannot cover another acceptance obligation", () => {
  assert.deepEqual(projectVisionWaitCoverage(facts()).uncovered_todo_ids, ["todo_b"]);
  assert.equal(projectVisionWaitCoverage(facts({ waiting_todo_ids: ["todo_a", "todo_b"] })).covered, true);
});

test("shared prerequisites do not turn sibling paths into substitutes", () => {
  assert.equal(projectVisionWaitCoverage(facts({
    causal_todo_ids: ["todo_b"], edges: [["todo_recovery", "todo_a"], ["todo_recovery", "todo_b"]],
  })).covered, false);
  assert.equal(projectVisionWaitCoverage(facts({
    causal_todo_ids: ["todo_recovery"], edges: [["todo_recovery", "todo_a"]],
  })).covered, true);
});

test("explicit successors carry lineage through replaced or completed predecessors", () => {
  assert.equal(projectVisionWaitCoverage(facts({
    causal_todo_ids: ["todo_old"], edges: [["todo_old", "todo_next"], ["todo_next", "todo_a"]],
  })).covered, true);
  assert.equal(projectVisionWaitCoverage(facts({ causal_todo_ids: ["todo_done"] })).covered, false);
});

test("every root needs coverage even when one has a concrete blocker", () => {
  assert.equal(projectVisionWaitCoverage(facts({ waiting_todo_ids: [], blocker_todo_ids: ["todo_a"] })).covered, false);
  assert.equal(projectVisionWaitCoverage(facts({ waiting_todo_ids: ["todo_b"], blocker_todo_ids: ["todo_a"] })).covered, true);
});

test("cycles terminate and unrelated edges and input order do not change coverage", () => {
  const edges = [["todo_a", "todo_b"], ["todo_b", "todo_a"], ["todo_other", "todo_remote"]];
  const a = projectVisionWaitCoverage(facts({ edges }));
  const b = projectVisionWaitCoverage(facts({ edges: [...edges].reverse(), causal_todo_ids: ["todo_b", "todo_a"] }));
  assert.deepEqual(a, b);
  assert.equal(projectVisionWaitCoverage(facts({ edges, waiting_todo_ids: [] })).covered, false);
});

test("unbound acceptance and malformed facts cannot prove a wait", () => {
  assert.equal(projectVisionWaitCoverage(facts({ causal_todo_ids: [] })).covered, false);
  for (const patch of [{ edges: [["todo_a"]] }, { edges: null }, { waiting_todo_ids: [null] }]) {
    assert.throws(() => projectVisionWaitCoverage(facts(patch)));
  }
});
