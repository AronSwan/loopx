# Validation, compatibility, and safety

This chapter is about how to prove a design holds, and how not to move the cost somewhere else. It
is the core of the engineering boundary: a design can be elegant and still be nothing but a claim,
if nobody can demonstrate that it works.

## Start from a bad ending

Here is a timeline. It is more common than most people would like to admit:

```text
Mon 14:20  An author edits a status output path. The local focused smoke passes.
Mon 15:05  PR CI is red: CLI output exceeds its budget by 4.1%.
Mon 15:30  The author recomputes and confirms the output really did grow. They raise the
           budget ceiling from 24000 to 25000.
Mon 15:31  CI is green. The PR merges.
Next Mon   A downstream lane's agent reads truncated output during one long-path call and
           starts selecting the wrong Todo.
Next Fri   Nobody connects that incident to the 4.1% from a week earlier.
```

The failure disappeared, and so did the engineering constraint. The budget exists to make "the
output quietly grew" visible. Raising it removes the visibility; the underlying question — that path
really does emit more information now — is still there, just no longer visible to anyone.

The second bad ending is quieter:

```text
Tue 09:10  An author changes a default field on an update event from optional to required:
           "there is only one producer anyway."
Tue 09:11  Every test passes. No smoke encoded that default, so no test turns red.
Tue 11:00  Merge.
Wed        Two downstream lanes start using the wrong field, because their producers never
           wrote the now-required one.
```

Nobody here violated a checked rule, because **the rule that changed was exactly the one nothing
checked**. A default-behavior change does not raise its hand the way a failing test does.

### The structure both endings share

In neither timeline did anyone "forget to run the tests." In the first, the author ran them and they
reported red honestly; in the second, they were genuinely green. The real gap is in two places:

- **Judgment:** when a budget is exceeded, should you compact, keep the ceiling, or
  raise it? No automation answers that for you, because the answer depends on which consumer and
  which decision each field supports.
- **Declaration:** when a default changes, the author has to say so. Behavior that no
  assertion covers does not become less real because nobody reported it.

## Why "add another layer of validation" does not fix the gap

The reflex is to add a validation layer, or to run the full set every time. Both routes are blocked:

- **The full set is slow and expensive.** Deterministic tests, focused smokes, canary
  premerge, real backend integration, model-behavior qualification, and the release gate together
  cost enough that authors start hunting for shortcuts — and shortcut-hunting is what produced the
  ending above.
- **Re-validating is not re-judging.** Treating `measurement-only` as a pass, treating a
  skipped test as an environment quirk, and treating a raised ceiling as a fix are semantically
  identical: each swaps a green for an unanswered question.

So the design goal shifts from "is there validation" to two narrower and more actionable questions:
**what does this evidence prove, and what does it leave unproven?** Judgment belongs to the author
and the reviewer; the shape of the evidence belongs to the contract.

## The evidence ladder: each rung proves something different

The rungs are ordered by cost. Each answers a different question, and a green rung never substitutes
for a green rung below it.

### Rung 1: deterministic tests

Deterministic tests are the floor, and every other rung stands on them: schemas, illegal state
transitions, exact field presence, cold-path recovery, and replay idempotence all belong here. A
test that cannot reproduce reliably is a lead, not evidence.

```bash
uv run --extra test python -m pytest -q
uv run --extra test python examples/control_plane/cli-output-budget-regression-smoke.py
```

The smallest step on this rung is artifact validation, confirming that files and schemas are
self-consistent: Markdown builds, internal links resolve, JSON and TOML parse, requests and
responses satisfy their JSON Schema, and fixtures can be reset from scratch. The book's own gate is:

