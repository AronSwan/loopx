"""One owner for the two shapes a stored SHA-256 digest can take.

A digest reaches a record in one of two envelopes: the bare 64 lowercase hex
characters, or that same hex behind the ``sha256:`` prefix that the
periodic-report and content-ops writers concatenate. Before this module the
decision was compiled independently in eighteen modules under three spellings.

Patterns that merely contain a hex digest inside a larger grammar (a
``cadence_…`` identifier, a journal filename, a ``40|64`` Git object id, a
compound cursor) answer a different question and stay with the surface that
owns that grammar. Producers that build the envelope by hand are the other half
of this decision and are deliberately unchanged here.
"""

from __future__ import annotations

import re

ENVELOPED_SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
BARE_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
