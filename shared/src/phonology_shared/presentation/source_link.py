"""Classify an inventory ``metadata.source`` string for display.

One inventory carries one free-form ``source`` string. It can be a
URL, a DOI, or a plain bibliographic citation. Both frontends route it
through :py:func:`classify_source` so the affordance behaves
identically: a URL or DOI opens the link; a plain citation opens a
small window showing the text. This is the single home for that
decision, so the desktop status bar and the web ``[Source]`` element
cannot drift.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# A bare DOI: ``10.<registrant>/<suffix>``. Suffix is permissive (the
# DOI spec allows almost anything); we only require a non-empty,
# whitespace-free tail so a citation sentence is not mistaken for one.
_DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")

# Affordance label. Kept here (not per-frontend) so the two UIs show
# the same word.
SOURCE_LABEL = "Source"


@dataclass(frozen=True)
class SourceLink:
    """A classified inventory source.

    ``kind`` is one of ``"url"``, ``"doi"``, ``"citation"`` or
    ``"none"``. ``href`` is the resolvable target for ``url``/``doi``
    (empty otherwise); ``text`` is the original string (shown in the
    citation window); ``label`` is the affordance text.
    """

    kind: str
    text: str
    href: str
    label: str

    def as_dict(self) -> dict[str, str]:
        """Plain-dict form for the web bridge payload."""
        return {
            "kind": self.kind,
            "text": self.text,
            "href": self.href,
            "label": self.label,
        }

    @classmethod
    def from_dict(cls, data: Any) -> SourceLink:
        """Rebuild from :py:meth:`as_dict` (or an empty value)."""
        if not isinstance(data, dict):
            return NONE_SOURCE
        return cls(
            kind=str(data.get("kind", "none")),
            text=str(data.get("text", "")),
            href=str(data.get("href", "")),
            label=str(data.get("label", SOURCE_LABEL)),
        )


NONE_SOURCE = SourceLink(kind="none", text="", href="", label="")


def classify_source(raw: str | None) -> SourceLink:
    """Classify a raw ``metadata.source`` string.

    ``http(s)://...`` becomes a ``url``; a bare or ``doi:``-prefixed
    DOI becomes a ``doi`` resolving through ``https://doi.org/``;
    anything else non-empty is a ``citation``; empty/absent is
    ``none`` (no affordance shown).
    """
    # Metadata values pass through the parser untouched, so a
    # hand-edited or future-baked inventory could carry a non-string
    # ``source`` (dict / list / number). Coerce at the boundary rather
    # than let ``.strip()`` raise and fail the entire load on both
    # frontends.
    if not isinstance(raw, str):
        return NONE_SOURCE
    text = raw.strip()
    if not text:
        return NONE_SOURCE
    low = text.lower()
    if low.startswith(("http://", "https://")):
        return SourceLink("url", text, text, SOURCE_LABEL)
    doi = text[4:].strip() if low.startswith("doi:") else text
    if _DOI_RE.match(doi):
        return SourceLink("doi", text, f"https://doi.org/{doi}", SOURCE_LABEL)
    return SourceLink("citation", text, "", SOURCE_LABEL)
