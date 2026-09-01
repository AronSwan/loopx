import { createHash, randomUUID } from "node:crypto";
import { mkdir, open, readFile, rename, rm } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";

import type { JsonObject } from "../effect_program.ts";
import { EffectRuntimeLockTimeoutError } from "../effect_runtime_errors.ts";
import { withFileMutationLock } from "../effect_runtime_io.ts";
import type {
  AuthorityStore,
  AuthorityStoreCommit,
  AuthorityStoreCommittedTransaction,
  AuthorityStoreCommitResult,
  AuthorityStoreIdentityResult,
  AuthorityStoreLoadResult,
  AuthorityStoreReadFailure,
  AuthorityStoreReceiptResult,
  AuthorityStoreScanResult,
} from "./authority_store.ts";

const FILE_AUTHORITY_STORE_SCHEMA = "loopx_file_authority_store_v0";
const STORE_IDENTITY_PATTERN = /^file:[0-9a-f]{32}$/;

interface FileAuthorityStoreDocument extends JsonObject {
  schema_version: typeof FILE_AUTHORITY_STORE_SCHEMA;
  goal_id: string;
  provider_revision: string;
  cursor: string;
  store_identity: string;
  head: JsonObject;
  committed: AuthorityStoreCommittedTransaction[];
}

class FileStoreProtocolError extends Error {}
class FileStoreUnavailableError extends Error {}

function isObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasExactKeys(value: JsonObject, keys: readonly string[]): boolean {
  const actual = Object.keys(value).sort(pythonUnicodeCompare);
  const expected = [...keys].sort(pythonUnicodeCompare);
  return actual.length === expected.length &&
    actual.every((key, index) => key === expected[index]);
}

function requireNonEmpty(value: unknown, name: string): string {
  if (typeof value !== "string" || value.trim() !== value || value.length === 0) {
    throw new FileStoreProtocolError(`${name} must be a non-empty trimmed string`);
  }
  return value;
}

function pythonUnicodeCompare(left: string, right: string): number {
  const leftPoints = Array.from(left, (item) => item.codePointAt(0) ?? 0);
  const rightPoints = Array.from(right, (item) => item.codePointAt(0) ?? 0);
  const shared = Math.min(leftPoints.length, rightPoints.length);
  for (let index = 0; index < shared; index += 1) {
    const difference = leftPoints[index] - rightPoints[index];
    if (difference !== 0) return difference;
  }
  return leftPoints.length - rightPoints.length;
}

function canonicalJson(value: unknown, stack = new Set<object>()): unknown {
  if (value === null || typeof value === "string" || typeof value === "boolean") {
    return value;
  }
  if (typeof value === "number") {
    if (!Number.isFinite(value)) throw new FileStoreProtocolError("JSON numbers must be finite");
    return value;
  }
  if (Array.isArray(value)) {
    if (stack.has(value)) throw new FileStoreProtocolError("JSON value must be acyclic");
    stack.add(value);
    try {
      return value.map((item) => canonicalJson(item, stack));
    } finally {
      stack.delete(value);
    }
  }
  if (!isObject(value)) throw new FileStoreProtocolError("value must be strict JSON");
  const prototype = Object.getPrototypeOf(value);
  if (prototype !== Object.prototype && prototype !== null) {
    throw new FileStoreProtocolError("JSON objects must be plain objects");
  }
  if (stack.has(value)) throw new FileStoreProtocolError("JSON value must be acyclic");
  stack.add(value);
  try {
    return Object.fromEntries(
      Object.keys(value).sort(pythonUnicodeCompare).map((key) => [
        key,
        canonicalJson(value[key], stack),
      ]),
    );
  } finally {
    stack.delete(value);
  }
}

function canonicalObject(value: unknown, name: string): JsonObject {
  if (!isObject(value)) throw new FileStoreProtocolError(`${name} must be an object`);
  return canonicalJson(value) as JsonObject;
}

function canonicalObjectList(value: unknown, name: string): JsonObject[] {
  if (!Array.isArray(value)) throw new FileStoreProtocolError(`${name} must be an array`);
  return value.map((item, index) => canonicalObject(item, `${name}[${index}]`));
}

function canonicalBytes(value: unknown): Buffer {
  return Buffer.from(JSON.stringify(canonicalJson(value)), "utf8");
}

function parseCursor(value: string | null): bigint {
  if (value === null) return 0n;
  if (!/^[1-9]\d*$/.test(value)) throw new FileStoreProtocolError("provider cursor is invalid");
  return BigInt(value);
}

function cloneTransaction(
  value: AuthorityStoreCommittedTransaction,
): AuthorityStoreCommittedTransaction {
  return structuredClone(value);
}

