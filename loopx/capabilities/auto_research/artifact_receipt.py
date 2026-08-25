from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .delivery_contract import (
    AUTO_RESEARCH_DELIVERY_CONTRACT_SCHEMA_VERSION,
    normalize_auto_research_delivery_contract,
)
from .research_state import build_research_evidence_graph_from_rollout_events
from .terminal_result_query import build_terminal_result_query
from ...agent_registry import registered_agent_ids_from_registry
from ...history import load_registry
from ...paths import resolve_runtime_root
from ...rollout_event_log import load_rollout_events, rollout_event_log_path


AUTO_RESEARCH_ARTIFACT_RECEIPT_SCHEMA_VERSION = (
    "auto_research_artifact_receipt_v0"
)
ARTIFACT_RECEIPT_STATUSES = {
    "verified",
    "partial",
    "inconclusive",
    "not_fulfilled",
    "stale",
}


def _details(event: Mapping[str, Any]) -> Mapping[str, Any]:
    value = event.get("details")
    return value if isinstance(value, Mapping) else {}


def _contract_events(
    rollout_events: Sequence[Mapping[str, Any]],
    *,
    wish_id: str,
) -> list[Mapping[str, Any]]:
    return [
        event
        for event in rollout_events
        if str(event.get("classification") or "")
        == AUTO_RESEARCH_DELIVERY_CONTRACT_SCHEMA_VERSION
        and str(_details(event).get("wish_id") or "") == wish_id
    ]


def _lineage_events(
    rollout_events: Sequence[Mapping[str, Any]],
    *,
    hypothesis_id: str,
) -> list[Mapping[str, Any]]:
    return [
        event
        for event in rollout_events
        if str(_details(event).get("hypothesis_id") or "") == hypothesis_id
        and str(event.get("event_kind") or "")
        in {"research_hypothesis", "research_evidence"}
    ]


def _artifact_refs(
    events: Sequence[Mapping[str, Any]],
    *,
    contract_revision: str,
) -> list[str]:
    refs = {
        str(ref)
        for event in events
        if str(_details(event).get("contract_revision") or "")
        == contract_revision
        for ref in event.get("artifact_refs") or []
        if str(ref).strip()
    }
    return sorted(refs)


def _failure_kind(result: Mapping[str, Any]) -> str:
    decision = result.get("terminal_decision")
    if result.get("decision_state") == "conflict":
        return "conflicting_terminal_decisions"
    review = result.get("peer_review")
    if isinstance(review, Mapping):
        if review.get("state") == "conflict":
            return "conflicting_peer_reviews"
        if review.get("state") == "independent_reviewed":
            if review.get("verdict") == "needs_more_evidence":
                return "needs_more_evidence"
            if review.get("verdict") == "reject":
                return "independent_review_rejected"
        if review.get("state") in {"self_review_only", "unreviewed"}:
            return "independent_review_missing"
    if (
        isinstance(decision, Mapping)
        and decision.get("outcome") == "retired"
        and decision.get("reason")
    ):
        return str(decision["reason"])
    if result.get("research_status") == "needs_retry":
        return "research_retry_pending"
    return "terminal_decision_missing"


