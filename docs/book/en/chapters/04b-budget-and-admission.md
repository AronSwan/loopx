# The ceiling on consumption, and outside observation

This chapter answers one question: for a system nobody is watching and that never stops on its own, how do you keep it from **running hot when nobody looks, or quietly pretending it is working**. It follows directly from requirement four: consumption needs a ceiling, and it needs to be observable from outside.

## Start from a bad ending

Consider a scenario that requires no one to make a mistake — only two monitors:

```text
10:00  Two external conditions are pending on a Goal: CI on PR #123, review on PR #456.
       M1 watches #123 (cadence 30m). M2 watches #456 (cadence 45m).
10:30  M1 comes due. The poll matches the previous result, so its no-change streak is 1.
10:45  M2 comes due. The poll matches the previous result, so its streak is 1.
11:00  M1 comes due. Streak 2.
11:15  M2 comes due. Streak 2.
...    The two monitors alternate and each counter climbs slowly, but neither
       ever reaches the threshold backoff needs: each wake-up sees the other lane just ran.
```

Nothing in that sequence lies. Every poll is legitimate: the monitor was genuinely due, the external condition genuinely had not changed, and the observation genuinely was written back.

The problem is that **the retreat decision was measured at the wrong scale**. If "should we back off" is decided from adjacent runs globally, then every M1 run interrupts M2's unchanged sequence and every M2 run interrupts M1's. The two lanes keep each other alive. The system looks busy and is in fact **hot-polling a world that never changes**.

The same root has a quieter expression:

```text
22:00  The last Agent turn ends. One external condition remains, unsubscribed.
Next
09:00  The user returns and finds that nothing happened.
```

**Silent stagnation.** No mechanism advances work while nobody supervises, and no mechanism declares "I am waiting" while nobody supervises.

The two endings look opposite. They are one defect: the system has no **externally observable criterion for its own consumption**. Hot polling happens because retreat was counted at the wrong scale; silent stagnation happens because waiting was never registered as a state something can wake.

## Why "set a budget ceiling" is not the cure

The instinct is to give the system an allowance: charge a little per round, stop at zero. That design misses in both directions at once.

**It does not stop spinning.** Every round of hot polling is a "legal" round, so the allowance drains on schedule until it is gone. The ceiling only gives hot polling an expiry time; it does not make it stop. Worse, the round that genuinely needed to react to an external change may land after the allowance ran out.

**It does not stop silent stagnation.** An external condition nobody observes will never produce a run on its own. A generous allowance does not tell the system "go look at the review on #456." A ceiling governs spending, and it cannot reach observation.

**It also misjudges legal no-cost rounds.** Monitor polls, dry-runs, and preflights are legal work whose cost does not sit in quota at all — a monitor poll settles without spending. A system reading a balance turns "allowance remains" into "start now," when the correct answer for this round may be "keep waiting."

So what is needed is not a ceiling but three cooperating mechanisms: **admission** decides whether this round should move; **backoff** decides how to retreat under repeated no-change; and **monitors** decide what does the waking.

## The design

### Admission: whether this round should move

The first mechanism is admission. Before deciding what to do, it answers what is permitted now — and the answer cannot come from the executor itself.

[One governed turn](03-one-turn.md) introduces quota as a decision compiler. Balance remains an input: `spent_slots >= allowed_slots` in the current window makes ordinary work `throttled`.

Available budget still requires Gate, capability, workspace, and frontier checks. Balance answers whether budget is available; full admission answers what this Agent may do now. Both matter.

The forbidden shortcuts share one shape: mistaking a local signal for global authority.

| Source fact | Admission meaning |
|---|---|
| Whether the Goal is registered and the Agent identified | Fail closed on unclear identity; consume no resources |
| Whether a User Gate blocks the current scope | Blocked paths do not run; unblocked fallbacks run independently |
| Whether an external dependency has been registered as a wait | With a typed dependency, do not retry — wait and keep an independent successor |
| Whether this round already has a settlement identity | One heartbeat turn has exactly one settlement Todo; another monitor cannot replace it |
| Whether the delivery type permits spend | A writeback with no validation, a dry-run, and an unchanged poll produce no delivery spend |

**Required accounting must happen; ineligible actions must not be charged as delivery.** Follow the current settlement contract for valid delivery.

Gate notifications, dry-runs, failed preflights, unchanged monitor polls, scheduler cadence changes, and duplicate writebacks do not count as delivery spend.

The quantity limit and accounting classification address different risks. Quota units are not an external model bill; a no-spend observation may still use tools, network resources, or a model.

