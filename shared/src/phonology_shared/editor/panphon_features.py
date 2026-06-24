"""Canonical mapping from PanPhon's short feature names to the
app's canonical names.

Lives in shared/ (not under desktop/) because two consumers depend
on it: (a) the desktop's live
:py:class:`phonology_features.providers.panphon_provider.PanPhonFeatureProvider`
that wraps :py:mod:`panphon` directly, and (b) the build-time bake
script + the runtime lookup provider that ship a JSON snapshot of
PanPhon's IPA table to the web bundle. Centralising the mapping
keeps the desktop and the web in lockstep without forcing either
to depend on the other's package.

Names on the right follow the app's canonical capitalisation
conventions (terminal features title-cased; the matching Hayes
bundle keys are recognised by the engine identically). Ordering
here also fixes the column order of
generated bundles so positional iteration over PanPhon's name
vector pairs values to the right column even when PanPhon adds new
columns in a future release (unknown PanPhon names are skipped
silently rather than raising).
"""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping

from phonology_shared.data.inventory import canonicalize_segment_label

PANPHON_TO_APP_FEATURE: Mapping[str, str] = {
    "syl": "Syllabic",
    "son": "Sonorant",
    "cons": "Consonantal",
    "cont": "Continuant",
    "delrel": "DelRel",
    "lat": "Lateral",
    "nas": "Nasal",
    "strid": "Strident",
    "voi": "Voice",
    "sg": "SpreadGl",
    "cg": "ConstrGl",
    "ant": "Anterior",
    "cor": "Coronal",
    "distr": "Distributed",
    "lab": "Labial",
    "hi": "High",
    "lo": "Low",
    "back": "Back",
    "round": "Round",
    "velaric": "Velaric",
    "tense": "Tense",
    "long": "Long",
    "hitone": "HighTone",
    "hireg": "HighRegister",
}


def panphon_value_to_app(value: object) -> str:
    """Coerce a single PanPhon feature value to the app's three-
    valued vocabulary.

    PanPhon emits ``"+"`` / ``"-"`` / ``"0"`` from
    :py:meth:`Segment.strings`; the numeric path (``1``, ``-1``,
    ``0``) is supported for forward-compatibility with PanPhon
    versions that switch their default representation.
    """
    if value in ("+", 1):
        return "+"
    if value in ("-", -1):
        return "-"
    return "0"


# COMBINING DOUBLE INVERTED BREVE (U+0361): the over-tiebar PanPhon
# uses for EVERY affricate / co-articulated segment in its table.
_TIEBAR = "͡"
# COMBINING DOUBLE BREVE BELOW (U+035C): the under-tiebar variant.
# Always a tiebar, so it folds to the over-tiebar unconditionally.
_UNDER_TIEBAR = "͜"

#: Affricate (and doubly-articulated stop) cores PanPhon recognises,
#: as ``(left, right)`` base-letter pairs. Derived from every
#: over-tiebar entry in PanPhon's ``ipa_all`` table (the left/right
#: letter around the first tiebar), so the set is exhaustive against
#: the installed PanPhon. ``ɡ`` is the script g (U+0261) PanPhon uses;
#: :py:func:`canonicalize_segment_label` folds ASCII ``g`` to it first.
#: PanPhon writes these ONLY with the over-tiebar, so a user who types
#: the under-tiebar, the ASCII-hyphen convention (``t-ʃ``), or the bare
#: digraph (``tʃ``) otherwise gets two segments and an unresolved
#: lookup. The list is explicit (not "any consonant pair") so a real
#: cluster the user intends is never silently fused.
_AFFRICATE_PAIRS: tuple[tuple[str, str], ...] = (
    ("b", "d"),
    ("b", "v"),
    ("b", "β"),  # b͡β
    ("d", "z"),
    ("d", "ɮ"),  # d͡ɮ
    ("d", "ʑ"),  # d͡ʑ
    ("d", "ʒ"),  # d͡ʒ
    ("k", "p"),
    ("k", "x"),
    ("p", "f"),
    ("p", "t"),
    ("p", "ɸ"),  # p͡ɸ
    ("q", "χ"),  # q͡χ
    ("t", "s"),
    ("t", "ɕ"),  # t͡ɕ
    ("t", "ɬ"),  # t͡ɬ
    ("t", "ʃ"),  # t͡ʃ
    ("ɖ", "ʐ"),  # ɖ͡ʐ
    ("ɟ", "ʝ"),  # ɟ͡ʝ
    ("ɡ", "b"),  # ɡ͡b
    ("ɡ", "ɣ"),  # ɡ͡ɣ
    ("ɢ", "ʁ"),  # ɢ͡ʁ
    ("ʈ", "ʂ"),  # ʈ͡ʂ
)

#: Variant diacritic codepoints PanPhon does NOT recognise (it folds
#: input with NFD only and these are absent from its table, so it
#: silently DROPS them and returns the bare-base features) mapped to
#: the codepoint PanPhon does carry. Conservative: only forms that are
#: unambiguous for the target diacritic. The ASCII apostrophe (U+0027)
#: and ASCII ``g`` are already handled upstream by
#: :py:func:`canonicalize_segment_label`, so they are not repeated here.
_DIACRITIC_VARIANTS: Mapping[str, str] = {
    "’": "ʼ",  # ' RIGHT SINGLE QUOTATION MARK -> ʼ (ejective)
    "′": "ʼ",  # ′ PRIME -> ʼ (ejective)
    ":": "ː",  # : COLON -> ː (long)
}


def to_panphon_form(segment: str) -> str:
    """Map a user segment to its PanPhon-compatible LOOKUP form.

    The original segment is never mutated: callers look features up on
    the returned string but keep storing and displaying the user's
    own input. This lets PanPhon resolve segments written with common
    non-PanPhon conventions (the under-tiebar or ASCII-hyphen affricate
    notations, smart-quote ejectives, an ASCII length colon) that
    PanPhon would otherwise split or silently strip.

    Pipeline, deliberately built ON TOP of the wide-scope inventory
    canonicalisation rather than duplicating it:

    1. :py:func:`canonicalize_segment_label` -- NFC, strip, and the
       shared IPA folds (ASCII ``g`` -> ``ɡ``, ``'`` -> ``ʼ``). This is
       the single source of IPA glyph folding; PanPhon reuses it.
    2. Affricate tiebars: the under-tiebar folds to the over-tiebar
       unconditionally; the ASCII-hyphen and bare-digraph forms of the
       explicit :py:data:`_AFFRICATE_PAIRS` fold to the over-tiebar.
    3. The conservative :py:data:`_DIACRITIC_VARIANTS` lookalike fold.
    4. NFD -- the form PanPhon normalises its own table and inputs to,
       so the returned string matches both the live ``FeatureTable``
       and the baked lookup snapshot (which carries NFD keys).

    Idempotent on a string already in PanPhon form.
    """
    s = canonicalize_segment_label(segment)
    s = s.replace(_UNDER_TIEBAR, _TIEBAR)
    for left, right in _AFFRICATE_PAIRS:
        s = s.replace(f"{left}-{right}", f"{left}{_TIEBAR}{right}")
        s = s.replace(f"{left}{right}", f"{left}{_TIEBAR}{right}")
    for variant, canonical in _DIACRITIC_VARIANTS.items():
        s = s.replace(variant, canonical)
    return unicodedata.normalize("NFD", s)
