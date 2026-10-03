# Proposed delegated operation stop: canonical lease revocation

- Baseline: `e55489c77`, measured October 3, 2026.
- Outcome: overall roadmap S4 ("restart/cancel/drain/stop retain work and
  fence old executors") and the R2 bounded single-operation stop; the
  revocation half of delivery 2 in the
  [September 27 host-supervision plan](2026-09-27-host-supervision.md)
  ("cancellation on expiry/reclaim/revocation"). No provider, capability,
  configuration surface or lease vocabulary is introduced.
- Status: proposed alternative, pending an explicit maintainer decision.
  This entry neither replaces the stop contract under review in #5308 nor
  claims that the stop surface has shipped. Its implementation qualification
  applies only if this alternative is selected.
- [中文](2026-10-03-delegation-stop-lease-fence.zh-CN.md).

## What was measured

[#5308](https://github.com/loopx-project/loopx/pull/5308) is open again. Its
[October 3 review](https://github.com/loopx-project/loopx/pull/5308#pullrequestreview-5401677786)
requires canonical lease-obligation readback (R1), complete execution drain
observation in the existing Host boundary (R2), and a typed separation between
next actions and final receipts (R3). That review explicitly removes historical
failure-by-failure attribution as a merge prerequisite. Earlier failures remain
historical evidence, not proof that its current design cannot be repaired.

The two proposals address the same caller outcome with different guarantees:

| Boundary | #5308 under review | This proposed alternative |
| --- | --- | --- |
| Ordering | Prove the original execution drained before releasing its lease | Revoke the lease first; observe drain separately |
| Completion feedback | `settled` requires ACK, released holders, Host drain and resolved lease obligation | `revoked` proves loss of commit authority; only `drained` reports execution exit |
| Authority modes | Includes existing unleased routes with the dispatch fence | Requires canonical `hard_lease`; refuses unleased routes |

These are alternative public contracts, not interchangeable phase names. Do
not implement both under the same `delegation stop` / `stop_delegation` entry
points. The current #5308 repair follows R1–R3. Selecting this alternative would
require an explicit supersession decision, the CLI/MCP/readback/docs companions,
and the implementation evidence below; merging a design note alone does not
change the runtime contract. Neither approach establishes whole-team or Goal
completion, and neither makes revocation proof of physical drain.

At the measured baseline, `main` already provides reusable lease fencing and
supervision:

- `Delegations._complete_delegated_todo` refuses to commit without the
  execution's acquired lease and completes through the canonical lease CAS
  ([#5466](https://github.com/loopx-project/loopx/pull/5466)).
- `runLeasedHostProcess` re-proves the original owner/key/epoch at
  `min(30 s, remaining/2)` and cancels the delegated CLI, including its nested
  Host, when a renewal is rejected, current proof is lost or the last proven
  `expires_at` passes; the forced group termination follows a six-second
  grace ([#5436](https://github.com/loopx-project/loopx/pull/5436)). Each
  lease command may run for 60 seconds and a lost reply is retried once with
  the same intent, while the proven expiry stays armed throughout:
  `tests/control_plane/test_leased_host_process.py::test_real_renewal_faults_keep_original_deadline_and_identity`
  shows on real File and SQLite authority that a hung renewal does not keep
  the Host running past that expiry.
- `tests/test_delegation_lease_lifetime.py::test_real_revocation_or_new_execution_stops_nested_host_without_acceptance`
  proves on real File and SQLite authority that releasing that lease stops the
  nested Host and its descendants before the worker returns, leaves the Todo
  open, and that retrying the operation neither reacquires the old execution
  nor launches the Host again.

A replay of the retired acquire receipt is the only way the old execution key
can reach the authority again. The acquire receipt identity is deterministic
in `(goal_id, todo_id, owner, idempotency_key)`, and replay requires current
proof, so a released lease retires its key permanently without a new status.

## Proposed contract

1. **Scope.** One authorized, bound delegated operation on the local host
   authority. Not a team or Goal stop, not coordinator pause, not cross-host
   signalling, not a frontend control beyond a recorded-state label.
2. **Intent.** `stop` is the explicit intent of the binding's requester for
   one operation. It is persisted beside the operation record before any
   fence write, carries the requester identity and one stable `stop_id`, and
   cannot be inferred from a signal, a timeout or progress. Repeated stops
   return the same receipt.
3. **Fence.** The execution's own canonical hard lease
   (`owner`, `idempotency_key`, `lease_epoch`) is the only fence. The
   Delegations host releases it through the existing canonical lifecycle with
   a CAS on the current version, retrying only a version-mismatch race. This
   is the same trust the host already exercises when it claims, renews and
   completes on the member's behalf. After release the authority rejects
   every renewal, completion CAS and acquire replay from that execution; late
   Todo completion and result acceptance are impossible by construction. No
   file lock, worker acknowledgement, lane probe or process-group record is
   part of the guarantee.
4. **Receipt.** The typed TypeScript owner derives one phase from current
   facts on every read; no phase is persisted.
   - `requested`: intent persisted, the execution has not yet exposed a lease
     to release. Read again; the worker observes the intent before it
     launches a Host.
   - `revoked`: the release committed, or the execution is already fenced by
     another epoch or by expiry. Safe to continue the Todo with a new
     operation; the old execution cannot commit any canonical effect.
   - `drained`: additionally, the operation recorded its `stopped`
     observation with `host_supervision` of `returned` (the leased supervisor
     returned after proof loss) or `not_launched` (no Host was launched).
   - `noop`: the operation was `accepted` or `rejected` before the fence took
     effect. Its prior conclusion stands and nothing is written.
   Drain is an observation, never a settlement condition. A dead worker
   leaves `revoked` with `host_supervision: unobserved`; later green reads do
   not upgrade it.
5. **Worker observation.** The worker checks the intent before acquiring a
   lease and again before launching a Host, releases its own lease on either
   checkpoint, and records `stopped` after any supervised execution returns
   while the intent exists. Those checkpoints avoid wasted work; the fence,
   not the checkpoint, is the guarantee.
6. **Authority mode.** Stop requires the Goal's canonical `hard_lease` mode.
   On `legacy` or `soft_claim` authority there is no execution lease and
   therefore no fence; `stop --execute` is refused before any write with a
   reason naming the mode. Promoting the Goal is the enabling step.
7. **Lifecycle.** A stopped operation refuses `resume`; continuing requires a
   new operation, which acquires a new lease epoch. Stop never completes the
   Todo, settles the Goal or changes an accepted result.
8. **Drain latency.** Revocation and drain run on different clocks. The
   fence holds from the moment the release commits. Physical drain follows
   when the existing supervisor cancels the delegated CLI, on the first of a
   rejected renewal, a renewal whose command fails twice, a current-proof
   read that fails or no longer proves the execution, or the last proven
   `expires_at`. Only that expiry bounds drain unconditionally: it is at most
   one lease TTL after the release commits, because nothing renews after the
   release, and the six-second grace and forced group kill follow it. About
   thirty-six seconds (a renewal interval of at most 30 seconds plus the
   grace, plus one lease command) is the nominal path only: no renewal is in
   flight when the release commits and the authority answers promptly. A
   renewal already in flight finishes on its own clock, so slow or lost
   authority replies move drain toward the expiry bound. `revoked` therefore
   never implies drain; treat execution resources as released only on
   `drained`. This slice adds no release-to-drain deadline and no signal
   accelerator; a tighter unconditional bound would need a supervisor-owned
   cancellation deadline with its own real-process qualification. Nested
   Host cleanup after a forced group kill remains the existing supervisor
   boundary from #5436 and is not re-proven here.
9. **Surfaces.** CLI `delegation stop --execute` and MCP `stop_delegation`
   share `Delegations.stop`; `read`, `wait` and the inventory expose the
   receipt and the `stopped` observation. The dashboard shows a recorded
   stop, not a claim that execution resources were released.

## Decisions proposed here

- **D1, hard-lease only.** This reduces the stop guarantee to the canonical
  lease fence, at the cost of refusing existing unleased routes. #5308 instead
  retains their dispatch-fence path; that tradeoff needs a maintainer decision.
- **D2, release instead of a new `revoked` lease status.** A new status would
  extend a vocabulary consumed by lifecycle, proof, retirement, migration and
  recovery owners; release already retires the key, as measured.
- **D3, drain reported, not required for revocation.** This makes authority
  loss observable while processes may still be running. It does not satisfy
  #5308's `settled` promise or qualify immediate resource handoff.

## Qualification the implementation owes

The implementation PR shows each of these on real processes against File and
SQLite authority, records the observed release-to-drain durations, and never
asserts the nominal thirty-six seconds:

- **Healthy revocation, the positive control.**
  `test_real_revocation_or_new_execution_stops_nested_host_without_acceptance`
  keeps passing: releasing the lease stops the nested Host and its
  descendants before the worker returns, and the Todo stays open.
- **Release while a renewal is in flight.** With a long TTL (for example 180
  seconds), the stop's release commits after a renewal has started and while
  that renewal's authority reply is delayed. The receipt is `revoked` once
  the release commits and does not report `drained` while the nested Host is
  still running. No renewal, Todo completion or acceptance from the old
  execution commits, and drain arrives after the delayed rejection, no later
  than the last proven expiry plus the grace.
- **Lost authority replies.** When the renewal command fails twice or never
  answers within its timeout, the same receipt and fence properties hold,
  and the supervisor cancels no later than the last proven expiry plus the
  grace.

## What this entry does not establish

The stop surface is not implemented by this entry. Windows native drain,
PostgreSQL re-qualification, cross-host stop, Lark controls, whole-team stop
and installed-product acceptance are outside the slice. Lease records are
opaque JSON to the File, SQLite and PostgreSQL providers, so no provider
change is expected, but that is a reviewed claim of the implementation PR.
