from __future__ import annotations

import json
from pathlib import Path

import pytest

from loopx.control_plane.work_items.work_lane import (
    lark_inbox_reply_due_work_lane_contract,
    operator_inbox_material_review_due_work_lane_contract,
    work_lane_contract_is_lark_inbox_reply_due,
    work_lane_contract_is_operator_inbox_material_review_due,
)
from loopx.extensions.external_connector_runtime import EFFECT_RECEIPT_SCHEMA_VERSION
from loopx.extensions.lark.event_inbox import (
    ingest_lark_event_inbox,
    inspect_lark_event_inbox,
    project_lark_event_inbox_urgency,
    settle_lark_event_inbox_material_review,
)


def _config(project: Path) -> Path:
    config = project / ".loopx" / "config" / "lark" / "event-inbox.json"
    config.parent.mkdir(parents=True)
    config.write_text(
        json.dumps(
            {
                "schema_version": "lark_event_inbox_config_v0",
                "enabled": True,
                "inbox_dir": ".loopx/inbox/lark/material-review",
                "capture_scope": "configured_chat_all",
                "reply": {
                    "enabled": True,
                    "sender_profile": "fixture-bot",
                    "sender_identity": "bot",
                    "bot_display_name": "Context Bot",
                    "chat_id": "oc_public_fixture",
                },
                "material_review": {"enabled": True, "drain_limit": 3},
            }
        ),
        encoding="utf-8",
    )
    return config


def _ingest(project: Path, config: Path) -> None:
    result = ingest_lark_event_inbox(
        project=project,
        config_path=config,
        events=[
            {
                "schema_version": "lark_event_inbox_event_v0",
                "event_id": "evt_material_text",
                "message_id": "om_material_text",
                "create_time": "2026-08-26T00:00:00Z",
                "content": "Iteration 42 is now planned.",
            },
            {
                "schema_version": "lark_event_inbox_event_v0",
                "event_id": "evt_material_attachment",
                "message_id": "om_material_attachment",
                "create_time": "2026-08-26T00:01:00Z",
                "content": "",
                "attachment_count": 1,
            },
            {
                "schema_version": "lark_event_inbox_event_v0",
                "event_id": "evt_direct",
                "message_id": "om_direct",
                "create_time": "2026-08-26T00:02:00Z",
                "content": "@Context Bot can you confirm?",
            },
        ],
        execute=True,
    )
    assert result["accepted_count"] == 3


def _boundary(urgency: dict[str, object]) -> dict[str, object]:
    return {
        "capabilities": {
            "lark_event_inbox": {
                "urgency": urgency,
                "drain_command": "loopx lark-inbox drain --goal-id fixture",
            }
        }
    }


def test_material_review_projection_is_separate_from_reply_due(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _ingest(tmp_path, config)

    urgency = project_lark_event_inbox_urgency(
        project=tmp_path,
        config_path=config,
    )

    assert urgency["pending_count"] == 3
    assert urgency["attention_required_count"] == 1
    assert urgency["reply_due"] is True
    assert urgency["material_review_count"] == 2
    assert urgency["material_attachment_count"] == 1
    assert urgency["material_review_due"] is True
    assert urgency["material_review_drain_limit"] == 3
    assert urgency["local_private_content_returned"] is False

    material = operator_inbox_material_review_due_work_lane_contract(
        _boundary(urgency),
        current_contract={"lane": "advancement_task"},
    )
    assert work_lane_contract_is_operator_inbox_material_review_due(material)
    assert material["drain_limit"] == 3
    assert str(material["drain_command"]).endswith("--limit 3")

    reply = lark_inbox_reply_due_work_lane_contract(
        _boundary(urgency),
        current_contract=material,
    )
    assert work_lane_contract_is_lark_inbox_reply_due(reply)
    assert reply["next_lane"] == "operator_inbox_material_review"


def test_material_review_no_follow_up_settlement_is_idempotent(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _ingest(tmp_path, config)

    preview = settle_lark_event_inbox_material_review(
        project=tmp_path,
        config_path=config,
        message_id="om_material_text",
        no_follow_up_reason="Informational context already captured.",
    )
    assert preview["ok"] is True
    assert preview["status"] == "preview_ready"
    assert preview["receipt_recorded"] is False
    assert preview["write_performed"] is False

    first = settle_lark_event_inbox_material_review(
        project=tmp_path,
        config_path=config,
        message_id="om_material_text",
        no_follow_up_reason="Informational context already captured.",
        execute=True,
    )
    replay = settle_lark_event_inbox_material_review(
        project=tmp_path,
        config_path=config,
        message_id="om_material_text",
        no_follow_up_reason="Informational context already captured.",
        execute=True,
    )

    assert first["status"] == "settled"
    assert first["effect_kind"] == "no_follow_up"
    assert first["receipt_recorded"] is True
    assert first["write_performed"] is True
    assert replay["status"] == "already_settled"
    assert replay["write_performed"] is False
    conflict = settle_lark_event_inbox_material_review(
        project=tmp_path,
        config_path=config,
        message_id="om_material_text",
        no_follow_up_reason="A conflicting replay rationale.",
        execute=True,
    )
    assert conflict["ok"] is False
    assert conflict["status"] == "material_review_receipt_conflict"
    assert inspect_lark_event_inbox(
        project=tmp_path,
        config_path=config,
    )["pending_count"] == 2


def test_material_review_requires_event_bound_effect_and_rejects_reply_items(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    _ingest(tmp_path, config)
    mismatched = {
        "schema_version": EFFECT_RECEIPT_SCHEMA_VERSION,
        "event_id": "evt_other",
        "effect_id": "todo-update-fixture",
        "effect_kind": "todo_update",
        "status": "committed",
    }
    rejected = settle_lark_event_inbox_material_review(
        project=tmp_path,
        config_path=config,
        message_id="om_material_attachment",
        effect_receipt=mismatched,
        execute=True,
    )
    assert rejected["ok"] is False
    assert rejected["status"] == "durable_effect_required"
    assert rejected["write_performed"] is False

    committed = {**mismatched, "event_id": "evt_material_attachment"}
    settled = settle_lark_event_inbox_material_review(
        project=tmp_path,
        config_path=config,
        message_id="om_material_attachment",
        effect_receipt=committed,
        execute=True,
    )
    assert settled["ok"] is True
    assert settled["effect_kind"] == "todo_update"

    with pytest.raises(ValueError, match="reply_due"):
        settle_lark_event_inbox_material_review(
            project=tmp_path,
            config_path=config,
            message_id="om_direct",
            no_follow_up_reason="Not a material review item.",
        )
