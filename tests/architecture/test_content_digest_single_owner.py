"""One owner decides what a stored SHA-256 looks like, and this keeps it that way.

Two halves, both required. The source scan catches a module that restates a
whole-value digest shape as its own literal even when the verdict is identical,
so an equal-by-accident copy still fails. The per-site cases catch a surface
wired to the wrong envelope. Neither half implies the other.

Only whole-value shapes are owned here. A hex digest embedded in a larger
grammar (a ``cadence_…`` id, a journal filename, a ``40|64`` Git object id, a
compound cursor) answers that grammar's question and stays with its surface, and
producers that concatenate ``"sha256:"`` by hand are a separate decision.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

import pytest

from loopx.control_plane import content_digest
from loopx.control_plane.content_digest import (
    BARE_SHA256_PATTERN,
    ENVELOPED_SHA256_PATTERN,
)

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "loopx"
OWNER_MODULE = "loopx/control_plane/content_digest.py"
HEX_CLASSES = ("[0-9a-f]", "[a-f0-9]")

# Restatements this branch records instead of absorbing, each with the reason the
# reviewer needs. A new entry has to earn its place; an entry that stops being
# true fails the test below rather than ageing quietly.
DEFERRED_WHOLE_VALUE_SITES = {
    "loopx/capabilities/content_ops/item_lifecycle.py": (
        "open PR #3313 is editing this file; migrating it here would collide, so "
        "the copy stays until that PR lands"
    ),
    "loopx/capabilities/manager_context/inspection.py": (
        "the shape is a JSON-schema `pattern` string consumed by a schema "
        "validator, not a compiled Python pattern; pinned equal to the owner below"
    ),
}

# Every module that now reads the owner instead of deciding for itself.
MIGRATED_SITE_MODULES: dict[str, tuple[str, ...]] = {
    "loopx.capabilities.benchmark_toolkit.behavior_finding": ("BARE_SHA256_PATTERN",),
    "loopx.capabilities.benchmark_toolkit.study_projection": ("BARE_SHA256_PATTERN",),
    "loopx.capabilities.periodic_report.archive": ("ENVELOPED_SHA256_PATTERN",),
    "loopx.capabilities.periodic_report.incremental": ("ENVELOPED_SHA256_PATTERN",),
    "loopx.capabilities.periodic_report.machine_defaults": (
        "ENVELOPED_SHA256_PATTERN",
    ),
    "loopx.capabilities.progress_review.receipt": ("BARE_SHA256_PATTERN",),
    "loopx.chat_action_normalization": ("BARE_SHA256_PATTERN",),
    "loopx.configuration_transaction": ("ENVELOPED_SHA256_PATTERN",),
    "loopx.control_plane.coordination.local_authority_shadow_outbox": (
        "ENVELOPED_SHA256_PATTERN",
    ),
    "loopx.control_plane.goals.activation_service": ("BARE_SHA256_PATTERN",),
    "loopx.control_plane.goals.deletion_service": ("BARE_SHA256_PATTERN",),
    "loopx.control_plane.goals.goal_amendment_proposal": ("ENVELOPED_SHA256_PATTERN",),
    "loopx.control_plane.projects.registry_codec": ("ENVELOPED_SHA256_PATTERN",),
    "loopx.control_plane.testing.release_commit_qualification": (
        "ENVELOPED_SHA256_PATTERN",
    ),
    "loopx.control_plane.work_items.governed_transition_proposal": (
        "ENVELOPED_SHA256_PATTERN",
    ),
    "loopx.control_plane.work_items.progress_review_policy": ("BARE_SHA256_PATTERN",),
    "loopx.extensions.openviking_semantic_preference.history_export": (
        "BARE_SHA256_PATTERN",
    ),
    "loopx.extensions.presentation": ("BARE_SHA256_PATTERN",),
}

HEX64 = "a" * 64
MIXED_HEX64 = "0123456789abcdef" * 4
ENVELOPED = f"sha256:{HEX64}"

ENVELOPED_ACCEPTS = (ENVELOPED, f"sha256:{MIXED_HEX64}")
ENVELOPED_REJECTS = (
    HEX64,  # the envelope is part of the stored shape
    f"sha256:{HEX64[:-1]}",
    f"sha256:{HEX64}0",
    f"sha256:{HEX64.upper()}",
    f"sha256:{'z' * 64}",
    f"prefix-sha256:{HEX64}",
    f"sha256:{HEX64} trailing",
    "",
)
BARE_ACCEPTS = (HEX64, MIXED_HEX64, "f" * 64)
BARE_REJECTS = (
    ENVELOPED,
    HEX64[:-1],
    f"{HEX64}0",
    HEX64.upper(),
    "z" * 64,
    f"x{HEX64}",
    f"{HEX64} ",
    "",
    "sha256:" + HEX64[:-1],
)


def _regex_literals(module_path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if _whole_value_digest_shape(node.value) is not None:
                found.append((node.lineno, node.value))
    return found


def _whole_value_digest_shape(text: str) -> str | None:
    """Return the envelope for `^`[sha256:]<hex class>`{64}`$`, else None.

    Exact on purpose: a literal with anything else in it is a different question
    and belongs to the grammar that wrote it.
    """

    if not (text.startswith("^") and text.endswith("$") and text.endswith("{64}$")):
        return None
    body = text[1:-1]
    enveloped = body.startswith("sha256:")
    remainder = body[len("sha256:") :] if enveloped else body
    for hex_class in HEX_CLASSES:
        if remainder == f"{hex_class}{{64}}":
            return "enveloped" if enveloped else "bare"
    return None


def _whole_value_sites() -> dict[str, list[tuple[int, str]]]:
    sites: dict[str, list[tuple[int, str]]] = {}
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        relative = f"loopx/{path.relative_to(PACKAGE_ROOT).as_posix()}"
        literals = _regex_literals(path)
        if literals:
            sites[relative] = literals
    return sites


def test_only_the_owner_module_states_a_whole_value_digest_shape():
    unexpected = {
        relative: literals
        for relative, literals in _whole_value_sites().items()
        if relative not in DEFERRED_WHOLE_VALUE_SITES and relative != OWNER_MODULE
    }
    assert not unexpected, f"second owner(s) of the digest shape: {unexpected}"


def test_owner_module_defines_each_shape_exactly_once():
    literals = _regex_literals(PACKAGE_ROOT / "control_plane" / "content_digest.py")
    shapes = [_whole_value_digest_shape(text) for _, text in literals]
    # Counted, not set-compared: a second literal of a shape already exported here
    # would leave the set unchanged and this branch's whole point unsaid.
    assert sorted(shapes) == ["bare", "enveloped"], literals
    assert len(literals) == 2, literals


def test_deferred_sites_are_still_the_ones_this_branch_recorded():
    for relative, reason in DEFERRED_WHOLE_VALUE_SITES.items():
        assert isinstance(reason, str) and reason, relative
        path = Path(__file__).resolve().parents[2] / relative
        assert path.is_file(), f"{relative} moved or vanished; update the allowlist"
        assert _regex_literals(path), f"{relative} no longer restates the shape"


def test_migrated_modules_hold_the_owner_object_not_an_equal_copy():
    import importlib

    for module_name, owned in MIGRATED_SITE_MODULES.items():
        module = importlib.import_module(module_name)
        for attribute in owned:
            assert getattr(module, attribute) is getattr(content_digest, attribute), (
                f"{module_name}.{attribute} is a second definition"
            )


@pytest.mark.parametrize("value", ENVELOPED_ACCEPTS)
def test_enveloped_pattern_accepts_a_prefixed_digest(value: str) -> None:
    assert ENVELOPED_SHA256_PATTERN.fullmatch(value) is not None


@pytest.mark.parametrize("value", ENVELOPED_REJECTS)
def test_enveloped_pattern_rejects_every_other_shape(value: object) -> None:
    assert ENVELOPED_SHA256_PATTERN.fullmatch(value) is None


@pytest.mark.parametrize("value", BARE_ACCEPTS)
def test_bare_pattern_accepts_lowercase_hex(value: str) -> None:
    assert BARE_SHA256_PATTERN.fullmatch(value) is not None


@pytest.mark.parametrize("value", BARE_REJECTS)
def test_bare_pattern_rejects_everything_else(value: object) -> None:
    assert BARE_SHA256_PATTERN.fullmatch(value) is None


@pytest.mark.parametrize("value", [HEX64, MIXED_HEX64, "A" * 64, "a" * 63, "g" * 64])
def test_the_two_retired_bare_spellings_could_never_disagree(value: str) -> None:
    """Merging `[a-f0-9]` into `[0-9a-f]` cannot change a verdict.

    The character class lists the same six letters and digits in a different
    order, so both copies accepted and rejected the same strings. This is the
    evidence that collapsing them is not a behaviour change.
    """

    first = re.compile(r"^[a-f0-9]{64}$")
    second = re.compile(r"^[0-9a-f]{64}$")
    assert bool(first.fullmatch(value)) == bool(second.fullmatch(value))
    assert bool(second.fullmatch(value)) == bool(BARE_SHA256_PATTERN.fullmatch(value))


def test_schema_string_site_is_the_same_question_as_the_owner_bare_shape() -> None:
    """`inspection.py` carries the shape as a JSON-schema string, not a pattern.

    It is deliberately not an f-string of the owner: the schema is data published
    to callers. This asserts it still describes the bare hex64 envelope, so the
    two cannot drift into different verdicts unnoticed.
    """

    from loopx.capabilities.manager_context import inspection

    literals = _regex_literals(Path(inspection.__file__))
    assert literals, "the recorded schema site no longer states the shape"
    for _, text in literals:
        assert _whole_value_digest_shape(text) == "bare"
        declared = re.compile(text)
        for value in (*BARE_ACCEPTS, *BARE_REJECTS):
            assert bool(declared.fullmatch(value)) is bool(
                BARE_SHA256_PATTERN.fullmatch(value)
            ), value


# --- per-site wiring: every migrated surface is entered through its own reader --


def test_periodic_report_archive_requires_the_envelope() -> None:
    from loopx.capabilities.periodic_report import archive

    assert archive._sha256(ENVELOPED, "revision") == ENVELOPED
    with pytest.raises(ValueError, match="must use sha256"):
        archive._sha256(HEX64, "revision")


def test_periodic_report_incremental_requires_the_envelope() -> None:
    from loopx.capabilities.periodic_report import incremental

    assert incremental._digest(ENVELOPED, "fact_fingerprint") == ENVELOPED
    with pytest.raises(ValueError, match="must use sha256"):
        incremental._digest(HEX64, "fact_fingerprint")


def test_progress_review_receipt_rejects_the_envelope_it_never_stored() -> None:
    from loopx.capabilities.progress_review import receipt

    assert receipt._hex64(HEX64, field="basis_digest") == HEX64
    with pytest.raises(ValueError, match="must be a sha256 hex digest"):
        receipt._hex64(ENVELOPED, field="basis_digest")


def test_presentation_extension_keeps_its_own_message_and_bare_shape() -> None:
    from loopx.extensions import presentation

    assert presentation._sha256(HEX64, context="artifact") == HEX64
    with pytest.raises(ValueError, match="must be a lowercase SHA-256"):
        presentation._sha256("z" * 64, context="artifact")
    # This surface also caps the field at 64 characters, so an enveloped digest
    # never reaches the shape check here. That limit is the surface's own policy
    # and is left alone; it is why the rejected probe above is same-length.
    with pytest.raises(ValueError, match="at most 64 characters"):
        presentation._sha256(ENVELOPED, context="artifact")


def test_release_commit_qualification_normalises_before_the_owner_check() -> None:
    from loopx.control_plane.testing import release_commit_qualification

    assert release_commit_qualification._digest(ENVELOPED, field="commit") == ENVELOPED
    with pytest.raises(ValueError, match="must be a sha256 digest"):
        release_commit_qualification._digest(HEX64, field="commit")


def test_configuration_revision_allows_the_absent_sentinel() -> None:
    from loopx.configuration_transaction import _validated_revision

    assert _validated_revision("absent", label="revision") == "absent"
    assert _validated_revision(ENVELOPED, label="revision") == ENVELOPED
    with pytest.raises(ValueError, match="must be absent or a sha256 revision"):
        _validated_revision(HEX64, label="revision")


def test_progress_review_policy_keeps_clearing_and_null_as_distinct_values() -> None:
    from loopx.control_plane.work_items.progress_review_policy import (
        normalize_progress_review_contract_revision,
    )

    assert normalize_progress_review_contract_revision(None) is None
    assert normalize_progress_review_contract_revision("") == ""
    assert (
        normalize_progress_review_contract_revision(HEX64) == HEX64
    )  # positive control
    with pytest.raises(ValueError, match="must be a sha256 hex digest"):
        normalize_progress_review_contract_revision(ENVELOPED)


def test_deletion_source_basis_checks_both_digest_fields() -> None:
    from loopx.control_plane.goals.deletion_service import (
        GOAL_DELETION_SOURCE_BASIS_SCHEMA_VERSION,
        _normalize_source_basis,
    )

    basis: dict[str, Any] = {
        "schema_version": GOAL_DELETION_SOURCE_BASIS_SCHEMA_VERSION,
        "source_identity": HEX64,
        "source_content_sha256": MIXED_HEX64,
        "route_mode": "source_to_global",
    }
    assert _normalize_source_basis(basis)["source_content_sha256"] == MIXED_HEX64
    with pytest.raises(ValueError, match="source identity"):
        _normalize_source_basis({**basis, "source_identity": ENVELOPED})
    with pytest.raises(ValueError, match="content digest"):
        _normalize_source_basis({**basis, "source_content_sha256": HEX64.upper()})


def test_periodic_report_delivery_authority_checks_its_effective_revision() -> None:
    from loopx.capabilities.periodic_report.machine_defaults import (
        DELIVERY_AUTHORITY_SCHEMA,
        normalize_periodic_report_delivery_authority,
    )

    authority = {
        "schema_version": DELIVERY_AUTHORITY_SCHEMA,
        "kind": "enabled_periodic_report_subscription",
        "goal_id": "goal-1",
        "source": "machine_default",
        "effective_revision": ENVELOPED,
        "route_ref": "route-1",
    }
    assert (
        normalize_periodic_report_delivery_authority(authority)["effective_revision"]
        == ENVELOPED
    )
    with pytest.raises(ValueError, match="effective_revision is invalid"):
        normalize_periodic_report_delivery_authority(
            {**authority, "effective_revision": HEX64}
        )


def test_governed_transition_receipt_checks_the_intent_basis_field_only() -> None:
    """`proposal_digest` is not checked by this shape, so the probe names the field.

    An earlier draft of this case passed a bare `proposal_digest` and concluded
    nothing; the migrated pattern guards the optional `intent_basis`.
    """

    from loopx.control_plane.work_items.governed_transition_proposal import (
        GOVERNED_TRANSITION_RECEIPT_SCHEMA_VERSION as RECEIPT_SCHEMA,
        validate_governed_transition_receipts,
    )

    receipt = {
        "schema_version": RECEIPT_SCHEMA,
        "kind": "continuous_monitor_upsert",
        "status": "committed",
        "proposal_id": "prop-1",
        "proposal_digest": ENVELOPED,
        "action": "upsert",
        "todo_id": "todo-1",
        "monitor_key": "monitor-1",
        "target_key": "target-1",
        "intent_basis": ENVELOPED,
    }
    assert (
        validate_governed_transition_receipts([receipt])[0]["intent_basis"] == ENVELOPED
    )
    with pytest.raises(ValueError, match="intent_basis is invalid"):
        validate_governed_transition_receipts([{**receipt, "intent_basis": HEX64}])


def test_shadow_outbox_cursor_keeps_its_envelope_and_its_absent_option() -> None:
    from loopx.control_plane.coordination.local_authority_shadow_outbox import (
        DRAIN_CURSOR_SCHEMA,
        OutboxError,
        decode_cursor,
    )
    from loopx.control_plane.coordination.local_authority_shadow_projection import (
        PARTITIONS,
    )

    def cursor(digest: object) -> dict[str, Any]:
        return {
            "schema_version": DRAIN_CURSOR_SCHEMA,
            "partition": PARTITIONS[0],
            "last_seq": 1,
            "last_entry_id": f"local-shadow-tx-{HEX64}",
            "last_partition_digest": digest,
            "last_cursor": "cursor-opaque",
            "last_provider_revision": "revision-opaque",
            "updated_at": "2026-09-28T00:00:00+00:00",
        }

    partition = PARTITIONS[0]
    assert decode_cursor(cursor(ENVELOPED), partition=partition)["last_seq"] == 1
    assert (
        decode_cursor(cursor(None), partition=partition) is not None
    )  # an unbound cursor is legal on this surface
    with pytest.raises(OutboxError, match="cursor binding"):
        decode_cursor(cursor(HEX64), partition=partition)