function transactionWithoutRevision(value: AuthorityStoreCommittedTransaction) {
  return {
    cursor: value.cursor,
    operation_id: value.operation_id,
    events: value.events,
    projection: value.projection,
    receipts: value.receipts,
  };
}

function providerRevision(
  goalId: string,
  storeIdentity: string,
  previousRevision: string | null,
  transaction: ReturnType<typeof transactionWithoutRevision>,
): string {
  const digest = createHash("sha256")
    .update(canonicalBytes({
      goal_id: goalId,
      store_identity: storeIdentity,
      previous_provider_revision: previousRevision,
      transaction,
    }))
    .digest("hex")
    .slice(0, 24);
  return `file:${transaction.cursor}:${digest}`;
}

async function syncDirectory(directory: string): Promise<void> {
  if (process.platform === "win32") return;
  const handle = await open(directory, "r");
  try {
    await handle.sync();
  } finally {
    await handle.close();
  }
}

async function durableReplace(path: string, payload: Uint8Array): Promise<void> {
  const directory = dirname(path);
  await mkdir(directory, { recursive: true, mode: 0o700 });
  const temporary = `${path}.tmp-${process.pid}-${randomUUID()}`;
  const handle = await open(temporary, "wx", 0o600);
  try {
    try {
      await handle.writeFile(payload);
      await handle.sync();
    } finally {
      await handle.close();
    }
    await rename(temporary, path);
    await syncDirectory(directory);
  } finally {
    await rm(temporary, { force: true });
  }
}

function decodeTransaction(value: unknown): AuthorityStoreCommittedTransaction {
  if (!isObject(value) || !hasExactKeys(value, [
    "cursor", "provider_revision", "operation_id", "events", "projection", "receipts",
  ])) throw new FileStoreProtocolError("committed transaction is invalid");
  return {
    cursor: requireNonEmpty(value.cursor, "transaction cursor"),
    provider_revision: requireNonEmpty(
      value.provider_revision,
      "transaction provider revision",
    ),
    operation_id: requireNonEmpty(value.operation_id, "operation id"),
    events: canonicalObjectList(value.events, "transaction events"),
    projection: canonicalObject(value.projection, "transaction projection"),
    receipts: canonicalObjectList(value.receipts, "transaction receipts"),
  };
}

function decodeDocument(
  value: unknown,
  goalId: string,
  storeIdentity: string,
): FileAuthorityStoreDocument {
  if (!isObject(value) || !hasExactKeys(value, [
    "schema_version", "goal_id", "provider_revision", "cursor", "store_identity",
    "head", "committed",
  ]) || value.schema_version !== FILE_AUTHORITY_STORE_SCHEMA) {
    throw new FileStoreProtocolError("file authority store schema mismatch");
  }
  if (value.goal_id !== goalId) throw new FileStoreProtocolError("file authority store goal mismatch");
  if (value.store_identity !== storeIdentity) {
    throw new FileStoreProtocolError("file authority store lineage mismatch");
  }
  const revision = requireNonEmpty(value.provider_revision, "provider revision");
  const cursor = requireNonEmpty(value.cursor, "provider cursor");
  const head = canonicalObject(value.head, "file authority store head");
  if (!Array.isArray(value.committed)) {
    throw new FileStoreProtocolError("file authority store history is invalid");
  }
  const committed = value.committed.map(decodeTransaction);
  if (committed.length === 0 || parseCursor(cursor) !== BigInt(committed.length)) {
    throw new FileStoreProtocolError("file authority store lineage is invalid");
  }
  let previousRevision: string | null = null;
  const operationIds = new Set<string>();
  for (const [index, entry] of committed.entries()) {
    if (parseCursor(entry.cursor) !== BigInt(index + 1)) {
      throw new FileStoreProtocolError("file authority store cursor lineage is invalid");
    }
    if (operationIds.has(entry.operation_id)) {
      throw new FileStoreProtocolError("file authority store operation identity is duplicated");
    }
    operationIds.add(entry.operation_id);
    const expectedRevision = providerRevision(
      goalId,
      storeIdentity,
      previousRevision,
      transactionWithoutRevision(entry),
    );
    if (entry.provider_revision !== expectedRevision) {
      throw new FileStoreProtocolError("file authority store revision lineage is invalid");
    }
    previousRevision = entry.provider_revision;
  }
  const last = committed.at(-1)!;
  if (
    last.cursor !== cursor || last.provider_revision !== revision ||
    !canonicalBytes(last.projection).equals(canonicalBytes(head))
  ) throw new FileStoreProtocolError("file authority store head lineage is invalid");
  return {
    schema_version: FILE_AUTHORITY_STORE_SCHEMA,
    goal_id: goalId,
    store_identity: storeIdentity,
    provider_revision: revision,
    cursor,
    head,
    committed,
  };
}

