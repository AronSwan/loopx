# Extension lifecycle and managed runtime

Installing a package and activating it in LoopX are separate stages. LoopX does not download arbitrary
packages or execute a caller-selected binary. It manages a doctor-validated Provider revision.

## Start from a bad ending

After one provider upgrade, support receives this report: "The upgrade succeeded, but we can no longer read
the output."

The reproduction path is concrete. The old response carried `result` as an object; the new one turns it
into a string and moves the version to `0.2.0`. `loopx extension upgrade <extension-id> --execute` passes, because the new
revision's doctor genuinely passed its readiness probe. Doctor only proves the entrypoint starts; it does
not tell you that downstream parsing code is now out of date.

The caller has two reactions available, and both are wrong:

- **Parse the new shape:** historical receipts become unreadable immediately, and they carry nothing beyond
  a schema_version to help;
- **Roll back:** `rollback` probes the previous revision, but the replaced package is no longer in the
  environment, so the probe fails and rollback is unavailable.

The fault lies in the upgrade sequence itself: **the upgrade action changes two things at once** — the
active revision LoopX records, and the executable in the Python environment. The lifecycle governs the
first. Aligning the environment stays a human step. This chapter is about where exactly that boundary
falls.

## 1. Install the Python package, and the line it does not cross

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -e './standalone-extension[test]'
```

This puts the `loopx-text-stats` console entrypoint in the active environment. It does not change LoopX
activation state.

Inspect the Provider directly during development:

```bash
loopx-text-stats --doctor
loopx-text-stats < standalone-extension/examples/request.json
```

Direct execution is a development aid. The supported user path is `loopx extension`, for the reason the
failure section covers: running the entrypoint directly bypasses the timeout, input limit, and output limit
the managed runtime fixes.

## 2. Preview and install

Preview:

```bash
loopx extension install \
  --manifest standalone-extension/extension.toml \
  --format json
```

Execute:

```bash
loopx extension install \
  --manifest standalone-extension/extension.toml \
  --execute \
  --format json
```

`--manifest` and `--bundled` are mutually exclusive and one is required: a provider shipped in the wheel is
selected with `--bundled <id>`, and an independently distributed provider is pointed at with
`--manifest <path>`.

Install:

1. reads the declarative manifest;
2. checks API compatibility and permissions;
3. resolves the installed entrypoint;
4. runs the read-only doctor;
5. records a validated manifest snapshot and revision;
6. activates that revision and sets `enabled`.

It does not download a package, execute an arbitrary caller binary, grant new permissions, store Provider
output in activation state, or read project Goal state.

Two things need separating precisely here. "Default-off" describes a **declaration**: a manifest read into
a catalog reports `declared=true, installed=false, enabled=false, ready=false`, and executes nothing. An
`install --execute` that passes doctor sets `enabled` to `true` in the same write. The careful statement
is therefore: **nothing takes effect until an explicit `--execute`.**

Install is not idempotent: installing the same id twice fails with "already installed", and submitting an
already-active revision as an upgrade fails with "revision is already active".

## 3. Inspect readiness

```bash
loopx extension list --format json
loopx extension doctor loopx-text-stats --execute --format json
```

`doctor --execute` runs the actual probe. Readiness binds the active manifest revision and the resolved
runtime identity, and that identity covers the entrypoint file contents, the selected Python interpreter,
the origin of a `python_module`, and any view validator the extension declares. A change to any of them
invalidates the old doctor proof. LoopX's own built-in validators are deliberately excluded, so upgrading
LoopX does not invalidate every extension with it.

Doctor status is a ladder rather than a boolean:

```text
entrypoint_missing              -> identity cannot be resolved
doctor_not_configured           -> doctor_args is empty
probe_required                  -> resolvable, but no --execute
provider_unavailable            -> probe exited nonzero
entrypoint_changed_during_probe -> identity differed across the probe
ready                           -> usable
```

A failed doctor clears stale readiness but does not switch revisions. It waits for an environment repair
and a new probe.

## 4. Invoke through the managed runtime

Preview:

```bash
loopx extension run loopx-text-stats \
  --input-json standalone-extension/examples/request.json \
  --format json
```

Execute:

```bash
loopx extension run loopx-text-stats \
  --input-json standalone-extension/examples/request.json \
  --execute \
  --format json
```

The managed runtime fixes:

- Extension id and active revision;
- entrypoint and arguments;
- stdin/stdout JSON protocol;
- timeout, taken from the manifest's `timeout_seconds` (1 to 120);
- permissions;
- request size limit;
- stdout and stderr limits.

The caller cannot add shell arguments or replace the executable. Timeout or output overflow terminates the
Provider's whole process group, so child processes do not survive after LoopX reports a stop.

`run` supports only an Extension that is enabled, doctor-ready, has a runtime, declares no
`[[provides]]` or `[[implements]]`, declares no permission at all, accepts the bounded request, and
receives an explicit `--execute`. Every other case should fail closed.

## 5. Disable and enable

```bash
loopx extension disable loopx-text-stats --execute --format json
```

A disabled Extension remains visible in lifecycle state but is not a dispatch candidate. `extension run`
must fail.

Enable it again:

```bash
loopx extension enable loopx-text-stats --execute --format json
```

Enable does not trust old readiness. It reruns doctor before setting the enabled bit. On failure it stays
disabled and clears the old doctor proof, so no state claims to be enabled and ready at the same time.

## 6. Upgrade and rollback

Before upgrade, update the package and manifest version, then install the new package into the same
environment.

Preview:

```bash
loopx extension upgrade \
  --manifest standalone-extension/extension.toml \
  --format json
