# Connect an existing Git project

This chapter answers one concrete question: when you connect a project that already exists, what exactly are you handing over — and why "run the command once" does not add up to an auditable onboarding.

It hangs on requirement one from earlier: **state must be able to live outside the context.** In a session, project state lives in the model's context. Long-running work requires it to live in the repository, where the next reader can pick it up. Onboarding is the act of handing your project's state to an external control plane.

!!! tip "Fast reading path"
    For basic onboarding, follow the steps under "The design" and stop after Git-isolation
    verification. Continue into the configuration sections only when the project actually needs an
    optional Capability or Extension.

## Start from a bad ending

Consider a scenario where every step looks reasonable:

```text
Mon 10:00  You start an Agent at the root of your service repository and ask it
           to "connect the project to LoopX."
Mon 10:02  The Agent runs loopx connect. It succeeds. .loopx/registry.json appears.
Mon 10:03  The Agent runs start-goal, writing active state and a host activation
           hint.
Mon 10:06  The task is done, so it runs git add -A and commits.
Mon 10:07  git push. The repository is public.
Mon 10:09  CI scans the commit: a raw run log, a local credentials file, and a
           path pointing at your internal host.
Fri 16:00  Security classifies it as a private-information exposure incident.
```

Nothing in that sequence is a lie. `connect` really did succeed, `doctor` really did report a usable installation, and the state files really do contain what the control plane meant to write.

The problem is that **onboarding puts two kinds of thing into one directory tree**: project source, which belongs in commits, and runtime state, which does not. The Agent saw "I finished a task and the working tree has changes," so it committed.

That is what separates onboarding from writing code. When you write code, new files in `git status` are almost always your product. After onboarding, new files in `git status` are control-plane private state by default. **The same command means opposite things in the two contexts.**

The second failure is quieter, because it raises no error at all: once onboarding finishes, the control plane starts treating "this Goal can write in this worktree" as settled. If the delivery workspace recorded in `registry` does not match the directory where files are actually changing, the Agent edits in one clean tree while you review another. The next `git status` shows no changes, yet the work counts as delivered.

## Why "run the documented commands" reads back no truth

The obvious reaction is to run the commands from the documentation and treat a success message as a finished onboarding.

The trouble is that onboarding success depends on **four facts holding at once**, and each one belongs to a different owner:

| Fact | Owned by | Can one command prove it |
|---|---|---|
| Install usable, import correct, runtime ready | The LoopX release | No; `which loopx` only proves an executable is on PATH |
| Where control-plane state landed, and which Goal it belongs to | Your repository | No; a successful write does not mean it wrote the right Goal |
| Private state did not enter a public commit | The Git index and the remote | No; `connect` does not look at Git at all |
| Who acts next, under which constraints | The quota / status projection | No; `should_run: true` does not equal permission for any arbitrary action |

One command covers one cell. Collapsing four cells into "the command returned 0" mistakes a local signal for global authority.

The second instinct is "then let the Agent do the whole thing automatically." That fails too, because five decisions in onboarding **should be yours alone**: which Goal to pick when several exist, whether to take over an existing Agent identity, which Host surface owns activation, whether external writes and credentials are allowed, and whether anything is committed or pushed. The Agent can execute; it cannot decide these for you. The workable shape is an Agent that performs the executable part and stops at those points to hand the decision back.

So the design goal is to make **onboarding something that can be read to the end, reviewed, and rolled back**, instead of one unobservable automation.

## Design one: establish the Git boundary before connecting

The order is itself the safety contract. Connect first and patch `.gitignore` later, and you are back at 10:07 in the opening timeline.

The first step is neither installation nor `connect`; it is an ignore rule for local control state:

```text
.loopx/
.codex/goals/
.local/
```

Those three lines cover three different things: `.loopx/` holds the registry and local projection, `.codex/goals/` holds active state, leases, and evidence pointers, and `.local/` holds other private working material. They coexist, and dropping any one line leaves a gap.

If the project already uses any of those names, read the existing contents before changing the rule. A LoopX state directory may already hold active state, a registry, leases, and local evidence pointers, and overwriting it destroys state that is in use.

