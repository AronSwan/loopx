# One governed turn

This chapter answers one question: across a single round of agent work, what happens between "should this move at all" and "this counts as done" — and why the **ordering itself** is a safety boundary.

## The process stops after writeback

Consider a teaching scenario: an Agent produces a compatibility fix, validation passes, and the result is written back. Quota settlement then times out and the process exits.

The CLI did not return success, yet code and some durable records already exist. Repeating the whole turn may duplicate effects; declaring completion may hide unfinished settlement.

The first question is: **which steps committed, which are confirmed absent, and which outcomes remain unknown?**

## Why recoverable commit boundaries matter

Saving only a final success record is simple, but cannot explain partial execution. Recording each step helps, although interruption can still occur between an external effect and its local checkpoint.

LoopX records identity, phases, and receipts for a governed Turn and provides readback for unresolved operations. Recovery preserves completed work, resolves uncertainty, and then decides whether continuation is legal.

When the evidence is insufficient, stopping safely is a valid recovery outcome.

## Scale one: the transaction inside one turn

### Seven phases describe confirmed progress

The LoopX Turn transaction contract defines seven ordered phases:

```text
host_execute → typed_result → validation
             → durable_writeback → quota_spend
             → scheduler_apply → scheduler_ack
```

A receipt's `completed_phases` must be a legal prefix of this sequence. This constrains **what may be claimed as complete**. It does not restrict crashes to phase boundaries or prove that an unrecorded effect never happened.

A provider may commit writeback before the process saves its checkpoint, leaving a `prepared` intent in the journal. Recovery reads back the same settlement identity and effect reference:

| Readback | Action | Remaining conditions |
| --- | --- | --- |
| `committed`, with a valid receipt | Record the existing result and skip that effect | Identity, payload, and phase match |
| `absent` | May execute the uncommitted step | Current recovery decision and authority allow it |
| `unknown`, or unavailable readback | Stop this recovery path and retain uncertainty | Obtain valid readback or repair through the responsible owner |

A legal prefix is only one recovery condition. The executor also checks journal identity, bindings, failure kind, and recovery permission. A saved Host result may allow continuation from validation.

Failures that require another Host invocation also have explicit retry and budget constraints.

### Why quota accounting follows writeback

`durable_writeback → quota_spend` connects delivery accounting to a validated, durable result. Spend here means LoopX budget slots. Model API or external-service costs may already have occurred during execution.

If writeback succeeds and spend fails, **the writeback is retained**. Recovery reuses confirmed results while completing outstanding settlement, avoiding a repeated Host call or writeback.

This preserves completed work without making the whole turn, including external systems, one atomic transaction.

Failure kinds locate the next investigation: `HOST_FAILURE` at `host_execute`, `WRITEBACK_FAILED` at `durable_writeback`, and `QUOTA_SPEND_FAILED` at `quota_spend`.

These fields must agree with the receipt. Knowing the failed phase alone does not authorize a retry.

### The five-stage closed loop: the shape of a normal delivery

Beyond interruption, the normal path has a fixed shape too. A delivery contains at least five stages:

```text
Decide  →  Act  →  Validate  →  Write back  →  Account
```

**Decide.** Read the current decision and select the Todo named by `agent_channel.primary_action`. Do not override the current contract with an old prompt, an old dashboard card, or a previous `recommended_action`.

**Act.** Complete one recoverable bounded segment. Bounded does not mean "one line changed" — it means the segment has clear inputs and boundaries, produces a coherent artifact, observation, or blocker, can be validated independently, and can produce a successor Todo or waiting condition. Reading a single file, repeating "analyzing," or running unrelated commands is not a delivery.

**Validate.** Validation checks the real postcondition; it does not take the executor's word:

| Delivery type | Validation |
|---|---|
| Code | focused test, contract test, smoke, or build |
| Docs | build, links, command surface, public-boundary scan |
| External effect | remote readback, revision, or service state |
| Blocker | explicit evidence of the missing dependency, permission, or observable handle |

`process exited 0` may only prove the tool started. It does not by itself prove the target behavior, external state, or acceptance.

**Write back.** After validation, write compact truth back through Todo lifecycle, event, evidence, or `refresh-state`, stating at minimum: what was delivered, on what revision/command/readback, which acceptance or blocker advanced, what comes next, and whether per-Agent Vision changed. Raw transcripts and long logs do not enter public-safe state.