```

Execute:

```bash
loopx extension upgrade \
  --manifest standalone-extension/extension.toml \
  --execute \
  --format json
```

Upgrade validates and probes the new manifest before changing the active revision. A failed probe leaves the
current revision active, so there is no half-state where the upgrade failed and the old version is also
unusable.

Rollback:

```bash
loopx extension rollback loopx-text-stats --execute --format json
```

Rollback probes the previous validated revision before switching. It is a lifecycle transition over
activation state, not an arbitrary Git checkout. Activation state retains a bounded number of validated
revision snapshots (five today).

That also explains why the second reaction at the start of this chapter fails: rollback switches the
revision LoopX recorded. It does not reinstall the previous package version into the Python environment for
you. When `rollback_available` is false, the correct action is to repair the environment, not to look for a
way around activation state.

## 7. Isolate example state

CI and tutorials can use `--state-file` to avoid modifying the user's default runtime state:

```bash
state_file="$(mktemp)"
rm -f "$state_file"

loopx extension install \
  --state-file "$state_file" \
  --manifest standalone-extension/extension.toml \
  --execute \
  --format json
```

The temporary file may contain local runtime identity and must not be committed to any public repository.

## When standalone `run` is not valid

Use a Capability or domain command for:

- file reads or writes;
- authenticated API access;
- sending messages;
- publishing content;
- managing external resources;
- modifying project state;
- any effect that needs action or scope authority.

An effectful dispatch creates a request-bound execution envelope after domain policy checks. It binds four
fields:

- `action`;
- `scope` (size-capped);
- `extension` (the id and active revision);
- `request_digest` (a digest over the bare request, with the envelope removed).

The envelope is not a service credential, and it does not replace an external system's own authorization.
A caller-created envelope, widened scope, changed request, or revision mismatch must fail closed.

## Cost and boundary

The lifecycle turns "is this extension live" into auditable state. The cost is a thicker operational
surface.

**Cost one: an upgrade is a two-part action.** LoopX manages the revision and the package manager manages
the environment, and a human keeps them aligned. Install the new package into the same environment first,
or the probe keeps examining the old file.

**Cost two: the managed runtime limits what a provider may do.** You cannot swap the executable, add
arguments, or exceed the timeout and output limits. A provider that needs to run for a long time does not
fit this path.

**Cost three: revision history is bounded.** Activation state retains a limited number of snapshots, so a
sufficiently old version cannot be rolled back to.

**Boundary one: the managed runtime is not a sandbox.** Extensions are trusted executable code, and a
permission declaration does not turn one into operating-system-level isolation.

**Boundary two: LoopX does not distribute.** It does not download, build, or install packages, create
credentials, or start services.

**Boundary three: readiness is not authorization.** A passing doctor says the current revision can be
invoked. It grants no effect permission.

## Named failures: what these constraints stop

**A permissioned Extension is rejected before invocation.** `test_extension_run_rejects_any_declared_permission_before_invocation`
parametrizes over many permission strings, asserts the error matches "standalone extension run grants no",
and asserts a marker file was never written: the rejection precedes the provider's start.

**A timeout kills the whole process group.** `test_extension_run_terminates_provider_on_timeout` asserts
`failure_kind == "timeout"` and `exit_code is None`, and that a grandchild's marker file does not exist
after the kill.

**A failed upgrade keeps the active revision.** `test_failed_upgrade_keeps_the_active_revision` and
`test_failed_enable_remains_disabled_and_clears_old_proof` assert the failure path changes no revision and
leaves no stale proof behind. `test_enabled_extension_doctor_batch_keeps_failed_provider_closed` asserts
that the failing member of a doctor batch stays blocked with `probe_nonzero_exit`.

Corresponding tests: `tests/extensions/test_extension_runtime.py`.

## Troubleshooting

| Symptom | Inspect first |
| --- | --- |
| `entrypoint_missing` | Whether the package is installed in the environment that runs `loopx` |
| Install preview succeeds but list is unchanged | Whether `--execute` was omitted |
| "already installed" | Whether the id is already installed; install does not merge idempotently |
| Doctor is stale | Whether the executable, interpreter, module source, or view validator changed |
| Run reports disabled | Run `enable --execute` and inspect doctor |
| Run rejects permissions | Whether the Provider belongs behind a Capability/domain command |
| Upgrade does not switch | Whether doctor failed for the new revision, or the revision is already active |
| Rollback is unavailable | Whether a validated previous revision exists and the old package is still installed |

Fix the contract or environment. Do not bypass managed runtime and pretend the Provider is activated.

## Invariants

1. **Package installation and activation are two stages.** A successful pip run changes no activation
   state, and a successful install installs no package.
2. **Nothing takes effect without an explicit `--execute`.** Preview, declaration, and doctor are all
   read-only; only `--execute` writes state.
3. **Readiness binds a revision and a runtime identity.** Swap the executable or the interpreter and the
   old proof is void.
4. **A failed probe changes no revision.** Upgrade, enable, and rollback all follow this rule; no half-state
   is allowed.
5. **Standalone `run` serves zero-permission providers only.** Once a permission is declared, the correct
   path is a Capability or a domain command.
6. **Rollback switches a recorded revision, not the package on disk.** Restoring availability requires a
   human to align the environment with that revision.

This chapter moved an Extension from "it runs" to "it is auditable." The next chapter changes direction:
when a change has to enter LoopX core itself, how the test and the responsibility split shift.