```bash
python3 -m pip install -r docs/requirements-docs.txt
book_site_dir="$PWD/output/dev-book-validation"
mkdocs build --strict --site-dir "$book_site_dir/docs"
mkdocs build --strict --config-file docs/book/mkdocs.zh.yaml --site-dir "$book_site_dir/docs/book"
mkdocs build --strict --config-file docs/book/mkdocs.en.yaml --site-dir "$book_site_dir/docs/book/en"
python3 examples/dev-book-publication-smoke.py --site-dir "$book_site_dir/docs/book"
python3 examples/dev-book-welcome-wagon-smoke.py --site-dir "$book_site_dir/docs/book"
```

Do not stop at parsing Markdown in isolation. Verify discoverability through the unified
`mkdocs.yaml` navigation, the GitHub Pages base path, and the homepage Learn route. The LoopX
monorepo publishes the site through MkDocs Material; dependency ranges live in
`docs/requirements-docs.txt`, and `examples/dev-book-publication-smoke.py` guards book navigation,
bilingual routes, official homepage entrypoints, and the no-Labs boundary. After a dependency
change, rerun `python3 -m pip check` and `mkdocs build --strict`. Before changing any UI or
documentation visual, read `docs/development/design.md`.

The [scaffold chapter](09-extension-scaffold.md) supplies setup and the contract tests. The official generator has no `[test]` extra. After copying the complete companion package, reuse its environment:

```bash
. .local/book-extension-venv/bin/activate
python3 -m unittest discover -s standalone-extension/tests -v
```

Then follow the [lifecycle chapter](10-extension-lifecycle.md) using an isolated state file to validate activation, invocation, disable, upgrade, and rollback. Markdown parsing alone cannot establish that user journey.

### Rung 2: product-surface validation

Check that the tutorial uses real release surfaces:

```bash
loopx --version
loopx doctor
loopx doctor --deep
loopx start-goal --help
loopx capability list --format json
loopx extension --help
```

Command existence is not workflow validation. Host automation, visible Goal, and Extension
activation each need their own readback. `doctor --deep` also starts and probes the TypeScript
Effect runtime packaged with the release. A successful return through a migration-time Python facade
does not by itself prove the TypeScript semantic owner, runtime decoder, and durable effect path.

### Rung 3: lifecycle validation

Project onboarding should prove that reconnect reuses existing state, status finds the active Goal,
local state is ignored by Git, Host activation is observable, and quota agrees with the selected
Todo.

An Extension or package-lifecycle contribution should prove that the package entrypoint resolves,
doctor succeeds without effects, install produces revision-bound state, a disabled Extension cannot
run, enable reruns doctor, an invalid request fails closed, and a failed upgrade preserves the
current revision.

A Control Plane, Capability, Provider, Host or Runner, or projection contribution should prove that
expected decisions come from an independently reviewed invariant rather than current implementation
output; that unit or contract tests cover positive, negative, and illegal states; that a focused
smoke or public-safe replay exercises the real protocol chain; that affected consumers such as
agent-facing output, scheduler, and writeback receive the right checks; that a Capability has a real
caller, outcome contract, and Domain State owner; that a Provider returns bounded observation,
effect, and readback without gaining Goal authority; that a Host or Runner preserves typed request
and result boundaries, independent validation, and real runtime readback; that a projection or
dashboard consumes a typed public-safe read model without creating browser write authority; that
docs and fixtures bind to a public contract and maintenance trigger instead of copying private
runtime state; that `loopx canary premerge --from-git-diff` or an equivalent risk set covers
cross-surface changes; and that the PR contains only the product, docs, and durable validation
needed for one protocol result.

### Rung 4: canary premerge

One focused smoke only proves the path you thought of. Cross-surface changes need a risk set
selected from the Git diff:

```bash
uv run --extra test loopx canary premerge --from-git-diff
# When the PR base is upstream/main:
uv run --extra test loopx canary premerge --from-git-diff --git-diff-base upstream/main
```

`premerge` uses the caller's Git root for diff hygiene, changed-Python compilation, and
public-boundary scanning, while the canary catalog runs from its own installed release root. One
hand-picked smoke cannot cover runtime, quota/status, scheduler, todo, install, dashboard,
benchmark-boundary, or public/private evidence changes. The gate has its own smoke:
`examples/canary/premerge-validation-gate-smoke.py`.

