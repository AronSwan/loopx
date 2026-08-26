import type { JsonObject } from "./effect_program.ts";
import {
  requireInteger,
  requireJsonObject as requiredObject,
  requireNonEmptyString as requiredString,
  requireStringArray,
} from "./runtime_decode.ts";
import { projectRepositoryDeliveryGate } from "./work_items/repository_delivery.ts";

export const CAPABILITY_HOOK_REGISTRATION_SCHEMA_VERSION =
  "loopx_capability_hook_registration_v0";
export const INTERACTION_PROJECTION_HOOK_RESULT_SCHEMA_VERSION =
  "loopx_interaction_projection_hook_result_v0";
export const TURN_START_HOOK_REGISTRATION_SCHEMA_VERSION =
  "loopx_turn_start_capability_hook_registration_v0";
export const TURN_START_HOOK_RESULT_SCHEMA_VERSION =
  "loopx_turn_start_capability_hook_result_v0";
export const POST_WRITEBACK_HOOK_REGISTRATION_SCHEMA_VERSION =
  "loopx_post_writeback_capability_hook_registration_v0";
export const POST_WRITEBACK_HOOK_RESULT_SCHEMA_VERSION =
  "loopx_post_writeback_capability_hook_result_v0";

const REGISTRATION_FIELDS = new Set([
  "schema_version",
  "hook_id",
  "capability_id",
  "phase",
  "projection_slots",
  "budget",
  "failure_policy",
  "requested_read_scope",
  "requested_write_scope",
]);
const BUDGET_FIELDS = new Set([
  "max_invocations_per_dispatch",
  "max_result_bytes",
]);
const RESULT_FIELDS = new Set([
  "schema_version",
  "hook_id",
  "capability_id",
  "phase",
  "status",
  "projection_slot",
  "payload",
]);
const TURN_START_REGISTRATION_FIELDS = new Set([
  "schema_version",
  "hook_id",
  "capability_id",
  "phase",
  "budget",
  "failure_policy",
  "requested_read_scope",
  "requested_write_scope",
]);
const TURN_START_RESULT_FIELDS = new Set([
  "schema_version",
  "hook_id",
  "capability_id",
  "phase",
  "status",
  "observation_count",
  "agent_read_required",
  "external_reads_performed",
  "external_writes_performed",
  "local_private_state_mutated",
  "private_content_returned",
  "provider_payload_returned",
  "error_code",
]);
const TURN_START_WRITE_SCOPES = new Set([
  "owner_private_inbox",
  "owner_private_cursor",
  "provider_message_reaction",
]);
const TURN_START_STATUSES = new Set([
  "not_applicable",
  "observed",
  "empty",
  "partial",
  "unavailable",
  "failed",
]);
const POST_WRITEBACK_REGISTRATION_FIELDS = new Set([
  "schema_version",
  "hook_id",
  "capability_id",
  "phase",
  "subscribed_event_kinds",
  "budget",
  "failure_policy",
  "requested_read_scope",
  "requested_write_scope",
]);
const POST_WRITEBACK_RESULT_FIELDS = new Set([
  "schema_version",
  "hook_id",
  "capability_id",
  "phase",
  "status",
  "intent_kind",
  "idempotency_key",
  "intent",
  "error_code",
]);
const POST_WRITEBACK_STATUSES = new Set([
  "not_applicable",
  "intent_ready",
  "failed",
]);
const TOKEN_RE = /^[a-z][a-z0-9_.:-]{2,95}$/;

function requireExactFields(
  value: JsonObject,
  expected: ReadonlySet<string>,
  label: string,
): void {
  const fields = Object.keys(value);
  if (
    fields.length !== expected.size ||
    fields.some((field) => !expected.has(field))
  ) {
    throw new Error(`${label} fields are invalid`);
  }
}