Have Git itself confirm the rule took effect, rather than trusting the rule file:

```bash
git check-ignore -v .loopx/registry.json
git check-ignore -v .codex/goals/example/ACTIVE_GOAL_STATE.md
```

Both commands should print the matching rule and its source line. Git skips the check for paths that do not exist yet, so force a verdict with `--no-index`:

```bash
git check-ignore -v --no-index .loopx/registry.json
```

**That is the actual mechanism in this section**: the correctness of the ignore rule is decided by Git, not by your reading or the Agent's. The rule holds when `check-ignore` prints a match.

## Design two: Delegate onboarding to an Agent, but only the execution

The recommended path hands onboarding to the Agent already working in the repository. You supply the goal, the Host, and the authority boundary. The Agent inspects the repository, reads the current command surface, executes the safe steps, and returns a report you can review.

The prompt below is an execution contract. Adapt the goal and the Host, then send it:

```text
Safely connect the current Git project to LoopX.

Goal:
- Establish a recoverable, verifiable release workflow for this project.
- The current Host is Codex App. If the environment is not that Host, tell me first; do not guess.

Execution contract:
1. Begin with a read-only inspection of the project root, current branch, git status, .gitignore, and any
   existing .loopx/registry.json, .codex/goals/, or other LoopX state. Do not overwrite, reset, or clean
   existing material.
2. Run loopx --version and loopx doctor, then read the current --help for every command you need. Do not
   rely on remembered arguments from an older version. If LoopX is not installed, report what is missing
   and where the official installer writes before asking for installation authority. Do not describe a
   discovered install command as a completed installation.
3. If LoopX state exists, read loopx registry, loopx status, and relevant history first. Prefer the exact
   existing goal_id. Do not force a reconnect or select a Goal from objective similarity.
4. Ensure .loopx/, .codex/goals/, and .local/ are ignored by Git. If those paths already serve another
   project purpose or are tracked, stop and report the conflict. Do not delete or untrack them yourself.
5. For a project that is not connected, run loopx connect --dry-run first and show the state it would
   create or change. Run loopx connect only after confirming there is no conflict. Do not bootstrap again
   merely to “start over” when a registry already exists.
6. If several Goals are possible, stop at the read-only goal_selection_gate and show me the choices and
   your recommendation. Before I choose, do not write Todos, register an Agent, or activate a Host loop.
7. For a new executor, choose a fresh public-safe agent_id. Preview registration, then use the command
   supported by the current CLI and read it back. Reuse an existing agent_id only when I explicitly
   authorize takeover.
8. Generate the transaction packet with loopx start-goal --guided --project . and the exact goal text.
   Pass the correct --host-surface when the Host is known. Execute only packet steps allowed by the
   current authority.
9. Stop at a Gate for user approval, external writes, credentials, wider permissions, Host selection, or
   destructive Git operations. Do not decide those for me.
10. Verify loopx status, todo list, history, quota should-run, git status, and
   git ls-files .loopx .codex/goals .local.
11. Do not commit or push. Finish with an "onboarding report" that names goal_id, agent_id, Host, changed
    files, current Todos and Gates, executed mutations, verification, unresolved issues, and the next
    action. If you completed only a preview, explicitly say that onboarding is not complete.
```

Note step 11: it rules out "the command succeeded" as a conclusion and demands a structured report instead. That is the auditable shape.

### The onboarding report

An auditable onboarding report includes:

```yaml
onboarding:
  status: complete | blocked | preview_only
  project_root: <repository root>
  goal_id: <exact goal id>
  agent_id: <fresh id or explicitly approved takeover id>
  host_surface: <exact host or unresolved>
changes:
  - <changed path and why>
gates:
  - <decision still owned by the user>
verification:
  doctor: pass | fail
  status_readback: pass | fail
  local_state_ignored: pass | fail
  tracked_private_state: []
next_action: <one concrete next step>
```

`gates` and `tracked_private_state` are the two fields most likely to be dropped, and the two where things most often go wrong. The first records the decisions still in your hands; the second records private state that has already reached Git. `tracked_private_state` should be an empty list. Once it is not, onboarding itself has manufactured a problem that needs repair.