**Account.** Record one quota spend on the CLI channel only when a validated writeback already exists. Gate notifications, dry-runs, failed preflights, unchanged monitor polls, scheduler cadence changes, and duplicate writebacks must not impersonate delivery spend.

The order cannot be inverted:

```text
wrong:  act → spend → decide later whether it worked
right:  act → independent validation → durable writeback → spend once
```

### Failure modes for a missing stage

The five stages form a dependency chain. Each missing stage produces a specific failure; the loop does not simply keep running:

| Missing stage | Visible symptom | Consequence |
|---|---|---|
| Validation | artifact exists, no postcondition check | Unqualified delivery enters writeback; later decisions rest on wrong evidence |
| Writeback | artifact produced, Todo still open | The next peer cannot see completion; duplicate work or a wrong frontier |
| Refresh | Todo updated, status/vision still stale | Quota targets the wrong goal; monitors judge on expired conditions |
| Spend | Delivery written back, no quota record | Quota accounting and delivery causality disagree |

**A missing validation is the most dangerous**, because it mistakes internal confidence for external fact. **A missing writeback is the most common**, because the agent skips the loop after "finishing the work" and keeps only a local artifact or chat message. **A missing refresh is the most subtle**: the surface state looks correct while quota and monitors were already reading stale values before the decision.

## Scale two: whether this turn should move at all

Everything above concerns what happens *after* work has been chosen. In long-running systems the more common failure is moving **when nothing should have moved**: starting because "quota is left," skipping validation because "the user hasn't complained," ignoring a Gate because "the goal is still active."

### Quota is a decision compiler

"Quota remaining" suggests subtraction: charge once per run, stop at zero. But a legal round of work may need no spend at all (monitor poll, dry-run, preflight), and a spend does not mean effective delivery (an artifact with no validation). Reading quota as a balance check breaks in these scenes:

- **While PR checks are pending:** you cannot call the model just because the goal is active. You must wait for the external result first.
- **After repeated dry-run or preflight failures:** no spend occurred, but the system must not retry forever. Repeated failure calls for repair or replan.
- **When a monitor is not due:** you must not poll early just because quota remains; that wastes external resources.

The correct model compiles source facts into an interaction contract under stable precedence. It decides what a turn may do and how many spends it allows, and rules out reasoning like "the balance is above zero, so start."

### The Decision pipeline: the order is itself the safety contract

A decision requires several rules to compile one contract together in dependency order, across nine stages:

```text
identity
  → authority and boundary
  → scoped decision
  → repair obligation
  → capability and workspace eligibility
  → frontier and continuation
  → interaction contract
  → scheduler
```

1. **Identity:** resolve the exact Goal and registered Agent; fail closed when identity is unclear.
2. **Goal boundary:** establish repository, write scope, authority source, spawn, and public/private boundary.
3. **User Gate:** normalize blocking scope, decision scope, the concrete question, and the projection gap.
4. **Outcome / repair obligation:** check consecutive surface-only progress and Vision or acceptance gaps to decide whether replan or self-repair is mandatory.
5. **Capability:** filter candidates the current execution surface can actually perform.
6. **Workspace:** check task repository, worktree, branch, and required write scope.
7. **Frontier:** resolve priority, claim/lease, dependency, successor, monitor, and terminal closure.
8. **Interaction contract:** compose the user, agent, and CLI channels.
9. **Scheduler hint:** derive the next wake, backoff, and ACK from the now-settled lifecycle state.

**The order is itself the safety contract.** Choosing a Todo before checking the workspace lets the Host start writing before discovering the working directory is wrong. Treating an open user item as a global block starves safe work that does not depend on that decision.

### The three channels can hold at once

A turn carries three perspectives, and all three can hold at once:

| Channel | What it answers |
|---|---|
| User | Must the user act now; notify or stay quiet; which action, lane, or whole Goal does the Gate block |
| Agent | Must this Agent attempt work; is delivery allowed, is a quiet no-op allowed; what is the single primary action |
| CLI | Which lifecycle command comes next; how to refresh/writeback after validation; when spend is allowed; why a Gate, wait, or no-change must not spend |

```text
user channel:
  action_required = true
  action = approve homepage publication
agent channel:
  must_attempt = true
  primary_action = run an independent link check
CLI channel:
  spend_after_validation = true
```

The user Gate stays visible, but it does not cover that independent link-check Todo. Collapsing this into "there is a user Todo, so the Agent stops" loses the scoped fallback; collapsing it into "the Agent can work, so no need to tell the user" is equally wrong.