Another product shape of admission is that waiting gets registered. When an admitted advancement turn discovers a real dependency, it registers a `monitor_changed:<todo_id>` or `todo_done:<todo_id>` wait while keeping an independently runnable successor. Settlement returns `typed_blocked_writeback_no_spend`: validation and durable-writeback receipts, no debit and no delivery credit. The old turn is therefore not stuck, and independent work stays selectable.

```text
loopx quota should-run --goal-id "$GOAL" --agent-id "$AGENT"   # read this round's admission
loopx task-lease inspect --goal-id "$GOAL" --todo-id "$MONITOR" # read the monitor's current lease
```

### Backoff: how to retreat under repeated no-change

The second mechanism is backoff, which answers "given that nothing changed, how long until we ask again."

The scheduler hint projects the current state into a cadence, including the unchanged-poll policy: a backoff multiplier (2 in the current implementation), an unchanged-poll limit per execution surface, and a max interval. Consecutive unchanged rounds stretch the interval step by step until it hits the ceiling.

Scheduler state is bound to `reset_token` and `identity_signature`. Changed identity or decision inputs, once read, can return cadence to the profile's initial value. Consecutive unchanged polls follow the backoff policy.

External change can precede its observation. Without a separate event-wake channel, it is detected at a later due poll. Backoff reduces repeated observation cost but may increase response latency; reset cannot recover the time already spent waiting.

The same retreat logic has a much stronger version for a monitor that observes without progress for a long time. Once a monitor-only lane's unchanged count reaches a threshold, the goal frontier stops waiting quietly and requires an autonomous replan:

```text
kind: monitor_no_change_streak
threshold: 5
```

The threshold of 5 has an explicit rationale in source: it sits deliberately above the 2-turn run-history stall threshold, because a quiet monitor legitimately waits several cadence cycles, and forcing replan after two unchanged polls creates churn for slow external sources. The specific number will move as the protocol evolves, but the fact that **"retreat far enough and you must change the question" needs a number** is stable.

### Monitors: waking on an external condition

The third mechanism stops the Agent from repeatedly asking, and registers what it is waiting for as a state.

When the frontier holds nothing but an external condition, create a `continuous_monitor`. A monitor needs at least six things:

- a **stable target key**: a durable identifier for the observed object (a PR, a tag, a release), not a description re-inferred on every poll;
- **cadence and next due**: how often to look, and when the next look is;
- a **bounded observation handle**: a readable handle so "we looked" has evidence, not just a self-report;
- a **material-change predicate**: what counts as a change;
- an **observation boundary**: the current contract accepts `expires_at`, `resume_when`, or explicit `watch_only=true`;
- a **no-change accounting policy**: how repeated no-change is recorded, and where.

Cadence determines the next observation; expiry determines time-based termination. They are different conditions. A monitor without expiry can validly use `resume_when` or `watch_only` and still have a next due time.

`last_checked_at`, `result_hash`, `consecutive_no_change`, and `material_change` record observations for later decisions. The monitor metadata contract validates boundedness and state transitions.

When an observation is written, the unchanged one and the changed one take different paths. The counter increments only on no-change with an unchanged hash; a material change or a changed hash zeroes it:

```typescript
// loopx/control_plane/todos/monitor_metadata.ts
const noChange = replay ? previousNoChange : material || (previousHash && previousHash !== resultHash)
  ? 0 : previousNoChange + 1;
```

The material-change predicate is a human choice, and that cost gets its own paragraph later. For now, note its position: **it is the only entrance that can trigger a successor**, so it decides what actually drives subsequent work.

### Per-lane counting across monitors and agents

Back to the hot polling from the opening. The fix is not to tune the threshold, it is to **change the scale of the count**.

The correct approach is to keep an independent `consecutive_no_change` counter per monitor Todo. When M2 has a material change, only M2 resets; M1 is unaffected. The turn order (A1, B1, A2, B2, …) does not clear either one.

The same per-lane design applies across agents: each agent's monitor is its own lane, they share one frontier read model, but the no-change judgment is per-lane. The shared read model keeps the global view consistent; per-lane counting keeps the retreat criterion from being contaminated by another lane's activity. Both must hold at once — only the former degrades into hot polling, only the latter loses the global view.

The result is directly observable. In the fixture below four lanes coexist: two with a streak of 1, one with a streak of 5 belonging to the current Agent, and one with a streak of 5 belonging to a peer Agent. Exactly one of them fires:

```text
kind: monitor_no_change_streak
todo_id: todo_unchanged_twice
target_key: github-pr-456
run_count: 5, threshold: 5, agent_id: <current Agent>
```