def _criterion_result(
    criterion: Mapping[str, Any],
    *,
    result: Mapping[str, Any] | None,
    evidence_node: Mapping[str, Any] | None,
    lineage_events: Sequence[Mapping[str, Any]],
    contract_revision: str,
) -> dict[str, Any]:
    observed_revisions = sorted(
        {
            str(_details(event).get("contract_revision") or "")
            for event in lineage_events
            if _details(event).get("contract_revision")
        }
    )
    current_lineage = [
        event
        for event in lineage_events
        if str(_details(event).get("contract_revision") or "")
        == contract_revision
    ]
    review = (
        result.get("peer_review")
        if isinstance(result, Mapping)
        and isinstance(result.get("peer_review"), Mapping)
        else {}
    )
    decision = (
        result.get("terminal_decision")
        if isinstance(result, Mapping)
        and isinstance(result.get("terminal_decision"), Mapping)
        else {}
    )
    result_artifact_refs: list[str] = []
    if isinstance(result, Mapping) and result.get("decision_state") == "current":
        result_artifact_refs.extend(decision.get("evidence_refs") or [])
        for item in review.get("reviews") or []:
            if isinstance(item, Mapping):
                result_artifact_refs.extend(item.get("evidence_refs") or [])
    observed_artifacts = sorted(
        set(
            _artifact_refs(
                lineage_events,
                contract_revision=contract_revision,
            )
        )
        | {str(ref) for ref in result_artifact_refs if str(ref).strip()}
    )
    missing_artifacts = sorted(
        set(criterion["required_artifact_refs"]) - set(observed_artifacts)
    )

    if observed_revisions and not current_lineage:
        status = "stale"
    elif not current_lineage or result is None:
        status = "inconclusive"
    elif result.get("decision_state") in {"conflict", "stale"}:
        status = (
            "stale"
            if result.get("decision_state") == "stale"
            else "inconclusive"
        )
    elif decision.get("outcome") == "retired":
        independently_confirmed = (
            not criterion["requires_independent_review"]
            or (
                review.get("state") == "independent_reviewed"
                and review.get("verdict") == "approve"
            )
        )
        status = "not_fulfilled" if independently_confirmed else "inconclusive"
    elif decision.get("outcome") != "promoted":
        status = "inconclusive"
    elif criterion["requires_independent_review"] and not (
        review.get("state") == "independent_reviewed"
        and review.get("verdict") == "approve"
    ):
        status = "inconclusive"
    elif missing_artifacts:
        status = "partial"
    else:
        status = "verified"

    if status == "stale":
        failure_kind = "contract_revision_changed"
    elif status == "partial":
        failure_kind = "required_artifact_missing"
    elif status == "inconclusive" and not current_lineage:
        failure_kind = "contract_evidence_missing"
    elif (
        isinstance(result, Mapping)
        and (
            result.get("decision_state") == "conflict"
            or review.get("state") == "conflict"
            or (
                criterion["requires_independent_review"]
                and review.get("state") in {"self_review_only", "unreviewed"}
            )
            or review.get("verdict") in {"needs_more_evidence", "reject"}
        )
    ):
        failure_kind = _failure_kind(result)
    elif (
        isinstance(evidence_node, Mapping)
        and evidence_node.get("failure_kind")
        and status != "verified"
    ):
        failure_kind = str(evidence_node["failure_kind"])
    elif isinstance(result, Mapping) and status != "verified":
        failure_kind = _failure_kind(result)
    else:
        failure_kind = ""
    return {
        "criterion_id": criterion["criterion_id"],
        "description": criterion["description"],
        "hypothesis_id": criterion["hypothesis_id"],
        "required": criterion["required"],
        "status": status,
        "required_artifact_refs": list(criterion["required_artifact_refs"]),
        "observed_artifact_refs": observed_artifacts,
        "missing_artifact_refs": missing_artifacts,
        "decision_state": (
            str(result.get("decision_state") or "missing")
            if isinstance(result, Mapping)
            else "missing"
        ),
        "terminal_outcome": str(decision.get("outcome") or ""),
        "terminal_reason": str(decision.get("reason") or ""),
        "review_state": str(review.get("state") or "not_applicable"),
        "review_verdict": str(review.get("verdict") or ""),
        "failure_kind": failure_kind,
        "measurement_scope": (
            str(evidence_node.get("measurement_scope") or "")
            if isinstance(evidence_node, Mapping)
            else ""
        ),
        "observed_contract_revisions": observed_revisions,
    }


def _receipt_status(
    criteria: Sequence[Mapping[str, Any]],
    *,
    missing_required_artifacts: Sequence[str],
    contract_state: str,
) -> str:
    required = [item for item in criteria if item.get("required") is True]
    statuses = {str(item.get("status") or "") for item in required}
    if contract_state == "stale" or "stale" in statuses:
        return "stale"
    if contract_state != "current":
        return "inconclusive"
    if "not_fulfilled" in statuses:
        return "not_fulfilled"
    if required and statuses == {"verified"} and not missing_required_artifacts:
        return "verified"
    if "verified" in statuses or "partial" in statuses:
        return "partial"
    return "inconclusive"


