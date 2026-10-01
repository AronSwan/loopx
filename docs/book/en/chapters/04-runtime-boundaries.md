# Recovery, self-repair, and runtime boundaries

The previous chapter explained how one turn leaves an acceptable result. Extend the timeline: sessions change, code advances, permission is revoked and external calls time out. Which work remains usable, which judgments must be repeated, and when should the route change or stop?

Recovery reconstructs **current conditions for action**, not hidden reasoning. Historical transcripts may persist under Host rules and help explain context; they do not replace current authority, applicable acceptance or external state. Recovering a historical fact and authorizing another action remain separate questions.

## Which operation is recovered after a lost response? {#receipt-recovery}

In this synthetic situation, T1's governed operation committed and persisted receipt R1, but the caller lost the response. A failed call does not prove the effect never happened.

```mermaid
sequenceDiagram
    participant C as Caller
    participant O as Command owner
    participant P as Selected provider
    C->>O: Submit original operation
    O->>P: Governed commit
    P->>P: Persist result and R1
    Note over C,P: Commit response is lost
    C->>O: Recover under original identity
    O->>P: Read original receipt
    alt Valid historical result
        P-->>O: Return R1
        O-->>C: Recover result without another commit
    else Still unconfirmed
        P-->>O: unavailable / unknown
        O-->>C: Retain uncertainty and recovery responsibility
    end
```

The first branch assumes R1 actually exists and is valid. An error without provider readback does not identify the branch. Even confirmed absence permits execution only under the current recovery contract, identity and authority, not merely because a local record is missing.

After R1 is recovered, reread T3's current conditions. A commit for C1 cannot validate C2, and T1 settlement does not replace G1's publication decision.

## Historical recovery or a new execution? {#recovery-or-new-execution}

“Keep the original identity” and “obtain a new execution key” answer different questions.

| Situation | Fact to establish now | Identity handling | Next step and stopping condition |
| --- | --- | --- | --- |
| Response lost; original outcome unconfirmed | What happened to this exact operation? | Preserve operation/effect identity and arguments | Original owner reads back; no new key to hide uncertainty |
| Original operation committed; its receipt is missing | How can the historical result be returned completely? | Recover or replay the original receipt | Check the result without recreating the effect |
| Execution legally released or finished; new work is intended | Do current work, owner and inputs permit another execution? | Retain history; obtain a new proof through admission | Refuse unmet conditions; old receipts do not revive permission |
| Input or requirements changed after validation | Which part does old evidence still support? | Retain history; validate against new inputs | Reassess affected judgments without inventing a global version |

