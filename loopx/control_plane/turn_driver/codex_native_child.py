"""Transient Codex host events adapted to native-child receipts.

Only opaque identities and typed outcomes reach the existing multi_subagent
log. Prompts, child messages and raw tool output are never retained.
"""
from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ...capabilities.multi_subagent.native_child_receipts import record_native_child


def configured_native_child_limit(request: Mapping[str, Any]) -> int | None:
    envelope = request.get("turn_envelope")
    context = envelope.get("agent_context") if isinstance(envelope, Mapping) else None
    contributions = context.get("contributions") if isinstance(context, Mapping) else None
    if not isinstance(contributions, list):
        return None
    for contribution in contributions:
        if not isinstance(contribution, Mapping) or contribution.get("capability_id") != "multi_subagent":
            continue
        facts = contribution.get("facts")
        count = facts.get("max_children") if isinstance(facts, Mapping) else None
        if isinstance(count, int) and not isinstance(count, bool) and count > 0:
            return count
    return None


class CodexNativeChildObserver:
    """Bound to one owned host invocation and one admitted LoopX Turn.

    The public recorder cannot select host provenance. Codex exec and app-server
    use different field casing; both are normalized here at the provider seam.
    Failed collab items lack a typed capacity error, so they remain host_failed.
    A host retry is recorded as observed fact, never authorized by this adapter.
    """

    def __init__(self, *, runtime_root: Path, lineage: Mapping[str, str],
                 turn_instance_id: str, configured_limit: int):
        self.runtime_root = runtime_root
        self.lineage = lineage
        self.turn_instance_id = turn_instance_id
        self.configured_limit = configured_limit
        self.children: dict[str, str] = {}

    def _record(self, *, stage: str, **record: str) -> None:
        record_native_child(
            runtime_root=self.runtime_root, goal_id=self.lineage["goal_id"],
            agent_id=self.lineage["agent_id"], turn_instance_id=self.turn_instance_id,
            configured_limit=self.configured_limit, stage=stage,
            entrypoint_id="codex_native_tools" if stage == "decision" else None,
            execute=True, _host_observed=True, **record,
        )

    def observe(self, item: Mapping[str, Any], *, session_id: str) -> None:
        item_type = item.get("type")
        if item_type not in {"collab_tool_call", "collabAgentToolCall"}:
            return
        snake = item_type == "collab_tool_call"
        sender = item.get("sender_thread_id" if snake else "senderThreadId")
        status = item.get("status")
        native_id = item.get("id")
        if sender != session_id or not isinstance(native_id, str) or not native_id or status not in {"completed", "failed"}:
            return
        tool = {"spawn_agent": "spawn", "spawnAgent": "spawn", "send_input": "followup",
                "sendInput": "followup", "resumeAgent": "followup", "wait": "wait"}.get(item.get("tool"))
        if tool is None:
            return
        receivers = item.get("receiver_thread_ids" if snake else "receiverThreadIds")
        if tool != "wait":
            started = status == "completed" and isinstance(receivers, list) and bool(receivers)
            if started and any(not isinstance(child, str) or not child for child in receivers):
                return
            # Successful spawn identity survives host event replay/restart; host
            # exec display-item counters alone are not globally unique.
            identity = receivers[0] if tool == "spawn" and started else session_id + ":" + native_id
            operation_id = "codex-" + hashlib.sha256(identity.encode()).hexdigest()[:32]
            self._record(stage="decision", operation_id=operation_id, operation=tool,
                         outcome="started" if started else "host_failed",
                         **({"reason_code": "host_failed"} if not started else {}))
            if started:
                for child in receivers:
                    self.children[child] = operation_id
        states = item.get("agents_states" if snake else "agentsStates")
        if not isinstance(states, Mapping):
            return
        for child, state in states.items():
            if child not in self.children or not isinstance(state, Mapping):
                continue
            outcome = {"completed": "completed", "errored": "failed", "shutdown": "cancelled"}.get(state.get("status"))
            if outcome:
                self._record(stage="result", operation_id=self.children[child], outcome=outcome)


def native_child_observer(request: Mapping[str, Any], *, runtime_root: Path,
                          lineage: Mapping[str, str]) -> CodexNativeChildObserver | None:
    limit = configured_native_child_limit(request)
    turn = request.get("turn_instance_id")
    if limit is None or not isinstance(turn, str) or not turn:
        return None
    return CodexNativeChildObserver(runtime_root=runtime_root, lineage=lineage,
                                    turn_instance_id=turn, configured_limit=limit)
