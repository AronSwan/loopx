from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from loopx.capabilities.external_research import cli


def _print_payload(payload, _format, _renderer):
    _print_payload.payload = payload


def test_discover_projects_connector_registry_as_inventory_only(
    tmp_path: Path, monkeypatch
) -> None:
    registry_path = tmp_path / "connectors.json"
    registry_path.write_text(
        json.dumps(
            {
                "schema_version": "connector_registry_v1",
                "connectors": [
                    {
                        "id": "official-docs",
                        "name": "Official docs",
                        "layer": "L1",
                        "kind": "documentation",
                        "status": "supported",
                        "value_tier": "P1",
                    }
                ],
                "usage": {},
            }
        ),
        encoding="utf-8",
    )
    captured = {}

    def fake_runtime(method, params):
        captured["method"] = method
        captured["params"] = params
        return {
            "schema_version": "loopx_external_evidence_discovery_v0",
            "status": "inventory_only",
        }

    monkeypatch.setattr(cli, "effect_runtime_result", fake_runtime)
    args = argparse.Namespace(
        command="external-evidence",
        external_evidence_action="discover",
        provider_inventory_json=None,
        connector_registry=str(registry_path),
    )
    assert (
        cli.handle_external_evidence_command(
            args,
            output_format=lambda _args: "json",
            print_payload=_print_payload,
        )
        == 0
    )
    assert captured["method"] == "external_evidence.discover"
    connector = next(
        provider
        for provider in captured["params"]["providers"]
        if provider["provider_id"] == "connector:official-docs"
    )
    assert connector == {
        "provider_id": "connector:official-docs",
        "provider_kind": "connector",
        "protocol": "external_evidence_research_v0",
        "declared": True,
        "installed": False,
        "enabled": False,
        "ready": False,
        "unavailable_reason": "connector_registry_is_inventory_not_readiness",
    }


