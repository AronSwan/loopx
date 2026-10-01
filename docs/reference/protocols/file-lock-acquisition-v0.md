# File Lock Acquisition v0

LoopX uses sibling kernel-lock files to serialize local read-modify-write
operations: POSIX uses `flock`, while Windows uses an `msvcrt` byte-range lock.
The kernel lock, not the file's existence, determines ownership. Operators and
automation must never delete a lock file to recover a waiter.

## Acquisition Policies

| Policy | Deadline | Timeout behavior |
| --- | ---: | --- |
| `mutation` | 5 seconds | Stop the command and require holder inspection before a manual retry. |
| `monitor` | 1 second | Stop the poll; do not tight-loop. Retry only on a later scheduled poll after inspection. |
| `single_flight` | no wait | Return an ordinary duplicate/no-op result without recording an incident. |

`exclusive_file_lock` uses `LOCK_EX | LOCK_NB`, a monotonic deadline, and a
bounded sleep between attempts. A deadline raises
`LockAcquireTimeoutError` with `error_code=lock_acquire_timeout`. The former
unbounded `LOCK_EX` wait is not part of this contract.

## Holder And Incident Records

After acquisition, the holder writes public-safe JSON to the POSIX `*.lock`
file or atomically overwrites the Windows `*.lock.holder.json` sidecar:

- stable hashed `lock_id` (never an absolute target path);
- PID, agent id, operation, policy, and acquisition time;
- release time after a normal exit.

Windows metadata is separate because a byte-range lock prevents another file
handle from reading the locked byte. POSIX retains the existing single-file
contract, where advisory metadata and `flock` share `*.lock`. In both cases the
kernel lock, not the metadata file's existence, is authoritative.

A timeout appends one `file_lock_incident_v0` row to the sibling
`*.lock.incidents.jsonl` channel. That append uses `O_APPEND` directly and does
not acquire the blocked lock. The row contains holder and waiter identities,
wait duration, policy, and an `operator_action`. Failure to append an incident
does not hide or delay the typed timeout.

## Operator Recovery

1. Inspect the recorded holder PID, agent, operation, and acquisition time.
2. Confirm that the process is still present and actually stalled.
3. Terminate the process only after that confirmation and within the operator's
   existing authority.
4. Retry according to the policy after the process exits. Do not delete the
   lock file; a later owner will overwrite the holder sidecar.

An absent PID or stale metadata is evidence to investigate, not permission to
remove a lock file. The kernel releases `flock` or `msvcrt` ownership when its
process or file descriptor exits.


> **LOCAL DEVIATION (2026-10-01, 调查庭裁决)**: 本机 clone 将 Windows 边车命名为
> `<lock>.holder`(无 .json 后缀; file_lock.py lock_holder_path 单点改动), 偏离本协议 v0 的
> `*.lock.holder.json` 明文契约。理由: 遗留边车(进程被杀)混入 *.json 通配扫描致
> peers.returns()/inbox.pending() 崩溃(复现取证: tmp-holder-exp/run_case.py)。
> 改名经全树核实无运行时破坏(所有读取方走 lock_holder_path(), TS 侧零字面引用)。
> 代价自负: 上游未来若在函数外新增字面量引用, 本地须跟改; 旧 .holder.json 残留对本机
> liveness 判为 absent。上游若修此 bug, 优先采纳其方案并删除本偏离。
