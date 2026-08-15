from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from loopx.control_plane.runtime.stride_observation import (
    STRIDE_EVALUATION_SCHEMA_VERSION,
    STRIDE_OBSERVATION_SCHEMA_VERSION,
    build_stride_observation,
    evaluate_stride_observation,
)

GOAL_ID = "fixture-stride-goal"
AGENT_ID = "codex-side-bypass"


def _write_run_index(
    runtime_root: Path,
    rows: list[dict],
) -> None:
    index_path = (
        runtime_root / "goals" / GOAL_ID / "runs" / "index.jsonl"
    )
    index_path.parent.mkdir(parents=True)
    index_path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )


def _run(
    *,
    classification: str,
    outcome: str,
    minutes_ago: int,
) -> dict:
    generated_at = (
        datetime.now(UTC) - timedelta(minutes=minutes_ago)
    ).isoformat()
    return {
        "generated_at": generated_at,
        "goal_id": GOAL_ID,
        "agent_id": AGENT_ID,
        "classification": classification,
        "delivery_outcome": outcome,
    }


def test_empty_runtime_is_fail_closed_observation(tmp_path: Path) -> None:
    observation = build_stride_observation(
        tmp_path,
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
    )

    assert observation["schema_version"] == STRIDE_OBSERVATION_SCHEMA_VERSION
    assert observation["lineage"]["source_run_count"] == 0
    assert observation["effect"]["unknown"] is True
    assert observation["shadow_only"] is True
    assert observation["delivery"]["evidence_fresh"] is False
    assert observation["authority"]["segment_disposition"] == "unknown"


def test_derives_delivery_and_authority_from_run_receipts(
    tmp_path: Path,
) -> None:
    _write_run_index(
        tmp_path,
        [
            _run(
                classification="bounded_replan_progress",
                outcome="outcome_progress",
                minutes_ago=180,
            ),
            _run(
                classification="exact_head_review_delivered_3206",
                outcome="outcome_progress",
                minutes_ago=60,
            ),
            _run(
                classification="monitor_watch",
                outcome="surface_only",
                minutes_ago=1,
            ),
        ],
    )

    observation = build_stride_observation(
        tmp_path,
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
    )

    assert observation["lineage"]["source_run_count"] == 3
    assert observation["delivery"]["material_slices"] == 2
    assert observation["delivery"]["latest_outcome"] == "surface_only"
    assert observation["delivery"]["evidence_fresh"] is True
    assert observation["authority"]["bounded_slices_since_change"] == 2
    assert observation["effect"]["unknown"] is True
    assert observation["mismatch_signals"] == []


def test_stale_evidence_reports_settlement_lag_signal(tmp_path: Path) -> None:
    _write_run_index(
        tmp_path,
        [
            _run(
                classification="monitor_watch",
                outcome="surface_only",
                minutes_ago=12 * 60,
            )
        ],
    )

    observation = build_stride_observation(
        tmp_path,
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
    )

    assert observation["delivery"]["evidence_fresh"] is False
    assert observation["mismatch_signals"] == ["settlement_lag"]

    evaluation = evaluate_stride_observation(observation)
    assert evaluation["schema_version"] == STRIDE_EVALUATION_SCHEMA_VERSION
    assert evaluation["signals"] == ["settlement_lag"]
    assert evaluation["recommendations"] == []
    assert evaluation["shadow_only"] is True


def test_other_agent_runs_are_not_attributed(tmp_path: Path) -> None:
    _write_run_index(
        tmp_path,
        [
            {
                "generated_at": (
                    datetime.now(UTC) - timedelta(minutes=5)
                ).isoformat(),
                "goal_id": GOAL_ID,
                "agent_id": "codex-quality-qualification",
                "classification": "exact_head_review_delivered_3206",
                "delivery_outcome": "outcome_progress",
            }
        ],
    )

    observation = build_stride_observation(
        tmp_path,
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
    )

    assert observation["lineage"]["source_run_count"] == 0
