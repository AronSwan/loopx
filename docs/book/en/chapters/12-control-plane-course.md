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
