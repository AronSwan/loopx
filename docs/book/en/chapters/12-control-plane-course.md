# Control-Plane Developer Course

> For developers who plan to modify LoopX Kernel, CLI, state projection,
> scheduler, or extension behavior.

## Relationship to the Dev Book

The Dev Book gives external developers a complete path from mechanism model to
project onboarding or contribution. The Control-Plane Developer Course is an
independent chapter for developers who need to enter implementation source,
judge rule precedence, locate bounded contexts, or add a new control-plane
rule.

Both share the official protocols and source as authority, but do not maintain
two copies of the full course:

- the Dev Book explains enough mechanism to predict behavior;
- the Course provides Showcase derivations, decision tables, source
  walkthroughs, experiments, and review questions.

## Course map

| Course chapter | Topic | Best entry point in the Dev Book |
|---|---|---|
| [Concept primer](/loopx/docs/development/control-plane-course/00-concept-primer/) | Limited context, externalized state, core concepts | [Four demands](02b-long-horizon-requirements.md) |
| [Long-horizon convergence](/loopx/docs/development/control-plane-course/topic-long-horizon-convergence/) | Direction, evidence, delta, liveness, terminal invariants | [Recovery and boundaries](04-runtime-boundaries.md) |
| [Lesson 1: Harness is the effectful program](/loopx/docs/development/control-plane-course/01-agent-loop-effectful-program/) | Harness as the agent-loop effect interpreter | [One governed turn](03-one-turn.md) |
| [Lesson 2: Architecture from three showcases](/loopx/docs/development/control-plane-course/02-goal-control-plane-architecture/) | Agent / Provider / Capability / Kernel ownership | [Sessions, Goals, and LoopX](02-session-goal-loopx.md) |
| [Lesson 3: First real loop](/loopx/docs/development/control-plane-course/03-first-real-loop/) | Guided start, todo, quota, refresh, spend | [Connect a project](05-connect-existing-project.md) |
| [Lesson 4: State substrate](/loopx/docs/development/control-plane-course/04-state-substrate/) | Registry, events, active state, run history, projection | [Durable state](state-substrate.md) |
| [Lesson 5: Work graph and peers](/loopx/docs/development/control-plane-course/05-work-graph-and-peers/) | Claim, lease, handoff, equal peers | [Work graphs and authority](work-graph-and-authority.md) |
| [Lesson 6: Quota kernel and interaction contract](/loopx/docs/development/control-plane-course/06-quota-decision-kernel/) | `should-run`, route, mode, interaction contract | [One governed turn](03-one-turn.md) |
| [Lesson 7: Host, heartbeat, stateful backoff](/loopx/docs/development/control-plane-course/07-host-scheduler-and-heartbeat/) | Execution context, RRULE, ACK, backoff | [Budget, admission, and observation](04b-budget-and-admission.md) |
| [Lesson 8: Evidence, refresh, self-repair](/loopx/docs/development/control-plane-course/08-evidence-refresh-and-self-repair/) | Material progress, replan, repair delta | [Recovery and boundaries](04-runtime-boundaries.md) |
| [Lesson 9: Add a control-plane rule](/loopx/docs/development/control-plane-course/09-engineering-a-control-plane-rule/) | Invariants, ordered rules, schemas, smokes | [Change a rule](source-change-control-plane-rule.md) |
| [Lesson 10: Layered quality gates](/loopx/docs/development/control-plane-course/10-autonomous-agent-quality-gates/) | Deterministic tests, canaries, model behavior, release gates | [Validation to PR](source-validation-to-pr.md) |
| [Lesson 11: Extensions, governed execution, and domain products](/loopx/docs/development/control-plane-course/11-extension-layer/) | Recoverable external-effect settlement, Explore, Graph/Harness, and domain products | [Extension lifecycle](10-extension-lifecycle.md) |

## Relationship to the Effect Interpreter RFC

Lesson 1 and the
[Agent Loop Effect Interpreter RFC](/loopx/docs/architecture/rfcs/agent-loop-effect-interpreter-v0/)
share one language: the harness is the effectful program around an agent loop,
and state machines are interpretation tables. Start with Lesson 1 before
entering Kernel implementation topics.

## From reading to making a judgment {#reader-checkpoints}