### Rung 5: model-behavior qualification

Some questions deterministic tests cannot ask, because they concern whether the model keeps the
protocol under real signals: whether it recognizes the selected todo, respects a human Gate,
continues after a healthy onboarding transition, and recognizes a known projection gap. A
low-frequency, explicitly manual gate answers those; day-to-day CI cannot carry it:

```bash
python3 scripts/qualify-doubao-model-behavior-live.py \
  --qualification-id <public-safe-run-id>
```

Its evidence boundary is stricter than the rungs below. `ARK_API_KEY` is injected only through the
process environment; prompts, packets, model responses, credentials, and conversations never enter
the repository, and only bounded receipts and mismatch codes may be retained. A fake transport tests
only adapter serialization, sanitization, and fail-closed handling — it never qualifies model
behavior. The command requires a clean candidate checkout, binds its receipt to that checkout's Git
source identity, and exits nonzero if any single real provider call fails.

### Rung 6: the release gate

The release gate does not rerun tests through a second orchestration framework. It aggregates
compact receipts from the existing lanes and proves they qualify the same clean source identity:

```bash
loopx canary release-qualification \
  --manifest-json release-qualification.json \
  --repo-root .
```

`exact_release_commit_qualification_manifest_v0` repeats `git_commit`, the Git tree id, clean-tree
status, package version, and version tag in every check receipt. A missing, failed, skipped, dirty,
rebased, or differently versioned receipt fails closed; results from an earlier commit cannot
qualify a later tag.

Be precise about this boundary: it is a read-only reducer. It runs no tests, calls no model, moves
no ref, creates no tag, and publishes nothing. **A ready receipt is not a release decision** — that
remains the owner's.

### Rung 7: real-path validation

Every rung above can still pass entirely on mocks or in-memory substitutes. Before delivering a
refactor you must validate the affected production entrypoint and real backend. The requirement
lives in the Refactor Real-Path Validation section of `AGENTS.md`, and the method and safety
boundary live in `docs/development/testing-and-quality.md`:

```bash
LOOPX_TEST_POSTGRES_URL="$DISPOSABLE_POSTGRES_URL" \
npm run test:postgresql-authority-store
```

The URI must name a disposable isolated server. The `file` and PostgreSQL providers execute the same
new rule, so "the two agree" cannot by itself prove compatibility. Tests must not touch active
state: use a separate database or tenant and a disposable runtime, with synthetic fixtures or an
owner-authorized read-only snapshot. Never test by promoting, rewriting, or corrupting an active
goal, its registry, writer fence, Todo, or lease state.

### The last step: outcome validation

The rungs above check commands and receipts. The last step checks the reader's and the consumer's
actual result:

- After onboarding, does the Agent really recover from the same canonical state?
- Does a Control Plane or Capability change preserve authority, precedence, replay, and
  recovery invariants?
- Do the Provider and Host paths prove results through real readback and an independent
  validator?
- Do projections, docs, and fixtures still point at the same authoritative source?
- Does the Extension return a correct, stable domain result?
- Are permissioned actions rejected or routed correctly?
- Does the documentation tell the reader how to recover when the normal path fails?

## Compatibility is not one version number

An Extension has at least four compatibility layers, and a meaning change in any one of them needs
its own disclosure:

| Layer | Example |
| --- | --- |
| package | Python version and dependency ranges |
| LoopX API | `requires_loopx_api = ">=1,<2"` |
| wire protocol | `loopx_text_stats_extension_v0` |
| domain schema | request and response schema versions |

A package version upgrade must not silently change the meaning of an existing schema. A breaking
wire contract needs a new protocol or schema version and a caller migration path.

### The disclosure obligation for default-behavior changes

This is the least-checked and most accident-prone rule in the chapter. When a default changes, the
author has three jobs:

