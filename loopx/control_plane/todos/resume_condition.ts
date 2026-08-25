import { EffectRuntimeRequestError } from "../effect_runtime_errors.ts";
import {
  optionalNonEmptyString,
  requireInteger,
  requireJsonObject,
  requireNonEmptyString,
  requireStringArray,
} from "../runtime_decode.ts";

import type { JsonObject } from "../effect_program.ts";

export const TODO_RESUME_NORMALIZE_REQUEST_SCHEMA_VERSION =
  "todo_resume_normalize_request_v0";
export const TODO_RESUME_EVALUATION_REQUEST_SCHEMA_VERSION =
  "todo_resume_evaluation_request_v0";
export const TODO_RESUME_EVALUATION_SCHEMA_VERSION =
  "todo_resume_evaluation_v0";
export const TODO_EXTERNAL_WAIT_REQUEST_SCHEMA_VERSION =
  "todo_external_wait_request_v0";
export const TODO_EXTERNAL_WAIT_TRANSITION_SCHEMA_VERSION =
  "todo_external_wait_transition_v0";

export const TODO_RESUME_KINDS = [
  "todo_done",
  "pr_merged",
  "capacity_available",
  "monitor_changed",
] as const;

type TodoResumeKind = typeof TODO_RESUME_KINDS[number];