### Example: first onboarding

```text
Use the Agent onboarding contract in this chapter to connect the current project to LoopX.
The goal is "Create a recoverable build, approval, and Pages deployment flow for every release candidate."
The current Host is the visible Codex CLI TUI. Use a fresh public-safe agent_id.
Do not commit, push, or trigger a deployment. Stop for my decision on Goal selection, authority, or any
external write.
```

### Example: continue existing state safely

```text
First inspect the current LoopX registry, Goals, Todos, Gates, and history read-only, then help me continue
the project. Prefer an exact existing goal_id, but do not automatically take over an existing agent_id.
If you find multiple Goals, an active lease, an unfinished mutation, or a workspace-route mismatch, return
diagnosis and choices only. Do not write state, commit, or push.
```

## Design three: what onboarding actually writes

Only now do the mechanism names arrive. Onboarding writes two pieces of state:

```text
your-project/
  .loopx/registry.json                          # which active states this project connects to
  .codex/goals/<goal-id>/ACTIVE_GOAL_STATE.md   # the durable state of this Goal
```

Those two local files are control-plane state rather than project source. That they can be read back on the next run is requirement one landing in practice.

### Why install the release instead of cloning LoopX first

Prerequisites:

- Python 3.11 or later;
- Node.js 22.22.3 or later for the LoopX-managed TypeScript Effect runtime;
- a macOS or Linux shell, or Windows PowerShell 7;
- an existing Git project.

```bash
python3 -m pip install --upgrade loopx
loopx workflow-skills --install
loopx doctor
```

!!! tip "Why not clone LoopX first?"
    Most users need a published CLI and workflow skills, not a Kernel source checkout. Clone-based installation is for
    developers who need live canaries or intend to contribute to LoopX.

Treat `loopx doctor` as the installation fact. A successful `which loopx` only proves that one executable
is on `PATH`; doctor also checks the release snapshot, Python import, installed skills, and Host
integration, and the TypeScript Effect runtime. LoopX starts that runtime automatically and lets it exit
when idle; users do not supervise a daemon manually. `stopped` is a healthy on-demand state, while
`missing`, `unsupported`, or `probe_failed` must be repaired first.

Use the deep check when you need to verify the real runtime and journal checkpoint path:

```bash
node --version
loopx doctor --deep
```

See [Installing LoopX](/loopx/docs/guides/installing-loopx/) for the complete native Windows installation,
upgrade, and rollback path. Do not require WSL merely to reproduce the POSIX examples.

### The three-step shape of a connection

From the project root:

```bash
loopx connect --dry-run
loopx connect
loopx status
```

Inspect the project root, `goal_id`, state file, and Git boundary in the dry-run before performing the real
connection. `connect` should reuse an existing registry and active state. If the project has too little
state to continue, start with an explicit task:

```bash
loopx start-goal \
  --guided \
  --project . \
  --goal-text "Establish a verifiable release workflow for this project"
```

This produces a guided transaction packet. It is a preview, not proof that Todo writeback, Host activation,
or an Agent turn has already happened. The Host integration must execute the planning, state writeback, and
activation described by the packet.

`connect` / `bootstrap` register the Goal and write the active state only: they create no first-connect
onboarding Todo, owner-decision gate, or host-loop opt-in gate. A freshly connected goal therefore has no
executable Agent Todo; the Agent writes the first delivery Todo after you confirm it, or the
connected domain adapter writes it, so automation starts from the caller's own work queue instead of a generated onboarding queue.

### Choose the Goal before choosing the Agent

Guided start keeps two decisions separate:

1. **Goal selection:** when the project has one registered Goal, reuse that exact `goal_id`; when it has
   several, return a read-only `goal_selection_gate`. Select one exact rerun command from `choices`. Before
   that selection, do not write Todos, register an Agent, or activate a Host loop.
2. **Agent identity:** for new onboarding with task text, omitting `--agent-id` defaults to fresh identity
   registration only when the Goal has no registered lanes (or `--new-peer` is explicit). When registered
   lanes exist, `start-goal` returns an identity gate that requires selecting one existing lane. Existing
   Agents are explicit takeover choices, not automatic defaults.

