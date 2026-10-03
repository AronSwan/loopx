/** Admission for compatibility prose only, never Todo or Goal amendment authority. */
import {createHash} from "node:crypto";
import {ENVELOPED_SHA256_PATTERN} from "../content_digest.ts";
import {type JsonObject} from "../effect_program.ts";
import {EffectRuntimeRequestError} from "../effect_runtime_errors.ts";
import {optionalNonEmptyString, requireJsonObject, requireNonEmptyString, requireStringArray} from "../runtime_decode.ts";

export function resolveNextActionWriteback(value: unknown): JsonObject {
  const request = requireJsonObject(value, "next_action_writeback");
  const goalId = requireNonEmptyString(request.goal_id, "goal_id");
  const revision = requireNonEmptyString(request.state_revision, "state_revision");
  const goalRevision = requireNonEmptyString(request.goal_revision, "goal_revision");
  if (!ENVELOPED_SHA256_PATTERN.test(revision) || !ENVELOPED_SHA256_PATTERN.test(goalRevision)) {
    throw new EffectRuntimeRequestError("state_revision and goal_revision must be SHA-256 revisions");
  }
  // The adapter supplies the complete normalized roster, including offline peers.
  const agents = [...new Set(requireStringArray(request.registered_agents, "registered_agents"))].sort();
  const entries = requireStringArray(request.next_action_entries, "next_action_entries");
  const basis = "sha256:" + createHash("sha256").update(JSON.stringify([
    goalId, goalRevision, agents, revision,
  ])).digest("hex");
  const context: JsonObject = {basis, registered_agents: agents, next_action_entries: entries};
  if (request.write === undefined || request.write === null) return context;
  const write = requireJsonObject(request.write, "write");
  const actor = optionalNonEmptyString(write.agent_id, "agent_id");
  const scope = requireNonEmptyString(write.progress_scope, "progress_scope");
  const expected = optionalNonEmptyString(write.expected_basis, "expected_basis");
  const sourceBasis = optionalNonEmptyString(write.source_basis, "source_basis");
  if (scope !== "goal" && scope !== "agent_lane") {
    throw new EffectRuntimeRequestError("progress_scope must be goal or agent_lane");
  }
  if (expected && !ENVELOPED_SHA256_PATTERN.test(expected)) {
    throw new EffectRuntimeRequestError("--next-action-basis must be a SHA-256 basis");
  }
  const reject = (code: string, error: string): JsonObject => ({
    ...context, admitted: false, error_code: code, error, reread_required: true,
  });
  if (actor && agents.length && !agents.includes(actor)) {
    return reject("next_action_actor_unregistered", "Next Action writer is not registered for this Goal");
  }
  if ((expected && expected !== basis) || (sourceBasis && sourceBasis !== basis)) {
    return reject("next_action_basis_conflict", "Next Action read basis changed; read current status and rejudge before retrying");
  }
  if (agents.length > 1 && !actor) {
    return reject("next_action_actor_required", "multi-agent Next Action write requires --agent-id");
  }
  if (scope === "agent_lane" && !(actor && agents.length === 1 && agents[0] === actor)) {
    return reject("next_action_shared_scope_required",
      "agent-lane refresh-state cannot update shared Next Action without a confirmed sole registered peer; update your Todo route, or use --progress-scope goal with --next-action-basis");
  }
  if (agents.length > 1 && !expected) {
    return reject("next_action_basis_required", "shared Next Action write requires --next-action-basis from current status");
  }
  return {...context, admitted: true};
}
