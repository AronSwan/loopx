import { createHash, randomUUID } from "node:crypto";
import { mkdir, open, readFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";

import type { JsonObject } from "../effect_program.ts";
import { atomicWriteJson, withFileMutationLock } from "../effect_runtime_io.ts";
import type {
  AuthorityStore,
  AuthorityStoreCommit,
  AuthorityStoreCommittedTransaction,
  AuthorityStoreCommitResult,
  AuthorityStoreHead,
} from "./authority_store.ts";

const FILE_AUTHORITY_STORE_SCHEMA = "loopx_file_authority_store_v0";

interface FileAuthorityStoreDocument extends JsonObject {
  schema_version: typeof FILE_AUTHORITY_STORE_SCHEMA;
  goal_id: string;
  provider_revision: string;
  cursor: string;
  store_identity: string;
  head: JsonObject;
  committed: AuthorityStoreCommittedTransaction[];
}

function isObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function requireNonEmpty(value: unknown, name: string): string {
  if (typeof value !== "string" || value.trim() !== value || value.length === 0) {
    throw new Error(`${name} must be a non-empty trimmed string`);
  }
  return value;
}

function parseCursor(value: string | null): number {
  if (value === null) return 0;
  if (!/^[1-9]\d*$/.test(value)) throw new Error("provider cursor is invalid");
  const cursor = Number(value);
  if (!Number.isSafeInteger(cursor)) throw new Error("provider cursor is invalid");
  return cursor;
}

function stableValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(stableValue);
  if (!isObject(value)) return value;
  return Object.fromEntries(
    Object.entries(value)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, child]) => [key, stableValue(child)]),
  );
}

function cloneTransaction(
  value: AuthorityStoreCommittedTransaction,
): AuthorityStoreCommittedTransaction {
  return structuredClone(value);
}

function providerRevision(
  goalId: string,
  cursor: string,
  transaction: Omit<AuthorityStoreCommittedTransaction, "provider_revision">,
): string {
  const digest = createHash("sha256")
    .update(JSON.stringify(stableValue({ goal_id: goalId, ...transaction })))
    .digest("hex")
    .slice(0, 24);
  return `file:${cursor}:${digest}`;
}

function decodeTransaction(value: unknown): AuthorityStoreCommittedTransaction {
  if (!isObject(value)) throw new Error("committed transaction is invalid");
  if (!Array.isArray(value.events) || !value.events.every(isObject)) {
    throw new Error("transaction events are invalid");
  }
  if (!isObject(value.projection)) throw new Error("transaction projection is invalid");
  if (!Array.isArray(value.receipts) || !value.receipts.every(isObject)) {
    throw new Error("transaction receipts are invalid");
  }
  return {
    cursor: requireNonEmpty(value.cursor, "transaction cursor"),
    provider_revision: requireNonEmpty(value.provider_revision, "transaction provider revision"),
    operation_id: requireNonEmpty(value.operation_id, "operation id"),
    events: structuredClone(value.events),
    projection: structuredClone(value.projection),
    receipts: structuredClone(value.receipts),
  };
}

function decodeDocument(
  value: unknown,
  goalId: string,
  storeIdentity: string,
): FileAuthorityStoreDocument {
  if (!isObject(value) || value.schema_version !== FILE_AUTHORITY_STORE_SCHEMA) {
    throw new Error("file authority store schema mismatch");
  }
  if (value.goal_id !== goalId) throw new Error("file authority store goal mismatch");
  if (value.store_identity !== storeIdentity) {
    throw new Error("file authority store lineage mismatch");
  }
  const revision = requireNonEmpty(value.provider_revision, "provider revision");
  const cursor = requireNonEmpty(value.cursor, "provider cursor");
  if (!isObject(value.head)) throw new Error("file authority store head is invalid");
  if (!Array.isArray(value.committed)) throw new Error("file authority store history is invalid");
  const committed = value.committed.map(decodeTransaction);
  const last = committed.at(-1);
  if (
    committed.length !== parseCursor(cursor) || !last || last.cursor !== cursor ||
    last.provider_revision !== revision ||
    JSON.stringify(stableValue(last.projection)) !== JSON.stringify(stableValue(value.head)) ||
    committed.some((entry, index) => parseCursor(entry.cursor) !== index + 1)
  ) throw new Error("file authority store lineage is invalid");
  return {
    schema_version: FILE_AUTHORITY_STORE_SCHEMA,
    goal_id: goalId,
    store_identity: storeIdentity,
    provider_revision: revision,
    cursor,
    head: structuredClone(value.head),
    committed,
  };
}

