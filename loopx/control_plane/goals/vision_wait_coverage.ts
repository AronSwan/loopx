import type { JsonObject } from "../effect_program.ts";
import { requireJsonObject, requireStringArray } from "../runtime_decode.ts";
import { EffectRuntimeRequestError } from "../effect_runtime_errors.ts";

/** Every causal obligation needs its own wait witness; shared prerequisites
 * do not make sibling work interchangeable. Inputs are evaluated Todo facts,
 * never model-maintained alternate-route declarations. */
export function projectVisionWaitCoverage(value: unknown): JsonObject {
  const request = requireJsonObject(value, "vision wait coverage");
  const roots = requireStringArray(request.causal_todo_ids, "causal_todo_ids");
  const waits = new Set(requireStringArray(request.waiting_todo_ids, "waiting_todo_ids"));
  const blockers = new Set(requireStringArray(request.blocker_todo_ids, "blocker_todo_ids"));
  if (!Array.isArray(request.edges)) throw new EffectRuntimeRequestError("edges must be an array");
  const graph = new Map<string, Set<string>>();
  for (const edge of request.edges) {
    const pair = requireStringArray(edge, "lineage edge");
    if (pair.length !== 2) throw new EffectRuntimeRequestError("lineage edge must have two ids");
    const targets = graph.get(pair[0]) ?? new Set<string>();
    targets.add(pair[1]);
    graph.set(pair[0], targets);
  }
  const witnesses = new Set<string>();
  const uncovered = new Set<string>();
  for (const root of roots) {
    const seen = new Set<string>();
    const pending = [root];
    let covered = false;
    while (pending.length) {
      const id = pending.pop()!;
      if (seen.has(id)) continue;
      seen.add(id);
      if (waits.has(id) || blockers.has(id)) {
        witnesses.add(id);
        covered = true;
      }
      for (const next of graph.get(id) ?? []) pending.push(next);
    }
    if (!covered) uncovered.add(root);
  }
  return {
    schema_version: "vision_wait_coverage_v0",
    covered: roots.length > 0 && uncovered.size === 0,
    witness_todo_ids: [...witnesses].sort(),
    uncovered_todo_ids: [...uncovered].sort(),
  };
}
