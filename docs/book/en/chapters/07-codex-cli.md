# Start from the visible Codex CLI TUI

Thursday morning you connect the project inside Codex CLI, set the current task to a visible `/goal`, and
close the terminal for lunch. When you come back in the afternoon, that Goal is still sitting on step one.

Nothing errored. No failure is recorded. Nothing looks broken. Codex CLI does not wake on its own: it has no
heartbeat, no timer, and no mechanism that keeps asking "what should happen now" after you walk away. Send no
message and there is no next turn. The Goal waits there patiently, and if you assume it is running, that
misunderstanding can survive a whole day.

## Why "just add a timer" does not hold

The reflex is to give the CLI a heartbeat too and let it wake itself on a schedule. That tears out the reason
this path exists.

The defining constraint of the CLI path is **visible and interruptible**: work happens in the TUI in front of
you, and silently switching to a hidden headless worker for the sake of automation is exactly what it
refuses. That constraint has a real price. The previous chapter established that a wake must be able to prove
it did not waste itself; in the CLI, you personally supply that proof, so it only holds while you are
present.

The second instinct is to let the Goal body loop on its own by pushing the whole decision into the prompt.
That fails elsewhere: the `/goal` body is **stable protocol**, and it does not know which Todos exist, which
Gate is blocking, or when a monitor comes due. Writing those judgments into the body maintains a second copy
of state inside the TUI, and that copy starts expiring the moment it is written.

Neither route works, because the CLI's answer is genuinely different: it does not pretend to self-drive.
It hands "when should this move" entirely back to the LoopX decision, triggered by you while you are there.

## The boundary: the CLI owns visible interaction, the LoopX decision owns the next step

The split looks like this:

```text
Codex CLI  -- provides the visible TUI, carries /goal continuation, is triggered by the user or a visible loop
LoopX      -- decides whether this invocation should work, which Todo, when to wait or block
```

The CLI is an **on-demand** Host. It supplies visibility, not persistence. What this path buys is that every
step is in front of you, interruptible at any moment, with a readable state at any point. What it gives up is
advancement while nobody is watching.

That is a deliberate choice, not a capability gap. Some task shapes specifically need visibility: you are
debugging behavior you do not yet understand, you are waiting on your own judgment, or you need to change
direction midway. In those cases a quietly spinning timer is the more dangerous option.

## Start the visible TUI

```bash
cd /path/to/your-project
codex
```

Send this setup request:

```text
Connect the current project to LoopX. Run loopx doctor first, reuse existing
active state, and confirm that .loopx/, .codex/goals/, and .local/ are ignored.
Do not use hidden headless execution. After connection, generate a thin heartbeat
task body and set the current Codex CLI task to a visible /goal <task_body>.
Report the active state id, current user gate, top agent todo, and next safe action.
```

The setup turn establishes connection and visible continuation. It should not start a large unplanned
delivery slice. If your very first turn produces a large diff, setup and delivery have been merged, and every
later step now stands on a plan nobody reviewed.

## Start a concrete objective with `$loopx`

With the command facade installed:

```text
$loopx Add compatible JSON output to this CLI, add tests, and wait for the
maintainer to approve the schema.
```

The Host should preserve the task text, plan Todos, and produce a Goal body suitable for the visible TUI.
The CLI fallback is:

```bash
loopx start-goal --guided --project . \
  --goal-text "Add compatible JSON output to this CLI, add tests, and wait for the maintainer to approve the schema" \
  --host-surface codex-cli-tui
```

The guided packet should contain or point to a copyable `/goal <task_body>`. It must not start a hidden agent
in another terminal. That one is worth confirming separately: if the guided start launched an agent in the
background, you have lost this path's only advantage, and it is hard to notice because everything on the
surface still looks correct.

## Compose native Goal and LoopX

The native Codex CLI Goal owns continuation inside the TUI. LoopX owns the project frontier:

```text
Visible Codex /goal
  -> run LoopX quota decision
  -> execute selected bounded Todo
  -> validate
  -> write LoopX state
  -> continue, wait, block, or complete
```

When LoopX returns a Gate, the Goal can become blocked. After the user satisfies the Gate, resume through
the Host's Goal surface. Do not create a second Goal to bypass the first Gate: the second Goal receives the
same frontier, and the two Goals then compete for the same Todos.

## Every turn still passes the quota Gate

Reading state from another shell does not mutate the TUI:

```bash
loopx status --goal-id <goal-id>
loopx history --goal-id <goal-id> --limit 10
loopx quota should-run \
  --goal-id <goal-id> \
  --agent-id <agent-id> \
  --runtime-profile codex_cli
```

The Host runtime should identify `codex_cli`, with scheduling owned by the Goal or agent loop rather than a
Codex App heartbeat. That distinction decides who is responsible for waking the work. If the packet reports
missing scheduler context, fix the runtime profile instead of ignoring the warning: without scheduler
context the system neither wakes itself nor tells you that it will not.

## Preserve identity and Todo ownership

An argument-bearing guided start does not default to a fresh Agent identity when the Goal has registered
Agents (even a single one); it returns an identity gate that requires selecting one lane. Fresh registration
is the default only for a Goal with no registered lanes or an explicit `--new-peer`. Reuse an existing id
only when the user explicitly requests takeover of that peer. After selection, the visible Goal, quota,
refresh, and writeback paths should preserve the same explicit `--agent-id`. A missing or mismatched identity
must fail closed rather than fall back to "the only Agent."

