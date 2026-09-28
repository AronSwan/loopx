# Canonical terminal review and validation

On an explicitly promoted local Goal, Agent completion and Monitor stop now use
the same reviewed recovery path as Todo edits and User completion. The initiating
Chat action binds the complete provider revision and registry digest, preserves
one operation identity, and acknowledges display only after the existing
projection outbox confirms the current view.

## Operate and recover

For ordinary CLI completion, retain the same explicit completion identity after
a lost response:

```bash
loopx todo complete --goal-id example-goal --todo-id todo_work \
  --agent-id agent-a --completion-identity-key reviewed-result --no-follow-up
loopx todo list --goal-id example-goal --todo-id todo_work
loopx todo project-markdown --goal-id example-goal --execute
```

Use `--no-follow-up` only when no successor is needed. Leased work additionally
requires its current `--task-lease-idempotency-key` and
`--task-lease-expected-version`; owner confirmation is not a lease or a lifecycle
grant. Chat users retry the same failed proposal. A stale proposal requires a
fresh preview, not a replacement identity that bypasses review.

| Boundary | Observable result |
| --- | --- |
| Provider/registration changes before a fresh reviewed completion | Reject before private validation execution; Chat marks the proposal stale |
| Provider changes during validation | Reject the old validation result; Todo remains unfinished |
| Lease expires during validation | Recheck runtime time and reject stale execution proof |
| Canonical commit succeeds, display delivery fails | Business remains committed; Chat reports recoverable failure without a successful display receipt |
| Response/action receipt is lost after commit | Retry recovers the original business receipt before checking current review freshness |
| Same operation carries a changed reviewed note, evidence, reason or basis | Reject identity reuse; never silently acknowledge the changed intent |
| Private declaration is unavailable after successful completion | Business receipt can recover from its public commitment; lossless display recovery still requires restoring the original declaration |

The TypeScript terminal owner performs admission, source checks, validation
planning, lease retirement, linked effects, CAS and receipt recovery. Python
transports facts, resolves private argv only when requested, executes declared
validation and drains projection. It does not decide whether a stale validation
can complete work. The preview executes no validator. Separate user-completion
edits retain their existing combined edit/terminal semantics and old stored Chat
proposals retain their existing protocol.

## Wire and migration boundary

The packaged Python adapter and TypeScript runtime use one request schema,
`loopx_local_coordination_todo_terminal_lifecycle_request_v3`, for complete and
supersede. `operation_identity` explicitly selects the operation's meaning:

- `{kind: "explicit", operation_id: "..."}` executes or recovers that named
  operation, including historical receipts created by earlier runtimes.
- `{kind: "current_monitor_cycle"}` completes a `continuous_monitor` without an
  explicit completion turn key. The TypeScript owner derives the operation id
  from Goal id, Todo id and authoritative `material_change_generation`.

Reopening the Monitor advances its generation, so earlier-cycle receipts cannot
complete the current open cycle. If an explicit operation already completed the
current cycle, the core records a generation-scoped no-change receipt. It never
infers cycle membership from an old unscoped receipt. Both identity modes share
one terminal transaction; ordinary completion and supersede use explicit identity.

The terminal method also accepts these bounded additions:

- `review_basis`, when present, contains exactly `provider_revision` and
  `registry_sha256`. It binds reviewed intent and is part of receipt identity.
- `validation_source_provider_revision` is null before an issued effect and is
  the returned revision on continuation. It is a freshness constraint, not new
  operation identity. Both caller validation and Goal acceptance validation
  require it in the current protocol.
- `validation_declaration_sha256` carries the canonical public commitment.
  Historical recovery precedes private declaration resolution. Fresh execution
  still requires the matching declaration and current authorization.

The existing method may return `resolve_validation` before `execute_validation`.
Both responses bind the source revision; neither commits the business operation.
For a validated fresh completion the host crosses the runtime boundary three
times (resolve, plan effects, commit), versus two before this change. Unvalidated
completion and historical recovery remain one terminal request. This bounded
extra crossing makes receipt recovery independent of host-local argv; it can
disappear when the native host owns declaration resolution and effect execution.

The old v0/v1/v2 request decoders are retired. These are internal, co-packaged
adapter/runtime requests, not stored operations: upgrade the pair together and
regenerate requests with the current runtime. Mismatched versions and the old
top-level `operation_id` shape fail before provider access. Persisted receipt
schemas, operation ids and request fingerprints are unchanged; receipt recovery
does not require keeping an old request decoder.
The public completion facade rejects a reviewed canonical request
if authority has reverted to an unpromoted legacy path.

No provider default, promotion, permission, retention or storage format changes.
Rollback restores compatible code while retaining provider data, receipts and
writer fences. Code that does not recognize the request version cannot execute
it; regenerate a preview with compatible code instead of stripping its review
fields or changing the operation identity. Markdown stays a permanent display.
These changes close the terminal review/recovery family, not all leased metadata
updates, executor-held external-effect fencing, D1–D3 or whole-Goal cutover.

Shared provider conformance uses the complete production-scale fixture, both
native and imported records, stale review/validation, expired proof, lost commit
response and unchanged non-target state. Real File/SQLite Chat HTTP tests exercise
the packaged entrypoint and retry feedback. The frontend runtime decoder and shared action-review plan now recognize the
terminal basis for exactly Agent completion and Monitor stop. The packaged Chat
bundle includes the original-operation retry path and distinguishes pending
display from verified completion; no new configuration or visual control is required. Lark receives no new
command or transport in this slice.