function normalizeCommit(commit: AuthorityStoreCommit): AuthorityStoreCommit {
  const expectedRevision = commit.expected_provider_revision;
  if (
    expectedRevision !== null &&
    (typeof expectedRevision !== "string" || expectedRevision.length === 0)
  ) throw new FileStoreProtocolError("expected provider revision is invalid");
  return {
    expected_provider_revision: expectedRevision,
    operation_id: requireNonEmpty(commit.operation_id, "operation id"),
    events: canonicalObjectList(commit.events, "events"),
    next_projection: canonicalObject(commit.next_projection, "projection"),
    receipts: canonicalObjectList(commit.receipts, "receipts"),
  };
}

function readFailure(error: unknown): AuthorityStoreReadFailure {
  if (error instanceof FileStoreProtocolError || error instanceof SyntaxError) {
    return { status: "failed", reason_code: "provider_protocol_violation", reason: error.message };
  }
  return {
    status: "unavailable",
    reason_code: "provider_read_unavailable",
    reason: error instanceof Error ? error.message : "provider read unavailable",
  };
}

/** File-backed Stage 1 conformance provider; LoopX owns all domain decisions. */
export class FileAuthorityStore implements AuthorityStore {
  readonly goalId: string;
  readonly directory: string;
  readonly path: string;
  readonly identityPath: string;

  constructor(directory: string, goalId: string) {
    this.goalId = requireNonEmpty(goalId, "goal id");
    if (typeof directory !== "string" || directory.length === 0) {
      throw new FileStoreProtocolError("store directory is required");
    }
    this.directory = resolve(directory);
    const digest = createHash("sha256").update(goalId, "utf8").digest("hex").slice(0, 16);
    this.path = join(this.directory, `authority-store-${digest}.json`);
    this.identityPath = join(this.directory, "store-identity");
  }

  /** Narrow effect seam for crash-window qualification; not a semantic hook. */
  protected async replaceDurably(path: string, payload: Uint8Array): Promise<void> {
    await durableReplace(path, payload);
  }

  private async readStoreIdentity(): Promise<string> {
    try {
      const identity = await readFile(this.identityPath, "utf8");
      if (!STORE_IDENTITY_PATTERN.test(identity)) {
        throw new FileStoreProtocolError("store identity does not match file:<32 lowercase hex>");
      }
      await syncDirectory(this.directory);
      return identity;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
    }
    return await withFileMutationLock(this.identityPath, async () => {
      try {
        const identity = await readFile(this.identityPath, "utf8");
        if (!STORE_IDENTITY_PATTERN.test(identity)) {
          throw new FileStoreProtocolError("store identity does not match file:<32 lowercase hex>");
        }
        await syncDirectory(this.directory);
        return identity;
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
      }
      const identity = `file:${randomUUID().replaceAll("-", "")}`;
      await this.replaceDurably(this.identityPath, Buffer.from(identity, "ascii"));
      return identity;
    });
  }

  async storeIdentity(): Promise<AuthorityStoreIdentityResult> {
    try {
      return { status: "available", store_identity: await this.readStoreIdentity() };
    } catch (error) {
      if (error instanceof FileStoreProtocolError) {
        return { status: "failed", reason_code: "store_identity_invalid", reason: error.message };
      }
      return {
        status: "unavailable",
        reason_code: error instanceof EffectRuntimeLockTimeoutError
          ? "store_identity_lock_timeout"
          : "store_identity_unavailable",
        reason: error instanceof Error ? error.message : "store identity unavailable",
      };
    }
  }

  private async readDocument(): Promise<FileAuthorityStoreDocument | null> {
    let raw: string;
    try {
      raw = await readFile(this.path, "utf8");
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") return null;
      throw new FileStoreUnavailableError(
        error instanceof Error ? error.message : "authority document unavailable",
      );
    }
    const identity = await this.readStoreIdentity();
    try {
      return decodeDocument(JSON.parse(raw), this.goalId, identity);
    } catch (error) {
      if (error instanceof SyntaxError) {
        throw new FileStoreProtocolError(`file authority store JSON is invalid: ${error.message}`);
      }
      throw error;
    }
  }

  async loadAuthority(): Promise<AuthorityStoreLoadResult> {
    try {
      const document = await this.readDocument();
      return document
        ? {
          status: "loaded",
          head: structuredClone(document.head),
          provider_revision: document.provider_revision,
          cursor: document.cursor,
        }
        : { status: "missing" };
    } catch (error) {
      return readFailure(error);
    }
  }