def _failure_feedback(
    *,
    status: str,
    contract_state: str,
    criteria: Sequence[Mapping[str, Any]],
    missing_required_artifacts: Sequence[str],
    fallback_artifact_refs: Sequence[str],
    reentry_conditions: Sequence[str],
    observed_artifact_refs: Sequence[str],
) -> dict[str, Any] | None:
    if status == "verified":
        return None
    failed = [
        item
        for item in criteria
        if item.get("required") is True and item.get("status") != "verified"
    ]
    verified = [
        item
        for item in criteria
        if item.get("status") == "verified"
    ]
    fallbacks = sorted(set(fallback_artifact_refs) & set(observed_artifact_refs))
    derived_reentry = [
        f"resolve:{item['criterion_id']}:{item['failure_kind']}"
        for item in failed
    ]
    failure_kinds = {
        str(item.get("failure_kind") or "")
        for item in failed
        if item.get("failure_kind")
    }
    if contract_state == "missing":
        failure_kinds.add("contract_record_missing")
        derived_reentry.insert(0, "record_current_delivery_contract")
    if missing_required_artifacts:
        failure_kinds.add("required_artifact_missing")
        derived_reentry.extend(
            f"provide:{artifact_ref}"
            for artifact_ref in missing_required_artifacts
        )
    summaries = {
        "stale": (
            "The delivery contract changed after the recorded research evidence; "
            "rerun the affected criteria against the current contract."
        ),
        "not_fulfilled": (
            "The current evidence supports a terminal conclusion that at least "
            "one required criterion cannot be fulfilled under this contract."
        ),
        "partial": (
            "Some required criteria or artifacts are verified, but the complete "
            "delivery contract is not satisfied."
        ),
        "inconclusive": (
            "The available evidence is insufficient for a verified or terminal "
            "not-fulfilled conclusion."
        ),
    }
    return {
        "summary": summaries[status],
        "failure_kinds": sorted(failure_kinds),
        "unmet_criteria": [str(item["criterion_id"]) for item in failed],
        "verified_boundary": [str(item["criterion_id"]) for item in verified],
        "missing_required_artifact_refs": list(missing_required_artifacts),
        "fallback_artifact_refs": fallbacks,
        "reentry_conditions": list(
            dict.fromkeys([*reentry_conditions, *derived_reentry])
        ),
    }


