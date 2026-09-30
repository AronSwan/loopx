# How to use this book

This book is for external developers who already use Git, a terminal, and at least one agent development
tool. You do not need to read the LoopX Kernel source or learn every CLI subcommand first.

## What you will accomplish

Eight numbered chapters and a state-machine map establish the architecture model before two practice paths: project onboarding and developer contributions.

```text
Control-plane foundations
├── Connect an existing Git project
└── Make a developer contribution
    ├── Control Plane, Capabilities, and Domain State
    ├── Providers, Hosts/Runners, projections, docs, and fixtures
    └── Extensions and independent package lifecycle
```

The foundations cover:

1. [From one session to long-running work](01-from-session-to-loop.md): why control information must outlive a session.
2. [Sessions, Host Goals, and LoopX](02-session-goal-loopx.md): state ownership and task qualification.
3. [Four demands of long-running work](02b-long-horizon-requirements.md): the book's question framework.
4. [Durable state and projections](state-substrate.md): sources, history, and current views.
5. [Work graphs, authority, and peers](work-graph-and-authority.md): ownership and commit boundaries.
6. [One governed turn](03-one-turn.md): execution, validation, writeback, and recoverable settlement.
7. [Recovery and boundaries](04-runtime-boundaries.md): repeated work, replanning, and stopping.
8. [Budget, admission, and observation](04b-budget-and-admission.md): when to run, wait, and observe again.

[Core state machines](core-state-machines.md) is a reference map. You can finish the Turn chapter first, then use it to reconnect mechanisms without memorizing every enum on the first pass.

## How the Dev Book and Control-Plane Course work together

This book and the repository's
[Control-Plane Developer Course](/loopx/docs/development/control-plane-course/)
serve different reading jobs:

- the **Dev Book** gives external developers a complete-enough mechanism model, then helps them onboard a
  project or deliver a public contribution;
- the **Control-Plane Course** serves developers who need to enter Kernel, CLI, state-projection, or
  scheduler implementation through Showcase derivations, decision tables, source walkthroughs,
  experiments, and review questions.

They share the official protocols and source as authority, but do not maintain two copies of the complete
course. The Dev Book explains enough mechanism to predict behavior. Follow its chapter-level pointers into
the course when you need rule precedence, bounded-context placement, or implementation detail. The deep
course is currently maintained in Chinese; the English Dev Book keeps the mechanism needed for its main
paths self-contained.
Developers ready to enter Kernel implementation can go directly to the
[independent Control-Plane Course chapter](./12-control-plane-course.md).

- **How do short sessions compose into long-running work?** Read [session-to-loop](01-from-session-to-loop.md) and [task qualification](02-session-goal-loopx.md), then descend into the
  [concept primer](/loopx/docs/development/control-plane-course/00-concept-primer/),
  [Lesson 1: Harness is the effectful program](/loopx/docs/development/control-plane-course/01-agent-loop-effectful-program/),
  and [Lesson 2](/loopx/docs/development/control-plane-course/02-goal-control-plane-architecture/), then walk
  through a real Loop in [Lesson 3](/loopx/docs/development/control-plane-course/03-first-real-loop/).
- **Who owns state, the work graph, and authority?** Read [state](state-substrate.md), [work graphs](work-graph-and-authority.md), and
  [Core state machines and transitions](./core-state-machines.md), then descend into
  [Lesson 4](/loopx/docs/development/control-plane-course/04-state-substrate/) and
  [Lesson 5](/loopx/docs/development/control-plane-course/05-work-graph-and-peers/).
- **Which rule wins when a Gate, Monitor, and Replan coexist?** Read
  [Core state machines and transitions](./core-state-machines.md) and [one governed turn](03-one-turn.md), then descend into
  [Lesson 6](/loopx/docs/development/control-plane-course/06-quota-decision-kernel/) and
  [Lesson 7](/loopx/docs/development/control-plane-course/07-host-scheduler-and-heartbeat/).
- **How does long-running work avoid drift and local loops?** Read [recovery and boundaries](04-runtime-boundaries.md), then descend into
  [long-horizon convergence](/loopx/docs/development/control-plane-course/topic-long-horizon-convergence/)
  and [Lesson 8](/loopx/docs/development/control-plane-course/08-evidence-refresh-and-self-repair/).
