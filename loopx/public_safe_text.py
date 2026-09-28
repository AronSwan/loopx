"""Canonical private-looking-text rules for public-safe control-plane fields.

Four real validator owners enforce the same contract: `feedback`,
`authority`, `boundary_authority`, and the TypeScript Vision checkpoint. The
rule set used to be copied into each owner, and the copies drifted: one still
rejected the ordinary English word "authorization" while another accepted a
quoted-JSON credential header. The three Python owners now share this module,
and the TypeScript owner mirrors the same semantics; the shared corpus in
`tests/fixtures/public_safe_text_corpus.json` pins both runtimes to one
contract.

Each owner keeps its own error message and guidance, because those describe
the owning surface, not the shared rule.
"""

from __future__ import annotations

import re


# Credential shape, not the plain English word. LoopX governance prose says
# "owner authorization" constantly, so the trigger is the header/assignment
# shape. The optional quote covers the JSON key form
# `{"Authorization": "Basic ..."}`, which a bare `name\s*[:=]` rule misses.
_AUTHORIZATION_CREDENTIAL_SHAPE = re.compile(
    r"\b" + "Author" + r"ization" + "[\"']?" + r"\s*[:=]",
    re.I,
)

# A credential value can also appear without its header name. Require a
# contiguous base64-shaped run so ordinary prose cannot match: no spaces or
# hyphens, at least 16 characters, and both cases present. "basic
# control-plane contract" fails every one of those conditions.
_BASIC_CREDENTIAL_VALUE = re.compile(
    "[Bb]" + "as" + r"ic\s+"
    r"(?=[A-Za-z0-9+/=]*[a-z])"
    r"(?=[A-Za-z0-9+/=]*[A-Z])"
    r"[A-Za-z0-9+/=]{16,}",
)

PRIVATE_TEXT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"/" + r"Users/"),
    re.compile(r"/" + r"ext_data/"),
    re.compile("la" + "rk" + "office", re.I),
    re.compile("docs" + r"\." + "internal", re.I),
    re.compile(r"\bt-20\d{12}-[a-z0-9]+\b"),
    re.compile(r"\b" + "Bear" + r"er\b", re.I),
    _AUTHORIZATION_CREDENTIAL_SHAPE,
    _BASIC_CREDENTIAL_VALUE,
    re.compile(r"\b" + "tok" + r"en\s*=", re.I),
    re.compile(r"\b" + "pass" + r"word\b", re.I),
    re.compile(r"\b" + "sec" + r"ret\b", re.I),
)


def find_private_text_match(value: str | None) -> re.Pattern[str] | None:
    """Return the first matching private-text pattern, or None when clean."""

    if not value:
        return None
    for pattern in PRIVATE_TEXT_PATTERNS:
        if pattern.search(value):
            return pattern
    return None