const TODO_ID_PATTERN = /^todo_[a-z0-9_-]{3,64}$/;
const CAPABILITY_PATTERN = /^[a-z][a-z0-9_:-]{0,63}$/;
const RESUME_PATTERN = /^[a-z][a-z0-9_-]{0,31}(?::[a-z0-9_.:@#/-]{1,181})?$/;
const PR_RESUME_PATTERN =
  /^pr_merged:(?:(?:[a-z0-9_.-]{1,80})\/(?:[a-z0-9_.-]{1,100}))?#[1-9][0-9]{0,8}$/;
const GITHUB_PULL_URL_PATTERN =
  /^https:\/\/github\.com\/([^/]+\/[^/]+)\/pull\/([0-9]+)(?:\b|\/|#|\?)/i;
const PR_REF_PATTERN =
  /^(?:([a-z0-9_.-]+\/[a-z0-9_.-]+)#|#|pr[-_\s]*)([0-9]+)$/i;
const PR_MERGED_EVENT_KINDS = new Set([
  "pr_merge",
  "pr_merged",
  "pull_request_merge",
  "pull_request_merged",
]);

interface ResumeSpec {
  kind: TodoResumeKind;
  target: string;
  normalized: string;
}

interface TodoItem extends JsonObject {
  todo_id: string;
  status?: string;
  task_class?: string;
  resume_when?: string;
  resume_ready?: boolean;
  resume_monitor_generation?: number;
  material_change_generation?: number;
}

function nonNegativeInteger(value: unknown, label: string): number | null {
  if (value === null || value === undefined || value === "") return null;
  const normalized = typeof value === "string" && /^[0-9]+$/.test(value)
    ? Number.parseInt(value, 10)
    : requireInteger(value, label);
  if (!Number.isSafeInteger(normalized) || normalized < 0) {
    throw new EffectRuntimeRequestError(`${label} must be a non-negative integer`);
  }
  return normalized;
}

function todoId(value: unknown, label: string): string {
  const normalized = requireNonEmptyString(value, label).trim().toLowerCase();
  if (!TODO_ID_PATTERN.test(normalized)) {
    throw new EffectRuntimeRequestError(`${label} must be a valid todo_id`);
  }
  return normalized;
}

function optionalString(value: unknown, label: string): string | undefined {
  const normalized = optionalNonEmptyString(value, label);
  return normalized === null ? undefined : normalized.trim();
}

function todoItem(value: unknown, label: string): TodoItem {
  const raw = requireJsonObject(value, label);
  const item: TodoItem = { todo_id: todoId(raw.todo_id, `${label}.todo_id`) };
  for (const field of [
    "status",
    "task_class",
    "archive_state",
    "source_section",
    "claimed_by",
    "task_repository",
  ] as const) {
    const normalized = optionalString(raw[field], `${label}.${field}`);
    if (normalized !== undefined) item[field] = normalized;
  }
  const resumeWhen = optionalString(raw.resume_when, `${label}.resume_when`);
  if (resumeWhen !== undefined) item.resume_when = resumeWhen.toLowerCase();
  if (typeof raw.resume_ready === "boolean") item.resume_ready = raw.resume_ready;
  const resumeGeneration = nonNegativeInteger(
    raw.resume_monitor_generation,
    `${label}.resume_monitor_generation`,
  );
  if (resumeGeneration !== null) item.resume_monitor_generation = resumeGeneration;
  const materialGeneration = nonNegativeInteger(
    raw.material_change_generation,
    `${label}.material_change_generation`,
  );
  if (materialGeneration !== null) {
    item.material_change_generation = materialGeneration;
  }
  return item;
}

function parseResumeWhen(value: unknown): ResumeSpec | null {
  if (typeof value !== "string") return null;
  const normalized = value.trim().toLowerCase();
  if (!normalized || !RESUME_PATTERN.test(normalized)) return null;
  const separator = normalized.indexOf(":");
  if (separator < 1) return null;
  const kind = normalized.slice(0, separator);
  const target = normalized.slice(separator + 1);
  if (!TODO_RESUME_KINDS.some((candidate) => candidate === kind)) return null;
  if ((kind === "todo_done" || kind === "monitor_changed") && !TODO_ID_PATTERN.test(target)) {
    return null;
  }
  if (kind === "capacity_available" && !CAPABILITY_PATTERN.test(target)) {
    return null;
  }
  if (kind === "pr_merged" && !PR_RESUME_PATTERN.test(normalized)) return null;
  return { kind: kind as TodoResumeKind, target, normalized };
}

function requireResumeWhen(value: unknown, label: string): ResumeSpec {
  const parsed = parseResumeWhen(value);
  if (!parsed) {
    throw new EffectRuntimeRequestError(
      `${label} must use todo_done:<todo_id>, monitor_changed:<monitor_todo_id>, ` +
        "pr_merged:[owner/repo]#<number>, or capacity_available:<capability>",
    );
  }
  return parsed;
}

export function normalizeTodoResumeWhen(value: unknown): string | null {
  const request = requireJsonObject(value, "todo_resume_normalize_request");
  if (request.schema_version !== TODO_RESUME_NORMALIZE_REQUEST_SCHEMA_VERSION) {
    throw new EffectRuntimeRequestError("Todo resume normalize request schema mismatch");
  }
  return parseResumeWhen(request.resume_when)?.normalized ?? null;
}

interface PrRef {
  repo: string | null;
  number: number;
  normalized: string;
}

function normalizedPrRef(value: unknown): PrRef | null {
  const candidate = typeof value === "string" ? value.trim().toLowerCase() : "";
  if (!candidate) return null;
  const pullUrl = GITHUB_PULL_URL_PATTERN.exec(candidate);
  if (pullUrl) {
    return {
      repo: pullUrl[1],
      number: Number.parseInt(pullUrl[2], 10),
      normalized: `${pullUrl[1]}#${pullUrl[2]}`,
    };
  }
  const match = PR_REF_PATTERN.exec(candidate);
  if (!match) return null;
  const repo = match[1] || null;
  const number = Number.parseInt(match[2], 10);
  return { repo, number, normalized: repo ? `${repo}#${number}` : `#${number}` };
}

function rolloutEventPrRefs(value: unknown): PrRef[] {
  const event = requireJsonObject(value, "rollout_event");
  const codeRefs = typeof event.code_refs === "object" && event.code_refs !== null &&
      !Array.isArray(event.code_refs)
    ? event.code_refs as JsonObject
    : {};
  const candidates: unknown[] = [codeRefs.pr_ref, event.pr_ref];
  if (Array.isArray(event.source_refs)) {
    for (const rawRef of event.source_refs) {
      if (typeof rawRef !== "object" || rawRef === null || Array.isArray(rawRef)) continue;
      const sourceRef = rawRef as JsonObject;
      const kind = String(sourceRef.kind ?? "").trim().toLowerCase();
      if (kind === "pull_request" || kind === "pr") candidates.push(sourceRef.ref);
    }
  }
  const refs: PrRef[] = [];
  const seen = new Set<string>();
  for (const candidate of candidates) {
    const ref = normalizedPrRef(candidate);
    if (!ref) continue;
    const identity = `${ref.repo ?? ""}#${ref.number}`;
    if (seen.has(identity)) continue;
    seen.add(identity);
    refs.push(ref);
  }
  return refs;
}

function githubRepository(value: unknown): string | null {
  const candidate = typeof value === "string" ? value.trim().toLowerCase() : "";
  const prefix = "git:github.com/";
  if (!candidate.startsWith(prefix)) return null;
  const repository = candidate.slice(prefix.length).replace(/^\/+|\/+$/g, "");
  return repository.split("/").length === 2 ? repository : null;
}

function prMergedCondition(
  spec: ResumeSpec,
  item: TodoItem,
  rolloutEvents: unknown[],
): JsonObject {
  const condition: JsonObject = {
    pr_number: null,
    pr_repo: null,
    source: "rollout_event_log",
  };
  const targetRef = normalizedPrRef(spec.target);
  if (!targetRef) return { ...condition, invalid_target: true };
  condition.pr_number = targetRef.number;
  let targetRepo = targetRef.repo;
  if (targetRepo) {
    condition.pr_repo = targetRepo;
    condition.repository_binding_source = "qualified_resume_when";
  } else {
    targetRepo = githubRepository(item.task_repository);
    if (targetRepo) {
      condition.pr_repo = targetRepo;
      condition.repository_binding_source = "task_repository";
    } else {
      const candidateRefs = new Set<string>();
      for (const rawEvent of rolloutEvents) {
        const event = requireJsonObject(rawEvent, "rollout_event");
        const eventKind = String(event.event_kind ?? "").trim().toLowerCase();
        if (!PR_MERGED_EVENT_KINDS.has(eventKind)) continue;
        for (const ref of rolloutEventPrRefs(event)) {
          if (ref.number === targetRef.number && ref.repo) candidateRefs.add(ref.normalized);
        }
      }
      return {
        ...condition,
        repository_binding_state: "ambiguous",
        repository_binding_reason: item.task_repository
          ? "task_repository_not_github"
          : "task_repository_missing",
        candidate_pr_refs: [...candidateRefs].sort().slice(0, 8),
      };
    }
  }
  for (const rawEvent of rolloutEvents) {
    const event = requireJsonObject(rawEvent, "rollout_event");
    const eventKind = String(event.event_kind ?? "").trim().toLowerCase();
    if (!PR_MERGED_EVENT_KINDS.has(eventKind)) continue;
    for (const ref of rolloutEventPrRefs(event)) {
      if (ref.number !== targetRef.number || ref.repo !== targetRepo) continue;
      return {
        ...condition,
        satisfied: true,
        matched_event_id: event.event_id ?? null,
        matched_event_kind: event.event_kind ?? null,
        matched_pr_ref: ref.normalized,
        matched_event_at: event.recorded_at ?? null,
      };
    }
  }
  return condition;
}

function conditionFor(
  item: TodoItem,
  spec: ResumeSpec,
  byId: Map<string, TodoItem>,
  rolloutEvents: unknown[],
  availableCapabilities: Set<string> | null,
): JsonObject {
  const condition: JsonObject = {
    schema_version: "todo_resume_condition_v0",
    resume_when: spec.normalized,
    kind: spec.kind,
    target: spec.target,
    satisfied: false,
  };
  if (spec.kind === "todo_done") {
    const target = byId.get(spec.target);
    condition.target_todo_id = spec.target;
    condition.target_status = target?.status ?? null;
    if (target) {
      condition.target_archive_state = target.archive_state ?? null;
      condition.target_source_section = target.source_section ?? null;
      condition.target_task_class = target.task_class ?? null;
      if (target.claimed_by) condition.target_claimed_by = target.claimed_by;
    }
    condition.satisfied = target?.status === "done";
    return condition;
  }
  if (spec.kind === "pr_merged") {
    return { ...condition, ...prMergedCondition(spec, item, rolloutEvents) };
  }
  if (spec.kind === "capacity_available") {
    condition.provider = "runtime_available_capabilities";
    condition.provider_required = availableCapabilities === null;
    condition.capability = spec.target;
    condition.satisfied = availableCapabilities?.has(spec.target) === true;
    return condition;
  }
  const monitor = byId.get(spec.target);
  const baseline = item.resume_monitor_generation;
  const generation = monitor?.material_change_generation ?? 0;
  condition.target_todo_id = spec.target;
  condition.target_status = monitor?.status ?? null;
  condition.target_task_class = monitor?.task_class ?? null;
  condition.baseline_generation = baseline ?? null;
  condition.material_change_generation = generation;
  condition.generation_fence = "strictly_greater_than_baseline";
  if (!monitor) condition.invalid_state = "monitor_not_found";
  else if (monitor.task_class !== "continuous_monitor") {
    condition.invalid_state = "target_not_continuous_monitor";
  } else if (baseline === undefined) {
    condition.invalid_state = "baseline_generation_missing";
  } else {
    condition.satisfied = generation > baseline;
  }
  return condition;
}

function resumeAvailabilityReason(condition: JsonObject): string {
  if (condition.satisfied === true) return "resume_condition_satisfied";
  if (
    condition.invalid_target === true ||
    typeof condition.invalid_state === "string"
  ) {
    return "resume_condition_invalid";
  }
  return "resume_condition_pending";
}

export function evaluateTodoResumeConditions(value: unknown): JsonObject {
  const request = requireJsonObject(value, "todo_resume_evaluation_request");
  if (request.schema_version !== TODO_RESUME_EVALUATION_REQUEST_SCHEMA_VERSION) {
    throw new EffectRuntimeRequestError("Todo resume evaluation request schema mismatch");
  }
  if (!Array.isArray(request.items) || !Array.isArray(request.source_items)) {
    throw new EffectRuntimeRequestError("Todo resume evaluation items must be arrays");
  }
  const items = request.items.map((item, index) =>
    todoItem(item, `todo_resume_evaluation_request.items[${index}]`)
  );
  const sourceItems = request.source_items.map((item, index) =>
    todoItem(item, `todo_resume_evaluation_request.source_items[${index}]`)
  );
  const rolloutEvents = Array.isArray(request.rollout_events)
    ? request.rollout_events
    : [];
  const availableCapabilities = request.available_capabilities === undefined ||
      request.available_capabilities === null
    ? null
    : new Set(requireStringArray(
      request.available_capabilities,
      "todo_resume_evaluation_request.available_capabilities",
    ).map((item) => item.trim().toLowerCase()));
  const requestedKinds = request.kinds === undefined || request.kinds === null
    ? null
    : new Set(requireStringArray(request.kinds, "todo_resume_evaluation_request.kinds"));
  const byId = new Map<string, TodoItem>();
  for (const item of [...sourceItems, ...items]) byId.set(item.todo_id, item);
  const conditions: JsonObject[] = [];
  for (const item of items) {
    const spec = parseResumeWhen(item.resume_when);
    if (!spec || (requestedKinds && !requestedKinds.has(spec.kind))) continue;
    const condition = conditionFor(
      item,
      spec,
      byId,
      rolloutEvents,
      availableCapabilities,
    );
    condition.availability_reason = resumeAvailabilityReason(condition);
    conditions.push({
      todo_id: item.todo_id,
      condition,
    });
  }
  return {
    schema_version: TODO_RESUME_EVALUATION_SCHEMA_VERSION,
    conditions,
  };
}

export function planTodoExternalWaitTransition(value: unknown): JsonObject {
  const request = requireJsonObject(value, "todo_external_wait_request");
  if (request.schema_version !== TODO_EXTERNAL_WAIT_REQUEST_SCHEMA_VERSION) {
    throw new EffectRuntimeRequestError("Todo external-wait request schema mismatch");
  }
  if (!Array.isArray(request.items)) {
    throw new EffectRuntimeRequestError("todo_external_wait_request.items must be an array");
  }
  const items = request.items.map((item, index) =>
    todoItem(item, `todo_external_wait_request.items[${index}]`)
  );
  const byId = new Map(items.map((item) => [item.todo_id, item]));
  const waitingTodoId = todoId(request.todo_id, "todo_external_wait_request.todo_id");
  const waitingTodo = byId.get(waitingTodoId);
  if (!waitingTodo) {
    throw new EffectRuntimeRequestError("external-wait Todo is absent from current state");
  }
  if (waitingTodo.status !== "open" || waitingTodo.task_class !== "advancement_task") {
    throw new EffectRuntimeRequestError(
      "external-wait transition requires an open advancement_task",
    );
  }
  const spec = requireResumeWhen(
    request.resume_when,
    "todo_external_wait_request.resume_when",
  );
  if (spec.kind !== "todo_done" && spec.kind !== "monitor_changed") {
    throw new EffectRuntimeRequestError(
      "external-wait transition supports todo_done or monitor_changed; use ordinary " +
        "resume_when authoring for PR and capacity conditions",
    );
  }
  if (spec.target === waitingTodoId) {
    throw new EffectRuntimeRequestError("external-wait Todo cannot resume from itself");
  }
  const dependency = byId.get(spec.target);
  if (!dependency) {
    throw new EffectRuntimeRequestError("external-wait dependency is absent from current state");
  }
  if (spec.kind === "todo_done") {
    if (dependency.task_class === "continuous_monitor") {
      throw new EffectRuntimeRequestError(
        "todo_done cannot wait on a continuous_monitor; use monitor_changed:<todo_id>",
      );
    }
    if (dependency.status === "done") {
      throw new EffectRuntimeRequestError("todo_done dependency is already complete");
    }
  } else if (
    dependency.status !== "open" || dependency.task_class !== "continuous_monitor"
  ) {
    throw new EffectRuntimeRequestError(
      "monitor_changed requires an open continuous_monitor target",
    );
  }
  const successors = requireStringArray(
    request.successor_todo_ids,
    "todo_external_wait_request.successor_todo_ids",
  ).map((item, index) => todoId(item, `successor_todo_ids[${index}]`));
  if (successors.length === 0) {
    throw new EffectRuntimeRequestError(
      "external-wait transition requires at least one independent runnable successor",
    );
  }
  for (const successorId of new Set(successors)) {
    const successor = byId.get(successorId);
    if (!successor || successorId === waitingTodoId) {
      throw new EffectRuntimeRequestError("external-wait successor is absent or self-referential");
    }
    if (successor.status !== "open" || successor.task_class !== "advancement_task") {
      throw new EffectRuntimeRequestError(
        "external-wait successor must be an open advancement_task",
      );
    }
    if (successor.resume_when && successor.resume_ready !== true) {
      throw new EffectRuntimeRequestError(
        "external-wait successor must be runnable, not resume-gated",
      );
    }
  }
  const metadataUpdates: JsonObject = { resume_when: spec.normalized };
  let baselineGeneration: number | null = null;
  if (spec.kind === "monitor_changed") {
    const sameCondition = waitingTodo.resume_when === spec.normalized;
    const currentCondition = conditionFor(
      waitingTodo,
      spec,
      byId,
      [],
      null,
    );
    if (sameCondition && currentCondition.satisfied === true) {
      throw new EffectRuntimeRequestError(
        "clear the satisfied resume_when before re-arming the same monitor wait",
      );
    }
    baselineGeneration = sameCondition && waitingTodo.resume_monitor_generation !== undefined
      ? waitingTodo.resume_monitor_generation
      : dependency.material_change_generation ?? 0;
    metadataUpdates.resume_monitor_generation = baselineGeneration;
  } else {
    metadataUpdates.resume_monitor_generation = null;
  }
  return {
    schema_version: TODO_EXTERNAL_WAIT_TRANSITION_SCHEMA_VERSION,
    state: waitingTodo.resume_when === spec.normalized ? "already_waiting" : "waiting",
    todo_id: waitingTodoId,
    resume_when: spec.normalized,
    resume_kind: spec.kind,
    dependency_todo_id: spec.target,
    successor_todo_ids: [...new Set(successors)],
    baseline_generation: baselineGeneration,
    metadata_updates: metadataUpdates,
    runnable_state: "excluded_until_resume_condition_satisfied",
    idempotency: "preserve_existing_monitor_baseline",
  };
}
