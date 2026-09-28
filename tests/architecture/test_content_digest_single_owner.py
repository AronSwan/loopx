"""One owner decides what a stored SHA-256 looks like, and this keeps it that way.

Three halves, none of which substitutes for the others:

* a **scan** that fails when any module states a whole-value digest shape itself. It
  unions two detectors, because `re.fullmatch(r"[0-9a-f]{64}", value)` states exactly
  the same decision as `^...$` while carrying no anchors at all, and an anchored-text
  search alone would be blind to it;
* an **identity** check that every consumer holds the owner object rather than a copy;
* **per-surface cases** that enter through each surface's own reader, which is the only
  half that can notice a surface wired to the wrong envelope.

Only whole-value shapes are owned. A hex digest inside a larger grammar (a `cadence_…`
id, a journal filename, a `40|64` Git object id, a compound cursor) answers that
grammar's question and stays with its surface, and producers that concatenate
`"sha256:"` by hand are a separate decision.
"""

from __future__ import annotations

import ast
import importlib
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

# Recorded instead of absorbed, each with a reason that stands on the field contract
# rather than on which other pull request happens to be open. An entry that stops being
# true fails the test below instead of ageing quietly.
DEFERRED_WHOLE_VALUE_SITES: dict[str, str] = {
    "loopx/capabilities/manager_context/inspection.py": (
        "published as a JSON-schema `pattern` string, so it is schema data handed to a "
        "validator rather than a matcher this owner may replace; pinned verdict for "
        "verdict to the owner instead"
    ),
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
    f"sha256:{HEX64[:-1]}",
)


def _whole_value_shape(text: Any) -> str | None:
    """Classify a literal as a whole-value digest shape, ignoring how it is anchored.

    Anchoring is the call's business: `re.fullmatch` gives whole-string semantics to an
    unanchored literal and `\\Z` is equivalent to `$`. Anything carrying extra grammar
    - a prefix, an alternation, a suffix - answers a different question and is skipped.
    """

    if not isinstance(text, str) or "{64}" not in text:
        return None
    body = text[1:] if text.startswith("^") else text
    for tail in ("$", "\\Z"):
        if body.endswith(tail):
            body = body[: -len(tail)]
            break
    enveloped = body.startswith("sha256:")
    remainder = body[len("sha256:") :] if enveloped else body
    for hex_class in HEX_CLASSES:
        if remainder == f"{hex_class}{{64}}":
            return "enveloped" if enveloped else "bare"
    return None


def _module_sites(path: Path) -> list[tuple[int, str, str]]:
    """Every whole-value digest literal this module states, and how it became one."""

    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: dict[int, tuple[str, str]] = {}

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        attribute = getattr(node.func, "attr", None)
        receiver = getattr(getattr(node.func, "value", None), "id", None)
        first = node.args[0]
        if attribute not in {"compile", "fullmatch"}:
            continue
        if not isinstance(first, ast.Constant) or not isinstance(first.value, str):
            continue
        shape = _whole_value_shape(first.value)
        if shape is None:
            continue
        if attribute == "compile":
            anchored = first.value.startswith("^") and first.value.endswith(("$", "\\Z"))
            if anchored:
                found[first.lineno] = (first.value, "compiled whole-value pattern")
        elif receiver == "re":
            found[first.lineno] = (first.value, "re.fullmatch literal")

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and _whole_value_shape(node.value)
            and node.value.startswith("^")
            and node.value.endswith("$")
        ):
            found.setdefault(node.lineno, (node.value, "anchored literal"))

    return sorted((line, literal, how) for line, (literal, how) in found.items())


def _scan_modules() -> list[Path]:
    return sorted(
        path
        for path in PACKAGE_ROOT.rglob("*.py")
        if "__pycache__" not in path.parts
    )


def _relative(path: Path) -> str:
    return f"loopx/{path.relative_to(PACKAGE_ROOT).as_posix()}"


def _consumer_modules() -> list[str]:
    """Module names of every file that imports the owner - derived, not listed."""

    consumers = []
    for path in _scan_modules():
        source = path.read_text(encoding="utf-8")
        if "content_digest import" not in source:
            continue
        parts = list(path.relative_to(PACKAGE_ROOT.parent).parts)
        parts[-1] = parts[-1][: -len(".py")]
        consumers.append(".".join(parts))
    return sorted(consumers)


def test_only_the_owner_module_states_a_whole_value_digest_shape():
    offenders = {}
    for path in _scan_modules():
        relative = _relative(path)
        if relative in DEFERRED_WHOLE_VALUE_SITES or relative == OWNER_MODULE:
            continue
        sites = _module_sites(path)
        if sites:
            offenders[relative] = sites
    assert not offenders, f"second owner(s) of the digest shape: {offenders}"


