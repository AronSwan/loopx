# From focused validation to a Pull Request

A control-plane PR is not strong because it runs many tests. It is strong when its evidence covers the
protocol chain it changes. One large smoke can miss a semantic error; one unit test can miss drift in
projection, scheduling, or writeback.

## Start with a bad outcome

Here is another common contribution chain. It differs from the error in the previous chapter because
every step looks correct:

```text
2026-04-07 14:20  A contributor changes a claim-related state-write rule on both sides.
14:35  Unit tests for the touched modules run. All green.
14:40  pytest -q runs. All green.
14:46  git diff --check runs. Clean.
14:50  git commit -s, push, open a PR. Description says "validated: pytest green".
Next day  A reviewer sees the change lands on the PostgreSQL authority store and asks:
          "Did the isolated-instance suite run? Where is the evidence?"
```

Unit tests and real behavior on PostgreSQL are two different things. This rule involves durable writes,
transaction boundaries, and revision conflicts under concurrency, and an in-memory fake smooths all of
them away. The contributor did not lie; they ran every command they knew about. What was missing is **a
layer they did not know they had to run**, and that layer covered exactly the part of the change most
likely to break.

There is a second problem on the same timeline, and it is quieter. The change moved a default behavior
from "reject unclaimed paths" to "self-heal first, then write". The smoke that encoded the old default
had `rejects-unclaimed-...` in its name; it now asserts the new behavior while its name still describes
the old contract. No release note mentions the change. CI is green, because the symptom here is
**documents and names that lie, not code that fails.**

Both problems share a root: **the contributor treated "the commands I ran" as "this change has been
proven".**

This chapter turns the decision-scope repair into a public evidence packet:

```text
independent invariant
  -> focused deterministic proof
  -> real public path
  -> risk-based cross-surface checks
  -> public/private scan
  -> reviewable commits and PR
```

The goal is not to reproduce maintainer-local automation. It is to let a reviewer judge the change from
protocols, invariants, and receipts.

## Why "run everything" is not enough

The natural reaction is to run every command available. On LoopX that does not work, for three reasons.

**The full suite does not fit.** The PR baseline includes lint, type, an output-budget smoke, layered
`pytest`, canary, and a public/private scan; the complete public smoke fleet is a separate matter. The
real path is slower still: a change affecting PostgreSQL authority needs a disposable isolated instance
and takes minutes to a quarter of an hour. Making every PR wait for the widest matrix costs all
contributors.

**More commands is not better coverage.** A hundred commands that all land on the same layer still
produce a one-layer conclusion. The PR above ran three command groups covering one thing: pure logic in
memory.

**Some obligations have no command at all.** "Was this default behavior change disclosed" cannot be
asserted by any test. Review is the only place it can be found.

So the order is: derive which evidence the risk requires, then decide what to run.

## Build the evidence matrix first

Do not begin by running every repository command. Map each risk to evidence:

| Risk | Independent oracle | Nearest proof | Cross-layer proof | Forbidden outcome |
| --- | --- | --- | --- | --- |
| Missing scope grants authority | `decision_scope_v0` | Decision table | Source-to-quota replay | Protected action runs |
| Missing scope becomes global | Explicit global-scope invariant | Negative test | Agent-frontier smoke | Independent work freezes |
| Lower-level flags override repair | Final interaction-contract authority | Precedence test | Scheduler replay | Host runs a stale action |
| Retry duplicates repair writeback | Write-correctness contract | Idempotency test | Interrupted writeback smoke | Duplicate event or spend |
| New field expands the hot path | Output contract | Shape or budget check | Actual CLI diff | Agent loses the next action |

If a validation command does not address a named risk, it may be convention rather than evidence for this
PR.

## Six evidence layers