The two lanes with a streak of 1 stay quiet, and the peer lane with a streak of 5 does not enter the current Agent's replan obligation. **Counting is per lane, and so is waking.**

### The scheduler hint says when to wake

The last distinction is the one this chapter is most likely to blur: **the scheduler hint and execution permission are two different things.**

```text
scheduler hint: when to wake
interaction contract: what this turn may do
```

The scheduler hint projects the current state into a Host cadence: run now, wait for fresh evidence, wait for reassignment, or wake on the monitor cadence. It answers a question about time. Whether this round may write, and may charge, is answered by the interaction contract.

Hence one hard rule: **a Host woken at exactly the right time must still re-run the current decision.** An old scheduler proposal, an old `should_run`, an old selected Todo must not be reused across a state change. Otherwise the scheduler turns from an alarm clock into an authorization.

By the same logic, three wake-related actions produce no delivery spend: cadence apply, failure writeback, and ACK. Waking is not itself a delivery.

## Cost and boundary

**Admission needs usable facts.** Unresolved identity, unclear Gate scope, or stale evidence may hold related work for repair. This avoids guessed authority while adding preparation cost.

**Observation frequency affects detection latency.** Longer cadence saves queries but cannot promise immediate discovery. A monitor's no-change replan threshold and polling interval are separate parameters, each tied to the observed process's time scale.

**Material-change predicates need domain knowledge.** Comparing selected fields may miss facts omitted from a fingerprint; including irrelevant timestamps may treat noise as progress. Choose facts relevant to the wait and bind their source and freshness.

**An unobservable condition needs an explicit handoff.** Record a Gate or blocker for the person who can supply evidence. Do not promise automatic observation of an external condition without a query path.

Quota consumption is not completed workload, and `monitor_quiet_skip` alone does not establish health. Inspect the target, next due, expiry where applicable, streak, and recovery owner.

Scheduler selection does not grant an execution lease or external write authority. The current interaction contract, lease, and operation-specific authority checks still apply.

## Named failures: what these constraints stop

Three scenarios below each have a corresponding test or protocol anchor you can run or read.

**Select replan by lane.** `tests/control_plane/test_monitor_replan_agent_scope.py::test_interleaved_monitors_keep_independent_no_change_streaks` supplies prepopulated counters and checks which eligible lane of the current Agent is selected.

It does not execute the opening observation timeline or scheduler backoff. Counter transitions belong to `monitor_metadata.ts` and its tests; cadence belongs to the scheduler.

**Auxiliary observations must be no-spend, and must not replace the settlement identity.** When an advancement is already bound to this turn's settlement Todo, a newly due monitor may write an auxiliary observation in the same turn, but it cannot replace the settlement identity and cannot produce a second debit. Replay must be idempotent. Corresponding test: `tests/control_plane/test_monitor_observation_admission.py`, plus the protocol `docs/reference/protocols/quota-monitor-observation-receipt-v0.md`, which states plainly that a receipt proves a historical outcome and does not authorize a new mutation.

**A real dependency is not propped up by a short timer.** An admitted turn that discovers a real dependency should register a causal wait and keep an independent successor, not retry on a short `resume_at`. Settlement returns `typed_blocked_writeback_no_spend`, with no debit and no delivery credit, while the Todo stays open with its original validator. Corresponding protocol: `docs/reference/protocols/quota-blocked-causal-closeout-v0.md`.

## Invariants

Six claims you can check yourself.

**On admission and retreat:**

1. **No delta means no spend.** A Gate notification, a dry-run, and an unchanged poll are not deliveries. The converse also holds: one spend does not prove an effective delivery happened.
2. **Retreat is counted per lane, never globally.** If you observe a system that looks busy while nothing changes, check whether no-change was measured at the global scale.
3. **Waking is not authorization.** A Host woken at the right time must still re-run the current decision.

**On observation:**

4. **Waiting needs a readable boundary.** Inspect the target, cadence/next due, and applicable `expires_at`, `resume_when`, or `watch_only` constraint. Missing expiry alone does not establish stagnation.
5. **The material-change predicate decides who drives subsequent work.** It is a human choice, which means it can be chosen wrongly.
6. **An external condition with no observable handle cannot use this machinery.** The fallback is then a person, and a person has a cost.

These six answer one question: **when nobody is watching and nothing is changing, what lets this system say it is still waiting correctly rather than already spinning or stalled?** The evidence is not how many rounds it ran, but whether it can say what it is waiting for, until when, and what would count as having arrived.