The whole Course is not a prerequisite for adopting LoopX. To operate your own project,
start with [onboarding](05-connect-existing-project.md) and the [Workspace](workspace-v1.md).
Before changing implementation, use the checks below. They connect four questions from
[the running example](00-reading-guide.md#running-example) to existing regression tests,
without adding a teaching state machine, running a model, or actually publishing T3.

For each check, predict the result, run the tests, and locate the assertions that support
the answer. Record input facts, allowed outcomes, forbidden outcomes, and evidence limits.
You do not need a new Goal, acceptance protocol, or committed exercise notes.

### Environment and evidence limits {#checkpoint-environment}

Run the commands from the repository root of a complete LoopX source checkout, not from
the business project you intend to manage. They need Python 3.11+, Node.js 22.22.3+, uv,
and the test extra; dependency installation may access package indexes. Record the
checkout first rather than treating the book's answer as a passing run on your machine:

```bash
git rev-parse HEAD
python --version
node --version
uv sync --extra test
```

The first three checks use real local state or CLI calls in temporary directories; the
fourth uses constructed quota inputs. These are not write-free demonstrations: they
create test state and may start a local Effect runtime. Do not replace fixture registries,
state deletion, or corruption injection with your live Goal. Missing dependencies or an
unavailable runtime block the exercise; they do not establish a passing rule. Do not
remove a guard to make the exercise pass.

Source links below are pinned to the inspected main commit; the commands execute your
recorded checkout. When a test is renamed or behavior changes, follow the original invariant
to its current owner and recheck the explanation instead of copying new output into the
expectation. Passing these tests covers their paths, not full-product or real-Host qualification.

<!-- reader-checkpoint:state:start -->
### Check one: which state can admit work? {#checkpoint-state}

**Predict first.** T1 is done or blocked in the selected File/SQLite authority, while old
Markdown still shows open. Can T1 execute? If authority reads temporarily fail, can
Markdown supply a fallback answer?

```bash
uv run --extra test pytest -q \
  tests/control_plane/test_quota_authority_settlement_journey.py::test_stale_markdown_cannot_admit_terminal_or_blocked_work \
  tests/control_plane/test_quota_authority_settlement_journey.py::test_failed_canonical_read_cannot_fall_back_to_markdown
```

**Compare with the answer.** The first test covers File/SQLite and done/blocked combinations:
`decision=skip`, no selected Todo, and a `not_committed` heartbeat receipt. The second makes
File authority unreadable: it must not select a Todo or create this Turn's heartbeat receipt.
The presence of a display does not create another admission source.

**Evidence limit.** This protects admission under a selected authority. It does not mean all
Markdown is a cache: a legacy path can still use Markdown as source. It also does not prove
the unavailable provider has been repaired. Revisit [state](state-substrate.md) and inspect
[the tests](https://github.com/loopx-project/loopx/blob/67930ab6af78491f10ca3de4ff74ef7a39954a51/tests/control_plane/test_quota_authority_settlement_journey.py).
<!-- reader-checkpoint:state:end -->

<!-- reader-checkpoint:lease:start -->
### Check two: does historical success still grant execution? {#checkpoint-lease}

**Predict first.** A acquires and renews a lease, then repeats the original acquire request.
Does it receive the current lease, or proof that automatically restores old execution rights?
After release, should the original acquire key grant execution again?

```bash
uv run --extra test pytest -q \
  tests/control_plane/test_canonical_lease_acquire.py::test_public_acquire_renew_complete_and_retired_retry
```

**Compare with the answer.** In this File/SQLite, `hard_lease` fixture, retry after renewal
returns the current lease while retaining the original receipt. Reusing the retired acquire
key after release is rejected as `idempotency_key_reuse`; a new valid acquire uses a new key.
After completion writeback, the Todo is done and the lease is released. The test asserts
`state.exists()` after actual completion, not that all state files are absent at the end.

**Evidence limit.** Read historical receipts and current execution proof separately. This
sequential test does not prove strong exclusion for every soft-claim path, or cover concurrent
real Hosts, TTL expiry, or fencing at an external write sink. Revisit
[authority](work-graph-and-authority.md) and inspect
[the test](https://github.com/loopx-project/loopx/blob/67930ab6af78491f10ca3de4ff74ef7a39954a51/tests/control_plane/test_canonical_lease_acquire.py).
<!-- reader-checkpoint:lease:end -->

<!-- reader-checkpoint:settlement:start -->
### Check three: which part of incomplete work should be repeated? {#checkpoint-settlement}

**Predict first.** T1's writeback exists, and quota has been debited, but its settlement
receipt is missing. Should recovery repeat T1, debit again, or recover the original operation's
receipt? What proves that recovery did not debit again?

```bash
uv run --extra test pytest -q \
  tests/control_plane/test_quota_authority_settlement_journey.py::test_returned_command_settles_and_repairs_receipts_without_another_debit
```

**Compare with the answer.** Initial writeback returns `spend_required`; executing its bound
command reaches `settled`. The fixture then simulates only a missing receipt. The next read
reports `spend_receipt_required`. Executing the returned recovery command reports
`appended=false`, and the debit count stays at one. A further read reaches `settled` without
`settlement_owed`. Inspect the count and final state, not just the process exit code.

**Evidence limit.** Do not turn fixture receipt deletion into an operating runbook, or invent
a repair command without the original Goal/Agent/Todo/Turn binding. This test does not resolve
an unknown external effect, establish a zero API bill, or close G1 or Goal acceptance.
Revisit [the normal Turn](03-one-turn.md) and [recovery](04-runtime-boundaries.md), and inspect
[the test](https://github.com/loopx-project/loopx/blob/67930ab6af78491f10ca3de4ff74ef7a39954a51/tests/control_plane/test_quota_authority_settlement_journey.py).
<!-- reader-checkpoint:settlement:end -->

<!-- reader-checkpoint:monitor:start -->
### Check four: does no change always require replanning? {#checkpoint-monitor}

**Predict first.** One current-Agent monitor lane has five unchanged observations while a
peer still has its own work. Must the current Agent keep waiting? Does the answer change
when it has selectable advancement, or the Monitor is explicitly `watch_only`?

```bash
uv run --extra test pytest -q \
  tests/control_plane/test_monitor_replan_agent_scope.py::test_interleaved_monitors_keep_independent_no_change_streaks \
  tests/control_plane/test_monitor_replan_agent_scope.py::test_current_agent_advancement_still_preempts_monitor_streak_replan \
  tests/control_plane/test_monitor_replan_agent_scope.py::test_watch_only_monitor_streak_does_not_create_replan_obligation
```

**Compare with the answer.** The interleaved-lane fixture produces `monitor_no_change_streak`
only for the eligible current-Agent lane, not an obligation to handle the peer's lane. With
current-Agent advancement, the result is `run` without this replan obligation. The explicit
watch-only fixture does not create the obligation even with a streak of 50. Five is the
specific policy threshold here, not a theorem about all waiting work.

**Evidence limit.** These tests preset counters and evaluate decisions; they do not send five
interleaved remote polls. They cannot establish concurrent counter-write correctness, actual
Host waking, or scheduler backoff timing. Revisit [observation](04b-budget-and-admission.md)
and inspect
[the tests](https://github.com/loopx-project/loopx/blob/67930ab6af78491f10ca3de4ff74ef7a39954a51/tests/control_plane/test_monitor_replan_agent_scope.py).
<!-- reader-checkpoint:monitor:end -->

## Use the checks to locate a real problem {#diagnostic-routing}

In a real project, collect current read-only facts first; do not copy the tests' fault
injections. This is a reading route, not another automatic recovery algorithm. Mutations
still belong to the current entrypoint and its owner.

| Observation | Inspect first | Do not infer or do | Return to |
| --- | --- | --- | --- |
| A page disagrees with Todo state | Current authority, exact Todo, projection freshness | Overwrite source from a newer-looking page | [State](state-substrate.md) |
| Acquire once succeeded; writeback now refuses | Current lease, mode, owner, version; historical receipt separately | Bypass instance checks with an old receipt or the same Agent name | [Authority](work-graph-and-authority.md) |
| Writeback exists; the Turn is unsettled | Settlement under the original identity and returned outstanding action | Rerun the Host or debit manually again | [Turn](03-one-turn.md) |
| An external request timed out; outcome is unknown | Original operation identity and availability of provider readback | Treat timeout as proof that nothing executed | [Recovery](04-runtime-boundaries.md) |
| A Monitor is quiet or repeatedly requests replan | Current lane, selectable work, watch-only, due state, actual Host liveness | Force polls from quota balance alone or fabricate ACK | [Observation](04b-budget-and-admission.md) |

Use the [appendix's read entrypoints](appendix-reference.md) to locate information; verify
actual command behavior and target before collecting evidence. A public issue or PR should
contain minimal public-safe facts, not a live registry, raw transcript, credentials, or full
private run records. When evidence is insufficient, name the missing readback rather than
claiming health or successful recovery.

## Transfer the model to another domain {#transfer-exercise}

Try one command-free synthetic exercise: replace the JSON-output task with a comparison
report based on two public sources. This is not another qualified product journey and does
not establish domain correctness. It checks whether you mistook Git/CI for necessary
control-plane concepts.

| Original task | Corresponding question in the report task |
| --- | --- |
| Commit C1 and tests | Source versions, scope, citations, and a reviewable comparison method |
| T1 implementation and T2 documentation | Separately acceptable research and analysis work, with dependencies where needed |
| M1 waiting for CI | Source-update observation with an explicit source and stopping condition; state the human boundary when observation is unavailable |
| G1 approving publication | Who accepts the report and what publication scope is allowed; generating an artifact is not approval |
| T3 delivery | Return a reviewable result while the current source material and decisions remain valid |

**Shape of a good answer.** When the material corresponding to C1 changes to C2, recheck the
old analysis's applicability; the old conversation does not automatically become new truth.
A finished report does not authorize external publication. Preserving fact ownership, valid
evidence, current authority, and continuation shows that you learned the control relationships,
not only a set of coding commands.

For a contribution, take one forbidden outcome into [rule changes](source-change-control-plane-rule.md)
and [validation to PR](source-validation-to-pr.md) to establish a real counterexample, owner,
and acceptance evidence. Checking that documented paths exist and both locales use the same
test commands is maintenance, not a substitute for behavior tests or bilingual semantic review.