function boundedTokens(
  value: unknown,
  label: string,
  limit: number,
): string[] {
  const tokens = requireStringArray(value, label);
  if (
    tokens.length > limit ||
    new Set(tokens).size !== tokens.length ||
    tokens.some((token) => !TOKEN_RE.test(token))
  ) {
    throw new Error(`${label} contains invalid tokens`);
  }
  return tokens;
}

export function validateInteractionProjectionHookRegistration(
  value: unknown,
): JsonObject & {
  hook_id: string;
  capability_id: string;
  projection_slots: string[];
  max_result_bytes: number;
} {
  const registration = requiredObject(value, "capability hook registration");
  requireExactFields(
    registration,
    REGISTRATION_FIELDS,
    "capability hook registration",
  );
  if (
    registration.schema_version !==
      CAPABILITY_HOOK_REGISTRATION_SCHEMA_VERSION ||
    registration.phase !== "interaction_projection" ||
    registration.failure_policy !== "isolate"
  ) {
    throw new Error("capability hook registration contract is invalid");
  }
  const hookId = requiredString(registration.hook_id, "capability hook hook_id");
  const capabilityId = requiredString(
    registration.capability_id,
    "capability hook capability_id",
  );
  if (!TOKEN_RE.test(hookId) || !TOKEN_RE.test(capabilityId)) {
    throw new Error("capability hook identity is invalid");
  }
  const projectionSlots = boundedTokens(
    registration.projection_slots,
    "capability hook projection_slots",
    8,
  );
  if (projectionSlots.length === 0) {
    throw new Error("capability hook projection_slots cannot be empty");
  }
  boundedTokens(
    registration.requested_read_scope,
    "capability hook requested_read_scope",
    16,
  );
  const writeScope = boundedTokens(
    registration.requested_write_scope,
    "capability hook requested_write_scope",
    16,
  );
  if (writeScope.length > 0) {
    throw new Error("interaction projection hooks cannot request write scope");
  }
  const budget = requiredObject(registration.budget, "capability hook budget");
  requireExactFields(budget, BUDGET_FIELDS, "capability hook budget");
  const maxInvocations = requireInteger(
    budget.max_invocations_per_dispatch,
    "capability hook max_invocations_per_dispatch",
  );
  const maxResultBytes = requireInteger(
    budget.max_result_bytes,
    "capability hook max_result_bytes",
  );
  if (maxInvocations !== 1 || maxResultBytes < 1024 || maxResultBytes > 65_536) {
    throw new Error("capability hook budget is outside the admitted envelope");
  }
  return {
    ...registration,
    hook_id: hookId,
    capability_id: capabilityId,
    projection_slots: projectionSlots,
    max_result_bytes: maxResultBytes,
  };
}

export function validateInteractionProjectionHookInvocation(input: {
  registration: unknown;
  result: unknown;
}): JsonObject {
  const registration = validateInteractionProjectionHookRegistration(
    input.registration,
  );
  const result = requiredObject(input.result, "capability hook result");
  requireExactFields(result, RESULT_FIELDS, "capability hook result");
  if (
    result.schema_version !== INTERACTION_PROJECTION_HOOK_RESULT_SCHEMA_VERSION ||
    result.hook_id !== registration.hook_id ||
    result.capability_id !== registration.capability_id ||
    result.phase !== "interaction_projection"
  ) {
    throw new Error("capability hook result identity is invalid");
  }
  if (
    new TextEncoder().encode(JSON.stringify(result)).byteLength >
      registration.max_result_bytes
  ) {
    throw new Error("capability hook result exceeds its budget");
  }
  if (result.status === "not_applicable") {
    if (result.projection_slot !== null || result.payload !== null) {
      throw new Error("not-applicable capability hook result must be empty");
    }
    return {
      schema_version: INTERACTION_PROJECTION_HOOK_RESULT_SCHEMA_VERSION,
      hook_id: registration.hook_id,
      capability_id: registration.capability_id,
      phase: "interaction_projection",
      status: "not_applicable",
      projection_slot: null,
      projection: null,
    };
  }
  if (result.status !== "candidate") {
    throw new Error("capability hook result status is invalid");
  }
  const slot = requiredString(
    result.projection_slot,
    "capability hook projection_slot",
  );
  if (!registration.projection_slots.includes(slot)) {
    throw new Error("capability hook projection_slot is not registered");
  }
  let projection: JsonObject | null;
  switch (slot) {
    case "repository_delivery":
      projection = projectRepositoryDeliveryGate(result.payload);
      break;
    default:
      throw new Error("capability hook projection_slot is unsupported");
  }
  return {
    schema_version: INTERACTION_PROJECTION_HOOK_RESULT_SCHEMA_VERSION,
    hook_id: registration.hook_id,
    capability_id: registration.capability_id,
    phase: "interaction_projection",
    status: projection ? "projected" : "not_applicable",
    projection_slot: projection ? slot : null,
    projection,
  };
}