Do not select a Goal from objective similarity, and do not take over an Agent merely because it is the only
registered identity. Preview and then atomically register a new public-safe id:

```bash
loopx register-agent \
  --goal-id <selected-goal-id> \
  --agent-id <new-public-safe-agent-id>

loopx register-agent \
  --goal-id <selected-goal-id> \
  --agent-id <new-public-safe-agent-id> \
  --execute
```

The preview lets you inspect the plan. Before Todo writeback, confirm that the execute result reports
`ok`, `changed`, and `written` as true, global sync succeeded, and source/global registration readback was
verified. If the user explicitly requests an old lane, use the packet command bound to that exact
`agent_id` instead of pretending to create a fresh registration.

If you know the active Host, state it explicitly:

```bash
# Codex App
loopx start-goal --guided --project . \
  --goal-text "Establish a verifiable release workflow for this project" \
  --host-surface codex-app

# Visible Codex CLI TUI
loopx start-goal --guided --project . \
  --goal-text "Establish a verifiable release workflow for this project" \
  --host-surface codex-cli-tui
```

When the Host is unknown, omit `--host-surface`. LoopX should return a read-only selection Gate instead of
guessing.

## Design four: what you read back afterwards

Whether onboarding worked is not decided by `connect`; it is decided by the readback. Use the shortest read paths first:

```bash
loopx registry
loopx status
loopx todo list --goal-id <goal-id>
loopx history --goal-id <goal-id>
loopx quota should-run --goal-id <goal-id> --agent-id <agent-id>
```

These commands answer different questions, and dropping one leaves the conclusion incomplete:

| Command | Primary question |
| --- | --- |
| `registry` | Which active states are connected to this project? |
| `status` | Who should act, and which Gates or risks are current? |
| `todo list` | What work units, owners, and lifecycle states exist? |
| `history` | Which bounded events were written back? |
| `quota should-run` | Is another delivery turn allowed now? |

Do not reduce `should_run: true` to permission for any arbitrary action. Also inspect the
`interaction_contract`, selected Todo, capability Gate, write scope, and scheduler hint.

### Verify isolation with Git

The other half of the readback lives on the Git side:

```bash
git status --short
git ls-files .loopx .codex/goals .local
```

The second command should print nothing. If it lists a path, Git is already tracking local control state;
**adding `.gitignore` does not untrack it.** Inspect the history before removing anything from the index so you
do not delete valuable local state.

Only at this point does each of the four facts have its own evidence: doctor reports the installation,
registry and status report the state, `git ls-files` reports the boundary, and `quota should-run` reports
admission for the next turn.

## Cost and boundary: what onboarding gives up

**Cost one: the project maintains an extra state directory.** `.loopx/` and `.codex/goals/` live in your working tree for the long haul, and they belong in `.gitignore`, in your backup policy, and in the notes you hand a new contributor. They are not source, and they are not a dispensable cache either.

**Cost two: onboarding does not stay done.** Changing Host, executor, worktree path, or release can invalidate the route. Each time you read back again, rather than assuming last time's conclusion still holds.

**Cost three: Agent authority has to be split by hand.** Some onboarding decisions are only yours, and what you delegate to the Agent is the execution. That is slower than letting the Agent run to completion on its own.

**Cost four: read-only and writable are two different connections.** A read-only check (registry, status, history, `git status`) changes no state and can be run at any time. `connect`, `register-agent --execute`, `configure-goal --execute`, and `extension enable --execute` all write state. Mixing the two into a single operation costs you the "look before changing" step.

**Boundary one: a project with strong regulatory constraints, an offline-only requirement, or a ban on external state directories is a poor fit.** If compliance forbids control-plane state outside the working tree, or forbids a third-party runtime process, the cost of onboarding cannot be paid. Stay at read-only use instead of connecting and sorting it out later.

**Boundary two: no Git repository means no onboarding.** This chapter assumes a Git project. Onboarding leans on branches, worktrees, and commit boundaries to express delivery; without version control the control plane cannot answer "which revision changed."