def test_owner_module_defines_each_shape_exactly_once():
    sites = _module_sites(PACKAGE_ROOT / "control_plane" / "content_digest.py")
    shapes = [_whole_value_shape(literal) for _, literal, _ in sites]
    # Counted, not set-compared: a second literal of an already-exported shape would
    # leave the set unchanged and leave this branch's whole point unsaid.
    assert sorted(shapes) == ["bare", "enveloped"], sites
    assert len(sites) == 2, sites


def test_the_scan_reads_usage_not_only_anchor_text(tmp_path: Path) -> None:
    """A `re.fullmatch` copy with no anchors at all must still be a violation.

    Without this case the scan cannot be told apart from a plain literal search, which
    is precisely how several production sites were written before this branch.
    """

    sample = tmp_path / "loopx" / "restated.py"
    sample.parent.mkdir(parents=True)
    sample.write_text(
        "import re\n\n\ndef check(value):\n"
        '    return re.fullmatch(r"[0-9a-f]{64}", value)\n',
        encoding="utf-8",
    )
    assert _module_sites(sample), "an unanchored whole-value restatement escaped the scan"

    grammar = tmp_path / "loopx" / "grammar.py"
    grammar.write_text(
        "import re\n\n\nPATTERN = re.compile(r\"cadence_[0-9a-f]{64}\")\n",
        encoding="utf-8",
    )
    assert not _module_sites(grammar), "a compound id must not be pulled into the owner"


def test_deferred_sites_are_still_the_ones_this_branch_recorded():
    for relative, reason in DEFERRED_WHOLE_VALUE_SITES.items():
        assert reason, relative
        path = PACKAGE_ROOT.parent / relative
        assert path.is_file(), f"{relative} moved or vanished; update the allowlist"
        assert _module_sites(path), f"{relative} no longer restates the shape"


def test_every_consumer_holds_the_owner_object_not_an_equal_copy():
    imported = 0
    for module_name in _consumer_modules():
        module = importlib.import_module(module_name)
        owned = [
            name
            for name in ("BARE_SHA256_PATTERN", "ENVELOPED_SHA256_PATTERN")
            if name in vars(module)
        ]
        assert owned, f"{module_name} imports neither owner name"
        for attribute in owned:
            assert getattr(module, attribute) is getattr(content_digest, attribute), (
                f"{module_name}.{attribute} is a second definition"
            )
        imported += 1
    assert imported >= 40, f"expected the migrated surfaces to be imported, saw {imported}"


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


@pytest.mark.parametrize(
    "value", [HEX64, MIXED_HEX64, "A" * 64, "a" * 63, "g" * 64, HEX64 + " "]
)
def test_the_two_retired_bare_spellings_could_never_disagree(value: str) -> None:
    """Merging `[a-f0-9]` into `[0-9a-f]` cannot change a verdict.

    The character class lists the same six letters and ten digits in a different order,
    so both copies accepted and rejected the same strings; this is the evidence that
    collapsing them is not a behaviour change.
    """

    first = re.compile(r"^[a-f0-9]{64}$")
    second = re.compile(r"^[0-9a-f]{64}$")
    assert bool(first.fullmatch(value)) == bool(second.fullmatch(value))
    assert bool(second.fullmatch(value)) == bool(BARE_SHA256_PATTERN.fullmatch(value))


@pytest.mark.parametrize("value", [HEX64, ENVELOPED, "A" * 64, HEX64 + "0"])
def test_the_dropped_unicode_anchor_variant_agrees_with_the_owner(value: str) -> None:
    r"""Sites written `...\Z` are collapsed into `$` without changing a verdict."""

    with_backslash = re.compile(r"^[0-9a-f]{64}\Z")
    assert bool(with_backslash.fullmatch(value)) is bool(
        BARE_SHA256_PATTERN.fullmatch(value)
    ), value


def test_schema_string_site_is_the_same_question_as_the_owner_bare_shape() -> None:
    from loopx.capabilities.manager_context import inspection

    sites = _module_sites(Path(inspection.__file__))
    assert sites, "the recorded schema site no longer states the shape"
    for _, text, _ in sites:
        assert _whole_value_shape(text) == "bare"
        declared = re.compile(text)
        for value in (*BARE_ACCEPTS, *BARE_REJECTS):
            assert bool(declared.fullmatch(value)) is bool(
                BARE_SHA256_PATTERN.fullmatch(value)
            ), value


# --- per-surface wiring: every case enters through that surface's own reader ------


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
    # This surface also caps the field at 64 characters, so an enveloped digest never
    # reaches the shape check here. That limit is the surface's own policy and is left
    # alone; it is why the rejected probe above is same-length.
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
    assert normalize_progress_review_contract_revision(HEX64) == HEX64  # positive control
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