export function validateTurnStartHookRegistration(
  value: unknown,
): JsonObject & {
  hook_id: string;
  capability_id: string;
  max_result_bytes: number;
  requested_write_scope: string[];
} {
  const registration = requiredObject(value, "turn-start hook registration");
  requireExactFields(
    registration,
    TURN_START_REGISTRATION_FIELDS,
    "turn-start hook registration",
  );
  if (
    registration.schema_version !== TURN_START_HOOK_REGISTRATION_SCHEMA_VERSION ||
    registration.phase !== "turn_start" ||
    registration.failure_policy !== "isolate"
  ) {
    throw new Error("turn-start hook registration contract is invalid");
  }
  const hookId = requiredString(registration.hook_id, "turn-start hook hook_id");
  const capabilityId = requiredString(
    registration.capability_id,
    "turn-start hook capability_id",
  );
  if (!TOKEN_RE.test(hookId) || !TOKEN_RE.test(capabilityId)) {
    throw new Error("turn-start hook identity is invalid");
  }
  boundedTokens(
    registration.requested_read_scope,
    "turn-start hook requested_read_scope",
    16,
  );
  const writeScope = boundedTokens(
    registration.requested_write_scope,
    "turn-start hook requested_write_scope",
    8,
  );
  if (writeScope.some((scope) => !TURN_START_WRITE_SCOPES.has(scope))) {
    throw new Error("turn-start hook requested_write_scope is not admitted");
  }
  const budget = requiredObject(registration.budget, "turn-start hook budget");
  requireExactFields(budget, BUDGET_FIELDS, "turn-start hook budget");
  const maxInvocations = requireInteger(
    budget.max_invocations_per_dispatch,
    "turn-start hook max_invocations_per_dispatch",
  );
  const maxResultBytes = requireInteger(
    budget.max_result_bytes,
    "turn-start hook max_result_bytes",
  );
  if (maxInvocations !== 1 || maxResultBytes < 1024 || maxResultBytes > 65_536) {
    throw new Error("turn-start hook budget is outside the admitted envelope");
  }
  return {
    ...registration,
    hook_id: hookId,
    capability_id: capabilityId,
    max_result_bytes: maxResultBytes,
    requested_write_scope: writeScope,
  };
}