function validateCommit(commit: AuthorityStoreCommit): void {
  if (
    commit.expected_provider_revision !== null &&
    (typeof commit.expected_provider_revision !== "string" ||
      commit.expected_provider_revision.length === 0)
  ) throw new Error("expected provider revision is invalid");
  requireNonEmpty(commit.operation_id, "operation id");
  if (!Array.isArray(commit.events) || !commit.events.every(isObject)) {
    throw new Error("events are invalid");
  }
  if (!isObject(commit.next_projection)) throw new Error("projection is invalid");
  if (!Array.isArray(commit.receipts) || !commit.receipts.every(isObject)) {
    throw new Error("receipts are invalid");
  }
}

/** File-backed conformance provider; domain decisions stay in LoopX authority. */
export class FileAuthorityStore implements AuthorityStore {
  readonly goalId: string;
  readonly path: string;
  readonly identityPath: string;

  constructor(goalId: string, path: string) {
    this.goalId = requireNonEmpty(goalId, "goal id");
    if (typeof path !== "string" || path.length === 0) throw new Error("store path is required");
    this.path = resolve(path);
    this.identityPath = `${this.path}.identity`;
  }

  async storeIdentity(): Promise<string> {
    return await withFileMutationLock(this.identityPath, async () => {
      try {
        return requireNonEmpty(await readFile(this.identityPath, "utf8"), "store identity");
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
      }
      await mkdir(dirname(this.identityPath), { recursive: true, mode: 0o700 });
      const identity = `file:${randomUUID()}`;
      const handle = await open(this.identityPath, "wx", 0o600);
      try {
        await handle.writeFile(identity, "utf8");
        await handle.sync();
      } finally {
        await handle.close();
      }
      const directory = await open(dirname(this.identityPath), "r");
      try {
        await directory.sync();
      } finally {
        await directory.close();
      }
      return identity;
    });
  }

  private async readDocument(): Promise<FileAuthorityStoreDocument | null> {
    try {
      return decodeDocument(
        JSON.parse(await readFile(this.path, "utf8")),
        this.goalId,
        await this.storeIdentity(),
      );
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") return null;
      throw error;
    }
  }

  async loadAuthority(): Promise<AuthorityStoreHead> {
    const document = await this.readDocument();
    return document ? {
      head: structuredClone(document.head),
      provider_revision: document.provider_revision,
      cursor: document.cursor,
    } : { head: null, provider_revision: null, cursor: null };
  }

  async commitAuthority(commit: AuthorityStoreCommit): Promise<AuthorityStoreCommitResult> {
    validateCommit(commit);
    const storeIdentity = await this.storeIdentity();
    return await withFileMutationLock(this.path, async () => {
      const current = await this.readDocument();
      if ((current?.provider_revision ?? null) !== commit.expected_provider_revision) {
        return {
          status: "conflict",
          current_provider_revision: current?.provider_revision ?? null,
          current_cursor: current?.cursor ?? null,
        };
      }
      const cursor = String(parseCursor(current?.cursor ?? null) + 1);
      const base = {
        cursor,
        operation_id: commit.operation_id,
        events: structuredClone(commit.events),
        projection: structuredClone(commit.next_projection),
        receipts: structuredClone(commit.receipts),
      };
      const revision = providerRevision(this.goalId, cursor, base);
      const transaction: AuthorityStoreCommittedTransaction = {
        ...base,
        provider_revision: revision,
      };
      const document: FileAuthorityStoreDocument = {
        schema_version: FILE_AUTHORITY_STORE_SCHEMA,
        goal_id: this.goalId,
        store_identity: storeIdentity,
        provider_revision: revision,
        cursor,
        head: structuredClone(commit.next_projection),
        committed: [...(current?.committed ?? []), transaction],
      };
      // atomicWriteJson performs complete temp-file write, fsync, then rename.
      // Persisting the projection and its receipts in this one document keeps
      // the file conformance provider from exposing either half alone.
      await atomicWriteJson(this.path, stableValue(document) as JsonObject);
      return { status: "applied", provider_revision: revision, cursor };
    });
  }

  async readReceipt(operationId: string): Promise<readonly JsonObject[] | null> {
    requireNonEmpty(operationId, "operation id");
    const transaction = (await this.readDocument())?.committed.find(
      (entry) => entry.operation_id === operationId,
    );
    return transaction ? structuredClone(transaction.receipts) : null;
  }

  async scanCommitted(
    afterCursor: string | null,
    limit: number,
  ): Promise<readonly AuthorityStoreCommittedTransaction[]> {
    const offset = parseCursor(afterCursor);
    if (!Number.isSafeInteger(limit) || limit < 1) {
      throw new Error("scan limit must be a positive safe integer");
    }
    const document = await this.readDocument();
    if (!document) return [];
    if (offset > parseCursor(document.cursor)) throw new Error("scan cursor is ahead of the provider head");
    return document.committed.slice(offset, offset + limit).map(cloneTransaction);
  }
}
