import assert from "node:assert/strict";
import test from "node:test";

import {
  ACTION_PORTFOLIO_REQUEST_SCHEMA_VERSION,
  ACTION_SELECTION_QUALIFICATION_REQUEST_SCHEMA_VERSION,
  projectQuotaActionPortfolio,
  qualifyActionSelection,
} from "../../loopx/control_plane/work_items/action_portfolio.ts";

function candidate(todoId: string, text: string, priority: string) {
  return {
    todo_id: todoId,
    text,
    priority,
    status: "open",
    task_class: "advancement_task",
    claimed_by: "codex-main",
    required_capabilities: [`capability_${todoId}`],
    required_write_scopes: [`artifacts/${todoId}/**`],
  };
}

test("action portfolio exposes one recommendation and bounded selectable alternatives", () => {
  const primary = candidate("todo_primary001", "Run the primary slice.", "P0");
  const result = projectQuotaActionPortfolio({
    schema_version: ACTION_PORTFOLIO_REQUEST_SCHEMA_VERSION,
    primary,
    candidates: [
      primary,
      candidate("todo_fallback001", "Run fallback one.", "P1"),
      candidate("todo_fallback001", "Duplicate fallback one.", "P1"),
      candidate("todo_fallback002", "Run fallback two.", "P2"),
      candidate("todo_fallback003", "Run fallback three.", "P3"),
    ],
    unavailable_higher_priority: [],
    max_alternative_actions: 2,
  });

  assert.equal(result?.schema_version, "quota_action_portfolio_v1");
  assert.deepEqual(result?.selection_policy, {
    decision_owner: "agent",
    mode: "explicit_turn_binding",
    recommendation_role: "default_not_binding",
    requires_explicit_turn_binding: true,
    direct_delivery_before_selection: false,
    max_alternative_actions: 2,
    candidate_scope: "current_authoritative_eligible_todos",
    suggestions_exhaustive: false,
  });
  assert.deepEqual(result?.suggested_actions, [
    {
      todo_id: "todo_primary001",
      text: "Run the primary slice.",
      priority: "P0",
      required_capabilities: ["capability_todo_primary001"],
      required_write_scopes: ["artifacts/todo_primary001/**"],
      selection_role: "recommended",
    },
    {
      todo_id: "todo_fallback001",
      text: "Run fallback one.",
      priority: "P1",
      required_capabilities: ["capability_todo_fallback001"],
      required_write_scopes: ["artifacts/todo_fallback001/**"],
      selection_role: "alternative",
    },
    {
      todo_id: "todo_fallback002",
      text: "Run fallback two.",
      priority: "P2",
      required_capabilities: ["capability_todo_fallback002"],
      required_write_scopes: ["artifacts/todo_fallback002/**"],
      selection_role: "alternative",
    },
  ]);
});

test("future or blocked higher priority work keeps the portfolio visible", () => {
  const result = projectQuotaActionPortfolio({
    schema_version: ACTION_PORTFOLIO_REQUEST_SCHEMA_VERSION,
    primary: candidate("todo_fallback001", "Run the ready fallback.", "P1"),
    candidates: [],
    unavailable_higher_priority: [
      {
        ...candidate("todo_monitor001", "Poll at the next window.", "P0"),
        task_class: "continuous_monitor",
        availability_reason: "scheduled_for_future",
        next_due_at: "2099-01-01T00:00:00Z",
      },
    ],
  });

  assert.equal(
    (result?.unavailable_higher_priority as Array<Record<string, unknown>>)[0]
      .availability_reason,
    "scheduled_for_future",
  );
  assert.equal(
    (result?.selection_policy as Record<string, unknown>)
      .requires_explicit_turn_binding,
    false,
  );
});

test("a single primary needs no redundant portfolio", () => {
  assert.equal(projectQuotaActionPortfolio({
    schema_version: ACTION_PORTFOLIO_REQUEST_SCHEMA_VERSION,
    primary: candidate("todo_primary001", "Run the only slice.", "P0"),
    candidates: [],
    unavailable_higher_priority: [],
  }), null);
});

test("malformed candidates fail closed at the typed boundary", () => {
  assert.throws(
    () => projectQuotaActionPortfolio({
      schema_version: ACTION_PORTFOLIO_REQUEST_SCHEMA_VERSION,
      primary: candidate("todo_primary001", "Run the primary slice.", "P0"),
      candidates: [{ text: "missing typed identity" }],
    }),
    /todo_id/,
  );
  assert.throws(
    () => projectQuotaActionPortfolio({
      schema_version: ACTION_PORTFOLIO_REQUEST_SCHEMA_VERSION,
      primary: candidate("todo_primary001", "Run the primary slice.", "P0"),
      candidates: [
        {
          ...candidate("todo_blocked001", "Blocked work.", "P1"),
          status: "blocked",
        },
      ],
    }),
    /status must be open/,
  );
  assert.throws(
    () => projectQuotaActionPortfolio({
      schema_version: ACTION_PORTFOLIO_REQUEST_SCHEMA_VERSION,
      primary: candidate("todo_primary001", "Run the primary slice.", "P0"),
      candidates: [
        {
          ...candidate("todo_contract001", "Malformed contract.", "P1"),
          required_write_scopes: "artifacts/**",
        },
      ],
    }),
    /required_write_scopes must be an array of strings/,
  );
});

test("pending selection qualifies only after current hard-lane arbitration", () => {
  const successor = candidate(
    "todo_successor001",
    "Run the visible successor slice.",
    "P1",
  );
  const qualified = qualifyActionSelection({
    schema_version: ACTION_SELECTION_QUALIFICATION_REQUEST_SCHEMA_VERSION,
    requested_todo_id: successor.todo_id,
    candidate: successor,
    should_run: true,
    normal_delivery_allowed: true,
    delivery_preemptions: [],
  });
  assert.equal(qualified.state, "qualified");
  assert.deepEqual(qualified.selected_todo, {
    todo_id: successor.todo_id,
    text: successor.text,
    priority: successor.priority,
    required_capabilities: successor.required_capabilities,
    required_write_scopes: successor.required_write_scopes,
    selection_binding: "pending_action_selection",
  });

  const deferred = qualifyActionSelection({
    schema_version: ACTION_SELECTION_QUALIFICATION_REQUEST_SCHEMA_VERSION,
    requested_todo_id: successor.todo_id,
    candidate: successor,
    should_run: true,
    normal_delivery_allowed: true,
    delivery_preemptions: ["blocking_work_lane"],
  });
  assert.deepEqual(deferred, {
    schema_version: "action_selection_qualification_v0",
    state: "deferred",
    requested_todo_id: successor.todo_id,
    reason: "blocking_work_lane",
    delivery_preemptions: ["blocking_work_lane"],
  });
});

test("pending selection rejects a Todo absent from the current eligible set", () => {
  assert.deepEqual(qualifyActionSelection({
    schema_version: ACTION_SELECTION_QUALIFICATION_REQUEST_SCHEMA_VERSION,
    requested_todo_id: "todo_missing001",
    candidate: null,
    should_run: true,
    normal_delivery_allowed: true,
    delivery_preemptions: [],
  }), {
    schema_version: "action_selection_qualification_v0",
    state: "rejected",
    requested_todo_id: "todo_missing001",
    reason: "candidate_not_currently_eligible",
  });
});