1. **Rename the smoke that encoded the old default**, so it stops implying the old
   behavior still holds;
2. **Update the docs and release notes** with the new default;
3. **Name the affected lanes**, so downstream knows its assumptions moved.

`.gitignore`, an all-green CI, and "there is only one producer" exempt nobody. State the nature of
the obligation too: **guidance versus a machine-enforced obligation** (such as `must_attempt_work`)
must be explicit in the contract rather than inferred from prose. Documenting a machine-enforced
obligation as a suggestion is worse than omitting it.

## The public/private boundary

Before a public commit, look at what the working tree actually contains:

```bash
git status --short
git diff --name-only
git ls-files --others --exclude-standard

loopx check \
  --scan-path README.md \
  --scan-path docs/book/
```

If you generated runnable directories from a book example, scan those too:

```bash
loopx check \
  --scan-path README.md \
  --scan-path standalone-extension/
```

Scanning does not replace manual review:

- credentials, tokens, cookies, and API keys;
- absolute machine paths and disposable environment URIs;
- `.loopx/`, `.codex/goals/`, or any runtime state;
- raw agent transcripts, trajectories, and verifier output;
- private issues, internal links, and unredacted organizational narrative;
- temporary probes and generated logs.

`.gitignore` does not replace scanning, and it does not make an already tracked file disappear.

## Assign documentation authority deliberately

| Content | Authoritative home |
| --- | --- |
| Learning order, concept explanation, recovery model, and scaffold guidance | `loopx-book` |
| Complete CLI arguments, protocols, and release behavior | Official LoopX repository |
| Product code, durable fixtures, and smoke tests | The corresponding LoopX or Extension source repository |
| Current Goal, Todo, Gate, and evidence for a project | Project-local LoopX state |
| Commits, PRs, CI, and external resources | The corresponding external system |

The book does not copy the full reference. High-drift commands keep only the minimum path needed to
finish a task and point at `--help` and official documentation.

### Maintenance triggers

After each LoopX minor release, review installer and `doctor`, `connect` and `start-goal`, Host
surface names, Codex App heartbeat and Codex CLI Goal activation, the Runtime Connector Catalog, the
shipped baseline, active phase, and facade exit conditions of the TypeScript migration RFC, core
protocols and bounded-context ownership, the Extension manifest and lifecycle, and whether book
steps still reproduce on the current official scaffold. Update theory chapters only when the public
contract changes; an internal file reorganization does not warrant rewriting the reader's mental
model.

## Cost and boundary: what this validation gives up

**Cost one: the full set is slow and expensive.** Running every rung on every change is
unaffordable, so the practice is to select a subset by risk — and selecting well is itself a
judgment that needs review.

**Cost two: real-path validation may be impossible, and then you must stop.** With no safe isolated
environment, the answer is to report the evidence gap and hold delivery; a skipped test is not a
pass. That cost is deliberately inconvenient: an inconvenient stop beats a qualification bar that
quietly becomes a mock.

**Cost three: part of the disclosure obligation cannot be automated.** Renaming a smoke and updating
docs can be checked; naming the affected lanes and stating whether something is guidance or an
obligation depend on the author's declaration and the reviewer's reading.

**Cost four: raising a ceiling is a legitimate option, on purpose.** Sometimes an increase is the
right tradeoff. The cost is that it must carry its reasoning: the value and cost of the retained
information, the old and new ceilings, measured headroom, and expected variation or scale, plus a
rerun of the original scenario and the affected semantic and scale checks. A budget-only change need
not force unrelated cleanup, but a frozen experiment or promotion threshold cannot be relaxed
retroactively.

**Boundary one: this ladder covers engineering validation, not all quality control.** It does not
prove how much a release improves long-horizon outcomes. Outcome claims need something else: a
stable-release-versus-candidate manifest matched on task semantics, runner, model, reasoning level,
timeout, and repetitions, where any mismatch or incomplete arm fails closed.

