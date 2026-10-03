import assert from "node:assert/strict";
import test from "node:test";
import {resolveNextActionWriteback as resolve} from "../../loopx/control_plane/work_items/next_action_writeback.ts";

const source = {
  goal_id: "goal-next-action", goal_revision: "sha256:" + "c".repeat(64),
  state_revision: "sha256:" + "a".repeat(64), registered_agents: ["agent-a"],
  next_action_entries: ["Keep the current route"],
};
const lane = {agent_id: "agent-a", progress_scope: "agent_lane"};
test("sole registered actor may update prose without changing report scope", () => {
  assert.equal(resolve({...source, write: lane}).admitted, true);
});
test("empty roster, unknown actor, and offline peers never qualify as a sole actor", () => {
  assert.equal(resolve({...source, registered_agents: [], write: lane}).admitted, false);
  assert.equal(resolve({...source, write: {...lane, agent_id: "agent-b"}}).admitted, false);
  assert.equal(resolve({...source, registered_agents: ["agent-a", "offline-peer"], write: lane}).admitted, false);
});
test("multi-peer shared writes require actor, goal scope, and exact basis", () => {
  const shared = {...source, registered_agents: ["agent-a", "agent-b"]};
  const basis = resolve(shared).basis;
  const write = {agent_id: "agent-b", progress_scope: "goal", expected_basis: basis};
  assert.equal(resolve({...shared, write}).admitted, true);
  assert.equal(resolve({...shared, write: {...write, expected_basis: null}}).error_code, "next_action_basis_required");
  assert.equal(resolve({...shared, write: {...write, agent_id: null}}).admitted, false);
  assert.equal(resolve({...shared, write: {...write, progress_scope: "agent_lane"}}).admitted, false);
  assert.equal(resolve({...shared, write: {...write, source_basis: basis, expected_basis: null}}).error_code, "next_action_basis_required");
});
test("invocation source basis also fences admission, without becoming caller authority", () => {
  assert.equal(resolve({...source, write: {...lane, source_basis: "sha256:" + "0".repeat(64)}}).error_code, "next_action_basis_conflict");
});
test("old prose, membership, lifecycle and instance bases conflict, including same-actor writes", () => {
  const write = {...lane, expected_basis: resolve(source).basis};
  for (const change of [
    {state_revision: "sha256:" + "b".repeat(64)}, {registered_agents: ["agent-a", "agent-b"]},
    {goal_revision: "sha256:" + "d".repeat(64)}, {goal_id: "other-goal"},
  ]) {
    assert.equal(resolve({...source, ...change, write}).error_code, "next_action_basis_conflict");
  }
});
test("roster ordering and duplicate identities do not create conflicts", () => {
  const shared = {...source, registered_agents: ["agent-b", "agent-a"]};
  assert.equal(resolve({...shared, registered_agents: ["agent-a", "agent-b", "agent-a"]}).basis, resolve(shared).basis);
});
test("unscoped legacy goal write remains admitted; malformed basis fails fast", () => {
  assert.equal(resolve({...source, registered_agents: [], write: {progress_scope: "goal"}}).admitted, true);
  assert.throws(() => resolve({...source, write: {...lane, expected_basis: "old"}}), /SHA-256 basis/);
});