export function validateTurnStartHookInvocation(input: {
  registration: unknown;
  result: unknown;
}): JsonObject {
  const registration = validateTurnStartHookRegistration(input.registration);
  const result = requiredObject(input.result, "turn-start hook result");
  requireExactFields(result, TURN_START_RESULT_FIELDS, "turn-start hook result");
  if (
    result.schema_version !== TURN_START_HOOK_RESULT_SCHEMA_VERSION ||
    result.hook_id !== registration.hook_id ||
    result.capability_id !== registration.capability_id ||
    result.phase !== "turn_start"
  ) {
    throw new Error("turn-start hook result identity is invalid");
  }
  if (
    new TextEncoder().encode(JSON.stringify(result)).byteLength >
      registration.max_result_bytes
  ) {
    throw new Error("turn-start hook result exceeds its budget");
  }
  const status = requiredString(result.status, "turn-start hook status");
  if (!TURN_START_STATUSES.has(status)) {
    throw new Error("turn-start hook result status is invalid");
  }
  const observationCount = requireInteger(
    result.observation_count,
    "turn-start hook observation_count",
  );
  if (observationCount < 0 || observationCount > 10_000) {
    throw new Error("turn-start hook observation_count is invalid");
  }
  for (const field of [
    "agent_read_required",
    "external_reads_performed",
    "external_writes_performed",
    "local_private_state_mutated",
    "private_content_returned",
    "provider_payload_returned",
  ]) {
    if (typeof result[field] !== "boolean") {
      throw new Error(`turn-start hook ${field} must be boolean`);
    }
  }
  if (result.private_content_returned || result.provider_payload_returned) {
    throw new Error("turn-start hook cannot return private provider content");
  }
  if (
    result.local_private_state_mutated &&
    registration.requested_write_scope.length === 0
  ) {
    throw new Error("turn-start hook mutated undeclared local-private state");
  }
  if (
    result.external_writes_performed &&
    !registration.requested_write_scope.includes("provider_message_reaction")
  ) {
    throw new Error("turn-start hook performed an undeclared external write");
  }
  const errorCode = result.error_code;
  if (errorCode !== null && (typeof errorCode !== "string" || !TOKEN_RE.test(errorCode))) {
    throw new Error("turn-start hook error_code is invalid");
  }
  if (status === "observed" && (
    observationCount === 0 ||
    errorCode !== null ||
    result.agent_read_required !== true
  )) {
    throw new Error("observed turn-start hook result is inconsistent");
  }
  if (status === "empty" && (
    observationCount !== 0 ||
    errorCode !== null ||
    result.agent_read_required
  )) {
    throw new Error("empty turn-start hook result is inconsistent");
  }
  if (status === "not_applicable" && (
    observationCount !== 0 ||
    result.agent_read_required ||
    result.external_reads_performed ||
    result.external_writes_performed ||
    result.local_private_state_mutated ||
    errorCode !== null
  )) {
    throw new Error("not-applicable turn-start hook result must be empty");
  }
  if (["partial", "unavailable", "failed"].includes(status) && errorCode === null) {
    throw new Error("failed turn-start hook result requires error_code");
  }
  if (status === "partial" && observationCount > 0 && !result.agent_read_required) {
    throw new Error("partial turn-start observations require Agent reading");
  }
  if (["unavailable", "failed"].includes(status) && result.agent_read_required) {
    throw new Error("unavailable turn-start hook cannot require unread evidence");
  }
  return { ...result };
}

