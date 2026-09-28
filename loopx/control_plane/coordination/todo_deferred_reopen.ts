/** A deferred Todo cannot acquire a hard lease until it is open. Reopening is
 * therefore a narrow lifecycle transition, not an unfenced execution edit. */
import type {JsonObject} from "../effect_program.ts";
import type {CoordinationProjectionMutation} from "./coordination_projection.ts";
import type {CoordinationTodoUpdateInput} from "./todo_update_intent.ts";
import {canonicalTaskLease} from "./task_lease_state.ts";
import {leaseIsActive, leaseVersion, leaseEpoch} from "../work_items/task_lease_acquire.ts";
import {releasedTaskLeaseRecord} from "../work_items/task_lease_lifecycle_decision.ts";

const REOPEN_FIELDS = new Set(["status", "clear_resume_when", "reason"]);

export function isDeferredReopen(input: CoordinationTodoUpdateInput, todo: JsonObject): boolean {
  const intent = input.planning_intent ?? {};
  return todo.role === "agent" && todo.status === "deferred" &&
    intent.status === "open" && intent.clear_resume_when === true &&
    typeof todo.resume_when === "string" && Boolean(todo.resume_when) &&
    Object.keys(input.patch).length === 0 && input.clear_fields.length === 0 &&
    Object.keys(intent).every(field => REOPEN_FIELDS.has(field));
}

/** Actor, claim, exclusion and binding admission happens before this check.
 * A retained inactive generation is history; a currently active one blocks
 * the transition even if its holder also owns the Todo. */
export function deferredReopenRejection(input: {
  goal_id: string; todo_id: string; actor_agent_id: string | null;
  registered_agents: readonly string[]; lease: JsonObject | undefined;
  lease_idempotency_key: string | null; lease_expected_version: number | null;
  now: Date;
}): {code: string; reason: string} | null {
  if (input.actor_agent_id === null || !input.registered_agents.includes(input.actor_agent_id)) {
    return {code: "actor_not_registered", reason: "Deferred resume requires a registered actor"};
  }
  if (input.lease_idempotency_key !== null || input.lease_expected_version !== null) {
    return {code: "deferred_resume_execution_proof_not_allowed",
      reason: "Deferred resume does not consume an old execution lease"};
  }
  if (input.lease === undefined) return null;
  const lease = canonicalTaskLease(input.lease, input.goal_id, input.todo_id);
  if (leaseIsActive(lease, input.now)) {
    return {code: "deferred_resume_active_lease",
      reason: "Release the active execution lease before resuming deferred work"};
  }
  return null;
}

/** Provider CAS commits the Todo reopening and any stale lease retirement
 * together. The next execution still has to acquire a fresh lease. */
export function planDeferredReopen(input: {
  goal_id: string; before: JsonObject; after: JsonObject;
  lease: JsonObject | undefined; now: Date;
}): {mutations: CoordinationProjectionMutation[]; transition: JsonObject | null} {
  if (input.before.status !== "deferred" || input.after.status !== "open" ||
      input.before.role !== "agent") return {mutations: [], transition: null};
  const lease = input.lease === undefined ? null :
    canonicalTaskLease(input.lease, input.goal_id, String(input.before.todo_id));
  const retiring = lease !== null && lease.status !== "released";
  return {
    mutations: retiring ? [{kind: "lease_upsert", lease: releasedTaskLeaseRecord(lease, input.now)}] : [],
    transition: {kind: "deferred_resumed", execution_authority_granted: false,
      lease_retirement: lease === null ? "absent" : retiring ? "released" : "already_released",
      next_execution: "acquire_fresh_lease",
      ...(lease === null ? {} : {retired_lease_version: leaseVersion(lease),
        retired_lease_epoch: leaseEpoch(lease)})},
  };
}
