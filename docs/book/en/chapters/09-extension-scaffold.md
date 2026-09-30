# Build a standalone Extension

This chapter creates `loopx-text-stats` from the official LoopX scaffold. The official scaffold supplies
the complete runnable baseline; this chapter provides the narrowed manifest, request and response
contracts, core function, and validation steps without a separate exercise repository.

## Start from a bad ending

Someone needs to connect an internal statistics task, decides the capabilities shipped with LoopX look
too heavy, and hand-writes a smaller directory instead: one `extension.toml`, one `cli.py`, reading stdin
and printing a result. `loopx extension install --manifest <path> --execute` accepts it, and `run` works.

Two weeks later an audit finds:

```text
request  carries a path field  -> the provider quietly read it as a file
response has no schema_version -> downstream cannot tell the protocol version
doctor   not implemented       -> ready only proves the process starts
version  written outside the manifest -> upgrade cannot resolve a revision
```

Each item looks like a small omission. Together they are one thing: **this provider has no checkable
contract, so LoopX cannot judge whether it was called legally.** That it "works" proves only that the
process starts.

The scaffold exists to make the path complete by default: obtain a baseline with every contract field
present, then delete from it, rather than building up from an empty directory. Deleting a domain field you
do not need has a visible consequence; omitting a schema or a doctor fails only at audit time.

## 1. Generate the official scaffold and its boundary

```bash
loopx extension init loopx-text-stats \
  --destination standalone-extension \
  --execute \
  --format json
```

`extension init` previews by default. `--execute` is required to write files. The default destination is
`packages/<extension-id>`, and `--destination` targets somewhere else. The destination must not already
exist, even as an empty directory; there is no force or merge mode.

The important part is the command's boundary: it does not build, install, register, or enable. Those are
three separate actions with three owners, and running them separately keeps the package manager and the
LoopX activation state from drifting together:

```bash
python3 -m pip install ./standalone-extension
loopx extension install \
  --manifest standalone-extension/extension.toml \
  --execute \
  --format json
```

The generated path is:

```text
standalone-extension/
├── extension.toml
├── pyproject.toml
├── README.md
├── examples/
│   └── request.json
├── schemas/
│   ├── request.schema.json
│   └── response.schema.json
└── src/
    └── loopx_text_stats/
        ├── __init__.py
        └── cli.py
```

This is a complete standalone path. It does not invent the Capability authority required for
`[[provides]]` or `[[implements]]`, for a practical reason: `[[provides]]` needs a real caller contract,
and `[[implements]]` needs an existing capability resolver, policy check, action/scope mapping, and
execution-envelope adapter. A generic scaffold cannot infer those semantics safely. Define a capability
integration profile first, then author the provider against it.

## 2. Read the manifest as a contract

After narrowing the generated scaffold to this example, the manifest is:

```toml
schema_version = "loopx_extension_manifest_v0"
id = "loopx-text-stats"
version = "0.1.0"
requires_loopx_api = ">=1,<2"
permissions = []

[runtime]
protocol = "loopx_text_stats_extension_v0"
entrypoint = "loopx-text-stats"
doctor_args = ["--doctor"]
required_permissions = []
timeout_seconds = 30
```

The important constraints are:

- `id` is the lifecycle identity: a lower-kebab path segment of at most 48 characters;
- `version` participates in revision and upgrade;
- `requires_loopx_api` declares the compatibility window; the current API version is the integer `1`;
- `protocol` is the Provider wire contract;
- `entrypoint` and `python_module` are mutually exclusive, and `entrypoint` must exist on `PATH` in the
  Python environment running LoopX;
- `doctor_args` names a read-only readiness probe;
- both permission lists are empty;
- `timeout_seconds` ranges from 1 to 120, is read by the managed runtime, and cannot be overridden by the
  caller.

One further fail-closed rule deserves its own line: `runtime.required_permissions` must be a subset of the
provider's `permissions`. Declaring a permission grants nothing; it only qualifies the provider to enter
the call path that needs it.

## 3. Define a bounded request

The example request is:

```json
{
  "schema_version": "loopx_text_stats_request_v0",
  "text": "LoopX keeps project state explicit.\nExtensions keep delivery lifecycle explicit."
}
```

The request schema requires:

- an object payload;
- an exact `schema_version`;
- a `text` string containing a non-whitespace character;
- `additionalProperties: false`.

Rejecting unknown fields is part of the permission boundary, not a style preference. If the caller sends:

```json
{
  "schema_version": "loopx_text_stats_request_v0",
  "text": "hello",
  "path": "input.txt"
}
```

the Provider must reject it. It must not reinterpret `path` as file-read authority. The schema is part of
the bounded request.

## 4. Implement pure computation

The example's core function is:

```python
def analyze_text(text: str) -> dict[str, int]:
    return {
        "characters": len(text),
        "non_whitespace_characters": sum(
            1 for character in text if not character.isspace()
        ),
        "words": len(re.findall(r"\S+", text)),
        "lines": len(text.splitlines()) or 1,
    }
```

It is a good first standalone Extension because it is deterministic, reads no environment or files, uses
no network, modifies no external system, and does not depend on LoopX project state.

The Provider validates structure before computation and returns errors through a versioned response:

