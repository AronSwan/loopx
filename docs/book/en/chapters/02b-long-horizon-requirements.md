# The four demands of long-running work

The previous chapter established which tasks require moving control information out of the current prompt. This chapter answers a more basic question: **once it is out, what must the system satisfy?** These four demands come from the fact of running long enough, not from any design preference inside LoopX. Every system that spans days, sessions, or processes meets them. Some systems choose not to acknowledge them.

## The four demands

| # | Demand | If ignored | Typical symptom |
|---|---|---|---|
| 1 | State must outlive the context | Work repeats or drifts the moment memory breaks | Completed rounds redone after a restart |
| 2 | Every interruption must stop at an identifiable position | A half-finished state cannot be judged; retries become guesswork | Charged, but no one can say where the result landed |
| 3 | Exactly one accountable actor may write | Two actors write the same state at once | Lost updates; a stale holder keeps editing |
| 4 | Consumption must be bounded and externally observable | Idle spinning, double charging, a human forced to watch | Nothing advances unwatched; hot polling when watched |

Each one below gets the same treatment: why it is unavoidable, and what happens when a designer does not face it.

## Demand one: state must outlive the context

Inside a single session, "I said it," "I remember," and "we decided this earlier" are trustworthy, because the transcript is still there. In long-running work all three fail:

- the context gets compacted, and early content yields to recent content;
- the session ends when the user closes the window;
- the Host switches — a Codex App heartbeat and a CLI invocation share no memory;
- time passes, and yesterday's judgment may already be stale.

So **anything "remembered" must live somewhere that does not depend on the transcript**.

Ignoring this shows up first as duplicated work: the agent restarts, finds no evidence of the completed round, and does it again. The second symptom is drift — it stops working toward the original goal, because the goal itself was compacted out of the context.

LoopX's answer is the separation of durable state from read-only projections, which later chapters cover. For now the criterion is enough: **if a piece of information exists only in a prompt, it has not been remembered.**

## Demand two: interruption is normal, not exceptional

Many systems assume the run will finish normally and only exceptions need handling. Long-running work inverts that assumption:

- processes get killed (deploys, OOM, the user hitting stop);
- networks drop (model APIs, external services, the Git remote);
- humans intervene (the direction looks wrong, the requirement changed);
- external conditions suspend progress (PR checks unfinished, a dependency unreleased).

These are not edge cases. Over a long enough run they **happen necessarily**, and they happen repeatedly. Recovery is therefore part of the main path, not an error handler.

Ignoring this leaves the system in an intermediate state that **nobody can locate**. Was it "edited but not accounted for," or "accounted for but not finished"? Without an answer, every retry branch is a guess.

One consequence is easy to miss: **if interruption is normal, then "done" must be decidable.** A work unit whose completion cannot be determined can never safely resume after being cut in half. That is why LoopX cuts a turn into a finite set of phases — phases can be enumerated, and only then does recovery stop being guesswork.

## Demand three: the actor must be unique and accountable

Run long enough and several potential writers coexist:

- multiple Agents on the same Goal;
- several process instances of one Agent (the old process has not exited during a restart);
- human operations and automation at the same time;
- after a Host switch, the old Host still holding an old judgment.

The counterintuitive part: **the problem is not who works faster, but who is permitted to write.**

Ignoring this means two actors each believing they are the current owner, writing the same state simultaneously. The outcome depends on timing — sometimes a lost update (the later write overwrites the earlier one), sometimes a duplicate effect (both executed). The subtler case is the **stale holder**: an actor that no longer holds authority keeps advancing on an expired judgment.

LoopX's response separates "I think I should do this" from "I am authorized to do this": claim, lease, and writer fence exist so that being permitted to write is a state that can be refused, rather than a default that holds.

The key criterion: **permission cannot be self-declared. A shared authority grants it, and can revoke it.**

## Demand four: consumption must be bounded and externally observable

Long-running work consumes two kinds of resource, and both misbehave.

**Compute and budget.** "Quota remaining" suggests subtraction, but a legal round may need no spend at all (monitor poll, dry-run), and a spend does not imply effective delivery. More importantly, **an autonomous system without a ceiling will eventually spin** — trying again, retrying, "checking once more."

**Human attention.** This is the more easily overlooked resource. A long-running system that needs a person watching continuously has not been automated; it merely moved the work from executing to supervising. And when the person stops watching, such a system often neither advances nor halts — it quietly idles.

Ignoring this produces two opposite failures. Either **hot polling**, where the system rechecks with no substantive change and burns external resources and budget; or **silent stagnation**, where nothing advances unwatched until someone returns and finds that nothing happened.

LoopX meets this with three mechanisms together: **admission** (should this turn move at all), **backoff** (how to yield when a monitor sees no change), and **monitors instead of polling** (waking on external conditions rather than an Agent repeatedly asking). The criterion: **no delta means no spend — and a system with no external observation mechanism necessarily degrades into a human polling loop.**

## How the four relate

These are not a flat list. They have a dependency order:

```text
State can persist              (demand one, the premise)
  → interruption is detectable (demand two; otherwise no recovery point)
  → actors can be constrained  (demand three; otherwise recovery may have two writers)
  → consumption can be limited (demand four; otherwise the system burns itself down)
```

The order matters. **Without demand one, demand two is meaningless** — if state is not durable, "which position it stopped at" has no referent. And without demand three, recovery creates a new problem: two instances attempting to recover the same turn at once.

This is also why the mechanisms stack in implementation: projections build on durable state, recovery builds on phase boundaries, leases build on a shared authority, and admission builds on readable state.

## Where these demands can be verified

These four are not claims unique to LoopX; they are general constraints on long-running systems. You can use them to examine any proposal claiming long-horizon support, by asking four questions:

1. **Memory:** kill the process and reopen it. Can it say what it just did, and on what evidence?
2. **Interruption:** kill it at any moment. After restart, can it tell where it stopped, or can it only redo the work?
3. **Ownership:** if two instances start at once, which one may write? Is the other refused, and on what basis?
4. **Consumption:** does it advance while nobody watches? Does it stop trying when nothing changed?

These four have observable answers, rather than requiring you to trust a design document.

## How the book proceeds

The remaining chapters are organized by these four demands. Each explains what concrete problem LoopX faced, what design it chose, what that design costs, and which checkable invariant the reader can take away.

The order goes through demand one and two first (state and recovery), since they are the premise; then demand three (ownership); then demand four (consumption and observation). Part III returns to how you should use it and where its boundaries are.

## Invariants

1. **Information that exists only in a prompt has not been remembered.** The test is whether it survives a process restart.
2. **If interruption is normal, completion must be decidable.** A work unit whose completion cannot be decided cannot safely resume after being cut in half.
3. **Permission cannot be self-declared.** A permission an executor claims for itself is, over a long run, no permission at all.
4. **No delta means no spend.** Conversely, a system without an external observation mechanism degrades into a human polling loop.

Together these four are four ways of asking one question: **when nobody remembers, nobody is watching, and there may be two of you working, why should anyone believe the system is still making progress?**