- **How do I change a rule and prove it is deliverable?** Read the [contribution map](source-protocol-map.md), [rule changes](source-change-control-plane-rule.md), and [validation to PR](source-validation-to-pr.md), then descend into
  [Lesson 9](/loopx/docs/development/control-plane-course/09-engineering-a-control-plane-rule/) and
  [Lesson 10](/loopx/docs/development/control-plane-course/10-autonomous-agent-quality-gates/).
- **How do Extensions, domain capabilities, and the Kernel compose?** Read [placement](08-extension-placement.md), [scaffolding](09-extension-scaffold.md), and [lifecycle](10-extension-lifecycle.md), then
  descend into [Lesson 11](/loopx/docs/development/control-plane-course/11-extension-layer/).

After those chapters:

- to learn the daily 1.0 operator surface first, start with
  [Operate the LoopX 1.0 Workspace](./workspace-v1.md);
- to manage your own repository, start with
  [Connect an existing Git project](./05-connect-existing-project.md);
- to make any public LoopX contribution, start with the
  [Developer contribution map](./source-protocol-map.md);
- once you know the contribution needs independent installation, activation, and upgrades, continue to
  [Choose the right extension point](./08-extension-placement.md).

The paths share the same foundations but do not depend on each other. Extension lifecycle is one
developer-contribution path, not the default destination for every contribution.

## The spine of this book

The book explains why LoopX is designed this way, then connects the design to use, waiting, recovery, and boundaries. Four questions join the architecture:

| Question | Architecture | Operational consequence |
| --- | --- | --- |
| How can work continue after context changes? | Durable state and projections | Identify current authority and applicable evidence |
| What happens to a partial turn? | Journals, receipts, recovery decisions | Reuse commits and resolve unknown effects |
| How do executors collaborate? | Work graphs, scopes, leases, fences | Check the writer's mode and authority |
| How does no-change work cost less? | Budget, admission, observation, backoff | Inspect wait targets, due time, and wake capability |

Each chapter begins with a concrete problem, then explains design, conditions, real costs, and the next action. Source and RFCs substantiate those explanations. Follow the contribution path and Course for implementation depth.

## How chapters are organized

Each chapter prioritizes four questions:

1. What job does the reader need to complete now?
2. What observable result proves success?
3. Which concepts are necessary to predict the behavior?
4. Where should the reader recover when the normal path fails?

Command snippets fall into three categories:

- **Runnable:** checked against the stated LoopX baseline.
- **Based on the official scaffold:** the example focuses on the domain changes, protocol, and validation
  needed for the task without a separate exercise repository.
- **Simplified for explanation:** illustrates a state relationship and must not be pasted into production
  configuration.

## How to read the evidence

| Statement type | Reading rule |
| --- | --- |
| Current implementation | Check this book's release, actual entrypoint, authority mode, and receipts; do not generalize to every Host/provider |
| RFC design target | Check milestones, ledger, and delivery boundary; Accepted does not mean every capability has shipped |
| Teaching scenario or advice | Explains a tradeoff; it is not a historical incident or machine-enforced rule |
| Tests and smokes | Establish only exercised inputs and assertions; matching headings/tables, existing paths, and successful builds do not establish semantic correctness |

During revision, prioritize operational guarantees and bilingual obligation sentences. Narrow unsupported claims and retire obsolete models from current paths. Retaining an old word count is not a reason to keep teaching retired behavior.

## Sources of authority

The English and Chinese editions share the same product facts. The Chinese root edition is the editorial
source of truth; the English edition is organized for English-speaking external developers rather than
maintained as a separate product specification. The two editions are semantic mirrors: a material
difference in version facts, status, commands, boundaries, or conclusions is a documentation defect.

| Subject | Authority |
| --- | --- |
| CLI arguments, protocols, and runtime behavior | LoopX releases, current `--help`, and the official repository |
| Learning path, scaffold guidance, explanations, and trade-off guidance | This book |
| Kernel source walkthroughs, combined cases, decision tables, and experiment routes | Control-Plane Developer Course |
| Facts about your project | Git, CI, external services, and project-owned sources |

When the book and a current release disagree, follow the release first and report the documentation drift.
Do not bypass a newer permission or lifecycle check just to make an older example pass.

## Version baseline

This book targets LoopX release `v1.2.3`. Local command examples were checked against
the public `loopx 1.2.3` CLI and protocol surface. It requires Python 3.11+ and Node.js 22.22.3+.
LoopX starts and reuses its managed, idle-exiting TypeScript Effect runtime automatically; users do not
operate that runtime as a manual daemon.

A release tag, installed CLI, and source checkout can be on different revisions, so verify these surfaces
against your actual environment:

- install and update;
- Host activation;
- the `start-goal` guided packet;
- Codex App heartbeat, visible Codex CLI Goal behavior, and other optional Hosts;
- TypeScript Effect runtime readiness;
- Extension manifest and lifecycle commands.

Before running commands from the book:

```bash
loopx --version
loopx doctor
node --version
```

If your version differs, inspect current command help and release notes before deciding whether you found
documentation drift, a release difference, or a product behavior change. This book does not guess what
different version identifiers imply.

### How to read the TypeScript migration

`v0.5.4` does not mean that all of LoopX has been rewritten in TypeScript. The current release baseline is:

- TypeScript owns the canonical semantics for migrated slices of the Effect Program, Turn and Host Todo
  settlement, Todo completion, quota delivery/spend/void/monitor-poll, the local task-lease lifecycle,
  Vision refresh, governed capability validation, and scheduler heartbeat/state;
- during the migration, the Python CLI still owns transport, legacy response projection, explicit
  external Provider calls, and some Markdown/event writeback;
- each migrated rule has one semantic owner. A Python facade adapts a TypeScript transaction; it must not
  become a second independent decision implementation;
- current `main` is in the transaction-payoff phase: later progress is measured by complete transaction
  cutovers and deleted legacy semantics, not by accumulating leaf helpers and bridge calls.

Treat the `v0.5.4` tag and release notes as the shipped baseline. Use the current status of the
[TypeScript Control-Plane Migration RFC](/loopx/docs/architecture/rfcs/typescript-control-plane-migration-v0/)
for later cutovers and final CLI/App convergence. `v0.5.4` ships only the first receipt-bound scheduler
follow-up slice of Stage 3; broader CLI/App convergence and Stage 4 distribution cleanup remain future
work.

### Updating your mental model from `v0.4.4` to `v0.5.4`

If you read an earlier edition of the Dev Book, recalibrate these four areas first:

| Area | Shipped in `v0.5.4` | Continue with |
| --- | --- | --- |
| Control Plane | Complete Turn/Host Todo settlement, quota commit, task-lease lifecycle, Vision refresh, and scheduler-heartbeat transactions have typed TypeScript owners; Python facades still carry migration-time boundaries | [Migration RFC](/loopx/docs/architecture/rfcs/typescript-control-plane-migration-v0/) |
| Operator surface | Personal Workspace exposes Goal, Task, Chat, and read-only status-source entrypoints; the UI is not a new source of truth | [Dashboard README](https://github.com/huangruiteng/loopx/blob/v0.5.4/apps/presentation/dashboard/README.md) |
| Host runtime | Codex, Claude Code, OpenCode, Pi, KunlunCode, DeepSeek Harness, and custom runners have distinct activation and stop contracts | [Runtime Connector Catalog](/loopx/docs/integrations/runtime-connector-catalog/) |
| Capability and Provider | A Capability is defined by a package-owned catalog entry, a real command, and durable validation; a Provider or Extension does not inherit Kernel authority | [Capability Catalog](/loopx/docs/capabilities/) |
| Shared authority | File, NoKV, and PostgreSQL providers remain staged candidates; installing a Provider does not change the default local authority | [Shared Authority RFC](/loopx/docs/architecture/rfcs/shared-goal-authority-state-provider-v0/) |

This table is a reading map, not a copy of the release notes. Confirm whether a surface is usable through
the installed release's `doctor`, `capability show`, Host readback, and versioned documentation.

### From `v0.5.4` into the `v1.0.0` Workspace

The `v1.0.0` product milestone is the Personal Workspace, not blanket promotion of every staged
authority path or optional Provider. It brings cross-Goal overview, Agent lanes, completed work,
Capability settings, verified reports, Goal Channels, and desktop recovery into one operator surface
while preserving the authority of the CLI, typed Kernel, and project state. Follow the
[1.0 Workspace operations chapter](./workspace-v1.md) through startup, readback,
preview/apply/receipt, configuration, and disable checks before entering the project-onboarding or
developer-contribution path.

## Deliberate scope

The developer-contribution path covers placement, protocol maps, rule changes, Capabilities and Providers,
Hosts and Runners, projections, documentation and fixtures, Extension lifecycle, validation, and PR
delivery. It does not duplicate the complete maintainer course or a full CLI reference.
Production effectful Providers, private organizational cases, and live benchmark operation remain outside
the main path. Use official source, protocol documentation, and the target project's own facts for those
workflows.
