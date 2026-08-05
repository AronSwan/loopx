# LoopX KunlunCode adapter

The KunlunCode adapter is a first-class LoopX host surface. It uses its own
project binding and registered agent identity; it does not read
`.claude/loop.md` or execute as Claude Code's `cc` lane.

## Install and connect

Run the command from one uv-managed environment containing LoopX and
`mcp==1.27.2`:

```bash
uv venv .venv
uv pip install --python .venv/bin/python -e . 'mcp==1.27.2'
.venv/bin/loopx-kunluncode connect \
  --project . \
  --goal-id my-goal \
  --agent-id kunlun \
  --python .venv/bin/python
```

KunlunCode currently stores MCP registrations in its user configuration even
when project or overlay settings contain `mcp_servers`. The installer therefore
creates one explicitly named global entry, `loopx-kunluncode`; project and
identity selection still come from the current working directory and the
ignored `.loopx/kunluncode.json` binding.

Read the connection back:

```bash
kunluncode --cwd "$PWD" mcp test loopx-kunluncode
.venv/bin/loopx-kunluncode status --project .
```

## Run

Add one bounded task and run one worker segment:

```bash
.venv/bin/loopx-kunluncode add --project . "Run the focused check and record the result"
.venv/bin/loopx-kunluncode run --project . --permission-mode auto
```

Each invocation runs at most one lifecycle segment:
`should_run -> claim_task -> work and verify -> complete_task -> should_run`.
Repeat `run` only when status still reports runnable work.
Use the default `--permission-mode ask` for an attended terminal; `auto` is the
explicit non-interactive choice used by the headless example. `dont-ask`
rejects tools that would otherwise require a prompt and therefore cannot drive
the MCP lifecycle.

## Disable and remove

Stop invoking `run` to disable execution without changing state. Remove the
host-wide MCP entry with:

```bash
.venv/bin/loopx-kunluncode uninstall
```

Remove `.loopx/kunluncode.json` only when the project should no longer resolve a
KunlunCode identity. Removing the binding does not delete goals, todos, run
history, or another host's adapter.

## Authority and privacy boundary

Activation grants no repository write, publish, destructive, credential, or
production authority. The MCP server only exposes LoopX lifecycle operations;
the selected todo and existing goal boundary remain authoritative. The binding,
active goal state, and run evidence stay below ignored `.loopx/` or the private
LoopX runtime and must not be committed.
