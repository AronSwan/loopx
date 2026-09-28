import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { configure, inspect, observe } from "../../loopx/control_plane/runtime/usage_statistics.ts";
import type { Context, Post } from "../../loopx/control_plane/runtime/usage_statistics.ts";
import { AGGREGATE_SCHEMA } from "../../loopx/control_plane/runtime/usage_statistics_contract.ts";
import type { Aggregate, Counter } from "../../loopx/control_plane/runtime/usage_statistics_contract.ts";

const row: Counter = { feature: "todo", outcome: "ok", duration: "lt_1s", error: "none", count: 1 };
async function fixture(t: test.TestContext) {
  const root = await mkdtemp(join(tmpdir(), "loopx-usage-delivery-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const path = join(root, "usage-ping.json");
  const ctx: Context = { env: { LOOPX_USAGE_PING_ENDPOINT: "http://127.0.0.1:8787/v1/ping" },
    version: "1.2.2", python: "3.13", channel: "source", now: new Date("2026-09-28T23:59:00Z") };
  await configure(path, ctx, "enable");
  const state = async () => JSON.parse(await readFile(path, "utf8"));
  const generation = (await state()).generation;
  const batches: Aggregate[] = [];
  const post: Post = async (_url, payload) => {
    if (payload.schema === AGGREGATE_SCHEMA) batches.push(payload);
    return 204;
  };
  const at = (minutes: number): Context => ({ ...ctx, now: new Date(ctx.now!.getTime() + minutes * 60000) });
  return { path, ctx, state, generation, batches, post, at };
}

test("first completed command sends today; startup and settings invent no counts", async t => {
  const { path, ctx, generation, batches, post } = await fixture(t);
  await observe(path, ctx, generation, null, post);
  assert.deepEqual(batches, []);
  assert.equal((await inspect(path, ctx)).aggregate_preview, null);
  const failure: Counter = { ...row, outcome: "failed", error: "command_failed" };
  await observe(path, ctx, generation, failure, post);
  assert.deepEqual(batches, [{ schema: AGGREGATE_SCHEMA, counters: [failure] }]);
  assert.equal((await inspect(path, ctx)).aggregate_preview, null);
});

test("midnight and high call volume cannot bypass 15-minute spacing; each batch is a delta", async t => {
  const { path, ctx, generation, batches, post, at } = await fixture(t);
  await observe(path, ctx, generation, row, post);
  for (let i = 0; i < 20; i++) await observe(path, at(1), generation, row, post);
  await observe(path, at(14.999), generation, row, post);
  assert.equal(batches.length, 1);
  assert.equal((await inspect(path, at(14.999))).aggregate_preview?.counters[0].count, 21);
  await observe(path, at(15), generation, row, post);
  assert.deepEqual(batches.map(b => b.counters[0].count), [1, 22]);
  await observe(path, at(16), generation, row, post);
  await observe(path, at(30), generation, null, post);
  assert.deepEqual(batches.map(b => b.counters[0].count), [1, 22, 1]);
  await observe(path, at(45), generation, null, post);
  assert.equal(batches.length, 3, "no empty periodic requests");
});

test("upgrade flushes retained legacy counts; expired counts are dropped before a new result", async t => {
  for (const [bufferDay, count] of [["2026-09-27", 8], ["2026-09-20", 1]] as const) {
    const { path, ctx, state, generation, batches, post } = await fixture(t);
    await writeFile(path, JSON.stringify({ ...await state(), day: bufferDay, counters: [{ ...row, count: 7 }], last_attempt_day: "2026-09-28" }));
    await observe(path, ctx, generation, row, post);
    assert.deepEqual(batches, [{ schema: AGGREGATE_SCHEMA, counters: [{ ...row, count }] }]);
  }
});

test("failed sends consume the batch without retrying or uploading errors; later batches contain new counts", async t => {
  const { path, ctx, state, generation, batches, post, at } = await fixture(t);
  let attempts = 0;
  await observe(path, ctx, generation, row, async (_url, payload) => {
    if (payload.schema === AGGREGATE_SCHEMA) { attempts++; throw new Error("PRIVATE-ERROR"); }
    return 204;
  });
  assert.equal(attempts, 1);
  assert.deepEqual((await state()).counters, []);
  await observe(path, at(1), generation, row, post);
  assert.deepEqual(batches, []);
  await observe(path, at(15), generation, null, post);
  assert.deepEqual(batches, [{ schema: AGGREGATE_SCHEMA, counters: [row] }]);
  assert.ok(!(await readFile(path, "utf8")).includes("PRIVATE-ERROR"));
});

test("clock rollback neither reopens a send nor mutates buffered counts", async t => {
  const { path, ctx, generation, batches, post, at } = await fixture(t);
  await observe(path, ctx, generation, row, post);
  await observe(path, at(15), generation, row, post);
  const before = await readFile(path, "utf8");
  await observe(path, at(14), generation, row, post);
  assert.equal(await readFile(path, "utf8"), before);
  assert.equal(batches.length, 2);
});

test("concurrent observers cannot claim duplicate aggregates while HTTP remains pending", async t => {
  const { path, ctx, generation, batches, post, at } = await fixture(t);
  let release!: () => void;
  let started!: () => void;
  const held = new Promise<void>(r => { release = r; });
  const ready = new Promise<void>(r => { started = r; });
  const sending = observe(path, ctx, generation, row, async (url, payload) => {
    await post(url, payload);
    if (payload.schema === AGGREGATE_SCHEMA) { started(); await held; }
    return 204;
  });
  await ready;
  try {
    const results = await Promise.allSettled(Array.from({ length: 8 }, () => observe(path, at(1), generation, row, post)));
    for (const result of results) {
      if (result.status === "rejected") assert.equal(result.reason.code, "mutation_lock_timeout");
    }
    assert.equal(batches.length, 1);
    await configure(path, at(1), "disable");
  } finally { release(); await sending; }
  assert.equal((await inspect(path, at(1))).aggregate_preview, null);
  await observe(path, at(15), generation, row, post);
  assert.equal(batches.length, 1);
});

test("invalid persisted delivery timestamp fails closed and disable repairs it", async t => {
  const { path, ctx, state } = await fixture(t);
  const initial = await state();
  for (const value of [-1, "yesterday", 1.5, null]) {
    await writeFile(path, JSON.stringify({ ...initial, aggregate_last_attempt_ms: value }));
    await assert.rejects(inspect(path, ctx), /usage_state_invalid/);
  }
  await configure(path, ctx, "disable");
  assert.equal((await inspect(path, ctx)).blocked_by, "disabled");
});

test("a malformed legacy buffer cannot bypass outgoing aggregate validation", async t => {
  const { path, ctx, state, generation, batches, post } = await fixture(t);
  await writeFile(path, JSON.stringify({ ...await state(), day: "2026-09-27", counters: [row, row] }));
  await observe(path, ctx, generation, null, post);
  assert.deepEqual(batches, [], "duplicate counter keys are not a valid wire payload");
});