def test_plan_projects_registry_as_inventory_not_readiness(
    tmp_path: Path, monkeypatch
) -> None:
    provider_path = tmp_path / "providers.json"
    provider_path.write_text(
        json.dumps(
            {
                "providers": [
                    {
                        "provider_id": "host:external-research",
                        "provider_kind": "method",
                        "protocol": "external_evidence_research_v0",
                        "declared": True,
                        "installed": True,
                        "enabled": True,
                        "ready": True,
                        "unavailable_reason": None,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    registry_path = tmp_path / "connectors.json"
    registry_path.write_text(
        json.dumps(
            {
                "schema_version": "connector_registry_v1",
                "connectors": [
                    {
                        "id": "official-docs",
                        "name": "Official docs",
                        "layer": "L1",
                        "kind": "documentation",
                        "status": "supported",
                        "value_tier": "P1",
                    }
                ],
                "usage": {},
            }
        ),
        encoding="utf-8",
    )
    captured = {}

    def fake_runtime(method, params):
        captured["method"] = method
        captured["params"] = params
        return {"schema_version": "loopx_external_evidence_plan_v0", "status": "ready"}

    monkeypatch.setattr(cli, "effect_runtime_result", fake_runtime)
    args = argparse.Namespace(
        command="external-evidence",
        external_evidence_action="plan",
        objective="Inspect current behavior",
        user_activity="Choose a provider",
        decision="Whether to adopt",
        evidence_kind=["current_behavior"],
        constraint=[],
        provider_inventory_json=str(provider_path),
        connector_registry=str(registry_path),
        preferred_provider_id="host:external-research",
    )
    assert (
        cli.handle_external_evidence_command(
            args,
            output_format=lambda _args: "json",
            print_payload=_print_payload,
        )
        == 0
    )
    assert captured["method"] == "external_evidence.plan"
    providers = captured["params"]["providers"]
    connector = next(
        row for row in providers if row["provider_id"] == "connector:official-docs"
    )
    assert connector["ready"] is False
    assert (
        connector["unavailable_reason"]
        == "connector_registry_is_inventory_not_readiness"
    )


def test_admit_passes_parent_decision_to_typed_owner(
    tmp_path: Path, monkeypatch
) -> None:
    plan_path = tmp_path / "plan.json"
    receipt_path = tmp_path / "receipt.json"
    plan_path.write_text(
        json.dumps({"schema_version": "loopx_external_evidence_plan_v0"})
    )
    receipt_path.write_text(
        json.dumps({"schema_version": "loopx_external_evidence_receipt_v0"})
    )
    captured = {}

    def fake_runtime(method, params):
        captured["method"] = method
        captured["params"] = params
        return {
            "schema_version": "loopx_external_evidence_admission_v0",
            "disposition": "reject",
        }

    monkeypatch.setattr(cli, "effect_runtime_result", fake_runtime)
    args = argparse.Namespace(
        command="external-evidence",
        external_evidence_action="admit",
        plan_json=str(plan_path),
        receipt_json=str(receipt_path),
        decision="reject",
        reason="Insufficient direct evidence",
        admit_source=[],
    )
    assert (
        cli.handle_external_evidence_command(
            args,
            output_format=lambda _args: "json",
            print_payload=_print_payload,
        )
        == 0
    )
    assert captured["method"] == "external_evidence.admit"
    assert captured["params"]["decision"]["disposition"] == "reject"


def test_receipt_passes_observed_execution_to_typed_owner(
    tmp_path: Path, monkeypatch
) -> None:
    plan_path = tmp_path / "plan.json"
    receipt_path = tmp_path / "receipt.json"
    plan_path.write_text(
        json.dumps({"schema_version": "loopx_external_evidence_plan_v0"})
    )
    receipt_path.write_text(
        json.dumps({"schema_version": "loopx_external_evidence_receipt_v0"})
    )
    captured = {}

    def fake_runtime(method, params):
        captured["method"] = method
        captured["params"] = params
        return {
            "schema_version": "loopx_external_evidence_receipt_observation_v0",
            "status": "succeeded",
        }

    monkeypatch.setattr(cli, "effect_runtime_result", fake_runtime)
    args = argparse.Namespace(
        command="external-evidence",
        external_evidence_action="receipt",
        plan_json=str(plan_path),
        receipt_json=str(receipt_path),
    )
    assert (
        cli.handle_external_evidence_command(
            args,
            output_format=lambda _args: "json",
            print_payload=_print_payload,
        )
        == 0
    )
    assert captured["method"] == "external_evidence.receipt"
    assert (
        captured["params"]["plan"]["schema_version"]
        == "loopx_external_evidence_plan_v0"
    )


def test_source_cli_reaches_typescript_owner(tmp_path: Path) -> None:
    provider_path = tmp_path / "providers.json"
    provider_path.write_text(
        json.dumps(
            {
                "providers": [
                    {
                        "provider_id": "host:external-research",
                        "provider_kind": "method",
                        "protocol": "external_evidence_research_v0",
                        "declared": True,
                        "installed": True,
                        "enabled": True,
                        "ready": True,
                        "unavailable_reason": None,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "loopx.cli",
            "external-evidence",
            "plan",
            "--objective",
            "Inspect current behavior",
            "--user-activity",
            "Choose a provider",
            "--decision",
            "Whether to adopt",
            "--evidence-kind",
            "current_behavior",
            "--provider-inventory-json",
            str(provider_path),
            "--preferred-provider-id",
            "host:external-research",
            "--format",
            "json",
        ],
        cwd=Path(__file__).resolve().parents[2],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == "loopx_external_evidence_plan_v0"
    assert payload["status"] == "ready"
    assert payload["selected_provider"]["provider_id"] == "host:external-research"


def test_source_cli_discovers_inventory_without_claiming_readiness(
    tmp_path: Path,
) -> None:
    registry_path = tmp_path / "connectors.json"
    registry_path.write_text(
        json.dumps(
            {
                "schema_version": "connector_registry_v1",
                "connectors": [
                    {
                        "id": "official-docs",
                        "name": "Official docs",
                        "layer": "L1",
                        "kind": "documentation",
                        "status": "supported",
                        "value_tier": "P1",
                    }
                ],
                "usage": {},
            }
        ),
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "loopx.cli",
            "external-evidence",
            "discover",
            "--connector-registry",
            str(registry_path),
            "--format",
            "json",
        ],
        cwd=Path(__file__).resolve().parents[2],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == "loopx_external_evidence_discovery_v0"
    assert payload["status"] == "inventory_only"
    assert payload["summary"]["provider_count"] >= 1
    assert payload["summary"]["connector_count"] == payload["summary"]["provider_count"]
    assert payload["summary"]["ready_count"] == 0
    assert payload["truth_contract"]["execution_observed"] is False
