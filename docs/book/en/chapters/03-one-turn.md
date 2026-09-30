# One governed turn

This chapter answers one question: across a single round of agent work, what happens between "should this move at all" and "this counts as done" — and why the **ordering itself** is a safety boundary.

## Start from a bad ending

Consider a scenario that is common in agent systems without governance:

```text
09:00  Agent turn 40. It reads the Todo list, picks one, starts editing files.
09:04  Done. A receipt is already written: code change + validation output.
09:04  The machine reboots (or the process is killed, or the user hits stop,
       or the model times out).
09:06  The Agent restarts and reads state: the Todo is still pending, and no
       evidence of the completed work is visible.
09:06  It concludes the round never happened, and does it again.
09:09  The second round "succeeds" too. Quota is charged twice, and the Todo
       list now carries two records pointing at the same result.
```

Nothing in that sequence is a lie. The agent did not misreport, the receipt really was written, and the Todo state was accurate at the time.

The problem is that **these facts share no common commit point**: the receipt lands somewhere that disappears, the charge lands somewhere that does not, and "this round finished" cannot be reconstructed from the read model after a restart.

That gap is what separates long-running work from a single session. In a session, "I said it" is roughly equivalent to "it happened," because the context is still there. In long-running work, **context is working memory that will be flushed**, so "what happened" has to be answerable by something that does not depend on it.

## Why "check before retrying" is not the fix

The obvious reaction is to have the agent check first. But checking requires reading state, and state may sit exactly in the middle — receipt written, charge not written — where both choices are wrong:

- **Skip it:** the change may genuinely be on disk but unrecorded, so it can never be accepted, handed off, or audited.
- **Redo it:** you may edit the same file twice, call the same external resource twice, or charge the same budget twice.

The hard problem is **whether you can tell how far it got.** Without that, every retry branch is a guess.

So the design goal is **every failure stopping at an identifiable position**. Fewer failures is a different, weaker goal.

## Scale one: the transaction inside one turn

### Seven phases, and only legal prefixes

LoopX splits one turn into seven ordered phases, recorded in a checkable contract:

```text
host_execute → typed_result → validation
             → durable_writeback → quota_spend
             → scheduler_apply → scheduler_ack
```

A turn only ever stops on some **prefix** of those seven. If it dies after phase 4, the completed set is the first four; after phase 6, the first six. There is no state in which phase 3 was skipped while phase 4 ran.

A validation rule maintains that constraint, not convention. When a transaction plan claims a set of completed phases, LoopX checks that the set is exactly a prefix:

```python
# loopx/control_plane/turn_driver/transaction.py
expected = list(TRANSACTION_PHASES[: len(phases)])
if phases != expected:
    errors.append("completed_phases must be an ordered transaction prefix")
```

**That is the mechanism that makes recovery work.** The set of possible crash positions collapses from "any state at any moment" to "one of seven prefixes." Recovery does not guess; it reads the last completed phase and continues from the next one. Forty-three restarts and one restart take the same path.

### Why the charge must come after the writeback

The ordering constraint yields a counterintuitive conclusion. Notice the relative position of these two phases:

```text
durable_writeback  →  quota_spend
```

Writing back before charging means the state "money spent, result not recorded" cannot occur. The cost is that a failed charge wastes the round. LoopX accepts that loss, because **one wasted round is far cheaper than an unauditable "we charged you and cannot say where the result is."**

Failure carries its own constraint. Every failure kind must declare which phase it stopped at:

```python
# loopx/control_plane/turn_driver/transaction.py
FAILURE_PHASES = {
    LoopXTurnResultKind.HOST_FAILURE:        "host_execute",
    LoopXTurnResultKind.VALIDATION_FAILED:   "validation",
    LoopXTurnResultKind.WRITEBACK_FAILED:    "durable_writeback",
    LoopXTurnResultKind.QUOTA_SPEND_FAILED:  "quota_spend",
    LoopXTurnResultKind.TERMINAL_CLOSEOUT_FAILED: "terminal_closeout",
}
```

A plan that declares `QUOTA_SPEND_FAILED` while claiming it stopped at `validation` is rejected. Failures cannot be attributed loosely, **because the attribution decides where recovery resumes.**

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