**Boundary two: deterministic and model-behavior tests validate a contract, not product value.**
They can prove a control-plane contract holds; they cannot prove the contract deserves to exist.

**Boundary three: green does not mean releasable.** The release gate is an aggregator; the publisher
is someone else. Once the receipts are in, the release decision still belongs to a person.

## Pre-publication checklist

- [ ] The first viewport identifies the reader, value, and two practice paths.
- [ ] Chinese is primary; code and necessary terminology stay in English;
- [ ] Six foundation chapters cover sessions, Goals, state, work graphs, Turns,
  recovery, and boundaries.
- [ ] Onboarding covers Codex App and Codex CLI.
- [ ] Developer contributions cover the Control Plane, Capabilities, Providers, Hosts
  and Runners, projections, documentation, and fixtures.
- [ ] Contribution guidance is organized around placement, protocols, invariants, and
  evidence rather than function lists.
- [ ] Extension is presented as a contribution subpath and its example remains
  reproducible on the current official scaffold.
- [ ] `python3 examples/dev-book-publication-smoke.py` passes.
- [ ] `mkdocs build --strict` passes.
- [ ] Internal links and the public-boundary scan pass.
- [ ] The homepage first screen has been reviewed by the owner.

Only after these checks should the GitHub Pages workflow publish the site from `main`. Pages is a
display surface, not the source of content truth or LoopX state.

## Named failures: what these constraints stop

**Raising the ceiling when a budget fails.** The correct first step is measuring the same contract:
record the base and head revisions, workload, metric, and measurement boundary. Compact JSON
characters, UTF-8 bytes, nested key counts, real stdout, and tokens are different metrics and cannot
be interchanged. Then name the consumer and decision each changed field supports. Only then choose —
and disclose — among compaction, keeping the ceiling, and a justified increase. The full decision
boundary is in the Budget Failure Decisions section of `docs/development/testing-and-quality.md`.
Classifying the limit is step one: for a hard external or authorized limit, a test edit cannot raise
it.

**Changing a default and leaving no trace.** The test is not whether CI is green, but whether the
smoke encoding the old default was renamed, the docs were updated, and the affected lanes were
named. Miss any one of the three, and the change has already altered someone else's behavior without
anyone noticing.

**Validating a refactor only on mocks.** Unit tests, mocks, and in-memory conformance are useful,
but they cannot replace evidence from a real backend. When PostgreSQL authority is affected, the
validation is a real suite run against an isolated disposable server. Without that environment,
report the gap and hold delivery; skipping yields an evidence gap and nothing else.

## Invariants

Six claims you can check yourself.

1. **Each rung of evidence proves only its own rung.** A green rung never endorses
   another, and a ready release gate never stands in for the owner's release decision.
2. **How a failure was "fixed" must be readable.** One raised ceiling, one skip, or one
   `measurement-only` run must come with one written reason; otherwise the problem was merely moved.
3. **A default-behavior change must leave three traces:** a renamed smoke, updated
   documentation, and named affected lanes. Missing one means it went undisclosed.
4. **Without real-path validation there is no validation.** A pass on mocks can enter a
   PR, but it is not delivery evidence; when the environment is unavailable, report the gap instead
   of converting it into a pass.
5. **Before a public commit, every private artifact in the working tree must be seen or
   scanned.** `.gitignore` is not retroactive, and already tracked files do not vanish.
6. **The three kinds of limit are not interchangeable.** A hard external limit, a
   regression budget, and a presentation cap each have a different repair path. Treating a
   regression budget as a number to nudge is exactly that Monday at 15:30.

These six answer one question: **when a change looks successful, what makes it true rather than a
cost moved elsewhere?** With this chapter, the validation, compatibility, and safety faces of the
engineering boundary close. The next chapter puts these constraints into the course: the
control-plane course shows how the same rules get engineered step by step, and what evidence each
step leaves behind.
