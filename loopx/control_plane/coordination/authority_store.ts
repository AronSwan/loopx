import type { JsonObject } from "../effect_program.ts";

export const AUTHORITY_STORE_CAPABILITIES = [
  "atomic_event_projection_receipt_commit",
  "compare_and_swap",
  "durable_readback",
  "opaque_revision",
  "ordered_cursor_scan",
  "stable_store_identity",
] as const;
export type AuthorityStoreCapability =
  (typeof AUTHORITY_STORE_CAPABILITIES)[number];

export const AUTHORITY_STORE_PROVIDER_CONFORMANCE = {
  file: AUTHORITY_STORE_CAPABILITIES,
  nokv: AUTHORITY_STORE_CAPABILITIES,
  postgresql: AUTHORITY_STORE_CAPABILITIES,
} as const satisfies Record<
  "file" | "nokv" | "postgresql",
  readonly AuthorityStoreCapability[]
>;

/** Provider-neutral persistence seam for one goal's shared authority. */
export interface AuthorityStoreCommit {
  expected_provider_revision: string | null;
  operation_id: string;
  events: readonly JsonObject[];
  next_projection: JsonObject;
  receipts: readonly JsonObject[];
}

export interface AuthorityStoreHead {
  head: JsonObject | null;
  provider_revision: string | null;
  cursor: string | null;
}

export interface AuthorityStoreCommittedTransaction {
  cursor: string;
  provider_revision: string;
  operation_id: string;
  events: readonly JsonObject[];
  projection: JsonObject;
  receipts: readonly JsonObject[];
}

export type AuthorityStoreCommitResult =
  | { status: "applied"; provider_revision: string; cursor: string }
  | {
    status: "conflict";
    current_provider_revision: string | null;
    current_cursor: string | null;
  }
  | { status: "ambiguous"; reason: string }
  | { status: "failed"; reason: string };

export interface AuthorityStore {
  storeIdentity(): Promise<string>;
  loadAuthority(): Promise<AuthorityStoreHead>;
  commitAuthority(commit: AuthorityStoreCommit): Promise<AuthorityStoreCommitResult>;
  readReceipt(operationId: string): Promise<readonly JsonObject[] | null>;
  scanCommitted(
    afterCursor: string | null,
    limit: number,
  ): Promise<readonly AuthorityStoreCommittedTransaction[]>;
}
