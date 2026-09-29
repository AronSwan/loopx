/** Conversation execution admission. Native lifecycle is a host observation;
 * this contract never settles canonical work or grants another Agent's lease. */
import type {JsonObject} from "../effect_program.ts";
import {EffectRuntimeRequestError} from "../effect_runtime_errors.ts";
import {requireJsonObject} from "../runtime_decode.ts";
import {resolveConversationScope} from "./conversation_scope.ts";

function requireThat(ok: unknown, message: string): asserts ok {
  if (!ok) throw new EffectRuntimeRequestError(message);
}

export function planChatMode(input: JsonObject): JsonObject {
  const session = requireJsonObject(input.session, "conversation session");
  const operation = input.operation;
  requireThat(["configure", "start", "resume", "pause", "exit", "message", "wake"].includes(String(operation)), "unsupported conversation operation");
  requireThat(resolveConversationScope(session).kind === "owner_goal"
    && (input.origin === "web" || (operation === "wake" && input.origin === "host"))
    && session.session_mode !== "attached_host"
    && session.agent_id === "codex", "LoopX mode requires a local managed Codex Goal conversation");
  const settings = requireJsonObject(input.settings, "conversation settings");
  const native = requireJsonObject(input.native ?? {}, "native Goal observation");
  if (operation === "wake") return planDelegationWake(input, session, settings, native);
  if (operation === "message") {
    const mode = requireJsonObject(session.loopx_mode ?? {}, "mode");
    const turn = requireJsonObject(input.turn ?? {}, "active execution turn");
    requireThat(mode.enabled === true && mode.paused !== true && !!session.active_turn_id
      && turn.loopx_execution === true && turn.turn_id === session.active_turn_id,
      "LoopX message delivery requires active conversation execution");
    requireThat(["queue", "inbox", "steer"].includes(String(input.delivery_mode)), "unsupported delivery mode");
    return {operation, delivery_mode: input.delivery_mode};
  }
  if (operation === "pause" || operation === "exit") {
    if (operation === "pause") requireThat(requireJsonObject(session.loopx_mode ?? {}, "mode").enabled === true,
      "pause requires enabled conversation execution");
    return {operation, enabled: operation !== "exit"};
  }
  requireThat(input.goal_active === true, "Goal is stopped or unavailable");
  requireThat(!session.active_turn_id, "wait for the current conversation turn before changing execution");
  requireThat(Number.isSafeInteger(settings.token_budget) && Number(settings.token_budget) > 0
    && Number(settings.token_budget) <= 2147483647, "set a positive coordinator token allowance");
  requireThat(typeof settings.agent_id === "string" && Array.isArray(input.registered_agents)
    && input.registered_agents.includes(settings.agent_id), "select a registered coordinator identity");
  requireThat(input.execution_binding_valid === true, "configure the coordinator's authorized execution bindings first");
  if (operation === "start") requireThat(!native.status || ["absent", "complete"].includes(String(native.status)),
    "resume the unfinished native Goal instead of replacing it");
  if (operation === "resume") {
    requireThat(["paused", "blocked", "usageLimited", "budgetLimited"].includes(String(native.status)),
      "resume requires a paused, blocked or limited native Goal");
    requireThat(Number(settings.token_budget) > Number(native.tokensUsed ?? 0), "total allowance must exceed consumed tokens");
  }
  return {operation, enabled: operation !== "configure", settings};
}

const RESUMABLE_NATIVE = ["paused", "blocked", "usageLimited", "budgetLimited"];

/** A delegated result was accepted; decide only whether the lead may continue now.
 *
 * The same facts that admit an owner resume admit a host wake, plus mode
 * enabled and not paused.  A refusal is terminal for that intent; pending
 * keeps it for a later tick.  A wake never unpauses the lead, never starts a
 * native Goal and never raises the conversation allowance. */
function planDelegationWake(input: JsonObject, session: JsonObject, settings: JsonObject, native: JsonObject): JsonObject {
  const mode = requireJsonObject(session.loopx_mode ?? {}, "mode");
  const outcome = (state: "pending" | "refused", reason: string) => ({operation: "wake", state, reason});
  if (input.goal_active !== true) return outcome("refused", "goal_stopped");
  if (mode.enabled !== true) return outcome("refused", "no_wake_owner");
  if (!(typeof settings.agent_id === "string" && Array.isArray(input.registered_agents)
    && input.registered_agents.includes(settings.agent_id))) return outcome("refused", "lead_unbound");
  if (input.execution_binding_valid !== true) return outcome("refused", "binding_revoked");
  const status = String(native.status ?? "absent");
  if (status === "complete") return outcome("refused", "native_goal_complete");
  if (status === "absent") return outcome("refused", "native_goal_absent");
  if (mode.paused === true) return outcome("pending", "lead_paused");
  if (session.active_turn_id || !RESUMABLE_NATIVE.includes(status)) return outcome("pending", "lead_turn_active");
  if (!(Number.isSafeInteger(settings.token_budget) && Number(settings.token_budget) > 0
    && Number(settings.token_budget) <= 2147483647
    && Number(settings.token_budget) > Number(native.tokensUsed ?? 0))) return outcome("pending", "allowance_exhausted");
  return {operation: "wake", state: "admitted", reason: null, settings};
}