```json
{
  "ok": false,
  "schema_version": "loopx_text_stats_response_v0",
  "extension_id": "loopx-text-stats",
  "error": "extension input has unsupported fields ['path']"
}
```

Do not expose tracebacks, environment variables, or local paths in public receipts.

## 5. Define the response contract

The stable domain response is:

```json
{
  "ok": true,
  "schema_version": "loopx_text_stats_response_v0",
  "extension_id": "loopx-text-stats",
  "request_schema_version": "loopx_text_stats_request_v0",
  "result": {
    "characters": 80,
    "non_whitespace_characters": 71,
    "words": 10,
    "lines": 2
  }
}
```

The response schema uses `oneOf` to separate success and failure. Tests should assert this domain contract,
not every field in the outer LoopX CLI receipt. That allows additive receipt changes in a minor release
without breaking a domain test.

## 6. Keep doctor free of effects

The starter doctor path is:

```python
if args.doctor:
    return 0
```

For this pure Provider, readiness means the entrypoint starts and parses arguments. Doctor must not:

- create files;
- access the network;
- write credentials;
- change Extension state;
- perform a business effect;
- emit unbounded logs.

A real Provider may perform bounded read-only dependency checks. Readiness still needs to be repeatable and
effect-free. The doctor receipt always reports `external_writes_performed: false`, and that assertion is
itself part of the contract.

## 7. Install the package and run tests

Use one Python environment for the Provider and LoopX:

```bash
cd standalone-extension
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -e '.[test]'
python3 -m pytest
```

The single-environment requirement follows from how LoopX locates a provider: through its installed
console entrypoint. If the package lives in another virtual environment, `entrypoint_missing` is the
correct result; LoopX must not search arbitrary source directories.

## Cost and boundary

The scaffold moves cost from audit time to the beginning, and that cost deserves stating.

**Cost one: you start with eight files.** A provider that only counts characters still carries two JSON
Schemas, a README, and a `pyproject.toml`. For a one-off script that weight is real.

**Cost two: the starter request and response are documentation, not a domain contract.** What it generates
runs, but it does not describe your domain. Replace it with bounded, domain-specific semantics before
productizing.

**Cost three: the scaffold does all four other actions not at all.** It does not build, install, register,
or enable. Skipping the install step lets the package and the activation state drift apart.

**Boundary one: `extension init` currently generates only the standalone path.** An Extension needing
`[[provides]]` or `[[implements]]` should have a capability integration profile first. Do not add manifest
tables merely to make a runtime installable.

**Boundary two: doctor proves readiness, and `--execute` proves intent.** Neither authorizes a business
effect.

**Boundary three: the destination is never reused.** Every existing directory is refused, which protects
an existing package from being overwritten by a new extension.

## Named failures: what these constraints stop

**The scaffold rejects unsafe identifiers.** `test_scaffold_rejects_unsafe_identifiers` asserts a failure
for `LoopX-example`, `loopx_example`, and the version string `v1`. The `id` becomes a path segment and a
lifecycle identity, so loose validation defers a naming problem to after installation.

**A preview writes nothing.** `test_scaffold_preview_is_read_only` asserts the preview returns the exact
eight-file list along with `managed_entrypoint == "loopx extension run"`, `starter_kind == "standalone"`,
and `capability_id is None`. That last one is the chapter's most important piece of evidence: the scaffold
explicitly claims no capability.

**The generated provider refuses out-of-bounds input.** The same suite asserts it rejects a non-object
payload and a request contract ending in `_v1`, with a nonzero return code and `ok is False`.

Corresponding tests: `tests/extensions/test_extension_scaffold.py`.

## Common mistakes

### Hand-writing a smaller scaffold

This often omits schema, doctor, compatibility, or the package entrypoint. Generate the complete official
path first, then make minimal domain changes.

### Accepting arbitrary keyword arguments

This destroys the bounded request and can expand authority accidentally. The JSON Schema and Provider
validation should both fail closed.

### Running business work in doctor

Doctor proves readiness. It does not authorize an effect. Business requests belong in the managed runtime
or an authorized Capability/domain command.

### Adding a permission for demonstration

Once a permission is declared, `extension run` rejects the call before invoking the provider, with the
message "standalone extension run grants no effect dispatch". Design the real Capability and authority
before building an effectful Provider.

## Invariants

1. **Every contract field in a scaffolded directory exists before you delete it.** Starting from an empty
   directory guarantees a missing one, and a missing field surfaces only at audit time.
2. **`extension init` generates only the standalone path.** It claims no capability and infers no
   authority for `[[provides]]` or `[[implements]]`.
3. **A provider call carries a checkable `schema_version`.** Without it, a receipt cannot be matched to a
   compatible version.
4. **Unknown fields are rejected outright.** Reading an extra field as implicit authorization defeats the
   permission boundary.
5. **Doctor must have zero side effect.** An `external_writes_performed` of `true` means the readiness
   probe crossed its boundary.
6. **The package and LoopX share one Python environment.** Across environments the correct result is
   `entrypoint_missing`, never a silent fallback.

The next chapter puts this structure through its real lifecycle: install, enable, invoke, upgrade, and
rollback.
