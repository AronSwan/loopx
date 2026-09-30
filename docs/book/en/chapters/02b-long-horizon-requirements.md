# The four demands of long-running work

A fix may involve editing code, testing it, waiting for PR checks, responding to review, and handing it to another Agent. Each step may fit one session; the whole task crosses sessions, processes, and human decisions.

This chapter uses that example to introduce four architectural questions. They form a reading framework for LoopX, not a claim that every LoopX path already provides the same guarantees. Other systems may choose different mechanisms.

## Four demands

| Question | What must be retained or decided | LoopX's main approach |
| --- | --- | --- |
| How does another session continue? | Objective, work items, evidence, and next action | Durable state and rebuildable projections |
| How does interrupted work avoid repetition? | Committed, absent, and unknown effects | Turn identity, journals, receipts, and provider readback |
| What if two executors arrive together? | Scope, write ownership, and current revision | Claims, leases, fences, and commit checks |
| How does an unchanged situation cost less? | Budget, runnable work, wait target, and next observation | Quota admission, monitors, backoff, and external scheduling |

Together these mechanisms support continued progress, including legitimate waits and stops. Long-running work does not require an always-live process or a delivery on every wake.

## Demand one: state must outlive the current context

The fix is submitted and the Agent changes session. The new session needs the exact PR, commit, passed checks, and outstanding decisions. A statement that the fix is done cannot reconstruct those relations.

Chat history may persist and help explain the past. It may still lack structure, refer to stale inputs, or be compressed. Facts governing the next action need an addressable owner, revision, and read entrypoint.

LoopX externalizes Goal, Todo, Gate, and receipt state, then projects it for people, Agents, and schedulers. Maintaining and reading records costs work, but lets another session reassess the conditions for action.

**Usage question:** can the next executor identify the objective, unfinished work, and recovery conditions from current sources? Information present only in a prompt cannot by itself prove durable writeback.

## Demand two: retain both known facts and uncertainty after interruption

Suppose a PR push succeeds, but the process exits before saving its local receipt. Missing local evidence cannot establish that nothing happened remotely. A blind retry may repeat an effect; skipping may leave settlement unfinished.

A governed LoopX Turn uses phases, identity, and receipts for confirmed progress. Prepared effects also require provider readback. Confirmed commits are reused; confirmed absence may allow execution; unknown outcomes retain a block and recovery owner.

Legal phase prefixes constrain recorded progress. They do not eliminate the gap between an external effect and a local checkpoint. Continuation also depends on bound identity, authority, and external observability.

**Usage question:** after a timeout, inspect the original Turn and recovery decision. Do not create a new identity simply to repeat work, or translate `unknown` into `false`.

## Demand three: parallel work needs explicit write boundaries

Two Agents can fix different modules or contend for one Todo. After a restart, an old instance may still hold a stale decision. Work ownership and the legality of the current write therefore need separate answers.

LoopX uses claims for ownership and leases, revisions, and fences to constrain applicable write paths. Checks belong at the relevant commit boundary; old display state or a takeover declaration cannot replace current authority.

These mechanisms have configuration and migration boundaries. Default legacy handoff differs from `hard_lease`, and legacy writers do not all enforce the same instance fence. Multiple peers also do not imply one executor for the entire Goal.

**Usage question:** identify the current authority, handoff mode, and writer checks before relying on takeover safety. A design target does not qualify a path where enforcement is not enabled.

## Demand four: budget and observation must bound unproductive repetition

While PR checks are pending, repeatedly asking a model to look again may return the same answer. A budget bounds quantity but cannot alone decide whether another turn is useful. Available budget can still mean waiting.

LoopX admission combines budget, Gates, frontier, capabilities, and workspace facts. Exhaustion restricts ordinary delivery. Monitors organize observations by cadence and material change; unchanged conditions can trigger backoff or replanning.

A monitor may use governed polling. An additional event channel can wake work sooner; without one, backoff increases detection latency. That is a real tradeoff between observation cost and response time.

Delivery quota is separate from actual token, network, and tool costs. A poll that consumes no delivery spend can still consume resources.

**Usage question:** are the wait target, next observation, budget limit, and release condition visible? Can the current Host or scheduler actually trigger work while no person is watching?

## How the four demands form one system

Follow the opening repair task:

```text
Persist Goal / Todo / acceptance conditions
  → select runnable work and check authority from current facts
  → Host execution, validation, durable writeback, and settlement
  → wait for PR checks; observe on cadence or an available event
  → reread facts, identity, and recovery conditions after session change or handoff
```

This is a workflow illustration, not another state machine or mandatory API order. State enables handoff; authority constrains continuation; receipts help interpret effects; budget and observation govern the next attempt.

No single mechanism guarantees that the objective succeeds.

## Reading routes and evidence

Read [durable state and projections](state-substrate.md), then [work graphs, authority, and peers](work-graph-and-authority.md) for facts and writers. [One governed turn](03-one-turn.md) connects them.

[Recovery and boundaries](04-runtime-boundaries.md) covers repeated turns; [budget, admission, and observation](04b-budget-and-admission.md) covers waiting and cost. Onboarding chapters apply these boundaries to a selected Host.

| Boundary to inspect | Evidence entry | What it does not prove alone |
| --- | --- | --- |
| Source versus projection | [Long-horizon state protocol](/loopx/docs/reference/protocols/long-horizon-agent-state-protocol-v0/) | Every reader is real-time |
| Turn recovery | [LoopX Turn protocol](/loopx/docs/reference/protocols/loopx-turn-v0/) | Every external effect can be retried automatically |
| Ownership and handoff | [Peer runtime protocol](/loopx/docs/reference/protocols/peer-agent-runtime-v1/) | Every mode enforces exclusive instances |
| Budget and waking | [Quota contract](/loopx/docs/quota-allocation/) | A Host without event integration immediately detects external changes |

Carry three questions into each chapter: where does this guarantee apply, which conditions does this environment satisfy, and who owns the next action after failure?