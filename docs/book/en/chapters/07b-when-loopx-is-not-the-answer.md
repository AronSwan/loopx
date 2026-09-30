# When LoopX is not the answer

The previous chapters explained what long-running work demands and how LoopX answers. This one goes the other way: **what it does not solve.**

That direction matters more than it sounds. An architecture description that cannot state its own boundaries leaves the reader unable to judge whether to adopt it — only whether to believe it. And "what it refuses to do" is checkable against code and protocol, which brings you closer to the design than a feature list does.

## A scene of the wrong tool

```text
Monday  A developer brings LoopX into their repository for a task:
        "add type annotations to a function."
Monday  The task itself takes twenty minutes.
Monday  Onboarding takes two hours: connect, bootstrap, work out how
        Todos are written, work out when a Gate needs a human.
Monday  The change is done. But completing the governed path takes
        longer still: writing state back, recording evidence,
        confirming quota spend.
Monday  The developer concludes: "This thing is too heavy."
```

The conclusion is right; the reason usually gets stated wrong. The problem is not that LoopX is heavy. It is that **the task did not need it**: closed in scope, finishable in one context, with no external wait and no handoff. For that task, none of the control plane's capabilities are used, while the full cost is paid.

## Four explicit refusals

### One: it does not own your goal

LoopX owns the work queue, authority, evidence, and recovery conditions. It **does not judge** whether an issue is worth fixing, whether an experiment's metric is significant, or whether a paragraph reads well — those are domain judgments belonging to Capability and the project's own sources of truth.

The consequence is practical. If a task's success criterion cannot be written as observable acceptance, LoopX cannot help. It will faithfully record "you said you would do this," and it cannot tell you whether you did.

**Test: if you cannot say what evidence would establish completion, do not onboard yet.**

### Two: it does not promise a fast single turn

Chapter 6 covered this: every turn reads state, checks legality, validates, and writes back. Those steps buy recoverability after interruption, at the cost of being slower than simply starting.

So LoopX optimizes **reliability across days and interruptions**, not the latency of one execution. If your bottleneck is "each call is too slow," adding a control plane makes it slower.

**Test: onboard only when you are willing to trade single-turn speed for recoverability.**

### Three: it is not general-purpose memory

Chapter 4 covers the state substrate in detail; here is the boundary up front. What LoopX records is **work-lifecycle fact** — goals, work items, Gates, evidence, spend, recovery conditions. It does not aim to be your knowledge base, your code index, or a memory of preferences.

Handing it "remember the design we discussed last time" produces something both incomplete and inconvenient; that need has better homes.

**Test: the thing to remember is "who decided what, and when" — not "what we talked about."**

### Four: it does not replace the harness

LoopX decides whether to work, what to work on, and whether the result counts. It **does not** govern how the model reasons, how tools are invoked, or how context is compacted — that is the harness's job.

This boundary means LoopX cannot repair a model that reasons poorly, nor turn a harness that cannot use tools into one that can. It can only guarantee that **above both, the work lifecycle is clear and auditable**.

**Test: is your problem "what should happen next," or "how do we do this step well"? The latter is not its problem.**

## When a plain session is enough

| Trait | Why no control plane is needed |
|---|---|
| Closed in scope, done in twenty minutes | Externalizing state costs more than the task |
| Waiting on no external event | No wait needs to survive the session |
| No handoff to another person or Agent | Ownership need not be recovered outside the session |
| Cheap to redo after failure | Recovery is worth less than redoing it |
| Acceptance is your own judgment | No machine-readable evidence needed |

When all of these hold, a plain session is the **correct choice**, not a sign of being unprepared. Chapter 2's qualification card uses the same criteria.

## Cost and boundary: what these refusals buy

Each "does not" corresponds to a "does better":

| It does not | It buys |
|---|---|
| Own domain judgment | Three entirely different domains share one control plane |
| Promise a fast single turn | Accurate recovery after interruption |
| Provide general memory | A state substrate that stays small and decidable |
| Replace the harness | Swapping models or Hosts without rewriting the control plane |

**This is also why "what it refuses" explains the design better than "what it can do."** A system that does everything is necessarily shallow in every direction; the boundaries these refusals draw are what let it go deep on long-horizon reliability.

## Invariants

1. **A task whose acceptance cannot be stated should not be onboarded.** The system will record faithfully and cannot judge completion.
2. **The value of onboarding grows with the time span.** The shorter the task, the higher the share of cost.
3. **It owns lifecycle, not domain.** Deciding whether something is worth doing stays with Capability.
4. **Single-turn speed and multi-day reliability are a trade.** Wanting both means accepting that one of them gets worse.

Together these answer one question: **does this task need better execution, or a clearer record?** If the former, LoopX is not the answer — and knowing it is not the answer is the premise of using it.
