# Durable State and Read-Only Projections

This chapter hangs on [requirement one](/loopx/docs/book/en/chapters/02b-long-horizon-requirements/): **state must be able to exist without the context**.

## Start from a bad ending

Consider a scene that repeats in long-running systems. Nothing in it is a lie, and the facts fork anyway:

```text
09:12  Agent A finishes a delivery, writes the receipt, marks Todo T1 done.
09:12  status regenerates once; the dashboard card reads "T1 done".
09:40  Agent A is restarted (deploy, OOM, the user hits stop).
09:41  Agent B picks up the work. It never reads the event stream or the Todo
       store; it opens the dashboard and the last review packet instead,
       because those pages "look like current state".
09:43  Agent B sees a dashboard card reading "T1 pending" — a projection
       cached at 08:00, because status has not regenerated since 09:12.
09:44  Agent B concludes T1 was never done and does it again.
09:52  Two deliveries reach one external resource. T1 now carries two
       lineages of completion evidence.
```

The next day's review asks a hard question: **at 09:41, what was the system's actual state?** Two answers exist at
once, and both can produce evidence — one from the event stream, one from a page.

That fork does not come from the agent reasoning badly. It comes from a more basic design choice: **whether a page
is allowed to be a source of fact.** Once a surface that merely "looks like current state" enters a decision, facts
have two owners, and the read model after a restart drifts from the true source.

So recovery cannot be judged by "what can I still read." It is judged by whether each fact has a stable owner and
can be re-projected into a fresh decision.

## Why "keep every page in sync" solves nothing

The instinctive reaction is to refresh every page in real time, or simply to trust whichever page is most convenient. That road has determined failure points:

- **Sync has no common commit point.** Page A updates, page B fails, and the system
  stops in the middle — same as 09:43, only a shorter window.
- **Reading convenience ends up defining fact.** Whoever is read most has the stalest cache, and therefore becomes the easiest source of truth.
- **Faster refresh does not fix authority.** Even a perfectly current page is still a read result; it cannot authorize a write.

The real question is a different one: **who owns this fact, and who may change it.** With ownership, a lagging projection is a detectable, repairable deviation. Without it, faster sync only narrows the fork window; it never closes it.

## The design: five state surfaces

LoopX's answer is the **separation of durable state from read-only projections**. Which surfaces own facts and which only help readers is stated explicitly in the protocol.

Start with identity.

The durable identity is the **Goal**, not a Host thread:

```text
Goal
├── objective and boundary
├── todos, gates and evidence lineage
├── registered peer identities
└── runtime and projection routes

Session / thread
└── one temporary executor context
```

Codex App, Codex CLI, or another Host can advance the same Goal at different times. One session can also read more
than one Goal.

Reading a Goal does not grant write authority, and ending a session does not delete the Goal.

### Reuse an exact Goal instead of guessing from text

Goal reuse depends on a stable `goal_id` and registry connection, not fuzzy objective similarity:

```text
one registered goal
  -> reuse that exact goal boundary

multiple registered goals
  -> read-only goal_selection_gate
  -> choose one exact goal_id
  -> rerun before any mutation
```

When a project has several registered Goals, `start-goal --guided` should list their ids, status, and exact rerun commands. Todo writes, Agent registration, and Host activation wait until the selection is resolved. Similar objective text, a shared repository, or overlapping acceptance criteria do not authorize LoopX to merge Goal boundaries silently.

Keep Goal reuse separate from Agent takeover. A new Agent can read the same public frontier and history, but it registers a fresh `agent_id` by default. Reusing an existing Agent identity requires the user to select that exact id. This preserves historical lineage without letting a new session inherit execution responsibility under another identity.

Recovery can therefore be written as:

```text
next decision =
  replay(durable project facts)
  + inspect(fresh workspace and external facts)
```

An old conversation may help interpretation. It cannot outrank current Git state, an unresolved Gate, current CI, or LoopX canonical lifecycle state.

### 1. Registry: identity, connection, and durable policy

The registry answers "which Goal is this, where is it connected, and which runtime routes are allowed?"

It carries:

- Goal id, repository, and active-state route;
- local or global runtime roots;
- registered Agent identities;
- coordination, write scope, and workspace guards;
- configuration for default-off features.

The registry does not prove that a Host successfully started. It also does not store every Agent result. It
owns connection and policy facts, not execution receipts.

### 2. Event ledger: what happened

