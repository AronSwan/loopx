"""One corpus, every real public-safe text owner.

The rule that decides whether control-plane text looks private is enforced by
four owners: `loopx.feedback`, `loopx.authority`, `loopx.boundary_authority`,
and the TypeScript Vision checkpoint reached through `build_vision_checkpoint`.
Testing one owner's helper cannot prove the contract, because the owners used
to disagree: the Vision path rejected ordinary "owner authorization" prose
while the Python patterns accepted a quoted-JSON credential header.

These tests drive the shared fixture through each owner's real entrypoint, so
any owner that drifts fails here instead of in a reviewer's manual probe. The
fixture has three buckets because the four owners are one tier: they validate
LoopX's own state, so they accept a bare credential word (Refs #5136 direction
2) while the stricter publication tier keeps rejecting it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from loopx.authority import validate_public_safe_text as validate_authority_text
from loopx.boundary_authority import build_checkpointed_boundary_authority_entry
from loopx.control_plane.goals.vision_checkpoint import build_vision_checkpoint
from loopx.feedback import validate_public_safe_text as validate_feedback_text
from loopx.public_safe_text import (
    ALL_CATEGORIES,
    CATEGORY_CREDENTIAL_WORD,
    TEXT_OWNER_CATEGORIES,
    classify_private_text,
    find_private_text_match,
)

CORPUS_PATH = (
    Path(__file__).resolve().parents[1] / "fixtures" / "public_safe_text_corpus.json"
)
PLACEHOLDER_RE = re.compile(r"\{([A-Z][A-Z_]*)\}")


def _load_corpus() -> dict[str, Any]:
    corpus = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    assert corpus["schema_version"] == "public_safe_text_corpus_v1"
    return corpus


def _render(template: str, tokens: dict[str, list[str]]) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name in tokens:
            return "".join(tokens[name])
        if name.endswith("_LOWER") and name[: -len("_LOWER")] in tokens:
            return "".join(tokens[name[: -len("_LOWER")]]).lower()
        raise AssertionError(f"corpus placeholder {name} has no token definition")

    return PLACEHOLDER_RE.sub(replace, template)


def _samples(group: str) -> list[tuple[str, str]]:
    corpus = _load_corpus()
    tokens = corpus["tokens"]
    return [
        (str(sample["id"]), _render(str(sample["template"]), tokens))
        for sample in corpus[group]
    ]


PUBLIC_SAFE_SAMPLES = _samples("public_safe")
PRIVATE_LOOKING_SAMPLES = _samples("private_looking")
INTERNAL_STATE_PROSE_SAMPLES = _samples("internal_state_prose")


def _ids(samples: list[tuple[str, str]]) -> list[str]:
    return [sample_id for sample_id, _ in samples]


def _boundary_authority_text(text: str) -> None:
    """Drive boundary_authority through its public builder, not its helper."""

    build_checkpointed_boundary_authority_entry(
        write_scopes=["goal_state"],
        source=text,
    )


def _vision_text(text: str) -> None:
    """Drive the real TypeScript Vision owner through the Python entrypoint."""

    build_vision_checkpoint(
        agent_id="kiro-cli",
        agent_vision=None,
        existing_agent_vision=None,
        vision_unchanged_reason=text,
        delivery_outcome="outcome_progress",
        active_state_next_action_update=None,
    )


OWNERS = (
    ("feedback", lambda text: validate_feedback_text("agent_vision.summary", text)),
    ("authority", lambda text: validate_authority_text("project_material.note", text)),
    ("boundary_authority", _boundary_authority_text),
    ("vision_checkpoint_ts", _vision_text),
)
OWNER_IDS = [owner_id for owner_id, _ in OWNERS]


@pytest.mark.parametrize("owner", [check for _, check in OWNERS], ids=OWNER_IDS)
@pytest.mark.parametrize("sample", PUBLIC_SAFE_SAMPLES, ids=_ids(PUBLIC_SAFE_SAMPLES))
def test_public_safe_corpus_is_accepted_by_every_owner(
    owner: Any,
    sample: tuple[str, str],
) -> None:
    owner(sample[1])


@pytest.mark.parametrize("owner", [check for _, check in OWNERS], ids=OWNER_IDS)
@pytest.mark.parametrize(
    "sample", PRIVATE_LOOKING_SAMPLES, ids=_ids(PRIVATE_LOOKING_SAMPLES)
)
def test_private_looking_corpus_is_rejected_by_every_owner(
    owner: Any,
    sample: tuple[str, str],
) -> None:
    with pytest.raises(ValueError, match="private-looking value"):
        owner(sample[1])


def test_corpus_covers_the_reviewed_credential_shapes() -> None:
    """Guard the corpus itself: the three shapes that motivated this contract."""

    required = {
        "raw_header_basic",
        "assignment_bearer",
        "quoted_json_key_basic",
    }
    assert required <= set(_ids(PRIVATE_LOOKING_SAMPLES))
    assert "governance_prose_needs_owner_authorization" in _ids(PUBLIC_SAFE_SAMPLES)
    # Direction 2's boundary is part of the contract, so the corpus must keep a
    # sample on each side of the value floor and one assignment per demoted word.
    private_ids = set(_ids(PRIVATE_LOOKING_SAMPLES))
    assert {
        "bearer_value_at_named_floor",
        "password_assignment_short_value",
        "secret_assignment_colon",
        "token_assignment_colon",
    } <= private_ids
    assert "bearer_word_in_prose" in _ids(INTERNAL_STATE_PROSE_SAMPLES)


@pytest.mark.parametrize("owner", [check for _, check in OWNERS], ids=OWNER_IDS)
@pytest.mark.parametrize(
    "sample", INTERNAL_STATE_PROSE_SAMPLES, ids=_ids(INTERNAL_STATE_PROSE_SAMPLES)
)
def test_internal_state_prose_is_accepted_by_every_text_owner(
    owner: Any,
    sample: tuple[str, str],
) -> None:
    owner(sample[1])


def test_internal_state_prose_stays_rejected_by_the_publication_tier() -> None:
    # The tier difference is the whole of direction 2, so it has to be visible
    # from the stricter surface as well: everything the four owners now let
    # through is still recognized by the full category set, and by the legacy
    # helper the repository-publication scan still reaches.
    for sample_id, value in INTERNAL_STATE_PROSE_SAMPLES:
        assert find_private_text_match(value) is not None, sample_id
        assert classify_private_text(value, categories=ALL_CATEGORIES) is not None, (
            sample_id
        )
        assert classify_private_text(value, categories=TEXT_OWNER_CATEGORIES) is None, (
            sample_id
        )


def test_no_value_bearing_form_left_the_internal_state_policy() -> None:
    # A category set is a blunt instrument: dropping `credential_word` must not
    # drop an assignment or a scheme-with-value. This walks every private-looking
    # sample and proves the narrower policy still rejects all of them, so the
    # only values the split can release are the prose samples above.
    for sample_id, value in PRIVATE_LOOKING_SAMPLES:
        match = classify_private_text(value, categories=TEXT_OWNER_CATEGORIES)
        assert match is not None, sample_id
        assert match.category != CATEGORY_CREDENTIAL_WORD, sample_id
