import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { FileAuthorityStore } from "../../loopx/control_plane/coordination/file_authority_store.ts";
import {
  AUTHORITY_STORE_CAPABILITIES,
  AUTHORITY_STORE_PROVIDER_CONFORMANCE,
} from "../../loopx/control_plane/coordination/authority_store.ts";

async function fixture(t: test.TestContext) {
  const root = await mkdtemp(join(tmpdir(), "loopx-authority-store-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const path = join(root, "authority.json");
  return { path, store: new FileAuthorityStore("goal-a", path) };
}

test("file provider atomically persists projection, events, and receipts", async (t) => {
  const { store } = await fixture(t);
  assert.deepEqual(await store.loadAuthority(), {
    head: null, provider_revision: null, cursor: null,
  });
  const applied = await store.commitAuthority({
    expected_provider_revision: null,
    operation_id: "operation-a",
    events: [{ type: "work_claimed", authority_revision: 1 }],
    next_projection: { schema_version: "example_head_v0", authority_revision: 1 },
    receipts: [{ operation_id: "operation-a", result: "applied" }],
  });
  assert.equal(applied.status, "applied");
  if (applied.status !== "applied") return;
  assert.deepEqual(await store.loadAuthority(), {
    head: { schema_version: "example_head_v0", authority_revision: 1 },
    provider_revision: applied.provider_revision,
    cursor: "1",
  });
  assert.deepEqual(await store.readReceipt("operation-a"), [
    { operation_id: "operation-a", result: "applied" },
  ]);
  assert.deepEqual(
    (await store.scanCommitted(null, 10)).map((entry) => entry.operation_id),
    ["operation-a"],
  );
});

test("provider capability matrix keeps backend primitives behind one contract", () => {
  assert.deepEqual(
    Object.keys(AUTHORITY_STORE_PROVIDER_CONFORMANCE),
    ["file", "nokv", "postgresql"],
  );
  for (const capabilities of Object.values(AUTHORITY_STORE_PROVIDER_CONFORMANCE)) {
    assert.deepEqual(capabilities, AUTHORITY_STORE_CAPABILITIES);
  }
});

test("file provider CAS admits one writer and reports opaque current lineage", async (t) => {
  const { store } = await fixture(t);
  const commit = (operationId: string) => store.commitAuthority({
    expected_provider_revision: null,
    operation_id: operationId,
    events: [{ type: "candidate" }],
    next_projection: { winner: operationId },
    receipts: [{ operation_id: operationId }],
  });
  const results = await Promise.all([commit("operation-a"), commit("operation-b")]);
  assert.deepEqual(results.map((result) => result.status).sort(), ["applied", "conflict"]);
  const applied = results.find((result) => result.status === "applied");
  const conflict = results.find((result) => result.status === "conflict");
  assert.ok(applied && applied.status === "applied");
  assert.ok(conflict && conflict.status === "conflict");
  assert.equal(conflict.current_provider_revision, applied.provider_revision);
  assert.equal(conflict.current_cursor, "1");
  assert.equal((await store.scanCommitted(null, 10)).length, 1);
});

test("committed scan is cursor-bounded and returned values are isolated", async (t) => {
  const { store } = await fixture(t);
  const first = await store.commitAuthority({
    expected_provider_revision: null,
    operation_id: "operation-a", events: [], next_projection: { revision: 1 },
    receipts: [{ id: "receipt-a" }],
  });
  assert.equal(first.status, "applied");
  if (first.status !== "applied") return;
  await store.commitAuthority({
    expected_provider_revision: first.provider_revision,
    operation_id: "operation-b", events: [], next_projection: { revision: 2 },
    receipts: [{ id: "receipt-b" }],
  });
  const page = await store.scanCommitted("1", 1);
  assert.equal(page[0]?.operation_id, "operation-b");
  (page[0]!.projection as { revision: number }).revision = 99;
  assert.deepEqual((await store.loadAuthority()).head, { revision: 2 });
  await assert.rejects(() => store.scanCommitted("3", 1), /ahead/);
  await assert.rejects(() => store.scanCommitted(null, 0), /positive/);
});

test("corrupt or cross-goal documents fail closed", async (t) => {
  const { path, store } = await fixture(t);
  await writeFile(path, JSON.stringify({ schema_version: "other" }), "utf8");
  await assert.rejects(() => store.loadAuthority(), /schema mismatch/);
  await writeFile(path, JSON.stringify({
    schema_version: "loopx_file_authority_store_v0",
    goal_id: "goal-b", provider_revision: "revision", cursor: "1",
    head: {}, committed: [],
  }), "utf8");
  await assert.rejects(() => store.loadAuthority(), /goal mismatch/);
});

test("file provider binds stored authority to a stable store lineage", async (t) => {
  const { path, store } = await fixture(t);
  const identity = await store.storeIdentity();
  assert.equal(await store.storeIdentity(), identity);
  await store.commitAuthority({
    expected_provider_revision: null,
    operation_id: "operation-a", events: [], next_projection: { revision: 1 },
    receipts: [],
  });
  await writeFile(`${path}.identity`, `file:${crypto.randomUUID()}`, "utf8");
  await assert.rejects(() => store.loadAuthority(), /lineage mismatch/);
});
