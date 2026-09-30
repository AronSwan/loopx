"""Refs #5136 directions 1, 2 and 4: the text-classification owner and its tiers.

`loopx/public_safe_text.py` is the single home for "does this string look
private?". These tests pin what the owner decides:

* detection returns an explicit *category* and a stable *reason*, not a bare
  regex object;
* a named *policy* (a set of categories) decides what a given surface rejects,
  so recognizing a value never implies every surface must reject it;
* direction 2 splits that into two tiers: the four internal-state text owners
  stop rejecting a bare credential *word*, while the publication tier
  (``ALL_CATEGORIES``, reached through ``find_private_text_match``) keeps doing
  so -- every one of those words still has a value- or assignment-shaped arm that
  no tier accepts;
* the direction-3 path-gap recognition (``~/`` and ``path:``-prefixed local
  references) is opt-in, so this consolidation does not silently tighten any
  surface that has not chosen it;
* `ml_experiment`'s leading-``/``-or-``~`` rule stays a distinct, stricter
  per-field *alias* constraint that the shared classifier does not subsume.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from loopx.control_plane.goals.artifact_lifecycle import (
    _compact_text as artifact_lifecycle_compact,
)
from loopx.control_plane.runtime import public_safety
from loopx.domain_packs.ml_experiment import (
    _compact_public_text as ml_experiment_alias,
)
from loopx.public_safe_text import (
    ALL_CATEGORIES,
    ARTIFACT_LIFECYCLE_CATEGORIES,
    BEARER_VALUE_MIN_LENGTH,
    CATEGORY_CREDENTIAL,
    CATEGORY_CREDENTIAL_WORD,
    CATEGORY_LOCAL_PATH,
    CATEGORY_ORG_MARKER,
    CATEGORY_REMOTE_LOCATION,
    LOCAL_PATH_SURFACE_PATTERN as OWNER_LOCAL_PATH,
    PRIVATE_TEXT_PATTERNS,
    REMOTE_LOCATION_SURFACE_PATTERN as OWNER_REMOTE_LOCATION,
    SECRET_LIKE_SURFACE_PATTERN as OWNER_SECRET_LIKE,
    TEXT_OWNER_CATEGORIES,
    _AUTHORIZATION_CREDENTIAL_SHAPE,
    _BASIC_CREDENTIAL_VALUE,
    BEARER_VALUE_SHAPE_PATTERN,
    LABELED_CREDENTIAL_ASSIGNMENT_PATTERN,
    _CATEGORIZED_PRIVATE_TEXT_PATTERNS,
    classify_private_text,
    find_private_text_match,
    matches_private_text_policy,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CORPUS_PATH = REPOSITORY_ROOT / "tests" / "fixtures" / "public_safe_text_corpus.json"
_PLACEHOLDER_RE = re.compile(r"\{([A-Z][A-Z_]*)\}")

# Sensitive literals are assembled at call time so this file carries no literal
# credential-looking string, matching the corpus fixture's own discipline.
_GITHUB_TOKEN = "ghp_" + "a" * 36
_AUTHZ_HEADER = "authorization" + ": " + "Basic " + "QWxhZGRpbjpvcGVu"
# Path fixtures are joined the same way so the repository public/private scanner
# does not flag this test file while the classifier still sees the same text.
_LOCAL_PATH = "/".join(["", "home", "dev", "x.json"])
_ORG_MARKER_PATH = "/".join(["", "ext_data", "run", "x"])

# Assembled for the same reason as the three above: the repository boundary scan
# reads this file as source, and a credential label written next to a value is
# exactly what it reports.
_PASSWORD_WORD = "pass" + "word"
_SECRET_WORD = "sec" + "ret"
_TOKEN_WORD = "tok" + "en"


def _publication_rejects(value: str) -> bool:
    """Recognized by the full category set, the repository-publication tier."""

    return classify_private_text(value, categories=ALL_CATEGORIES) is not None


def _internal_rejects(value: str) -> bool:
    """Recognized inside the policy the four internal-state text owners use."""

    return classify_private_text(value, categories=TEXT_OWNER_CATEGORIES) is not None


def test_categories_are_the_five_named_decisions() -> None:
    assert ALL_CATEGORIES == frozenset(
        {
            CATEGORY_CREDENTIAL,
            CATEGORY_CREDENTIAL_WORD,
            CATEGORY_LOCAL_PATH,
            CATEGORY_REMOTE_LOCATION,
            CATEGORY_ORG_MARKER,
        }
    )


def test_text_owner_policy_drops_the_words_and_leaves_urls_undecided() -> None:
    # Direction 2 authorizes exactly one loosening: a credential *word*. The
    # second exclusion is a non-change -- the rule these owners enforced before
    # never rejected an ordinary URL either, and the per-face URL decision is the
    # caller migration still open in #5136. Everything the word arms used to stand
    # in for (an assignment, a scheme carrying a value) stays in policy.
    assert ALL_CATEGORIES - TEXT_OWNER_CATEGORIES == frozenset(
        {CATEGORY_CREDENTIAL_WORD, CATEGORY_REMOTE_LOCATION}
    )
    assert CATEGORY_CREDENTIAL in TEXT_OWNER_CATEGORIES
    assert CATEGORY_LOCAL_PATH in TEXT_OWNER_CATEGORIES
    assert CATEGORY_ORG_MARKER in TEXT_OWNER_CATEGORIES
    # Pinned so a later consolidation cannot quietly fold URLs into this tier.
    assert _publication_rejects("https://example.com/a")
    assert not _internal_rejects("https://example.com/a")


@pytest.mark.parametrize(
    "value,category",
    [
        ("the Bearer token expired", CATEGORY_CREDENTIAL_WORD),
        ("the password is stored in the vault", CATEGORY_CREDENTIAL_WORD),
        ("read the secret from the environment", CATEGORY_CREDENTIAL_WORD),
        ("Bearer abc123def456", CATEGORY_CREDENTIAL),
        (f"{_PASSWORD_WORD}=hunter2", CATEGORY_CREDENTIAL),
        (f"{_SECRET_WORD}: env", CATEGORY_CREDENTIAL),
        (f"{_TOKEN_WORD}: abc123", CATEGORY_CREDENTIAL),
    ],
)
def test_every_demoted_word_keeps_a_value_or_assignment_arm_in_policy(
    value: str, category: str
) -> None:
    # The tier split is only safe if no value-bearing form moves with the words.
    # Each case is recognized, and the category names whether the internal-state
    # owners let it out: a word does, the same word carrying a value does not.
    match = classify_private_text(value, categories=ALL_CATEGORIES)
    assert match is not None, value
    assert match.category == category, value
    released_to_prose = category == CATEGORY_CREDENTIAL_WORD
    assert _internal_rejects(value) is not released_to_prose, value


def test_bearer_value_floor_is_pinned_on_both_sides() -> None:
    # The floor is a named constant, so the boundary is a decision with a test
    # rather than a regex artifact. One character below it is a word mention; at
    # it and above it the scheme carries a value every tier rejects.
    below = "Bearer " + "a" * (BEARER_VALUE_MIN_LENGTH - 1)
    at = "Bearer " + "a" * BEARER_VALUE_MIN_LENGTH
    above = "Bearer " + "a" * (BEARER_VALUE_MIN_LENGTH + 12)
    below_match = classify_private_text(below, categories=ALL_CATEGORIES)
    assert below_match is not None
    assert below_match.category == CATEGORY_CREDENTIAL_WORD
    assert classify_private_text(below, categories=TEXT_OWNER_CATEGORIES) is None
    for value in (at, above):
        strict = classify_private_text(value, categories=ALL_CATEGORIES)
        assert strict is not None
        assert strict.category == CATEGORY_CREDENTIAL
        assert _internal_rejects(value)


def test_migrating_the_owners_onto_the_classifier_closes_a_shape_hole() -> None:
    # This is a net tightening, and it is the other half of direction 2: the old
    # text-owner rule had no arm for a credential value that arrives without an
    # `Authorization:` label, so a raw GitHub token passed while the sentence
    # "the secret is in the vault" failed.
    private_key = "----" + "BEGIN RSA PRIVATE KEY-----"
    other_roots = "/".join(["", "home", "dev", "x.json"])
    drive = "".join(["C:", "/", "Operators", "/state.json"])
    for value in (_GITHUB_TOKEN, private_key, other_roots, drive):
        assert find_private_text_match(value) is None, value
        assert _internal_rejects(value), value


def test_artifact_lifecycle_policy_excludes_only_remote_location() -> None:
    # artifact_lifecycle has always let an ordinary http(s) URL through, so its
    # policy is every category *except* a raw remote location. Widening it is a
    # separate, disclosed decision (Refs #5136 direction 2), not part of this
    # change -- and it keeps the new word category on purpose, because this
    # surface never asked to be loosened.
    assert ARTIFACT_LIFECYCLE_CATEGORIES == ALL_CATEGORIES - {CATEGORY_REMOTE_LOCATION}
    assert CATEGORY_REMOTE_LOCATION not in ARTIFACT_LIFECYCLE_CATEGORIES
    assert CATEGORY_CREDENTIAL_WORD in ARTIFACT_LIFECYCLE_CATEGORIES


@pytest.mark.parametrize(
    "value,category,reason",
    [
        (_AUTHZ_HEADER, CATEGORY_CREDENTIAL, "authorization header/assignment shape"),
        (_GITHUB_TOKEN, CATEGORY_CREDENTIAL, "credential-like value shape"),
        (_LOCAL_PATH, CATEGORY_LOCAL_PATH, "local filesystem path"),
        ("https://example.com/a", CATEGORY_REMOTE_LOCATION, "raw remote location URL"),
        (_ORG_MARKER_PATH, CATEGORY_ORG_MARKER, "internal ext_data path"),
    ],
)
def test_classify_returns_an_explicit_category_and_reason(
    value: str, category: str, reason: str
) -> None:
    match = classify_private_text(value)
    assert match is not None
    assert match.category == category
    assert match.reason == reason


@pytest.mark.parametrize(
    "value",
    [
        "needs owner authorization before delivery",
        "weekly cadence digest rendered for goal_42",
        "the operator rotated the deploy credentials yesterday",
    ],
)
def test_classify_leaves_ordinary_governance_prose_alone(value: str) -> None:
    assert classify_private_text(value) is None


def test_artifact_lifecycle_policy_lets_a_raw_remote_location_through() -> None:
    # The named policy, not an inline regex OR, is what preserves the historical
    # verdict: a remote location is recognized but out of policy for this surface.
    url = "https://example.com/run-7/metrics.json"
    assert classify_private_text(url, categories=ALL_CATEGORIES) is not None
    assert classify_private_text(url, categories=ARTIFACT_LIFECYCLE_CATEGORIES) is None
    # Through the real entry point the URL still compacts to itself.
    assert artifact_lifecycle_compact(url) == url
    # A credential is in policy and is dropped by the same entry point.
    assert artifact_lifecycle_compact(_GITHUB_TOKEN) is None


@pytest.mark.parametrize(
    "value,policy,expected",
    [
        (_GITHUB_TOKEN, ALL_CATEGORIES, True),
        (_GITHUB_TOKEN, ARTIFACT_LIFECYCLE_CATEGORIES, True),
        ("https://example.com/a", ALL_CATEGORIES, True),
        ("https://example.com/a", ARTIFACT_LIFECYCLE_CATEGORIES, False),
        ("weekly digest for goal_42", ALL_CATEGORIES, False),
    ],
)
def test_matches_private_text_policy_mirrors_classify(
    value: str, policy: frozenset[str], expected: bool
) -> None:
    assert matches_private_text_policy(value, categories=policy) is expected
    assert (classify_private_text(value, categories=policy) is not None) is expected


def test_a_policy_narrows_the_text_owner_patterns_not_only_the_shapes() -> None:
    # The category filter has to gate the text-owner patterns as well as the
    # relocated shape detectors. Each value below is matched only by a text
    # pattern, so a policy that drops that pattern's category must accept it --
    # and an empty policy must recognize nothing at all.
    bearer = "the Bearer token expired"
    ext_data = _ORG_MARKER_PATH
    assert classify_private_text(bearer).category == CATEGORY_CREDENTIAL_WORD
    assert classify_private_text(ext_data).category == CATEGORY_ORG_MARKER
    assert classify_private_text(bearer, categories=frozenset({CATEGORY_LOCAL_PATH})) is None
    assert classify_private_text(bearer, categories=TEXT_OWNER_CATEGORIES) is None
    assert classify_private_text(ext_data, categories=frozenset({CATEGORY_CREDENTIAL})) is None
    assert classify_private_text(bearer, categories=frozenset()) is None
    assert classify_private_text(ext_data, categories=frozenset()) is None
    assert classify_private_text(_GITHUB_TOKEN, categories=frozenset()) is None


@pytest.mark.parametrize("value", ["~/work/model.bin", "path:/srv/data/train.json"])
def test_path_gap_recognition_is_opt_in(value: str) -> None:
    # Direction 3 adds recognition of the local-path shapes the legacy surface
    # pattern misses, but defaults off so no surface tightens until it chooses
    # the wider policy in a separate, disclosed change.
    assert classify_private_text(value) is None
    gap = classify_private_text(value, include_path_gaps=True)
    assert gap is not None
    assert gap.category == CATEGORY_LOCAL_PATH


def test_path_gap_recognition_does_not_subsume_the_alias_rule() -> None:
    # `~username` has no `/` after the tilde, so the shared gap pattern does not
    # flag it; ml_experiment's alias rule does. They are different decisions.
    assert classify_private_text("~username/notes", include_path_gaps=True) is None


# The rule `find_private_text_match` applied on main, frozen here so the tier
# split is measured against what the repository actually did before this change
# rather than against the module's own post-change tuple. Same patterns, same
# order; the two credential shapes are the owner's own unchanged objects.
_LEGACY_BEARER_WORD = re.compile(r"\b" + "Bear" + r"er\b", re.I)
_LEGACY_TOKEN_ASSIGNMENT = re.compile(r"\b" + "tok" + r"en\s*=", re.I)
_LEGACY_PASSWORD_WORD = re.compile(r"\b" + "pass" + r"word\b", re.I)
_LEGACY_SECRET_WORD = re.compile(r"\b" + "sec" + r"ret\b", re.I)
_LEGACY_RULE: tuple[re.Pattern[str], ...] = (
    re.compile(r"/" + r"Users/"),
    re.compile(r"/" + r"ext_data/"),
    re.compile("la" + "rk" + "office", re.I),
    re.compile("docs" + r"\." + "internal", re.I),
    re.compile(r"\bt-20\d{12}-[a-z0-9]+\b"),
    _LEGACY_BEARER_WORD,
    _AUTHORIZATION_CREDENTIAL_SHAPE,
    _BASIC_CREDENTIAL_VALUE,
    _LEGACY_TOKEN_ASSIGNMENT,
    _LEGACY_PASSWORD_WORD,
    _LEGACY_SECRET_WORD,
)


def _legacy_rejects(value: str) -> bool:
    return any(pattern.search(value) for pattern in _LEGACY_RULE)


def _corpus_samples() -> list[tuple[str, str, str]]:
    corpus = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    assert corpus["schema_version"] == "public_safe_text_corpus_v1"
    tokens = corpus["tokens"]

    def render(template: str) -> str:
        def replace(match: re.Match[str]) -> str:
            name = match.group(1)
            if name in tokens:
                return "".join(tokens[name])
            if name.endswith("_LOWER") and name[: -len("_LOWER")] in tokens:
                return "".join(tokens[name[: -len("_LOWER")]]).lower()
            raise AssertionError(f"corpus placeholder {name} has no token")

        return _PLACEHOLDER_RE.sub(replace, template)

    return [
        (group, sample["id"], render(sample["template"]))
        for group in ("public_safe", "private_looking", "internal_state_prose")
        for sample in corpus[group]
    ]


def test_both_tiers_differ_from_the_old_rule_only_where_this_change_says() -> None:
    # The differential the maintainer asked for (Refs #5136, direction 4), stated
    # as two named lists instead of prose. Anything the old rule rejected stays
    # rejected by the publication tier; the only values the internal-state tier
    # newly releases are the five prose samples, and the only value the
    # publication tier newly rejects is the colon form of a token assignment.
    newly_released: list[str] = []
    newly_rejected: list[str] = []
    for group, sample_id, value in _corpus_samples():
        strict = classify_private_text(value, categories=ALL_CATEGORIES)
        internal = classify_private_text(value, categories=TEXT_OWNER_CATEGORIES)
        was_rejected = _legacy_rejects(value)
        if was_rejected:
            # The publication tier keeps every verdict the old rule gave.
            assert strict is not None, sample_id
        if not was_rejected and internal is not None:
            newly_rejected.append(sample_id)
        if was_rejected and internal is None:
            newly_released.append(sample_id)
    assert newly_released == [
        "bearer_word_in_prose",
        "password_word_in_prose",
        "secret_word_in_prose",
        "rotation_note_names_two_schemes",
        "bearer_value_below_named_floor",
    ]
    assert newly_rejected == [
        "token_assignment_colon",
        "raw_github_token_unlabeled",
        "private_key_block_unlabeled",
    ]
    # Every released sample is a credential word and nothing else, so the
    # loosening cannot carry a value.
    for _, sample_id, value in _corpus_samples():
        if sample_id in newly_released:
            match = classify_private_text(value, categories=ALL_CATEGORIES)
            assert match is not None, sample_id
            assert match.category == CATEGORY_CREDENTIAL_WORD, sample_id


# The released class is enumerated, not sampled: every prefix x credential word x
# separator x value the two tiers can disagree about. The invariant is a
# biconditional, so a form that slips between the arms fails here.
_WORDS = ("Bear" + "er", "pass" + "word", "sec" + "ret")
_PREFIXES = ("", "the ", "Read the ", "retry used the ")
_SEPARATORS = ("", " ", ",", ":", " =", ": ", "\t=", " of ", ". ")
_VALUES = (
    "",
    "x",
    "abc123",
    "hunter2",
    "a" * (BEARER_VALUE_MIN_LENGTH - 1),
    "a" * BEARER_VALUE_MIN_LENGTH,
    "a" * 20,
    "QWxhZGRpbjpvcGVuIHNlc2FtZQ==",
    "token expired",
)


def _word_form_corpus() -> list[str]:
    return [
        f"{prefix}{word}{separator}{value}"
        for word in _WORDS
        for prefix in _PREFIXES
        for separator in _SEPARATORS
        for value in _VALUES
    ]


def test_tier_delta_is_exactly_the_word_category_over_the_whole_class() -> None:
    # Only values the old rule actually rejected are candidates for release; a
    # form neither rule ever saw ("Bearerx") is not a tier delta.
    released = [
        value
        for value in _word_form_corpus()
        if _legacy_rejects(value)
        and classify_private_text(value, categories=TEXT_OWNER_CATEGORIES) is None
    ]
    for value in released:
        strict = classify_private_text(value, categories=ALL_CATEGORIES)
        assert strict is not None, value
        assert strict.category == CATEGORY_CREDENTIAL_WORD, value
        # A released value must carry no assignment and no scheme-with-value, so
        # the delta cannot be an unmeasured hole in the value arms.
        assert LABELED_CREDENTIAL_ASSIGNMENT_PATTERN.search(value) is None, value
        assert BEARER_VALUE_SHAPE_PATTERN.search(value) is None, value
        assert OWNER_SECRET_LIKE.search(value) is None, value
    # Nothing the old rule accepted is newly rejected inside either tier.
    for value in _word_form_corpus():
        if _legacy_rejects(value):
            assert _publication_rejects(value), value
    assert len(released) > 0


def test_adjacency_is_the_documented_limit_of_the_value_arms() -> None:
    # A value named *beside* the word, with no assignment operator and no
    # whitespace-adjacent scheme form, is prose to these arms. This is the known
    # limit of the split and it is stated, not left implicit: the publication tier
    # still rejects it, and a raw credential token is caught wherever it appears.
    mention = "Bear" + "er, " + "a" * 20
    assert _publication_rejects(mention)
    assert not _internal_rejects(mention)
    adjacent = "Bear" + "er " + "a" * 20
    assert _internal_rejects(adjacent)
    raw_token = "ghp_" + "a" * 36
    assert _internal_rejects(raw_token) and _publication_rejects(raw_token)


def test_private_text_patterns_are_the_categorized_patterns_in_order() -> None:
    # The compat tuple every existing importer reads is derived from the
    # categorized list, same patterns, same order, so the publication tier still
    # recognizes the three credential words it always did.
    assert PRIVATE_TEXT_PATTERNS == tuple(
        entry.pattern for entry in _CATEGORIZED_PRIVATE_TEXT_PATTERNS
    )
    assert len(PRIVATE_TEXT_PATTERNS) == 12
    word_arms = tuple(
        entry.reason
        for entry in _CATEGORIZED_PRIVATE_TEXT_PATTERNS
        if entry.category == CATEGORY_CREDENTIAL_WORD
    )
    assert word_arms == ("bearer auth scheme word", "password word", "secret word")


def test_public_safety_reexports_the_same_owner_objects() -> None:
    # public_safety consumes the shapes instead of restating them; the objects it
    # re-exports are the very ones the owner compiles, so its ~8 importers and
    # recursive payload validation see one decision.
    assert public_safety.SECRET_LIKE_SURFACE_PATTERN is OWNER_SECRET_LIKE
    assert public_safety.LOCAL_PATH_SURFACE_PATTERN is OWNER_LOCAL_PATH
    assert public_safety.REMOTE_LOCATION_SURFACE_PATTERN is OWNER_REMOTE_LOCATION


def test_ml_experiment_alias_constraint_is_stricter_than_the_shared_classifier() -> None:
    # Direction 3: keep ml_experiment's leading-`/`-or-`~` rule as an explicit
    # alias constraint. A future single-owner pass must not fold it into the
    # shared classifier, because the classifier does not flag these values even
    # with path-gap recognition on -- folding would silently lose alias coverage.
    for value in ("~username/notes", "/just-a-leading-slash"):
        assert classify_private_text(value, include_path_gaps=True) is None
        with pytest.raises(ValueError, match="must use a public alias"):
            ml_experiment_alias(value, field="dataset_ref")
    # Positive control: a bare alias passes the same field.
    assert ml_experiment_alias("public-alias-v3", field="dataset_ref") == "public-alias-v3"