### Common interaction modes

The combination of the three channels compresses into a **testable mode**. An external developer should at least recognize these:

| Mode | Agent behavior | User behavior | Spend |
|---|---|---|---|
| `bounded_delivery` | Complete one bounded artifact, blocker, or state delta | Usually no interruption | Once, after validation + writeback |
| `user_gate` | Do not run paths the Gate covers | Answer, reject, cancel, or redirect | No spend |
| `scoped_user_gate_fallback` | Run only the selected fallback that does not depend on that Gate | Gate stays visible | Once, after fallback validation |
| `external_evidence_observation` | Read a bounded handle or readback; invent no delivery | Provide a missing handle if needed | Only after a material transition |
| `monitor_quiet_skip` | Stay quiet when not due or with no material change | No interruption | No spend |
| `agent_scope_wait` | The current peer has no in-scope candidate; wait for reassignment | Usually no action | No spend |
| `autonomous_replan` | Write a Todo, Vision, acceptance, or no-follow-up delta | Interrupt only for owner-held decisions | After an accountable delta |
| `outcome_floor_recovery` | Restore only missing outcome evidence, or write a blocker | Depends on the blocker's owner | After recovery validation |
| `blocked_health` / repair | Repair registry, projection, or boundary first | Intervene only when owner authority is needed | No spend without a valid delta |

Specific modes shift as the protocol evolves. **What is worth keeping is the discrimination method**, not a memorized enumeration: who owns the next transition, what behavior is allowed, and what evidence permits writeback.

### What observation, evidence, and receipts each prove

The three carry different responsibilities within one turn, and conflating them produces accidents of the "I assumed someone validated it" kind:

| Object | Proves | Does not prove |
|---|---|---|
| Observation | What was seen at some moment | That the conclusion was accepted, or is still fresh |
| Evidence | Which materials support a judgment | That a state transition was actually written |
| Receipt | That an action or transition was accepted under bound inputs and revision | That the outside world will stay that way |

Taking a timed-out `git push`, the chain separates like this:

```text
tool invocation                → merely an attempt
the result of git ls-remote    → a readback observation
remote ref equals expected commit → can become evidence
LoopX records the publish transition → that is the durable receipt
```

**A proposal is not an effect either.** A protocol declaring "recommends publishing" grants no credentials or permissions and does not prove the remote changed.

### The other face of a missing stage: treating a local signal as global authority

| Source fact | Decision meaning |
|---|---|
| Whether the Goal is registered and the Agent identified | Fail closed on unclear identity; consume no resources |
| Whether a User Gate blocks the current scope | Blocked paths do not run; unblocked fallbacks run independently |
| Whether the frontier has a claimable Todo | With no runnable candidate, enter monitor or agent-scope wait |
| Whether consecutive deliveries lack outcome | After several surface-only rounds, require a real outcome or self-repair |
| Whether external evidence is fresh | Expired evidence cannot enter the decision; refresh readback first |

Forbidden shortcuts include skipping a Gate because the goal is active, skipping the workspace check because quota once existed, and skipping validation because the user has not complained. Each of these mistakes a local signal for global authority.

See [Control-Plane Course lesson 6](/loopx/docs/development/control-plane-course/06-quota-decision-kernel/) for the full decision table, the nine combined cases, and rule precedence, and [lesson 8](/loopx/docs/development/control-plane-course/08-evidence-refresh-and-self-repair/) for the failure replay and repair path at each rung of the evidence ladder. This chapter teaches the discrimination method; it does not enumerate modes that will shift as the protocol evolves.

### Who solely owns a rule

The nine-stage order from scale two holds only on one further condition: **a rule can have exactly one owner.** If Python and TypeScript each implement "when is charging allowed," the two implementations will eventually diverge, and the divergence means the ordering contract quietly stops holding on one side.

LoopX moves the canonical semantics of the complete transaction into TypeScript:

```text
Python CLI / Host adapter
  → typed request
  → managed TypeScript Effect runtime
  → domain-owned decision or effect receipt
  → Python compatibility projection / explicit external Provider
```

Published typed owners include **Turn settlement**, **Todo completion**, and **Host Todo settlement**, plus quota delivery routing, **spend/void/monitor-poll commit**, the **full local task-lease lifecycle**, **Vision refresh**, governed capability-lifecycle validation, and scheduler heartbeat/state with **receipt-bound scheduler follow-up**.