[`event_sourced_state_contract_v0`](https://github.com/loopx-project/loopx/blob/main/docs/reference/protocols/event-sourced-state-contract-v0.md)
represents Todo, Gate, run, evidence, projection, and quota changes as append-only events.

At least four invariants matter:

| Invariant | Why it matters |
| --- | --- |
| Append-only | New facts extend history instead of rewriting it to hide an earlier action |
| Ordered | Replay reconstructs the same lifecycle sequence |
| Idempotent | Replaying the same `event_id` with the same payload does not duplicate the effect |
| Privacy-partitioned | Public-safe summaries do not mix with local or private payloads in the same public stream |

Marking a Markdown checkbox as `[x]` cannot prove that a Todo completed.

A legal transition should keep the Todo id, producer, completion evidence, time, and event lineage so status, review
packets, and the next quota decision can reuse the same fact.

### 3. Active-state workbench: a human-readable work surface

`ACTIVE_GOAL_STATE.md` helps humans and Agents read the Objective, Next Action, User Todos, Agent Todos, and
Progress.

It is an important workbench, and "all truth lives in Markdown" is the wrong model for it.

During migration or compatibility windows, Markdown may still participate in Todo reads. Canonical writes should
still pass through LoopX lifecycle commands and controlled writeback so they form governed events.

Editing a projected paragraph does not automatically perform a lifecycle transition.

[`active_state_structured_projection_v0`](https://github.com/loopx-project/loopx/blob/main/docs/reference/protocols/active-state-structured-projection-v0.md)
defines a typed, read-only view of Todos, Gates, and Next Action from that workbench. Its Reader Contract preserves
several boundaries:

- a projection can be recomputed;
- a projection grants no write authority;
- a generated compatibility id is not automatically a migration-ready canonical id;
- duplicate ids or missing sections become diagnostics instead of disappearing silently.

### 4. Run history: what one bounded turn observed and delivered

Run history keeps a compact index for one bounded turn, such as:

- participating Agent, Todo, and Goal;
- whether the run was observation, delivery, or blocker work;
- validation and evidence references;
- delivery scale and outcome;
- successor, replan, or no-follow-up;
- whether spend conditions were satisfied.

A run snapshot covers less than complete project memory. It answers what this turn saw, attempted, and
proved, while Goal lifecycle still depends on the combination of Todos, Gates, events, and acceptance.

Rich logs, raw transcripts, and verifier tails can stay in local or private runtime artifacts.

A public projection should retain only the bounded references required for review and recovery.

### 5. Status and other projections: how a consumer reads now

`loopx status`, `quota should-run`, dashboards, review packets, and task graphs are different read models for different consumers.

They may:

- aggregate several source facts;
- compress large payloads;
- reorganize state for a user, Agent, CLI, or operator;
- surface staleness, gaps, repair needs, and attention signals.

They must not:

- invent a Todo absent from the source;
- turn display order into lifecycle priority;
- let card or graph edits bypass the write API;
- treat a stale external observation as a current fact.

[`task_graph_projection_v0`](https://github.com/loopx-project/loopx/blob/main/docs/reference/protocols/task-graph-projection-v0.md)
is explicit about this boundary. Relationships such as `blocks`, `validates`, `continues`, and `hands_off_to` are
derived graph edges, not new scheduling commands.

## Three ledgers: turn journal, goal state, and run history

Treating "all records" as the same kind of state leads to "phase recorded" being mistaken for "business transition." LoopX distinguishes three ledgers:

| Ledger | What it owns | Lifecycle | Typical use |
| --- | --- | --- | --- |
| Turn journal | Recovery information for a single transaction | Single transaction | Recover an interrupted bounded segment |
| Goal/event state | Durable lifecycle transitions | Cross-session, cross-Host | Determine current frontier, Gate, acceptance |
| Run history/status | Historical evidence index and projection | Read-only, not rewritable | Context for review, replan, handoff |

**Turn journal** answers "what happened in this turn and how to recover if interrupted." It records temporary
state within a single transaction, not durable business facts. The classic mistake of treating a journal as
goal state: an agent sees "entered phase three" in the journal and assumes the goal transitioned to phase
three. The journal only records what the agent intended; only goal/event state records the actual completed
transition.

**Goal/event state** answers "what is the current frontier, and who can do what." It records lifecycle
transitions (Todo completion, Gate resolution, Vision update) through append-only events and supports cross-session
reconstruction.

It is the authoritative source for durable lifecycle facts, and quota compiles it together with
registry/boundary, Todo/Gate, capability/workspace, run outcomes/history, scheduler context, and fresh
external facts.

**Run history/status** answers "what happened historically, and what evidence exists." It is read-only and
cannot write back into goal state.

A run record saying "tests passed this round" does not mean the corresponding acceptance in goal state is
closed; only a transition written through a lifecycle command counts.

The cost of conflating the three shows up most clearly during recovery. An executor reading only run history will
redo work; an executor reading only the turn journal will believe an intent already landed; only an executor
reading goal/event state knows where the frontier actually advanced.

The practical significance of distinguishing these three:

- before every write-back, confirm you are writing to goal/event state (a transition), not to the turn journal
  (temporary records);
- before every decision read, confirm you are reading goal/event state, not an old projection from run history.

For complete source paths and experiments on the three ledgers, see
[Control-Plane Course Lesson 8](/loopx/docs/development/control-plane-course/08-evidence-refresh-and-self-repair/).

## Five source facts and the projection truth contract

The five surfaces are now separate, but "a projection is not writable" still needs a machine-checkable declaration, or it stays a sentence in a document.

The Projection Protocol section of
[`long_horizon_agent_state_protocol_v0`](https://github.com/loopx-project/loopx/blob/main/docs/reference/protocols/long-horizon-agent-state-protocol-v0.md)
writes the source/projection relationship as one checkable verdict:

```json
{
  "schema_version": "long_horizon_agent_state_protocol_v0",
  "projection_is_writable": false,
  "source_of_truth": [
    "registry",
    "active_state",
    "todo_item_v0",
    "run_history",
    "rollout_event_log",
    "operator_gate",
    "human_reward"
  ],
  "write_apis": [
    "loopx todo",
    "loopx refresh-state",
    "loopx operator-gate",
    "loopx reward",
    "loopx quota spend-slot"
  ]
}
```

Every entry in `source_of_truth` has a corresponding source state row, covering the registry, active_state,
`todo_item_v0`, `run_history`, `loopx_rollout_event_v0` (the rollout event log), `operator_gate`, and
`human_reward`.

The protocol defines them this way: **they are writable only through LoopX lifecycle commands or project-owned state
files; dashboards and showcase fixtures must not mutate them directly.**

The same document states the other boundary immediately:

> Projection protocol fields are read-only views. They may summarize, rank, and
> compress state, but they do not own truth or grant permission.

Those three verbs plus one denial are a minimal complete set.

**Summarize** lets a projection compress a long payload into a readable digest; **rank** lets it order by
priority; **compress** lets it drop detail.

**Grant permission** is explicitly excluded: however authoritative a projection looks, it is not write
authority.

The same pattern repeats across other projections.

The payload of `task_graph_projection_v0` carries:

```python
# loopx/control_plane/work_items/task_graph.py
"truth_contract": {
    "event_ledger_is_source_of_truth": True,
    "projection_is_writable": False,
    "write_api": False,
    "recompute_rule": "Recompute from status, active state, gates, leases, and run history after each lifecycle event.",
}
```

The agent management projection in `loopx/control_plane/agents/management_projection.py` carries the same
`projection_is_writable: False` and `write_api: False`.

That gives readers a checkable signal: **open any projection JSON and find `truth_contract`; if it claims to be
writable, that is a defect, not a feature.**

## Canonical state, workbench, projection, and external fact

These four layers must stay separate, because they answer the question "can this directly authorize a transition" differently:

| Layer | Typical content | Who can change it | Can it directly authorize a transition? |
| --- | --- | --- | --- |
| Canonical state | Events, typed Todos, Gate resolution, quota spend | LoopX lifecycle writer | Yes |
| Workbench | Active-state Markdown and human explanation | Controlled writeback or compatibility editing | Only after normalization into governed facts |
| Projection | Status, quota packet, dashboard, task graph | Projection builder | No; it informs a decision |
| External fact | Git commit, PR, CI result, cloud resource | The corresponding external system | Only through fresh readback and evidence |

A page saying "the PR is merged" may be a stale projection. A previous run saying "tests passed" may refer to
an older commit.

Inspect the external system and verify revision, freshness, and scope before using that observation for a
current transition.

## Storage medium and the authority contract

The current LoopX control plane is **local-first**: the project registry, active-state workbench, event and run
history, and runtime state live in project-local or user-local storage.

This does not make a Markdown file the authority by itself, and replacing files with a database does not
automatically create correct concurrency or recovery semantics.

[`event_sourced_state_contract_v0`](https://github.com/loopx-project/loopx/blob/main/docs/reference/protocols/event-sourced-state-contract-v0.md)
allows JSONL, SQLite, or another local-first append-only implementation when it preserves:

- stable event ids and ordered replay;
- idempotent append;
- projection head alignment with the event-store head;
- public-safe, local-private, and private-pointer partitions;
- Markdown as a workbench or projection rather than an arbitrary write API.

[`local_state_write_correctness_v0`](https://github.com/loopx-project/loopx/blob/main/docs/reference/protocols/local-state-write-correctness-v0.md)
is currently marked as a public-safe protocol draft. Its stronger write-correctness target separates `prepare ->
preview -> apply -> record -> project`:

- one `idempotency_key` should not duplicate the logical effect;
- an `expected_revision` mismatch should fail closed or recompute a non-overlapping patch from fresh state;
- a foreign or expired lease should never be silently cleared;
- the default target boundary is one Goal, narrowed only for a single order-independent Todo write;
- external writes, credentials, production, and private reads remain behind independent Gates.

Current Todo lifecycle commands reread and write under the active-state file lock, and preview exposes a write
intent.

The protocol also states that hard idempotency, uniform optimistic CAS, and lease-conflict enforcement are promoted
writer by writer. Do not assume that every writer already enforces the complete Draft.

Files, SQLite, and future providers answer "where are the bytes?" Events, revisions, CAS, leases, and authority answer "which transition is legal?"

### Shipped boundary versus design boundary

Shared-authority work in `v0.5.4` is more than a paper design: the repository contains a provider-neutral TypeScript
`AuthorityStore` contract plus staged file, NoKV, and PostgreSQL candidates with conformance evidence. That is still
not an enabled shared control plane. The release does not wire these candidates into the default runtime or ship a
ready-to-enable remote authority service. Installing a Provider does not change a Goal's source of truth.

Post-`v0.5.4` `main` may contain further default-off shadow, parity, fencing, or provider-first cutover slices. They
prove migration mechanics; they are not evidence that `v0.5.4` shipped cloud collaboration. Use the matching tag and
release notes for stable behavior and the current stage in the [Shared Control-Plane Authority
RFC](/loopx/docs/architecture/rfcs/shared-goal-authority-state-provider-v0/) for experimental status.

You can currently rely on:

- local project state and the global registry projection;
- the Todo lifecycle writer's active-state file lock, preview/readback, and currently implemented
  idempotency behavior;
- registered peers, soft claims, optional task leases, and independent-worktree guards;
- several Hosts reading one registry and Goal through controlled writeback;
- staged file, NoKV, and PostgreSQL candidates for development and qualification; they do not acquire
  runtime authority automatically.

Do not currently promise:

- automatic online authority shared across devices;
- new claims, completion, lease renewal, or protected writes while a device is offline;
- consistent distributed state from putting the project directory in a sync drive;
- NoKV, a database, or IM automatically replacing the LoopX lifecycle owner.

A future cross-device control plane should retain one canonical LoopX authority, revision-bound idempotent commands
and receipts, and separate message delivery, context memory, and state authority. Until the Draft has an
independently reviewed promotion, runtime wiring, and release validation, this book teaches those boundaries rather
than a fictional cloud-mode quickstart.

## Three layers of integrity for historical artifacts

LoopX can prevent research, validation, and decision artifacts from being rewritten silently. That does not make an old conclusion perpetually applicable. Evaluate historical evidence in three layers:

| Layer | Question | Typical checks |
| --- | --- | --- |
| Lineage integrity | Who produced the artifact, when, and was it appended, corrected, or superseded? | `event_id`, `run_id`, producer, recorded revision, append-only references |
| Current applicability | Do its inputs, scope, and external facts still match the current problem? | Commit, target key, source revision, time window, Gate scope, fresh readback |
| Supersession | Did later evidence or a decision replace, narrow, or revoke it? | `supersedes`, `superseded_by`, compensating event, newer decision, replan delta |

Append-only lineage protects history from silent alteration; it does not prove that an old conclusion is fresh.

Research notes, test results, and PR readbacks need stable join keys and a new applicability check after material
inputs change.

When applicability is unknown, retain the artifact as a historical observation or stale evidence instead of deleting
it or treating it as current authority.

That distinction is what keeps the 09:52 duplicate from becoming two legal completions: both entries keep their
lineage, and only one of them matches the current source revision.

[`agent_scoped_evidence_ledger_v0`](https://github.com/loopx-project/loopx/blob/main/docs/reference/protocols/agent-scoped-evidence-ledger-v0.md)
provides a bounded, read-only Agent chronology for replan and handoff. It does not replace current status, a quota
decision, or external-system readback.

## Replay does not preserve an old conclusion

Replay aims to reconstruct current state from ordered facts; preserving old judgments forever is not its job.

Assume the ledger contains:

```text
todo_added(T1)
todo_claimed(T1, agent-a)
gate_added(G1, scope=public_claim:action:homepage)
run_recorded(R1, tests_passed_at=commit-a)
```

Git later advances to `commit-b`, and the user changes the homepage direction. Replay still proves that R1 and G1
existed.

It does not prove:

- R1 remains valid for `commit-b`;
- G1 covers the revised homepage action;
- `agent-a` is still executing in the correct workspace;
- the current frontier is ready to publish.

The recovering executor combines replayed project facts with a fresh environment inspection. That is also why the 09:41 question can only be answered by reading the source, never by reading the most convenient page.

## A projection gap is a control-plane failure

Do not choose whichever surface is most convenient when sources disagree:

- an event contains an open Todo, but status omits it;
- a Gate is resolved, but quota still reports operator wait;
- active state has a Next Action with no corresponding Todo;
- a dashboard reports runnable work while the workspace guard points to another worktree.

These are **projection gaps**. Handle them in order:

1. identify the authoritative source;
2. classify source-write failure, stale projection, migration drift, or stale external observation;
3. repair through the owning lifecycle or writeback path;
4. recompute the projection and verify its source revision;
5. do not run delivery that depends on the disputed state until it is consistent.

Manually editing several displays into agreement only hides the fault.

The 09:43 scene happened precisely because Agent B skipped step one and started working before step five.

## Cost and boundary

What this separation buys is "one owner per fact," and the cost needs stating, because it is how readers decide when not to rely on a projection.

**Cost one: a projection is eventually consistent and may lag.** After any source write there is a window in
which the projection still shows the old value. That window may last milliseconds, or 31 minutes as at 09:43,
depending on who recomputes and when. The system does not stop working because of it, so **reading a projection
has to carry a freshness judgment**.

**Cost two: reading a projection cannot replace a fresh decision.** A projection exists for fast human reading,
and it has already summarized, ranked, and compressed. The dropped detail may be exactly what this turn needs —
a Todo's `resume_when` condition, or the revision an evidence item is bound to. After a status digest, you still
read the source once for the decision.

**Cost three: every write must go through the write_apis.** `loopx todo`, `loopx refresh-state`, `loopx
operator-gate`, `loopx reward`, and `loopx quota spend-slot` are the write paths the protocol names. Bypassing
them to edit a projection directly produces the 09:52 fork: two lineages both claim to be T1's completion
evidence, and the system has no basis to rule which one is legal.

**Cost four: every recovery reads more than once.** A recovering executor cannot act after reading a single
page; it reads the source and checks the freshness of external facts. That is a real cost, and it is the price
requirement one charges in implementation.

**Boundary one: a projection only describes the source as of its recompute.** When a projection's `generated_at`
predates the latest lifecycle event, it describes the past. Whether a projection may inform a current decision
depends on the source refs it carries and on whether the source has moved.

**Boundary two: a source owner is authoritative only inside the protocol's scope.** Git, CI, PRs, and cloud
resources are owned by their external systems, and LoopX stores only bounded readback. Making those systems
"sync into" LoopX is not the goal of this design.

**Boundary three: `local_state_write_correctness_v0` is a Draft, not an enabled guarantee.** Its hard
idempotency, uniform CAS, and lease-conflict enforcement are promoted writer by writer. Treating the Draft as a
contract every writer already follows yields conclusions stronger than the reality.

## Named failures: what these rules stop

**A writable projection is a defect.** Run `loopx --format json status --include-task-graph` and inspect
`truth_contract` in the returned object:

```text
expected: projection_is_writable = false, write_api = false
actual:   projection_is_writable = true
          -> some projection builder claims write authority; repair it first
```

These fields have consumers beyond prose:

- `examples/long-horizon-agent-state-protocol-smoke.py` asserts the protocol text contains
  `"projection_is_writable": false`;
- `examples/project/goal-channel-status-export-smoke.py` asserts the exported payload's
  `truth_contract["projection_is_writable"]` is `False`.

Either failure means some projection builder started claiming write authority, and that class of defect does
not self-correct: once a consumer treats the projection as writable, the fork starts there.

**Editing Markdown directly performs no transition.** After changing a checkbox in `ACTIVE_GOAL_STATE.md`
to `[x]`, the Todo's status does not change, because the canonical write path never ran. The legal route is a
`loopx todo` lifecycle command, which leaves behind the Todo id, producer, and completion evidence.

The difference is not who typed it, but whether lineage was left behind: a manual edit leaves an unowned byte
change, while the lifecycle command leaves the same fact that status, review packets, and the next quota
decision can all reuse.

**A stale projection cannot supply a current fact.** The 09:43 scene tests the same rule: one card says T1
pending while the event stream says T1 is done. Agent B must stop and read the source rather than take the
more convenient answer and continue.

The rule applies to people too. The open-gate count an operator sees on a dashboard may lag the real state in
`loopx operator-gate`; using it to decide whether a human must act now can mean reading a Gate that is already
resolved.

## Decide where a new field belongs

Ask in this order:

1. Does it describe durable identity, configuration, or routing? Put it in the registry.
2. Does it describe a lifecycle transition? Put it in an event.
3. Does it describe one observation or delivery turn? Put it in a run snapshot or evidence bundle.
4. Does it serve only one reader view? Derive it as a projection from existing facts.
5. Does GitHub, CI, or another system own it? Keep that external authority and store bounded readback.
6. Is it a domain-specific result for Issue-Fix, Explore, or another pack? Keep it in Domain State rather than forcing it into generic Todo or quota state.

If one field tries to carry configuration, event, display, and permission semantics, the protocol boundary probably needs to be split first.

## Protocol reading routes

This chapter owns the learning sequence, not the complete schemas. For state changes, start with:

- [`event_sourced_state_contract_v0`](https://github.com/loopx-project/loopx/blob/main/docs/reference/protocols/event-sourced-state-contract-v0.md)
  for events, replay, ordering, and privacy;
- [`active_state_structured_projection_v0`](https://github.com/loopx-project/loopx/blob/main/docs/reference/protocols/active-state-structured-projection-v0.md)
  for the typed read model over the Markdown workbench;
- [`task_graph_projection_v0`](https://github.com/loopx-project/loopx/blob/main/docs/reference/protocols/task-graph-projection-v0.md)
  for the read-only relation graph;
- [`long_horizon_agent_state_protocol_v0`](https://github.com/loopx-project/loopx/blob/main/docs/reference/protocols/long-horizon-agent-state-protocol-v0.md)
  for source and projection ownership, concurrent Agents, and lifecycle in long-running work;
- [`agent_scoped_evidence_ledger_v0`](https://github.com/loopx-project/loopx/blob/main/docs/reference/protocols/agent-scoped-evidence-ledger-v0.md)
  for the Agent-scoped chronological read model used before replan and handoff;
- the [Status Data Contract](https://github.com/loopx-project/loopx/blob/main/docs/status-data-contract.md)
  for Agent and operator-facing aggregation.

If you plan to change registry, event, Domain State, replay, or projection builders, continue to [Control-Plane
Course Lesson 4](/loopx/docs/development/control-plane-course/04-state-substrate/). It enters source paths and
experiments through fact ownership in Issue-Fix, Auto ML, and Auto Research. This chapter remains the external
developer's conceptual entrypoint.

## Invariants

Six claims you can check yourself.

1. **A projection never grants write authority.** Open any projection JSON: `projection_is_writable` in
`truth_contract` must be `false`. If it turns `true`, that is a defect.
2. **When source and projection disagree, the answer is the source.** Cards, dashboards, and review packets are
not the arbiter; on a disagreement, find the authoritative source before acting.
3. **A projection may lag, so reading one carries a freshness judgment.** A projection whose `generated_at`
predates the latest lifecycle event describes the past, and cannot be treated as now.
4. **Every write goes through the write_apis.** Editing a projection directly creates a second lineage, and the
system has no basis to rule on its legality.
5. **Append-only keeps history from being silently rewritten; it does not keep an old conclusion fresh.**
Lineage integrity, current applicability, and supersession are three separate checks.
6. **Recovery is replay plus one fresh inspection.** Replay alone yields a correct history and an expired
present.

These six answer one question: **once the context is flushed, what still lets "what happened" be answered?** This chapter gave LoopX's answer on fact ownership. The next chapter builds a work graph on this substrate: who may do what, which condition blocks it, and how work legally continues, hands off, or ends.