**Boundary three: onboarding does not change your product's permission model.** `connect` registers the Goal and writes active state. It grants no new external write permission, installs no Provider, and widens no write scope. Optional capabilities must be configured explicitly.

**Boundary four: onboarding is not the same as having a plan.** A first connection creates no onboarding Todo. The absence of executable work in the state is the control plane declining to invent a work queue for you.

## Named failures and recovery paths

Talking abstractly about "safe onboarding" convinces nobody. The four scenarios below each leave an observable trace, and each has a recovery path.

### `loopx doctor` fails

Read the command path, release snapshot, and skill status in the report. If a command skill is missing
after an upgrade:

```bash
loopx slash-commands
loopx slash-commands --install
```

Do not copy `.loopx/` from another checkout without understanding the failure; that treats unidentified state as the fix.

### The project already has LoopX state

Reuse it by default. Run `loopx registry`, `loopx status`, and `loopx history` before deciding whether a
migration is necessary. Continue one exact `goal_id`; when several Goals exist, resolve the selection Gate
first. Then register a fresh `agent_id` for the new executor or take over a named identity only when the
user requests it. Do not force a reconnect over a Goal that still carries useful state, and do not confuse
an old Agent identity with the Goal itself.

### A linked worktree points at the wrong directory

This is the formal version of the second opening failure. The delivery workspace must match the worktree where files are actually changing. Inspect the registry and
repair the route with the supported `refresh-state --delivery-workspace-path` flow. Do not copy active state
to manufacture a second source of truth.

### The global registry is not writable

Project-local state and global visibility are separate layers. `loopx sync-global` merges the project `.loopx/registry.json` into the global registry, and by default it only affects the global projection rather than rewriting project-source state. If that step fails after connecting, `loopx status` may not see the Goal you just onboarded.

Use the registry permission report from `loopx doctor`, repair ownership or permissions, and run `loopx sync-global` again. Never commit the global registry to the project.

## Optional: enable Providers and Goal features

Basic onboarding is complete at this point. Continue only when this project needs an optional capability. If you only wanted the basic path, you can stop here.

Start with discovery and Goal configuration. Continue to the Extension example only when you have a
separately distributed Provider to activate.

### Discover Capabilities and optional features

The Capability catalog, Goal feature configuration, and Extension activation are three different
surfaces:

Use `loopx capability list` for discovery and
`loopx --format json configure-goal --goal-id <goal-id>` for the current Goal's optional features.

```bash
loopx capability list --format json
loopx capability show <capability-id> --format json
loopx --format json configure-goal --goal-id <goal-id>
loopx extension list --format json
```

`capability list/show` is a read-only catalog. It reports the caller outcome, entry command, protocol,
smoke, and boundary. It does not modify the Goal or install a Provider. Passing
`--extension-manifest` only declares a Provider for that catalog read; `declared=true` does not mean
installed, enabled, or ready.

`configure-goal` without a setting flag is also read-only and returns the current on-demand feature
catalog. There is no generic “enable any capability id” command. Every default-off feature has explicit
configuration fields and boundaries. For example:

```bash
loopx configure-goal --goal-id <goal-id> --change-quality-enabled
loopx configure-goal --goal-id <goal-id> --change-quality-enabled --execute
```

For `multi_subagent`, Explore Graph, Explore Harness, Reward Memory, Lark inbox, and other optional
features, read the current `configure-goal --help` and the catalog's exact delta instead of guessing flags
from feature names. Always follow "read catalog -> preview -> inspect delta -> execute -> readback".

Also keep the two Todo capability fields separate:

- `required_capabilities`: Host or runtime abilities that must already exist for this execution; a missing
  requirement Gates that candidate;
- `target_capabilities`: an ability this Todo is building, repairing, or validating; a missing target may
  enter repair mode and must not make the repair Todo impossible to run.

Configuration entry points may use the global registry, but the Goal's configuration authority
remains the project registry identified by `source_registry`. CLI and frontend reads, previews,
revision checks and writes resolve that source before synchronizing the global projection.
`--runtime-root` selects the projection target, not a different authority. An unreadable source
fails explicitly instead of falling back to a mirror write, so later project synchronization
cannot undo a successfully saved setting.