Python still carries the current CLI transport, explicit external Provider/Host effects, legacy projection, and the Markdown/event writeback not yet migrated. The migration does not mean "**Python has been removed**" — but the same rule must never be reimplemented in a Python facade, because that creates a second source of truth and breaks exactly what this section protects. `v0.5.4` still ships a runnable `turn plan` / `turn run-once` path, and the migration effectively began from that release.

The [TypeScript Control-Plane Migration RFC](https://github.com/huangruiteng/loopx/blob/main/docs/architecture/rfcs/typescript-control-plane-migration-v0.md) on current `main` defines the remaining work as transaction-payoff: one migration should move a complete transaction and delete the Python semantic path it replaced. Adding only leaf handlers, DTOs, or bridge calls does not count as migration progress.

When the two sides disagree, locate the current contract owner. TypeScript owns migrated Turn settlement, while Python still owns some Todo read rules.

Language alone does not decide correctness; use the migration RFC delivery boundary and actual caller path.

## Cost and boundary: what recovery requires

**Recovery records must remain readable.** Journals, identity bindings, and provider receipts add storage, validation, and migration costs. Missing or corrupt records may block recovery; absence of evidence is not proof of nonexecution.

**Unknown outcomes may require waiting.** Retaining completed work reduces duplicate execution but requires provider readback. An external API without queries or idempotency identifiers needs its own recovery strategy.

**Phases constrain settlement.** `host_execute` may include multiple tool calls. Fixed settlement phases do not forbid editing a file and clearing a cache. Any added external effect still needs its own authority, idempotency, and readback boundary.

TurnEnvelope is an explicitly enabled bounded projection. LoopX Turn has an experimental protocol and runnable `turn plan` / `turn run-once` paths for explicit opt-in integrations.

These boundaries do not give every tool call in every Host the same recovery guarantees.

## How to judge whether recovery can proceed

Start from the original Turn identity. A CLI timeout does not justify creating a new task to repeat the work. For diagnosis, inspect its journal:

```bash
loopx turn inspect-journal \
  --goal-id <goal-id> --agent-id <agent-id> \
  --turn-key <turn-key> --format markdown
```

Read `recorded_effects` and `recovery_decision`. `null` means unknown. Inspection neither performs recovery nor grants retry permission; follow the current executor decision and provider readback while preserving the original identity.

| Claim | Evidence entry | Evidence boundary |
| --- | --- | --- |
| Completed phases must form a legal prefix | `turn_driver/transaction.py`, `test_effect_program_fault_replay_matrix.py` | Checks record shape; controlled receipts do not exhaust real crashes |
| Unknown prepared effects cannot be blindly executed | `turn_driver/settlement.ts`, `tests/control_plane_ts/turn_settlement.test.ts` | Still depends on trustworthy provider readback |
| Failed spend preserves writeback | Spend rejection and recovery cases in `tests/test_loopx_turn_executor.py` | Synthetic providers verify executor branches, not external billing |

See the [LoopX Turn protocol](/loopx/docs/reference/protocols/loopx-turn-v0/) for complete fields and recovery conditions. This evidence supports guarantees within named boundaries, not exactly-once behavior for arbitrary external operations.

## How a turn ends

A turn can end in several ways, and all of them are legal:

- validated delivery + writeback + spend;
- concrete blocker + recovery condition;
- user Gate notification;
- bounded external observation;
- quiet monitor or no-candidate wait;
- replan or repair delta;
- stop after a terminal audit.

**Writing no code is not necessarily a failure** — a Gate, a wait, and a quiet no-op may be exactly what the protocol requires. Conversely, writing a lot of code does not make a turn effective if it bypassed the selected Todo, authority, workspace, or validation.

## Boundaries to preserve in use

1. Completed phases describe a legal prefix of confirmed results; unrecorded effects may still require readback.
2. Retain valid receipts under the same settlement identity; a spend failure does not undo completed writeback.
3. Resolve unknown results before proceeding; do not use a new identity to bypass the original Turn's recovery checks.
4. User, agent, and CLI channels may all carry obligations; apply each within its scope.
5. Cost optimizations must preserve admission precedence and authority checks at commit time.
6. Account according to the current settlement contract; Gate notifications, dry-runs, and unchanged polls are not delivery spend.

The next chapter follows these rules across multiple turns: when to retry, when to replan, and when a human must take over.