The official
[Testing and Quality](https://github.com/huangruiteng/loopx/blob/main/docs/development/testing-and-quality.md)
guide defines the current quality system. For external contributors, organize it around the job.

### 1. Unit and contract tests

Use these for pure rules, schemas, transitions, and illegal-state rejection.

The decision-scope case directly tests:

```text
matching scope -> operator Gate
unrelated scope -> independent frontier
notice only -> authority remains unmet
ambiguous scope -> typed repair
explicit global scope -> global Gate
```

This layer is the best proof of a specific invariant. It does not prove that the CLI, projection, and
scheduler are wired together correctly.

### 2. Focused deterministic smoke

Exercise one real path through a shipped entrypoint:

```text
public-safe source fixture
  -> real projection
  -> real quota decision
  -> interaction contract
```

A smoke should be thin and durable. It protects shipped behavior or a historical regression. It should
not freeze incidental builder fields, and it should not depend on raw logs, real project state, or dated
research packets.

### 3. Public-safe decision replay

A replay lets a reviewer see:

```text
source facts
  + independently reviewed invariant
  -> expected decision and forbidden outcomes
```

and then recomputes the result through the real product path.

Replay differs from a snapshot. A snapshot may simply store current output. A replay's expected outcome
must come from the protocol, not from the code under test.

### 4. Risk-based canary

Canary selects the smallest cross-surface set from the Git diff:

```bash
loopx canary premerge --from-git-diff
```

It catches "scope policy is fixed but the scheduler, output budget, or another consumer drifted". It
cannot replace focused regression, because it does not always name this change's specific error.

### 5. Full public smoke fleet

The complete public sweep suits `main`, daily runs, or explicit manual dispatch:

```bash
loopx canary smoke-suite --suite full-public --jobs 4 --timeout-seconds 120
```

An ordinary PR should not synchronously wait for the widest matrix. The fleet owns broad coverage,
inventory, and health. It cannot replace per-PR semantic design.

### 6. Model behavior and release qualification

Use a real model only for questions deterministic checks cannot answer, such as whether an Agent
understands a compressed default packet.

Gate precedence in this chapter is a deterministic rule, so the model layer is usually `not_applicable`.
Making a model judge scope coverage is expensive and weakens clear contracts.

Release qualification additionally binds an exact commit, tree, version, and clean state. A contributor PR
may supply code-level evidence. It must not describe that evidence as a qualified release or as behavior
live in production.

## Prove the semantics before the implementation

Keep validation in this order:

```text
Is the intended rule correct?
  -> Does the pure implementation conform?
  -> Does the shipped path preserve it?
  -> Do adjacent surfaces remain compatible?
```

The dangerous order is the reverse:

```text
run current code
  -> save output
  -> assert output never changes
```

That second path only produces characterization. When current output contradicts the protocol, refreshing
the golden file freezes the bug into a contract.

### What an independent oracle contains

At minimum:

- source facts;
- the authority owner;
- allowed outcomes;
- forbidden outcomes;
- irrelevant mutations;
- freshness and revision conditions.

For the decision-scope repair:

```text
Authority owner:
  valid decision-scope relation and its lifecycle writer

Allowed:
  typed repair before normal gated delivery

Forbidden:
  approval, implicit global block, or hidden gate

Irrelevant mutations:
  wording, unrelated agent gates, unrelated backlog size

Freshness:
  decision is recomputed from current source revision
```

A reviewer can approve this oracle before it becomes a test.

## Test counterexamples, not just the happy path

Control-plane bugs usually come from combinations. For each rule, design at least:

### A positive case

It fires under legal conditions.

### A suppression case

It does not fire when a higher-priority owner or a safe frontier exists.

### An illegal state

Missing fields, conflicts, duplicates, and stale revisions fail closed or enter repair.

### A metamorphic case

Changing an irrelevant input leaves the output unchanged:

```text
add unrelated gate
change user-facing prose
increase other-agent backlog
reorder projection rows
```

None of these may turn an ambiguous Gate into authorization.

### Retry and interruption

Interrupt between prepare, host result, validation, writeback, or spend. Recovery must not duplicate an
effect or a spend.

These dimensions protect the protocol better than ten full JSON snapshots.

## Test doubles must obey the real contract

A fake Host, a fake clock, or an in-memory store can reduce test cost. It must not invent product
semantics.

Check a fake for:

1. defaults matching the real adapter;
2. observation, housekeeping, and meaningful effects kept separate;
3. denied, timeout, non-zero, and malformed results staying on distinct branches;
4. idempotency and proposal identity being recorded;
5. final assertions checking a receipt rather than "the call happened".

A file created or cleaned up during setup, for example, is test scaffolding rather than material
progress. Only protocol-declared effects with an independently validated postcondition should form a
delivery receipt.

When a fake disagrees with the real contract, repair the test infrastructure before deciding the product
regressed.

## Real-path validation: the most expensive layer

The previous five layers finish in seconds on a laptop. This one does not, and it covers the part that
breaks most easily.

### Why a fake cannot prove authority writes

Durable writes, transaction boundaries, revision conflicts under concurrency, and cross-process lease
semantics all flatten inside an in-memory store: no real commit semantics, no real race, no schema-level
failure. A fake always agrees with your assumptions, which is exactly why it is cheap.

The gate for this class of change is explicit: refactors must exercise the affected production entrypoint
and real backend before delivery. For changes affecting PostgreSQL authority, point `LOOPX_TEST_POSTGRES_URL`
at an isolated disposable server and run `npm run test:postgresql-authority-store`, recording the exact
commit, backend version, tested behavior, and failures or limits. The `PostgreSQL Integration` workflow
runs the same ladder row and the service admission suite against a disposable server, so the path stays
qualified locally and in CI.

### Isolation is the precondition

Use a disposable database or tenant and runtime directory, with synthetic fixtures or an owner-authorized
read-only snapshot. Never point the suite at a shared or production database: it creates roles and injects
schema-level failure triggers, which is both how it finds problems and why it cannot run against real data.

Never promote a running goal, switch its provider, or mutate its registry, writer fence, Todos, or leases
for a test. Report a concurrent source change instead of overwriting or restoring it. Private snapshots
and raw output stay out of Git and out of public review. Stop the temporary server afterward.

### What to do when the environment is unavailable

If no safe isolated instance exists, the correct result is to **hold delivery and report the evidence
gap**, not to skip the layer and continue.

A skipped test is not a passing test. Both produce zero evidence. The difference is that the skipped one
leaves clean-looking output, which is why it so easily becomes "validated" in a PR description. That is
precisely the mistake made by the 14:50 PR at the top of this chapter: the description did not lie, it
said "pytest green", but a reader takes that sentence to mean "the behavior is verified".

The honest version states which environment the layer needs, why it is unavailable now, which conclusions
therefore remain unverified, and who can unblock it.

## Choose local validation commands

The official LoopX contribution baseline is:

```bash
python -m pip install -e ".[test]"
python -m ruff check tests loopx/canary loopx/control_plane loopx/domain_packs loopx/presentation
python -m mypy
python examples/control_plane/cli-output-budget-regression-smoke.py
python -m pytest -q
git diff --check
```

During development, start from the most focused command instead:

```text
changed decision rule
  -> related unit/contract test
  -> one real-path focused smoke
  -> affected output/compile/lint check
  -> diff-selected canary
```

Current repository, issue, and quality catalog decide specific smoke names. This book does not maintain a
drift-prone command list.

### Documentation and protocol PRs

Public-docs-only changes normally need at least:

```bash
git diff --check
loopx check --scan-path <changed-doc-or-directory>
```

A protocol document that changes shipped behavior still needs its contract or smoke. "Markdown only" does
not mean zero behavioral risk.

### Python rule PRs

Consider at least:

- lint, type, and compile for touched modules;
- pure decision table;
- focused public smoke;
- CLI output budget when a hot path is affected;
- `loopx canary premerge --from-git-diff`;
- public/private scan.

### Host, writeback, and scheduler PRs

Additionally cover:

- fake Host and clock;
- interrupted phase replay;
- no-effect and no-spend paths;
- idempotency and revision conflict;
- scheduler ACK and reset identity;
- capability and authority denial.

One successful happy path does not vouch for an external side effect.

## Default behavior changes must be disclosed

This is the row in the table above with no command to run, and the class review misses most often.

When a rule's default behavior changes, three things must happen together:

1. rename or rewrite the smoke that encoded the old default, so its name describes the new contract;
2. update docs and release notes with the before and after behavior;
3. name the affected lanes in the PR description.

A missing step 1 is the quietest symptom of the three. A failing test gets noticed; **a test whose name
lies is always green.** That is the `rejects-unclaimed-...` case: the assertion already moved with the
implementation while the name and the release note still described the old contract, leaving two
statements about the same behavior in the repository, one of them stale.

Disclosure has a second requirement that is easy to confuse with it: **guidance and machine-enforced
obligations must be written separately.** A field like `must_attempt_work` is a state the machine
rejects; a sentence saying "check first" is not. Writing the second as the first implies the system will
intervene; writing the first as advice tells a reviewer it is negotiable. Both must be explicit in the
contract rather than inferred from prose.

This class has no automated check because it requires a judgment about what the current default was, and
that is exactly what the implementation has already changed. Any assertion can only read the new value.
So it lands on the reviewer, which is why it belongs in the PR description: the reviewer's inputs are the
description and the diff, and the boundary they can find is the boundary the description mentions.

## Interpret validation results correctly

Validation is not a `passed: true/false` flag:

| Result | Meaning | How to write it in a PR |
| --- | --- | --- |
| `pass` | Current check is satisfied | Command, scope, and result |
| `blocking_failure` | An invariant is violated | Do not submit as ready; repair or narrow scope |
| `infra_failure` | The environment did not produce a product conclusion | Record the runner or provider problem; do not write "product failure" |
| `manual_hold` | Automated evidence is insufficient and needs an owner | State the question and the decision required |
| `advisory` | A risk signal that does not block this change | Explain why work may continue |
| `deferred_gap` | Valuable but not yet covered | Name the owner and successor; do not present it as covered |
| `not_applicable` | The layer does not fit this semantics | Give a stable reason |

An unavailable real model service, for instance, cannot prove Gate policy wrong. A passing unit test
cannot override a deterministic canary failure either.

## Keep the change reviewable in Git

Before a non-trivial contribution:

1. create a clean branch or worktree from the latest default branch;
2. confirm the working tree has no unrelated task in it;
3. change only the files the same protocol result requires;
4. reclassify every path before staging;
5. stage by explicit pathspec, never a broad `git add .`.

Inspect first:

```bash
git status --short --branch
git diff --stat
git diff --name-only
git ls-files --others --exclude-standard
```

This is not Git formalism. A LoopX checkout can hold source, public fixtures, local runtime state, and
generated evidence at once, and they must be separated before commit.

## Classify paths before staging

Assign every changed path:

| Category | Examples | Action |
| --- | --- | --- |
| Product code | Protocol policy, writers, projections | Commit when it belongs to this PR |
| Public docs | Protocols, contributor guides | Commit when it explains current behavior |
| Durable validation | Contract tests, public-safe smokes | Commit when it protects this rule |
| Local or private state | `.loopx/`, `.codex/goals/`, live state | Do not commit |
| Generated or raw evidence | Logs, transcripts, verifier tails | Do not commit |
| Unrelated artifacts | Other experiments, reformatting | Keep out of the PR |

Scan candidate paths for:

- credentials, tokens, or secrets;
- machine-local absolute paths;
- private issues, documents, or internal links;
- raw benchmark tasks, trajectories, or verifier output;
- real local content from an active Goal or Todo;
- large generated logs and screenshots.

A public fixture keeps only the minimal synthetic facts needed to reproduce the state machine.

## How to split commits

Split by the reviewer's judgment task, not mechanically by file type.

A small rule repair can be one cohesive commit:

```text
repair ambiguous decision-scope routing
  - policy correction
  - focused contract and replay
  - protocol clarification only if needed
```

When a behavior-preserving mechanical move is involved, commit characterization or the move first:

```text
commit 1: characterize existing protocol behavior
commit 2: move cohesive rule family without behavior change
commit 3: change rule and add negative/replay evidence
```

Do not mix a formatter pass, an unrelated rename, another extension, and this Gate repair in one commit.

Commit messages state the outcome:

```text
fix(control-plane): repair ambiguous decision scopes
```

rather than:

```text
update quota helpers
```

### Every commit needs a DCO sign-off

Every commit on a pull-request branch must carry:

```text
Signed-off-by: Your Name <your.email@example.com>
```

Create it with `git commit -s`. If a commit is missing the trailer, amend it with `git commit --amend -s`,
or use an interactive rebase for several commits and update the branch. The `Sign-off` check rejects
unsigned commits, and together with `merge-gate` it forms the required-check contract. Manual merge
commits and web edits need signatures too, because the check exempts only verifiable GitHub-generated
two-parent merges.

This requirement has nothing to do with tests, yet it ranks alongside them: it certifies who made the
commit and under what license. A branch that passes every check but carries no sign-off still cannot
reach `main`.

## The PR description is a protocol evidence packet

A strong PR description follows this shape:

### Problem

Describe a reader-visible or state-machine failure. Do not start from a filename.

### Protocol and invariant

Name the contract that owns the semantics and the outcomes that must be allowed or forbidden.

### Change

State which of source, projection, decision, effect, or writeback changed, and what explicitly did not.

### Validation

List by risk:

- unit and contract;
- focused smoke or replay;
- output or boundary;
- canary;
- the layers not run or not applicable, with reasons.

### Compatibility and recovery

Cover public fields, migration, retry, rollback, manual holds, and release impact. Name the affected lanes
for a default behavior change and link the renamed smoke.

### Public boundary

Confirm there is no local state, private evidence, credentials, raw session, or machine-local path.

A reviewer should be able to answer from the description:

```text
What contract changed?
Why is the new decision correct?
Which consumers were checked?
What remains owner-held?
```

## Link an issue and a public task

Non-trivial work should link the
[Contributor Task Board](https://github.com/huangruiteng/loopx/blob/main/docs/development/contributor-tasks.md)
or a GitHub issue:

- declare the slice you intend to take before a large change;
- keep scope close to the claimed task;
- get design or owner feedback before changing public schemas, scoring, permissions, release, or
  production behavior;
- publish the concrete blocker and the validation you tried when you are stuck;
- do not copy a `Maintainer-owned` live run.

An issue is a public collaboration boundary. It is not a place to paste local Goal state wholesale.

## PRs that must stop and wait

Do not push through these by running more tests:

- public JSON or schema fields must be removed or renamed;
- canonical state storage or migration must change;
- permission, production effect, or credential boundaries must change;
- benchmark scoring, task semantics, submission, or leaderboard behavior must change;
- authority fields must be removed from the default agent-facing packet;
- private sources or maintainer-owned live evidence are required;
- a release or merge owner must decide the outcome;
- the first screen, hero, or primary CTA needs owner presentation review.

These are decision gates, not test gaps. Validation cannot grant a user's or maintainer's authorization.

## Review feedback is protocol validation

After receiving review, do not mechanically apply every suggestion. Decide:

1. Is the reviewer pointing at the invariant, the implementation, readability, or scope?
2. Does the suggestion agree with the current protocol and evidence?
3. Would the change affect another consumer, a migration, or validation?
4. Does it need a new counterexample rather than only a code edit?
5. Do the PR description and docs need reorganizing too?

When review exposes protocol ambiguity, agree on semantics first. Do not leave two contradictory tests
both "passing".

### Review has to execute, not only read

One of those judgments carries an execution requirement. For behavior-bearing changes, a reviewer does
not infer equivalence from a title: they inventory the legacy caller branches at an immutable baseline
and compare the same synthetic inputs at the exact head through the same public entrypoint, covering
successful and rejected paths, diagnostics and remediation, omitted or empty or cleared arguments,
persisted readback, ownership, and receipts. Several providers that share the new rule agreeing with each
other is not before/after compatibility evidence.

Sensitivity must be shown too: the focused case has to fail on the historical defect or a deliberate
mutation and pass on the fix. Missing comparison evidence blocks a change approved on "behavior is
unchanged". And the evidence must be executable: baseline, exact head, and the sensitivity case each
record a replayable command or bounded script invocation, the real affected backend, an immutable fixture
fingerprint, exit status, and a normalized observation fingerprint.

One honest caveat: in the implementation, this requirement is projected as a check in the review packet,
and the packet's tests prove the requirement is projected, not that a reviewer executed it and not that
the product is defect-free. Which is exactly why it belongs in the same class as default-behavior
disclosure: **the last executor of these obligations is review, not CI.**

## Two real community contributions

This section mirrors the Chinese chapter. A substantive difference in case facts, conclusions, link
targets, or risk boundaries is a documentation defect.

<!-- community-casebook:small-pr:start -->
<!-- community-casebook:small-pr-problem -->

### Case one: a complete small PR from a CLI inconsistency

[PR #3540](https://github.com/huangruiteng/loopx/pull/3540)
comes from a real first-run and deep-use observation: `loopx --format json doctor` worked, but the more
intuitive `loopx doctor --format json` failed during argparse at the time (that spelling works today). The contributor reused the existing
subcommand format contract instead of building a second renderer.

<!-- community-casebook:small-pr-scope -->

The final change covers only parser wiring, the doctor handler, and one end-to-end CLI regression. Its
validation covers:

- the new subcommand argument position;
- the older global argument position;
- the precedence when both appear;
- an illegal format failing closed before diagnostics run.

<!-- community-casebook:small-pr-lesson -->

The value is not that the diff was small. It is that the change forms a complete chain:

```text
real user friction
  -> an existing public contract
  -> the correct owner
  -> positive, compatibility, and negative validation
  -> a reviewer who can judge it independently
```

A small PR is not a lower standard. It keeps the same user outcome inside a range that is easier to
validate and to roll back.
<!-- community-casebook:small-pr:end -->

<!-- community-casebook:review-repair:start -->
<!-- community-casebook:review-repair-problem -->

### Case two: reviewing a high-risk state write with counterexamples

[PR #3529](https://github.com/huangruiteng/loopx/pull/3529)
turns the shared-goal coordination aggregate head, file provider, and `claim_work` executor into one
provider-neutral Stage 2 slice. The first revision already had many positive tests, and the reviewer
still constructed stronger illegal states: a partial write reported as `applied`, a corrupted receipt
raising an unclassified exception, an oversized TTL crossing the typed boundary, Windows failing to
import the lock implementation, and naive timestamps plus bool-as-int reaching persisted state.

<!-- community-casebook:review-repair-response -->

The author did not add a string special case per input. They repaired the trust boundary all of them
pointed at:

- durable writes became write-all with fsync, atomic replace, and an `ambiguous` result when
  verification cannot complete;
- persisted receipts, timestamps, and generations are typed-validated before reaching the executor;
- locking reuses the repository's existing cross-platform owner;
- the RFC, negative tests, and CI record the machine-enforced obligation together.

<!-- community-casebook:review-repair-lesson -->

The case shows that review is not style picking after the code is done. A valuable review proposes a
concrete counterexample that breaks the current invariant and requires the repair to land in the real
owner; the author then proves with new negative cases that the same class of illegal state cannot re-enter
the semantic core. A final `APPROVE` applies only to the revalidated exact head.
<!-- community-casebook:review-repair:end -->

## What to validate after merge

Merging a PR does not prove deployment, release, or that every external Host updated. Depending on the
change, follow-up may include:

- the full public smoke on `main`;
- release qualification;
- packaged install checks;
- Host and plugin compatibility;
- documentation site deployment;
- fresh external readback.

Keep these distinct in the PR or release notes:

```text
merged
released
deployed
observed in target environment
```

Do not write an earlier state as a later one.

## Cost and boundaries: what this method gives up

**Cost one: the most expensive layer is also the slowest, and its judgment cannot be cached.** Unit tests
give you seconds; the real backend on an isolated instance gives you minutes, and it is the only evidence
for authority write behavior. Keeping the development loop fast means accepting that "green locally" is
an intermediate state, not a conclusion.

**Cost two: one test serving two purposes fails at both when the default changes.** A smoke both asserts
behavior and names it, and a default change pulls those apart. The cost is that every default change
touches the test name, docs, and release notes, and nothing in the compiler tells you which one you
missed.

**Cost three: evidence must be public-safe, which constrains fixture shape.** The most persuasive evidence
is often live state, and it cannot enter Git. Synthetic fixtures are weaker, and they are accepted
because an independent reviewer can reproduce them.

**Boundary one: the full suite belongs to `main`, daily, and manual lanes, not to each PR.** That is good
news for contributors, and it also means the widest matrix may first run after your merge. Your choice is
not whether to run everything; it is whether you named the highest-risk layer for this change.

**Boundary two: `not_applicable` is a valid answer when it carries a reason.** Gate precedence here is a
deterministic rule, so the model layer is `not_applicable`. Running every layer would not strengthen the
conclusion; it would only slow the PR.

**Boundary three: release, deploy, and observed are three states.** Merging, releasing, deploying to a
target environment, and being observed there each need their own evidence. A contributor PR can supply
code-level evidence. It cannot claim production is live.

**Boundary four: this chapter does not claim a task for you.** The Contributor Task Board and issues
decide which slices external contributors can take; changes needing private sources, maintainer-owned
live evidence, or presentation review still need an owner decision no matter how much validation they
carry.

## Checklist

Before opening a PR, confirm:

- [ ] Every risk has an independent oracle and a forbidden outcome.
- [ ] Unit, focused smoke, replay, and canary layers are chosen by risk, not by quantity.
- [ ] Characterization was not treated as correctness authority.
- [ ] Fakes, fixtures, and snapshots did not invent product semantics.
- [ ] Real-path validation (for example PostgreSQL integration) ran on an isolated instance, or the gap is written down as a blocker.
- [ ] A default behavior change renamed the smoke, updated docs and release notes, and named the affected lanes in the PR.
- [ ] Every commit carries a `Signed-off-by` trailer.
- [ ] Failures are classified, with no infrastructure failure written as a product conclusion.
- [ ] Every changed path is classified and staged by explicit pathspec.
- [ ] `.loopx/`, `.codex/goals/`, live state, credentials, private links, raw logs, and machine-local paths are not committed.
- [ ] Commits and the PR are organized by protocol result rather than a function list.
- [ ] Compatibility, recovery, unverified items, and owner gates are explicit.
- [ ] The PR links a public issue or task and does not copy maintainer-owned work.
- [ ] "merged", "released", "deployed", and "observed" are not conflated.

To pick deterministic tests, decision replay, canary, model-behavior checks, or release gates for
different risk surfaces, continue to
[Control-Plane Course Lesson 10](/loopx/docs/development/control-plane-course/10-autonomous-agent-quality-gates/).
The course provides combined-risk cases; this chapter keeps the delivery thread from local evidence to a
public PR.

At this point you have completed one control-plane path through developer contribution: pick an owner
from the contribution map, locate implementation along the protocol chain, change one rule, and deliver a
PR with independent evidence. Capability, provider, Host and runner, projection, docs and fixtures, and
extension contributions each have a different nearest proof, and all reuse one principle: establish the
protocol and permission owner first, then let evidence cover the real delivery boundary.

You do not need to memorize LoopX's current functions. You need to be able to say where a fact comes
from, who may change it, which invariant protects the decision, and what receipt lets the next turn
continue. When a contribution needs its own version, optional installation, or independent lifecycle,
move on to the
[extension placement decision](./08-extension-placement.md) instead of wrapping every contribution in an
extension.

## Invariants

Five sentences you can check yourself.

1. **Every validation maps to a named risk.** A command that maps to none is convention, not evidence for
   this PR.
2. **Expected values come before implementation.** An assertion reverse-engineered from current output can
   only characterize; it cannot be a correctness authority.
3. **Skipped is not passed.** With no isolated environment available, the correct action is to report the
   evidence gap and hold delivery.
4. **A default behavior change requires three things: rename the smoke, update docs and release notes,
   name the affected lanes.** A missed rename leaves a green test, which is what makes it dangerous.
5. **Merged, released, deployed, and observed are four states.** Never use one state's evidence to claim
   the next.

These five answer one question: **when "I ran it locally" is both a contributor's strongest claim and the
easiest one to misread, what lets a reviewer decide that this change was actually proven?**
