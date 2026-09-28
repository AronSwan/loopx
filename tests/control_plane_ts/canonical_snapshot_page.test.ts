import assert from "node:assert/strict";
import test from "node:test";
import {mkdtemp, rm, readdir} from "node:fs/promises";
import {tmpdir} from "node:os";
import {join} from "node:path";
import type {JsonObject} from "../../loopx/control_plane/effect_program.ts";
import {FileAuthorityStore} from "../../loopx/control_plane/coordination/file_authority_store.ts";
import {SqliteAuthorityStore} from "../../loopx/control_plane/coordination/sqlite_authority_store.ts";
import {sqliteRuntimeIdentity} from "../../loopx/control_plane/coordination/sqlite_runtime.ts";
import {coordinationTodoReadModel} from "../../loopx/control_plane/coordination/coordination_projection.ts";
import {readCanonicalSnapshotFromStore, readCanonicalSnapshotPage, CANONICAL_SNAPSHOT_PAGE_BYTES} from "../../loopx/control_plane/coordination/canonical_snapshot_page.ts";
import {productionScaleCoordinationFixture} from "./production_scale_coordination_fixture.ts";
import {collectSnapshot, registerCanonicalSnapshotConformance, seedSnapshot, snapshotRequest, snapshotFixture} from "./canonical_snapshot_conformance.ts";

async function fixture(t: test.TestContext, kind: "file" | "sqlite" = "file") {
  const root = await mkdtemp(join(tmpdir(), "canonical-snapshot-"));
  t.after(() => rm(root, {recursive: true, force: true}));
  const Store = kind === "file" ? FileAuthorityStore : SqliteAuthorityStore;
  return {store: new Store(root, "goal-a"), contender: new Store(root, "goal-a")};
}
const qualifiedSqlite = sqliteRuntimeIdentity().sqlite_authority_qualified;
if (!qualifiedSqlite) test.skip("SQLite snapshot conformance requires a qualified SQLite runtime", () => {});
for (const kind of (qualifiedSqlite ? ["file", "sqlite"] : ["file"]) as ("file" | "sqlite")[]) {
  registerCanonicalSnapshotConformance(kind, t => fixture(t, kind));
  test(`${kind}: a normal complete collection keeps a single RPC response`, async t => {
    const {store} = await fixture(t, kind);
    const source = productionScaleCoordinationFixture("goal-a", "native");
    await seedSnapshot(store, source.projection);
    const result = await collectSnapshot(store);
    assert.equal(result.pages.length, 1);
    assert.equal(result.todos.length, source.expected_initial_todo_count);
    assert.equal(result.leases.length, source.expected_current_lease_count);
  });
  test(`${kind}: UTF-8 byte pages retain records beyond the old 2 MiB RPC ceiling`, async t => {
    const {store} = await fixture(t, kind);
    const projection = snapshotFixture().projection;
    const todos = projection.todos as JsonObject[];
    assert.ok(Buffer.byteLength(JSON.stringify(projection)) > 2 * 1024 * 1024);
    await seedSnapshot(store, projection);
    const result = await collectSnapshot(store);
    assert.deepEqual(new Map(result.todos.map(row => [row.todo_id, row])), new Map(todos.map(row => [row.todo_id, row])));
    assert.ok(result.pages.some(page => (page.todos as unknown[]).length < 4096 && page.next !== null));
  });
}

test("oversized single records fail explicitly instead of truncating or looping", async t => {
  const {store} = await fixture(t);
  const projection = snapshotFixture().projection;
  const todos = projection.todos as JsonObject[];
  todos[0].note = "x".repeat(CANONICAL_SNAPSHOT_PAGE_BYTES);
  projection.todo_read_model = coordinationTodoReadModel(todos, "loopx_todo_domain_read_record_v0");
  await seedSnapshot(store, projection);
  const before = await store.loadAuthority();
  await assert.rejects(collectSnapshot(store), {code: "canonical_snapshot_record_too_large"});
  assert.deepEqual(await store.loadAuthority(), before);
});

for (const position of [null, -1, true, "128", 0.5]) {
  test(`invalid continuation offset ${JSON.stringify(position)} is rejected`, async t => {
    const {store} = await fixture(t);
    await seedSnapshot(store, snapshotFixture().projection);
    const first = await readCanonicalSnapshotFromStore(snapshotRequest(), store);
    const after = structuredClone(first.next) as JsonObject;
    after.todo_offset = position;
    await assert.rejects(readCanonicalSnapshotFromStore(snapshotRequest({after}), store), {code: "canonical_snapshot_request_invalid"});
  });
}


test("a missing runtime provider read does not initialize a replacement authority", async t => {
  const root = await mkdtemp(join(tmpdir(), "canonical-missing-"));
  t.after(() => rm(root, {recursive: true, force: true}));
  const before = await readdir(root);
  const result = await readCanonicalSnapshotPage(snapshotRequest({runtime_root: root}));
  assert.equal(result.status, "missing");
  assert.equal(result.reason_code, undefined);
  assert.deepEqual(await readdir(root), before);
  assert.equal("todos" in result, false);
});

test("ordering uses Unicode code points rather than JavaScript default UTF-16 sorting", async t => {
  const {store} = await fixture(t);
  const projection = snapshotFixture().projection;
  projection.todos = ["z", "\ue000", "🙂"].map(todo_id => ({
    schema_version: "todo_domain_record_v0", todo_id, role: "agent", status: "open", done: false,
    text: "Preserve stable identity", task_class: "advancement_task", archive_state: "active"}));
  projection.leases = [];
  projection.todo_read_model = coordinationTodoReadModel(projection.todos as JsonObject[], "loopx_todo_domain_read_record_v0");
  await seedSnapshot(store, projection);
  assert.deepEqual((await collectSnapshot(store)).todos.map(row => row.todo_id), ["z", "\ue000", "🙂"]);
});
