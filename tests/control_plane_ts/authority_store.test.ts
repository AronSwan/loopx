import assert from "node:assert/strict";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { FileAuthorityStore } from "../../loopx/control_plane/coordination/file_authority_store.ts";
import {
  AUTHORITY_STORE_PROVIDER_PROFILES,
  AUTHORITY_STORE_REQUIRED_GUARANTEES,
} from "../../loopx/control_plane/coordination/authority_store.ts";

async function fixture(t: test.TestContext, goalId = "goal-a") {
  const root = await mkdtemp(join(tmpdir(), "loopx-authority-store-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  return { root, store: new FileAuthorityStore(root, goalId) };
}

function commit(
  expectedProviderRevision: string | null,
  operationId: string,
  authorityRevision: number,
  leaseEpoch: number,
) {
  return {
    expected_provider_revision: expectedProviderRevision,
    operation_id: operationId,
    events: [{
      schema_version: "loopx_authority_event_v0",
      type: "todo_claimed",
      authority_revision: authorityRevision,
      lease_epoch: leaseEpoch,
    }],
    next_projection: {
      schema_version: "loopx_coordination_head_v1",
      authority_revision: authorityRevision,
      coordination: {
        leases: { "todo-a": { lease_epoch: leaseEpoch } },
      },
    },
    receipts: [{
      schema_version: "loopx_authority_receipt_v0",
      operation_id: operationId,
      accepted_authority_revision: authorityRevision,
      lease_epoch: leaseEpoch,
    }],
  };
}

test("file provider atomically persists one LoopX transition and its receipt", async (t) => {
  const { store } = await fixture(t);
  assert.deepEqual(await store.loadAuthority(), { status: "missing" });

  const applied = await store.commitAuthority(commit(null, "operation-a", 41, 7));
  assert.equal(applied.status, "applied");
  if (applied.status !== "applied") return;
  assert.match(applied.provider_revision, /^file:1:[0-9a-f]{24}$/);
  assert.notEqual(applied.provider_revision, "41");
  assert.notEqual(applied.provider_revision, "7");

  const loaded = await store.loadAuthority();
  assert.equal(loaded.status, "loaded");
  if (loaded.status !== "loaded") return;
  assert.equal(loaded.head.authority_revision, 41);
  assert.deepEqual(loaded.head.coordination, {
    leases: { "todo-a": { lease_epoch: 7 } },
  });
  assert.equal(loaded.provider_revision, applied.provider_revision);
  assert.equal(loaded.cursor, "1");

  const receipt = await store.readReceipt("operation-a");
  assert.equal(receipt.status, "found");
  if (receipt.status === "found") {
    assert.equal(receipt.receipts[0]?.accepted_authority_revision, 41);
    assert.equal(receipt.receipts[0]?.lease_epoch, 7);
  }
});

test("provider profiles map one logical contract onto different backend primitives", () => {
  assert.equal(AUTHORITY_STORE_REQUIRED_GUARANTEES.length, 6);
  assert.deepEqual(Object.keys(AUTHORITY_STORE_PROVIDER_PROFILES), [
    "file", "nokv", "postgresql",
  ]);
  assert.equal(AUTHORITY_STORE_PROVIDER_PROFILES.file.stage, "stage1_implemented");
  assert.equal(
    AUTHORITY_STORE_PROVIDER_PROFILES.nokv.revision_primitive,
    "path_generation_compare_and_publish",
  );
  assert.equal(
    AUTHORITY_STORE_PROVIDER_PROFILES.nokv.store_lineage_mapping,
    "workbench_workspace_incarnation_id",
  );
  assert.ok(
    AUTHORITY_STORE_PROVIDER_PROFILES.nokv.qualification_holds.includes(
      "capacity_and_receipt_retention",
    ),
  );
  assert.equal(
    AUTHORITY_STORE_PROVIDER_PROFILES.postgresql.atomic_commit_mapping,
    "one_sql_transaction_over_head_events_and_receipts",
  );
  assert.match(AUTHORITY_STORE_PROVIDER_PROFILES.postgresql.trust_boundary, /tenant_scoped/);
  assert.notDeepEqual(
    AUTHORITY_STORE_PROVIDER_PROFILES.file,
    AUTHORITY_STORE_PROVIDER_PROFILES.nokv,
  );
});

test("file CAS admits one writer and reports only storage conflict facts", async (t) => {
  const { root } = await fixture(t);
  const first = new FileAuthorityStore(root, "goal-a");
  const second = new FileAuthorityStore(root, "goal-a");
  const results = await Promise.all([
    first.commitAuthority(commit(null, "operation-a", 1, 1)),
    second.commitAuthority(commit(null, "operation-b", 1, 1)),
  ]);
  assert.deepEqual(results.map((result) => result.status).sort(), ["applied", "conflict"]);
  const applied = results.find((result) => result.status === "applied");
  const conflict = results.find((result) => result.status === "conflict");
  assert.ok(applied && applied.status === "applied");
  assert.ok(conflict && conflict.status === "conflict");
  assert.equal(conflict.conflict_kind, "provider_revision_mismatch");
  assert.equal(conflict.current_provider_revision, applied.provider_revision);
  assert.equal(conflict.current_cursor, "1");
});

test("historical receipt survives later commits and operation identity stays unique", async (t) => {
  const { store } = await fixture(t);
  const first = await store.commitAuthority(commit(null, "operation-a", 1, 3));
  assert.equal(first.status, "applied");
  if (first.status !== "applied") return;
  const second = await store.commitAuthority(
    commit(first.provider_revision, "operation-b", 2, 9),
  );
  assert.equal(second.status, "applied");
  if (second.status !== "applied") return;

  const historical = await store.readReceipt("operation-a");
  assert.equal(historical.status, "found");
  if (historical.status === "found") {
    assert.equal(historical.cursor, "1");
    assert.equal(historical.receipts[0]?.lease_epoch, 3);
  }
  const duplicate = await store.commitAuthority(
    commit(second.provider_revision, "operation-a", 3, 10),
  );
  assert.deepEqual(duplicate, {
    status: "conflict",
    conflict_kind: "operation_id_exists",
    current_provider_revision: second.provider_revision,
    current_cursor: "2",
  });
  const loaded = await store.loadAuthority();
  assert.equal(loaded.status, "loaded");
  if (loaded.status === "loaded") assert.equal(loaded.head.authority_revision, 2);
});

test("committed scan is cursor-bounded, paged, and isolated", async (t) => {
  const { store } = await fixture(t);
  const first = await store.commitAuthority(commit(null, "operation-a", 1, 1));
  assert.equal(first.status, "applied");
  if (first.status !== "applied") return;
  await store.commitAuthority(commit(first.provider_revision, "operation-b", 2, 2));

  const firstPage = await store.scanCommitted(null, 1);
  assert.equal(firstPage.status, "page");
  if (firstPage.status !== "page") return;
  assert.equal(firstPage.transactions[0]?.operation_id, "operation-a");
  assert.equal(firstPage.next_cursor, "1");
  assert.equal(firstPage.has_more, true);
  (firstPage.transactions[0]!.projection as { authority_revision: number })
    .authority_revision = 99;

  const secondPage = await store.scanCommitted("1", 1);
  assert.equal(secondPage.status, "page");
  if (secondPage.status === "page") {
    assert.equal(secondPage.transactions[0]?.operation_id, "operation-b");
    assert.equal(secondPage.next_cursor, "2");
    assert.equal(secondPage.has_more, false);
  }
  const loaded = await store.loadAuthority();
  assert.equal(loaded.status, "loaded");
  if (loaded.status === "loaded") assert.equal(loaded.head.authority_revision, 2);
  assert.equal((await store.scanCommitted("3", 1)).status, "failed");
  assert.equal((await store.scanCommitted(null, 0)).status, "failed");
});

test("malformed JSON values fail before any authority write", async (t) => {
  const { store } = await fixture(t);
  const invalidNumber = commit(null, "operation-nan", 1, 1);
  invalidNumber.next_projection.authority_revision = Number.NaN;
  assert.deepEqual(
    (await store.commitAuthority(invalidNumber)).status,
    "failed",
  );
  const invalidObject = commit(null, "operation-date", 1, 1);
  (invalidObject.next_projection as Record<string, unknown>).coordination = new Date();
  assert.equal((await store.commitAuthority(invalidObject)).status, "failed");
  assert.deepEqual(await store.loadAuthority(), { status: "missing" });
});

test("corrupt, cross-goal, or revision-divergent documents fail closed", async (t) => {
  const { store } = await fixture(t);
  const applied = await store.commitAuthority(commit(null, "operation-a", 1, 1));
  assert.equal(applied.status, "applied");
  const original = JSON.parse(await readFile(store.path, "utf8"));

  await writeFile(store.path, JSON.stringify({ ...original, goal_id: "goal-b" }), "utf8");
  assert.equal((await store.loadAuthority()).status, "failed");

  await writeFile(store.path, JSON.stringify({ ...original, unexpected: true }), "utf8");
  assert.equal((await store.loadAuthority()).status, "failed");

  const changed = structuredClone(original);
  changed.committed[0].projection.authority_revision = 99;
  changed.head.authority_revision = 99;
  await writeFile(store.path, JSON.stringify(changed), "utf8");
  const divergent = await store.loadAuthority();
  assert.equal(divergent.status, "failed");
  if (divergent.status === "failed") assert.match(divergent.reason, /revision lineage/);
});

test("store identity is one durable directory lineage and restored bytes are fenced", async (t) => {
  const { root, store } = await fixture(t);
  const handles = Array.from({ length: 8 }, () => new FileAuthorityStore(root, "goal-a"));
  const identities = await Promise.all(handles.map((handle) => handle.storeIdentity()));
  assert.ok(identities.every((result) => result.status === "available"));
  const values = identities.flatMap((result) =>
    result.status === "available" ? [result.store_identity] : []
  );
  assert.equal(new Set(values).size, 1);
  assert.match(values[0]!, /^file:[0-9a-f]{32}$/);

  await store.commitAuthority(commit(null, "operation-a", 1, 1));
  await writeFile(store.identityPath, `file:${"a".repeat(32)}`, "ascii");
  const restored = await store.loadAuthority();
  assert.equal(restored.status, "failed");
  if (restored.status === "failed") assert.match(restored.reason, /lineage mismatch/);
});

test("proven missing is distinct from provider read unavailability", async (t) => {
  const { store } = await fixture(t);
  assert.deepEqual(await store.loadAuthority(), { status: "missing" });
  const identity = await store.storeIdentity();
  assert.equal(identity.status, "available");
  await mkdir(store.path);
  const unavailable = await store.loadAuthority();
  assert.equal(unavailable.status, "unavailable");
});

test("orphan temporary writes never become the visible authority head", async (t) => {
  const { store } = await fixture(t);
  await writeFile(`${store.path}.tmp-crashed-writer`, "{truncated", "utf8");
  assert.deepEqual(await store.loadAuthority(), { status: "missing" });
  const applied = await store.commitAuthority(commit(null, "operation-a", 1, 1));
  assert.equal(applied.status, "applied");
  const loaded = await store.loadAuthority();
  assert.equal(loaded.status, "loaded");
});

test("ambiguous file commits reconcile only from durable receipt readback", async (t) => {
  const { root } = await fixture(t);
  class FaultStore extends FileAuthorityStore {
    fault: "before" | "after" | null = null;

    protected override async replaceDurably(path: string, payload: Uint8Array): Promise<void> {
      if (path === this.path && this.fault === "before") {
        this.fault = null;
        throw new Error("injected before replace");
      }
      await super.replaceDurably(path, payload);
      if (path === this.path && this.fault === "after") {
        this.fault = null;
        throw new Error("injected after durable replace");
      }
    }
  }

  const store = new FaultStore(root, "goal-a");
  await store.storeIdentity();
  store.fault = "before";
  const unproved = await store.commitAuthority(commit(null, "operation-before", 1, 1));
  assert.equal(unproved.status, "ambiguous");
  assert.deepEqual(await store.readReceipt("operation-before"), { status: "missing" });
  assert.deepEqual(await store.loadAuthority(), { status: "missing" });

  store.fault = "after";
  const recoverable = await store.commitAuthority(commit(null, "operation-after", 1, 2));
  assert.equal(recoverable.status, "ambiguous");
  const receipt = await store.readReceipt("operation-after");
  assert.equal(receipt.status, "found");
  if (receipt.status === "found") assert.equal(receipt.receipts[0]?.lease_epoch, 2);
  const loaded = await store.loadAuthority();
  assert.equal(loaded.status, "loaded");
  if (loaded.status === "loaded") assert.equal(loaded.head.authority_revision, 1);
});