The [lease regression test](https://github.com/loopx-project/loopx/blob/76b7583a9f67d6090b43a8c6e58c42cb67a1f3c6/tests/control_plane/test_canonical_lease_acquire.py) provides a concrete example: after renewal, replayed acquisition preserves the original receipt but returns the current lease; after release, reusing the retired acquire key is rejected. Historical explanation and current execution proof are different materials.

Recovery is not an opportunity to change the original intent. When an interface requires exact replay, do not casually replace receiver, Todo, TTL or version. Resolve the original operation first, then express new intent through a new legal lifecycle action. Request-digest and replay requirements belong to each current contract.

## What do different revisions protect? {#revision-bases}

| Identity or revision | Question answered | What it cannot replace |
| --- | --- | --- |
| Artifact / commit revision | Which artifact was validated or delivered? | Provider commit revision or execution permission |
| Provider revision | Can this storage snapshot still be committed? | Artifact revision or lease epoch |
| Lease version | Which current lease record does this request use? | Another Todo's or provider's revision |
| Lease epoch / execution key | Which execution holds current proof; was the older one retired? | Readback of an external effect |
| Turn / operation identity | Which action, writeback or settlement is bound and recovered? | Admission for a new turn |
| Evidence time and source | Where did the observation come from, and is it applicable? | Correct object and scope merely because it was just read |

No one integer represents all these dimensions. Separate reads also need not be one atomic snapshot. Retain each basis and source; report missing fields instead of supplying an invented `version=0`. See [state](state-substrate.md) and the [state-machine topic](core-state-machines.md).

### What becomes stale when C1 changes to C2? {#changed-evidence}

Checks on C1 remain trustworthy history, but do not automatically validate C2. Identify what changed: code, validation declarations, dependencies, approval scope or the execution environment.

A formatting-only documentation edit need not repeat every domain experiment; an output-schema change requires reassessing dependent code, examples, acceptance and approval. Support impact judgment with the diff, current requirements and a validation plan, not the assertion that a change is small.

Whether G1 still covers C2 depends on the object and conditions of the original decision. Not every decision necessarily expires, and historical approval is not perpetual permission. Use existing planning and decision entrypoints to update applicability, revalidate affected work, and let current admission choose the next action.

## Four continuation actions for four kinds of problem

**Continuation:** the objective and route remain valid, and another legal segment begins. Even a resumable Host session must reread current guards rather than reuse an old selected Todo.

**Retry / reconcile:** original intent remains valid, but the original operation must be confirmed or finished. Retry only under a verified idempotency/recovery boundary; prefer reconciliation or readback while external outcome is unknown. `unknown` is not another spelling of failure.

**Replan:** the meaning of the work must change, for example after contradictory evidence, changed acceptance or an exhausted frontier with unmet objectives. Produce a result accepted by the current contract: Todo, Vision, successor or acceptance relationships, or a justified terminal result, not another copy of the plan.

**Self-repair:** the work may remain correct, but sources, projections, routing or receipt lineage have a gap. Locate the owner and repair that gap. Deleting Gates, weakening validators or clearing history is not repair.

Dreaming proposes directions or hypotheses; it does not acquire execution authority. Accepted planning/decision and lifecycle writeback are required before proposals affect actual work. Domain results likewise enter through Capability/Provider contracts and do not own generic permission rules.

## Material evidence delta: activity is not progress

Imagine a teaching case in which a day produces notes, unrelated tests and directory reorganization, but reduces none of the acceptance gaps. The artifacts may exist; that alone does not establish convergence. This is not a claim that current policy unconditionally permits infinite repetition.

Material evidence delta concerns new evidence or state that changes the next judgment, not counts of turns, files or characters. Negative results can matter: rejecting a hypothesis, confirming a blocker or narrowing an unknown can change the route.

Delivery Batch Scale describes change scope; Delivery Outcome describes its relation to the objective. `multi_surface` or `implementation` does not automatically complete a Goal. Interpret `surface_only`, `outcome_gap`, `outcome_progress` and `primary_goal_outcome` under their contract; an attractive label is not evidence.

### Vision checkpoints and baselines

Vision is a per-Agent execution route, not a scratchpad. Applicable material refresh must account for a patched route, supported unchanged result, retirement/supersession, or why the role does not require Vision.

“Unchanged” needs a comparable baseline. Establish the route when none exists rather than describing never-checked as unchanged. For gaps such as `vision_checkpoint_missing`, return to the checkpoint owner and supply the actual relationship, not more aspirational prose. Current owners still determine precedence among replanning and repair; this explanation is not a global rule table for all Hosts.

### Six convergence invariants

These questions check completeness; they add no public fields or automatic acceptance algorithm:

1. **Direction:** how does current work relate to the Goal or Acceptance and applicable Vision?
2. **Authority:** is the correct actor currently eligible for the correct object and scope? Capability is not permission.
3. **Evidence:** do observation, validation and decisions bind the correct inputs and sources and satisfy freshness requirements?
4. **Delta:** what rereadable fact was added, or which legitimate wait was established?
5. **Liveness:** does unfinished work have an action, executable observation, decision, repair or explicit stopping responsibility?
6. **Terminal state:** were successors, waits, receipts and acceptance gaps handled under the applicable contract, rather than merely finding an empty list?

Safety avoids incorrect progress; liveness avoids getting stranded without a next entrypoint. Neither guarantees arbitrary objectives will succeed. See [long-horizon convergence](/loopx/docs/development/control-plane-course/topic-long-horizon-convergence/) and [evidence and repair](/loopx/docs/development/control-plane-course/08-evidence-refresh-and-self-repair/).

## Which surface should be repaired when two disagree? {#projection-repair}

```text
Detect disagreement
  → verify Goal, source, mode, time and truncation range
  → identify the source owning that fact
  → distinguish non-commit, source error, stale projection, read failure and migration differences
  → repair through the appropriate owner
  → read back and reassess dependent work
```

Legacy Markdown can still be source; a Todo under a selected canonical provider cannot fall back to old Markdown. If source committed but display is old, repair projection. If source itself is wrong, use its lifecycle. If reads fail, retain uncertainty. Manually making several pages agree does not restore correct state.

`refresh-state` is controlled writeback, not a universal diagnostic query. Separate inspection from mutation using the [field reference](appendix-reference.md#read-before-change). See the Workspace [pause case](workspace-v1.md#pause-readback) for comparing an operation receipt with a displayed status.

## Stop, closure and compensation

An owner-stopped Goal, paused quota or exited Host does not prove completion. `terminal_no_followup` needs its frontier/acceptance conditions. Zero visible Todos is insufficient: output may be truncated, or Monitors, Gates, successors, handoff, replanning and result-return responsibilities may remain.

When requirements are satisfied, record the basis through the existing terminal entrypoint. Keep a successor for unfinished work or observation/blocker for unknown results. Verified negative results and coverage-backed no-follow-up can honestly end a route without inventing success.

A wrong effect that already occurred needs compensation, not deleted history. The [rollback packet protocol](/loopx/docs/reference/protocols/rollback-packet-v0/) describes affected objects, origins, recovery choices, approval and validation; the packet is not execution permission. Revert, fix-forward, external cleanup and support requests have different prerequisites. Rolling back installation need not reverse state formats or remote effects.

After compensation, recheck actual postconditions and identify what the acceptor still needs to confirm. Internal closeout, recipient receipt and overall acceptance remain separate; see [first delivery](05-connect-existing-project.md#first-delivery).

## Recovery costs and public boundaries

Recovery depends on readable original records, available provider readback and current permission. Missing prerequisites can require people or external support; changing identity does not make the problem disappear. Repeated projection repair is an engineering problem, not justified merely because the system can repair itself.

Evidence collection costs time and resources and should match the risk. Too little checking misses changes; excessive repetition can consume the delivery budget. Retain minimally sufficient evidence, not every thought forever.

Private registries, active state, leases, session handles, credentials and raw transcripts do not belong in public examples. Handoff carries necessary bounded references, freshness and legal retrieval routes, not all private material. Establish Git boundaries for `.loopx/`, `.codex/goals/` and `.local/` according to actual use; ignore rules do not replace credential scans or inspection of already committed history.

You should now be able to classify an interruption, identify preserved identity and freshly observed conditions, and name the recovery entrypoint and stopping condition. When the result remains unknown, return explicit recovery responsibility rather than “run it again and see.”