This boundary has a practical consequence for readers: **when the two sides disagree, the canonical answer lives on the TypeScript side**, and the Python side is adaptation or compatibility projection. To tell where a piece of logic belongs, ask whether it is already a domain-owned decision or an effect receipt.

## Cost and boundary: what this design gives up

Every rule above buys one property by paying elsewhere. The costs matter, because they determine when you should not expect this machinery to help.

**Cost one: every turn reads state first.** You cannot act on a judgment embedded in a prompt from an hour ago. That is slower than "keep going," and the state you read may already be stale when you finish reading it.

**Cost two: the phase count is fixed.** You cannot slip an extra step into a round — "edit the file and clear the cache while we're here." That flexibility is traded for enumerability, and enumerability is what recovery requires.

**Cost three: wasted work is possible.** If the charge fails after writeback, the round produces no accounting at all. The system discards it rather than keep an unclassifiable partial result.

**Cost four: you cannot skip stages on intuition.** The nine stages mean an obvious-looking judgment — "the user hasn't complained, so continue" — has no place in the pipeline. To speed up decisions you improve the quality of source facts; you do not compress the order.

**Boundary one: these seven phases describe a governed turn only; they do not cover everything an agent does.** The model's reasoning inside `host_execute`, and the order of its tool calls, are not governed by these phases — that belongs to the harness. LoopX governs **the part that crosses process boundaries, can be interrupted, and must be accounted for.**

**Boundary two: TurnEnvelope and LoopX Turn are not default paths.** TurnEnvelope is an explicitly enabled bounded projection, not the default quota output. LoopX Turn is an experimental protocol, though the current release ships a runnable `turn plan` / `turn run-once` path and a Host adapter. Both suit understanding boundaries and explicit opt-in integrations; neither should be described as a recurring runtime every Host adopts by default.

**Boundary three: Python still owns real responsibilities.** Python carries the current CLI transport, explicit external Provider/Host effects, legacy projection, and the Markdown/event writeback not yet migrated. The migration does not mean "Python was removed," and the same rule must never be reimplemented in a Python facade — that creates a second source of truth.

## Named failures: what these constraints stop

Talking abstractly about "recoverability" convinces nobody. Three scenarios below each have a corresponding test you can run to watch the constraints take effect.

**Replaying a legal prefix produces no duplicate effect.** For every legal prefix, a replay must converge on the same result — no second charge, no extra record. The tests cover every prefix combination; none of them sample. The decisive assertions are that `replay_calls == []` and that `combined_calls` contains at most one `DURABLE_WRITEBACK` and at most one `QUOTA_SPEND`.

**A charge without a writeback must fail closed.** A plan claiming it will charge while carrying no corresponding `durable_writeback` must be rejected rather than charged first and reconciled later. This guards precisely the 09:04 state from the opening: money spent, landing site unknown.

**One failure short-circuits every later effect.** After phase 3 fails, phases 4 through 7 do not run. Otherwise you get internally contradictory states like "validation failed but writeback succeeded."

Corresponding tests: `tests/control_plane/test_effect_program_fault_replay_matrix.py`. They serve as executable evidence for this design at each crash point, well beyond demonstration.

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

## Invariants

Six claims you can check yourself.

**On the single-turn transaction:**

1. **A turn's completion state is always some prefix of the seven phases.** If you observe spend performed without writeback, that is not a recovery boundary — it is a defect.
2. **Replaying the same turn adds no effect.** Replay is idempotent, so retrying is safe — but retrying does not erase the question of how far it got.
3. **A failure must declare where it stopped.** A failure that cannot name its phase cannot be recovered, and therefore cannot be handed off.

**On cross-turn admission:**

4. **The three channels can hold at once.** Collapsing any one of them into a global boolean loses either legal parallel work or a required human decision.
5. **The decision order cannot be compressed.** To speed up decisions, improve the quality of source facts.
6. **No delta means no spend.** Gate notifications, dry-runs, and unchanged polls are not deliveries.

These six answer one question: **when nobody remembers what just happened and nobody is watching, what lets the system know whether to move and how far it got?** This chapter gave LoopX's answer at the single-turn scale. The next chapter stretches the scale — when a goal takes dozens or hundreds of turns across interruptions and handoffs, how these constraints continue to hold.
