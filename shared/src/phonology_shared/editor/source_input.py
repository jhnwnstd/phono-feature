# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Required Notice: Copyright 2026 John Winstead,
# https://github.com/jhnwnstd/phono-feature
"""Normalize a user-entered inventory source for ``metadata.source``.

The inventory editor lets a user attach a source (provenance) to an
inventory. Most sources are already a plain citation, a URL, or a DOI;
those pass through untouched and are classified for display by
:py:func:`phonology_shared.presentation.source_link.classify_source`
exactly like a predefined inventory's source. As a convenience, a
pasted BibTeX entry (``@type{key, field = {..}}``) is rendered into a
plain citation string so it displays cleanly instead of showing raw
BibTeX markup in the citation window.

This is a deliberately small formatter, not a BibTeX processor: it
pulls the handful of fields a one-line citation needs and degrades
gracefully (falling back to the raw text) when they are absent. The
stored value is always the same free-form string the display layer
already reads, so nothing downstream changes.
"""

from __future__ import annotations

import re

# An entry opens with ``@type{`` (optionally spaced). This is the only
# signal that the input is BibTeX rather than a plain citation; anything
# else is returned verbatim so URLs / DOIs / hand-typed citations are
# never mangled.
_BIB_ENTRY_RE = re.compile(r"^\s*@\s*\w+\s*\{", re.IGNORECASE)

# ``field = {value}`` | ``"value"`` | ``bare`` . The brace branch allows
# one level of nesting (common in titles, e.g. ``{The {ATR} contrast}``).
_BIB_FIELD_RE = re.compile(
    r"(\w+)\s*=\s*"
    r"(?:\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}|\"([^\"]*)\"|([^,\n}]+))"
)


def _bib_fields(entry: str) -> dict[str, str]:
    """Extract ``field -> value`` pairs from a BibTeX entry body.

    First occurrence wins; values are stripped of BibTeX brace grouping
    and have their whitespace collapsed. The entry citekey (the bare
    token before the first comma) has no ``=`` and is ignored.
    """
    fields: dict[str, str] = {}
    for match in _BIB_FIELD_RE.finditer(entry):
        key = match.group(1).lower()
        value = match.group(2) or match.group(3) or match.group(4) or ""
        value = " ".join(value.replace("{", "").replace("}", "").split())
        if key and value and key not in fields:
            fields[key] = value
    return fields


def _format_authors(raw: str) -> str:
    """Render a BibTeX ``author`` field ("A and B and C") as a readable
    list, keeping each name as written."""
    names = [n.strip() for n in re.split(r"\s+and\s+", raw) if n.strip()]
    if len(names) <= 1:
        return raw.strip()
    if len(names) == 2:
        return f"{names[0]} & {names[1]}"
    return ", ".join(names[:-1]) + f" & {names[-1]}"


def normalize_source_input(text: str | None) -> str:
    """Return the string to store under ``metadata.source``.

    A pasted BibTeX entry is rendered to a plain citation; any other
    text (plain citation / URL / DOI) is returned stripped and
    otherwise unchanged. Empty / whitespace / ``None`` returns ``""``,
    which the caller treats as "no source" (drop the key so
    :py:func:`classify_source` yields ``none``).
    """
    if not text:
        return ""
    stripped = text.strip()
    if not stripped or not _BIB_ENTRY_RE.match(stripped):
        return stripped

    fields = _bib_fields(stripped)
    author = _format_authors(fields.get("author", ""))
    year = fields.get("year", "")
    title = fields.get("title", "")
    container = next(
        (
            fields[k]
            for k in (
                "journal",
                "booktitle",
                "publisher",
                "school",
                "institution",
            )
            if fields.get(k)
        ),
        "",
    )

    parts: list[str] = []
    if author:
        parts.append(f"{author} ({year})." if year else f"{author}.")
    elif year:
        parts.append(f"({year}).")
    if title:
        parts.append(f"{title}.")
    if container:
        parts.append(f"{container}.")

    # If none of the expected fields were present, the entry is unusable
    # as a citation; keep the raw text rather than emit an empty string.
    return " ".join(parts).strip() or stripped