  async commitAuthority(commit: AuthorityStoreCommit): Promise<AuthorityStoreCommitResult> {
    let normalized: AuthorityStoreCommit;
    try {
      normalized = normalizeCommit(commit);
    } catch (error) {
      return {
        status: "failed",
        reason_code: "invalid_commit_request",
        reason: error instanceof Error ? error.message : "invalid commit request",
      };
    }
    try {
      return await withFileMutationLock(this.path, async () => {
        let identity: string;
        let current: FileAuthorityStoreDocument | null;
        try {
          // Read the identity under the same document lock used by the commit.
          // A restored directory must not race a missing-head bootstrap and
          // bind new authority bytes to an identity observed before the lock.
          identity = await this.readStoreIdentity();
          current = await this.readDocument();
        } catch (error) {
          return {
            status: "failed",
            reason_code: error instanceof FileStoreProtocolError
              ? "provider_protocol_violation"
              : "provider_read_unavailable",
            reason: error instanceof Error ? error.message : "provider read unavailable",
          };
        }
        if ((current?.provider_revision ?? null) !== normalized.expected_provider_revision) {
          return {
            status: "conflict",
            conflict_kind: "provider_revision_mismatch",
            current_provider_revision: current?.provider_revision ?? null,
            current_cursor: current?.cursor ?? null,
          };
        }
        if (current?.committed.some((entry) => entry.operation_id === normalized.operation_id)) {
          return {
            status: "conflict",
            conflict_kind: "operation_id_exists",
            current_provider_revision: current.provider_revision,
            current_cursor: current.cursor,
          };
        }
        const cursor = (parseCursor(current?.cursor ?? null) + 1n).toString();
        const base = {
          cursor,
          operation_id: normalized.operation_id,
          events: normalized.events,
          projection: normalized.next_projection,
          receipts: normalized.receipts,
        };
        const revision = providerRevision(
          this.goalId,
          identity,
          current?.provider_revision ?? null,
          base,
        );
        const transaction: AuthorityStoreCommittedTransaction = {
          ...base,
          provider_revision: revision,
        };
        const document: FileAuthorityStoreDocument = {
          schema_version: FILE_AUTHORITY_STORE_SCHEMA,
          goal_id: this.goalId,
          store_identity: identity,
          provider_revision: revision,
          cursor,
          head: normalized.next_projection,
          committed: [...(current?.committed ?? []), transaction],
        };
        try {
          await this.replaceDurably(this.path, canonicalBytes(document));
        } catch (error) {
          return {
            status: "ambiguous",
            reason_code: "commit_outcome_unknown",
            reason: error instanceof Error ? error.message : "commit outcome unknown",
          };
        }
        return { status: "applied", provider_revision: revision, cursor };
      });
    } catch (error) {
      return {
        status: "failed",
        reason_code: error instanceof EffectRuntimeLockTimeoutError
          ? "provider_lock_timeout"
          : "provider_write_unavailable",
        reason: error instanceof Error ? error.message : "provider write unavailable",
      };
    }
  }

  async readReceipt(operationId: string): Promise<AuthorityStoreReceiptResult> {
    let normalized: string;
    try {
      normalized = requireNonEmpty(operationId, "operation id");
    } catch (error) {
      return {
        status: "failed",
        reason_code: "invalid_operation_id",
        reason: error instanceof Error ? error.message : "invalid operation id",
      };
    }
    try {
      const transaction = (await this.readDocument())?.committed.find(
        (entry) => entry.operation_id === normalized,
      );
      return transaction
        ? {
          status: "found",
          cursor: transaction.cursor,
          provider_revision: transaction.provider_revision,
          receipts: structuredClone(transaction.receipts),
        }
        : { status: "missing" };
    } catch (error) {
      return readFailure(error);
    }
  }

  async scanCommitted(afterCursor: string | null, limit: number): Promise<AuthorityStoreScanResult> {
    let offset: bigint;
    try {
      offset = parseCursor(afterCursor);
      if (!Number.isSafeInteger(limit) || limit < 1) {
        throw new FileStoreProtocolError("scan limit must be a positive safe integer");
      }
    } catch (error) {
      return {
        status: "failed",
        reason_code: "invalid_scan_request",
        reason: error instanceof Error ? error.message : "invalid scan request",
      };
    }
    try {
      const document = await this.readDocument();
      if (!document) {
        return { status: "page", transactions: [], next_cursor: afterCursor, has_more: false };
      }
      const headCursor = parseCursor(document.cursor);
      if (offset > headCursor || offset > BigInt(Number.MAX_SAFE_INTEGER)) {
        return {
          status: "failed",
          reason_code: "scan_cursor_out_of_range",
          reason: "scan cursor is ahead of the provider head",
        };
      }
      const start = Number(offset);
      const transactions = document.committed.slice(start, start + limit).map(cloneTransaction);
      return {
        status: "page",
        transactions,
        next_cursor: transactions.at(-1)?.cursor ?? afterCursor,
        has_more: start + transactions.length < document.committed.length,
      };
    } catch (error) {
      return readFailure(error);
    }
  }
}
