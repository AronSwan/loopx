import assert from "node:assert/strict";
import test from "node:test";
import {evaluateTodoSuccession, projectTodoSuccession, projectTodoClosure} from "../../loopx/control_plane/todos/succession.ts";

const row = (todo_id: string, overrides = {}) => ({todo_id, status: "done", active: true,
  advancement: true, no_followup: false, successors: [], superseded_by: null,
  unblocks: null, resumes: null, handoff: false, context_fields: ["claimed_by"], ...overrides});

test("one resolver recognizes explicit, supersession and inferred links in source order", () => {
  const rows = [row("todo_source", {successors: ["todo_explicit", "todo_source", "todo_missing"], superseded_by: "todo_replaced", handoff: true}),
    row("todo_explicit", {advancement: false}), row("todo_replaced"),
    row("todo_inferred", {resumes: "todo_source", unblocks: "todo_source", active: false})];
  const result = evaluateTodoSuccession(rows)[0];
  assert.deepEqual(result.successor_todo_ids, ["todo_explicit", "todo_replaced", "todo_inferred"]);
  assert.deepEqual(result.unresolved_successor_ids, ["todo_source", "todo_missing"]);
  assert.equal(result.handoff_state, "superseded");
  assert.equal(result.successor_gap, false);
});

for (const [status, extra, expected] of [
  ["open", {}, "blocking"], ["blocked", {}, "blocking"], ["deferred", {}, "deferred"],
  ["done", {}, "cleared_without_successor"], ["done", {no_followup: true}, "cleared_no_followup"],
  ["done", {successors: ["todo_next"]}, "cleared_with_successor"],
  ["open", {superseded_by: "todo_next"}, "superseded"],
  ["open", {superseded_by: "todo_missing"}, "blocking"],
] as const) test(`handoff ${status} ${JSON.stringify(extra)} → ${expected}`, () => {
  assert.equal(evaluateTodoSuccession([row("todo_gate", {status, handoff: true, ...extra}), row("todo_next")])[0].handoff_state, expected);
});

test("archived and deferred rows are evidence but never unfinished completed work", () => {
  const results = evaluateTodoSuccession([row("todo_archive", {active: false}), row("todo_deferred", {status: "deferred"}),
    row("todo_plain", {context_fields: []}), row("todo_closed", {no_followup: true})]);
  assert.deepEqual(results.map(value => value.successor_gap), [false, false, false, false]);
});

test("filtering preserves full-source evidence; editing relevant facts invalidates it", () => {
  const source = row("todo_source");
  const evaluations = evaluateTodoSuccession([source, row("todo_next", {resumes: "todo_source"})]);
  const request = {schema_version: "todo_succession_request_v0", rows: [source], evaluations: [evaluations[0]]};
  assert.equal((projectTodoSuccession(request).evaluations as Record<string, unknown>[])[0].successor_gap, false);
  assert.throws(() => projectTodoSuccession({...request, rows: [{...source, no_followup: true}]}), /matching full-source/);
  assert.throws(() => projectTodoSuccession({...request, evaluations: []}), /cardinality/);
  assert.throws(() => evaluateTodoSuccession([source, source]), /duplicate succession identity/);
});

const closed = {status: "done", watch_only: false, no_followup: true, successor_gap: false, replan: false, handoff_state: null};
const closure = (rows: unknown[], full_selection = true) => projectTodoClosure({schema_version: "todo_closure_request_v0",
  role: "agent", source_section: "Agent Todo", full_selection, rows});
test("terminal proofs require full selection and absence of every unresolved obligation", () => {
  assert.ok(closure([closed]).terminal_closure_proof);
  assert.ok(closure([]).terminal_closure_proof);
  for (const override of [{successor_gap: true}, {replan: true}, {status: "deferred"},
    {status: "open"}, {handoff_state: "cleared_without_successor"}]) {
    assert.equal(closure([{...closed, ...override}]).terminal_closure_proof, undefined);
  }
  assert.equal(closure([closed], false).terminal_closure_proof, undefined);
  assert.equal(closure([closed], false).source_proof, undefined);
  const watch = closure([{...closed, status: "open", watch_only: true}]);
  assert.equal((watch.terminal_closure_proof as Record<string, unknown>).all_convergent_todos_done, true);
  assert.equal((watch.terminal_closure_proof as Record<string, unknown>).all_todos_done, false);
});

test("interned field sets are lossless and reject invalid references", () => {
  const rows = Array.from({length: 4000}, (_, index) => row(`todo_history_${index}`, {
    active: false, context_fields: index % 2 ? ["claimed_by", "completed_at"] : [],
  }));
  const request = {schema_version: "todo_succession_request_v0", context_field_sets: [[], ["claimed_by", "completed_at"]],
    rows: rows.map((value, index) => ({...value, context_fields: index % 2}))};
  assert.deepEqual(projectTodoSuccession(request).evaluations, evaluateTodoSuccession(rows));
  for (const index of [-1, 2, 0.5, "0"]) assert.throws(() => projectTodoSuccession({...request,
    rows: [{...rows[0], context_fields: index}]}), /context field index/);
});

test("a cached result cannot contradict its matched item facts", () => {
  const source = row("todo_source"), evaluation = evaluateTodoSuccession([source])[0];
  for (const mutation of [{successor_gap: false}, {tracked_completion: false}, {handoff_state: "superseded"},
    {successor_todo_ids: [null]}, {successor_todo_ids: [source.todo_id]}]) {
    assert.throws(() => projectTodoSuccession({schema_version: "todo_succession_request_v0",
      rows: [source], evaluations: [{...evaluation, ...mutation}]}), /succession evaluation|successor identity/);
  }
});


test("active identity replaces archived edges regardless of source order", () => {
  const source = row("todo_source");
  const archived = row("todo_reused", {active: false, resumes: "todo_source"});
  const active = row("todo_reused", {status: "open"});
  for (const generations of [[archived, active], [active, archived]]) {
    const result = evaluateTodoSuccession([source, ...generations]);
    assert.equal(result[0].successor_gap, true);
    assert.deepEqual(result[0].successor_todo_ids, []);
    const explicit = evaluateTodoSuccession([{...source, successors: ["todo_reused"]}, ...generations]);
    assert.deepEqual(explicit[0].successor_todo_ids, ["todo_reused"]);
  }
  assert.throws(() => evaluateTodoSuccession([active, active]), /duplicate succession identity/);
  assert.throws(() => evaluateTodoSuccession([archived, archived, active]), /duplicate succession identity/);
});