def build_auto_research_artifact_receipt(
    *,
    delivery_contract: Mapping[str, Any],
    rollout_events: Sequence[Mapping[str, Any]],
    registered_agent_ids: Sequence[str],
) -> dict[str, Any]:
    contract = normalize_auto_research_delivery_contract(delivery_contract)
    research_contract = contract["research_contract"]
    contract_events = _contract_events(
        rollout_events,
        wish_id=contract["wish"]["wish_id"],
    )
    latest_revision = (
        str(_details(contract_events[-1]).get("contract_revision") or "")
        if contract_events
        else ""
    )
    contract_state = (
        "current"
        if latest_revision == contract["contract_revision"]
        else "stale"
        if latest_revision
        else "missing"
    )
    current_research_events = [
        event
        for event in rollout_events
        if str(event.get("event_kind") or "")
        not in {"research_hypothesis", "research_evidence"}
        or str(_details(event).get("contract_revision") or "")
        == contract["contract_revision"]
    ]
    evidence_graph = build_research_evidence_graph_from_rollout_events(
        goal_id=research_contract["goal_id"],
        rollout_events=[dict(event) for event in current_research_events],
    )
    query = build_terminal_result_query(
        evidence_graph=evidence_graph,
        rollout_events=rollout_events,
        registered_agent_ids=registered_agent_ids,
        include_history=True,
    )
    results = {
        str(item.get("hypothesis_id") or ""): item
        for item in query["results"]
    }
    evidence_nodes = {
        str(item.get("hypothesis_id") or ""): item
        for item in evidence_graph.get("nodes") or []
        if isinstance(item, Mapping)
    }
    criteria = [
        _criterion_result(
            criterion,
            result=results.get(criterion["hypothesis_id"]),
            evidence_node=evidence_nodes.get(criterion["hypothesis_id"]),
            lineage_events=_lineage_events(
                rollout_events,
                hypothesis_id=criterion["hypothesis_id"],
            ),
            contract_revision=contract["contract_revision"],
        )
        for criterion in contract["acceptance_criteria"]
    ]
    observed_artifact_refs = sorted(
        {
            ref
            for criterion in criteria
            for ref in criterion["observed_artifact_refs"]
        }
    )
    missing_required_artifacts = sorted(
        {
            artifact["artifact_ref"]
            for artifact in contract["required_artifacts"]
            if artifact["required"]
        }
        - set(observed_artifact_refs)
    )
    status = _receipt_status(
        criteria,
        missing_required_artifacts=missing_required_artifacts,
        contract_state=contract_state,
    )
    return {
        "ok": True,
        "schema_version": AUTO_RESEARCH_ARTIFACT_RECEIPT_SCHEMA_VERSION,
        "goal_id": research_contract["goal_id"],
        "wish": contract["wish"],
        "contract": {
            "contract_ref": contract["contract_ref"],
            "contract_revision": contract["contract_revision"],
            "latest_recorded_revision": latest_revision or None,
            "state": contract_state,
        },
        "status": status,
        "artifacts": {
            "required": contract["required_artifacts"],
            "observed_refs": observed_artifact_refs,
            "missing_required_refs": missing_required_artifacts,
        },
        "acceptance_results": criteria,
        "verification_summary": {
            "required_count": len(
                [item for item in criteria if item["required"]]
            ),
            "verified_count": len(
                [item for item in criteria if item["status"] == "verified"]
            ),
            "not_fulfilled_count": len(
                [item for item in criteria if item["status"] == "not_fulfilled"]
            ),
            "independent_review_required": any(
                item["requires_independent_review"]
                for item in contract["acceptance_criteria"]
            ),
            "evidence_graph_revision": query["evidence_graph_revision"],
        },
        "failure_feedback": _failure_feedback(
            status=status,
            contract_state=contract_state,
            criteria=criteria,
            missing_required_artifacts=missing_required_artifacts,
            fallback_artifact_refs=contract["failure_policy"][
                "fallback_artifact_refs"
            ],
            reentry_conditions=contract["failure_policy"]["reentry_conditions"],
            observed_artifact_refs=observed_artifact_refs,
        ),
        "learning_disposition": (
            "candidate"
            if status in {"verified", "not_fulfilled"}
            else "none"
        ),
        "boundary": {
            "raw_logs_recorded": False,
            "private_artifacts_recorded": False,
            "absolute_paths_recorded": False,
            "user_acceptance_inferred": False,
            "automatic_skill_promotion": False,
        },
    }


def load_auto_research_artifact_receipt(
    *,
    contract_path: str | Path,
    registry_path: Path,
    runtime_root_arg: str | None,
) -> dict[str, Any]:
    raw_contract = json.loads(
        Path(contract_path).expanduser().read_text(encoding="utf-8")
    )
    if not isinstance(raw_contract, Mapping):
        raise ValueError("delivery contract file must contain a JSON object")
    contract = normalize_auto_research_delivery_contract(raw_contract)
    goal_id = contract["research_contract"]["goal_id"]
    registry = load_registry(registry_path)
    runtime_root = resolve_runtime_root(registry, runtime_root_arg)
    events = load_rollout_events(rollout_event_log_path(runtime_root, goal_id))
    return build_auto_research_artifact_receipt(
        delivery_contract=contract,
        rollout_events=events,
        registered_agent_ids=registered_agent_ids_from_registry(
            registry_path,
            goal_id,
        ),
    )