That fail-closed rule guards one specific mistake: when a Goal holds only one identity, "just use it" looks
harmless, but if that identity belongs to another Host or another lane, the work's ownership was silently
rewritten.

Agent identity labels the LoopX lane. It does not prove that the work runs in Codex CLI. Use
`host_surface`, runtime profile, or run metadata to identify the Host.

A proper handoff is:

1. the current agent writes back validated work;
2. it updates or completes the Todo;
3. the new agent previews and atomically registers a fresh identity;
4. the new agent claims the unfinished Todo;
5. the new Host reads the same registry and Goal;
6. the visible Goal resumes.

## Cost and boundary

**Cost one: no external trigger means no progress.** If you do not invoke it, it does not move. That is the
definition of this path, not a configuration problem. Expecting it to advance overnight projects a
capability from the App onto a surface that explicitly does not have it.

**Cost two: visibility depends on you being present.** The visible TUI pays off while you are watching it.
The longer you are away, the longer that stretch of no advancement runs, and it leaves no anomaly in the log.

**Cost three: stability rests on process, not on mechanism.** The `/goal` body must stay stable, setup and
delivery must stay separate, and handoff must run in order. All of that depends on operating correctly; the
CLI will not enforce it for you. The App side at least has the physical fact of an automation to read back,
whereas here you check the registry, identity, and history.

**Boundary one: native Goal continuation is not the LoopX frontier.** The Goal guarantees you can keep going
inside the same TUI; it does not guarantee that this Todo is the one to do. Advance when the two agree.

**Boundary two: a visible Goal is not automation.** Setting `/goal` makes the work visible and resumable. It
creates no timed wake and cannot replace the decision.

**Boundary three: the two Hosts may read the same Goal but share no execution right.** With App and CLI both
active, inspect claim, lease, and scheduler ownership. An effectful Todo can have only one legal executor.

## When to choose CLI, and when to choose App

Both face the same frontier; they differ in how they wake:

| Task shape | Better fit | Why |
|---|---|---|
| You need to watch intermediate results and step in | CLI visible TUI | Every step is in front of you, interruptible at any time |
| A short focused session with the user present | CLI visible TUI | No need to keep waking after the session ends |
| External state is changing and you must wait for it | App heartbeat | Still woken while you are away |
| A steady pace of advancement is available | App heartbeat | A timer matches step-by-step progress |

Two rules of thumb:

- **Choose CLI when you need to watch the process**, and App when you need attempts to continue while you
  are away. The first buys visibility at the cost of self-driving; the second buys persistence at the cost of
  timer overhead and the ACK convergence chain.
- **Either way, the LoopX decision owns whether the next step is legal.** The CLI does not produce that
  judgment; it hands the question to LoopX when you invoke it.

## Recovery paths

### The TUI closes

Start `codex` again from the same project root, inspect `loopx status`, and resume the existing Goal. Do not
bootstrap a duplicate objective, which leaves you with two Goals pointing at one target.

### The `/goal` body is stale

A stable body avoids copying dynamic Todos, but protocol or CLI versions can still change. Generate a new
thin body and replace the visible Goal through the Host surface. Do not hand-edit internal fields.

### Work moved to a hidden worker

Stop the worker and inspect whether it wrote evidence or acquired a lease. Restore Todo ownership before
returning to the visible TUI, and do not let two executors modify the same worktree. Check this against the
actual claim and lease ownership rather than your memory of who was running.

### The Goal polls without change

After the unchanged limit, block or wait quietly. External observation belongs in a monitor Todo. Resume
through the Host Goal surface instead of repeatedly resending the full objective; resending the same round
makes one round of work look like several of progress.

### App and CLI are both active

Inspect claim, lease, and scheduler ownership. Both Hosts may read the same Goal, but an effectful Todo can
have only one legal executor.

## Invariants

1. **No invocation, no turn.** The CLI does not self-drive; any assumption that it is running in the
   background needs separate evidence.
2. **The setup turn only establishes connection.** Merging connection with delivery puts every later step on
   an unreviewed plan.
3. **The `/goal` body stays stable.** Dynamic Todos, Gates, and capabilities come from the current decision
   packet, not from the prompt.
4. **The visible Goal and the selected Todo are separate things.** The Goal can continue; that does not make
   this Todo the right one.
5. **Identity is always explicit.** A missing or mismatched identity fails closed rather than falling back to
   "the only Agent."
6. **One effectful Todo has one legal executor.** Two Hosts may coexist; execution right may not.

## After project onboarding

At this point you can, without modifying LoopX core:

- give an existing Git project a recoverable Goal, Todo, Gate, and evidence lifecycle;
- start the same project state from Codex App or the visible Codex CLI TUI;
- preserve authority, identity, and workspace boundaries while changing Hosts;
- verify continuation through status, history, and quota.

Choose the next path by your job:

- to contribute a protocol-level change to LoopX core, continue with the
  [Developer contribution map](./source-protocol-map.md);
- to deliver an independently installed Provider, continue with
  [Choose the right extension point](./08-extension-placement.md);
- to use LoopX only as a project control plane, apply this onboarding pattern to your repository.