“Visible in catalog,” “enabled for this Goal,” “Provider doctor-ready,” and “available in this turn” are
four different facts.

### Enable an existing Extension during onboarding

Project onboarding may also activate an optional Provider locally, but `connect` must not do that
implicitly. The current `loopx-finance-value-discovery` package is a separately distributed,
zero-permission Extension. An Agent can install it only when you already have a LoopX source checkout, or
an equivalent provider source package, containing
[`packages/loopx-finance-value-discovery`](https://github.com/huangruiteng/loopx/tree/main/packages/loopx-finance-value-discovery).

Append this contract to the onboarding prompt:

```text
After project connection is complete, inspect whether loopx-finance-value-discovery is installed and
enabled in the current environment.

- Run loopx extension list --format json first. Do not infer activation from a directory.
- If the Extension is installed and enabled, execute a read-only doctor probe; do not install it again.
- If it is installed but disabled, explain that enable reruns doctor, then preview and execute enable.
- If it is absent, first confirm that the provider source package and
  packages/loopx-finance-value-discovery/extension.toml exist.
- Changing the Python environment is a local environment write. Show the pip install, extension install,
  and doctor commands and wait for my authority before execution.
- Install the package into the same Python environment that runs `loopx`, and make the Provider entrypoint
  visible on the current shell's `PATH`. Otherwise doctor should report `entrypoint_missing`; do not
  bypass it.
- If the provider source package is unavailable, stop and report that a release-only environment cannot
  download or enable this Extension implicitly.
- Do not describe it as a market-data collector or investment-advice capability. It only reduces frozen
  public-safe evidence supplied by the caller into a bounded research packet. It performs no network,
  account, trading, or continuous-monitoring action.
- Report package installation, Extension enablement, doctor readiness, and one example run separately.
```

The equivalent manual flow is:

```bash
# 1. Observe activation state
loopx extension list --format json

# 2. Only when the provider source package exists and Python-environment writes are authorized
python3 -m pip install ./packages/loopx-finance-value-discovery

# When using a venv, activate it and confirm both commands resolve from that environment
command -v loopx
command -v loopx-finance-value-discovery

# 3. Preview, then register and activate the installed Provider
loopx extension install \
  --manifest packages/loopx-finance-value-discovery/extension.toml \
  --format json

loopx extension install \
  --manifest packages/loopx-finance-value-discovery/extension.toml \
  --execute \
  --format json

# 4. Execute the read-only readiness probe
loopx extension doctor \
  loopx-finance-value-discovery \
  --execute \
  --format json
```

If `extension list` reports the Extension as installed with `enabled=false`, preview `extension enable` and then add `--execute` instead of installing it again. Invocation also needs a `finance_value_discovery_input_v0` file. The onboarding report may say “Extension available” only after `extension list`, an executed doctor, and an example `extension run --execute` all succeed.

## Invariants

Six claims you can check yourself.

1. **Git decides the ignore rule; reading does not.** The rule holds when `git check-ignore -v` prints a match.
2. **`git ls-files .loopx .codex/goals .local` is empty.** Output means private state already reached version history, and adding `.gitignore` does not repair that.
3. **A connection reuses an exact `goal_id`.** A second bootstrap, a force reconnect, or a Goal picked from objective similarity is a defect.
4. **Identity is confirmed in two steps.** A new executor gets a fresh public-safe `agent_id`; takeover is an explicit choice, not a default.
5. **The readback covers four facts.** Installation, state, the Git boundary, and next-turn admission each have their own evidence, and none substitutes for another.
6. **Writes stop at a Gate.** Credentials, external writes, wider permissions, Host selection, destructive Git, and commit or push are yours to decide.

These six answer one question: **when you hand an existing project to an external control plane, what tells you what you handed over, where it landed, and that it stayed inside the boundary?** This chapter gave requirement one's answer at the onboarding scale. The next two chapters activate that same state from two entry points, Codex App and the Codex CLI: where the state lives is now settled, and what remains is who reads it.
