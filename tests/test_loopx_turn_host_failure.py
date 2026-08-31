from __future__ import annotations

import pytest

from loopx.control_plane.turn_driver.host_failure import (
    build_host_failure_record,
    host_failure_retry_available,
    normalize_host_failure_record,
    project_host_failure,
)


def test_provider_capacity_uses_bounded_exponential_backoff() -> None:
    first = build_host_failure_record("provider_capacity", attempt=1)
    second = build_host_failure_record("provider_capacity", attempt=2)
    exhausted = build_host_failure_record("provider_capacity", attempt=3)

    assert first["retry"] == {
        "strategy": "same_configuration",
        "max_attempts": 3,
        "backoff_seconds": 30,
    }
    assert second["retry"]["backoff_seconds"] == 60
    assert host_failure_retry_available(first) is True
    assert host_failure_retry_available(exhausted) is False


def test_host_failure_record_rejects_caller_authored_retry_policy() -> None:
    forged = build_host_failure_record("provider_capacity", attempt=1)
    forged["retry"]["max_attempts"] = 99

    with pytest.raises(ValueError, match="invalid retry policy"):
        normalize_host_failure_record(forged)


def test_non_retryable_failure_has_no_automatic_retry_policy() -> None:
    failure = build_host_failure_record("auth_failed", attempt=1)

    assert failure == {
        "schema_version": "loopx_turn_host_failure_v0",
        "kind": "auth_failed",
        "attempt": 1,
        "retryable": False,
    }
    assert host_failure_retry_available(failure) is False


def test_public_projection_rejects_unallowlisted_failure_fields() -> None:
    failure = build_host_failure_record("provider_capacity", attempt=1)
    failure["provider_message"] = "private provider prose"

    with pytest.raises(ValueError, match="unsupported fields"):
        project_host_failure({"host_failure": failure})