export function validatePostWritebackHookRegistration(
  value: unknown,
): JsonObject & {
  hook_id: string;
  capability_id: string;
  subscribed_event_kinds: string[];
  max_result_bytes: number;
} {
  const registration = requiredObject(
    value,
    "post-writeback hook registration",
  );
  requireExactFields(
    registration,
    POST_WRITEBACK_REGISTRATION_FIELDS,
    "post-writeback hook registration",
  );
  if (
    registration.schema_version !==
      POST_WRITEBACK_HOOK_REGISTRATION_SCHEMA_VERSION ||
    registration.phase !== "post_writeback" ||
    registration.failure_policy !== "isolate"
  ) {
    throw new Error("post-writeback hook registration contract is invalid");
  }
  const hookId = requiredString(
    registration.hook_id,
    "post-writeback hook hook_id",
  );
  const capabilityId = requiredString(
    registration.capability_id,
    "post-writeback hook capability_id",
  );
  if (!TOKEN_RE.test(hookId) || !TOKEN_RE.test(capabilityId)) {
    throw new Error("post-writeback hook identity is invalid");
  }
  const subscribedEventKinds = boundedTokens(
    registration.subscribed_event_kinds,
    "post-writeback hook subscribed_event_kinds",
    8,
  );
  if (subscribedEventKinds.length === 0) {
    throw new Error("post-writeback hook subscribed_event_kinds cannot be empty");
  }
  boundedTokens(
    registration.requested_read_scope,
    "post-writeback hook requested_read_scope",
    16,
  );
  const writeScope = boundedTokens(
    registration.requested_write_scope,
    "post-writeback hook requested_write_scope",
    16,
  );
  if (writeScope.length > 0) {
    throw new Error("post-writeback hooks cannot request write scope");
  }
  const budget = requiredObject(registration.budget, "post-writeback hook budget");
  requireExactFields(budget, BUDGET_FIELDS, "post-writeback hook budget");
  const maxInvocations = requireInteger(
    budget.max_invocations_per_dispatch,
    "post-writeback hook max_invocations_per_dispatch",
  );
  const maxResultBytes = requireInteger(
    budget.max_result_bytes,
    "post-writeback hook max_result_bytes",
  );
  if (maxInvocations !== 1 || maxResultBytes < 1024 || maxResultBytes > 65_536) {
    throw new Error("post-writeback hook budget is outside the admitted envelope");
  }
  return {
    ...registration,
    hook_id: hookId,
    capability_id: capabilityId,
    subscribed_event_kinds: subscribedEventKinds,
    max_result_bytes: maxResultBytes,
  };
}

export function validatePostWritebackHookInvocation(input: {
  registration: unknown;
  result: unknown;
}): JsonObject {
  const registration = validatePostWritebackHookRegistration(input.registration);
  const result = requiredObject(input.result, "post-writeback hook result");
  requireExactFields(result, POST_WRITEBACK_RESULT_FIELDS, "post-writeback hook result");
  if (
    result.schema_version !== POST_WRITEBACK_HOOK_RESULT_SCHEMA_VERSION ||
    result.hook_id !== registration.hook_id ||
    result.capability_id !== registration.capability_id ||
    result.phase !== "post_writeback"
  ) {
    throw new Error("post-writeback hook result identity is invalid");
  }
  if (
    new TextEncoder().encode(JSON.stringify(result)).byteLength >
    registration.max_result_bytes
  ) {
    throw new Error("post-writeback hook result exceeds its budget");
  }
  const status = requiredString(result.status, "post-writeback hook status");
  if (!POST_WRITEBACK_STATUSES.has(status)) {
    throw new Error("post-writeback hook result status is invalid");
  }
  const intentKind = result.intent_kind;
  if (intentKind !== null && (typeof intentKind !== "string" || !TOKEN_RE.test(intentKind))) {
    throw new Error("post-writeback hook intent_kind is invalid");
  }
  const idempotencyKey = result.idempotency_key;
  if (
    idempotencyKey !== null &&
    (typeof idempotencyKey !== "string" || !TOKEN_RE.test(idempotencyKey))
  ) {
    throw new Error("post-writeback hook idempotency_key is invalid");
  }
  const intent = result.intent;
  if (intent !== null && typeof intent !== "object") {
    throw new Error("post-writeback hook intent must be an object");
  }
  const errorCode = result.error_code;
  if (
    errorCode !== null &&
    (typeof errorCode !== "string" || !TOKEN_RE.test(errorCode))
  ) {
    throw new Error("post-writeback hook error_code is invalid");
  }
  if (status === "intent_ready" && (
    intentKind === null ||
    idempotencyKey === null ||
    intent === null ||
    errorCode !== null
  )) {
    throw new Error("intent-ready post-writeback hook result is incomplete");
  }
  if (status === "not_applicable" && (
    intentKind !== null ||
    idempotencyKey !== null ||
    intent !== null ||
    errorCode !== null
  )) {
    throw new Error("not-applicable post-writeback hook result must be empty");
  }
  if (status === "failed" && (errorCode === null || intent !== null)) {
    throw new Error("failed post-writeback hook result requires error_code");
  }
  return { ...result };
}
