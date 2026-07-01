"""PHOIBLE column-name → app feature-name mapping.

PHOIBLE 2.0 ships SPE-style feature columns. Most map one-for-one
onto an app canonical name (`syllabic` → `Syllabic`); a couple
require semantic aliasing (`periodicGlottalSource` → `Voice`,
`click` → `Velaric`). PHOIBLE-only columns pass through under
PHOIBLE's own names so users see exactly what PHOIBLE specifies
and can drop columns they do not want via the editor's
column-remove gesture.

Lives in shared/ alongside :py:mod:`panphon_features` so the bake
script, the desktop provider, and the web bridge all read from one
source.

Bake-time invariant: the KEY order in this dict fixes the column
order of the JSON snapshot, so reordering or inserting in the
middle rotates the positional encoding and invalidates every
shipped bundle. Append new keys at the end. The VALUES can be
renamed freely; the runtime ``feature_names`` list just picks up
the new labels on the next bake.
"""

from __future__ import annotations

from collections.abc import Mapping

#: PHOIBLE column name -> app feature label. Order matches PHOIBLE's
#: CSV column order so positional iteration in the bake script
#: pairs values to the right column.
PHOIBLE_TO_APP_FEATURE: Mapping[str, str] = {
    # === Header-tier features (suprasegmental). PHOIBLE-only ===
    # PHOIBLE's ``tone`` marks tonality, not pitch height: every tone
    # letter, high or low, carries ``tone=+``. Map it to the generic
    # ``Tone`` marker, not ``HighTone`` (which is the pitch LEVEL).
    "tone": "Tone",
    "stress": "Stress",
    # === Major-class features (overlap with app canonical names) ===
    "syllabic": "Syllabic",
    "short": "Short",
    "long": "Long",
    "consonantal": "Consonantal",
    "sonorant": "Sonorant",
    "continuant": "Continuant",
    "delayedRelease": "DelRel",
    # === Manner features ===
    "approximant": "Approximant",
    "tap": "Tap",
    "trill": "Trill",
    "nasal": "Nasal",
    "lateral": "Lateral",
    # === Place features ===
    "labial": "Labial",
    "round": "Round",
    "labiodental": "Labiodental",
    "coronal": "Coronal",
    "anterior": "Anterior",
    "distributed": "Distributed",
    "strident": "Strident",
    "dorsal": "Dorsal",
    "high": "High",
    "low": "Low",
    "front": "Front",
    "back": "Back",
    "tense": "Tense",
    # PHOIBLE's ``advancedTongueRoot`` and ``retractedTongueRoot``
    # are the canonical +ATR / +RTR phonological features. Mapping
    # them to the short abbreviations reuses the existing ``ATR``
    # slot in :py:data:`FEATURE_GROUPS` and aligns with the way
    # academic papers cite these features.
    "retractedTongueRoot": "RTR",
    "advancedTongueRoot": "ATR",
    # === Laryngeal features ===
    # PHOIBLE uses ``periodicGlottalSource`` for what most SPE
    # tables call ``Voice``. They are not strictly identical
    # (periodic-source is the airstream feature; voicing is
    # phonological) but the values align in 99%+ of cases and
    # mapping aliases let app-side consumers query ``Voice``
    # uniformly across provider sources.
    "periodicGlottalSource": "Voice",
    "epilaryngealSource": "EpilaryngealSource",
    "spreadGlottis": "SpreadGl",
    "constrictedGlottis": "ConstrGl",
    "fortis": "Fortis",
    "lenis": "Lenis",
    "raisedLarynxEjective": "RaisedLarynxEjective",
    "loweredLarynxImplosive": "LoweredLarynxImplosive",
    # === Airstream ===
    # PHOIBLE splits velaric clicks out as their own column;
    # the closest app-side analog is ``Velaric``.
    "click": "Velaric",
}


def normalize_phoible_value(value: str) -> str:
    """Coerce a PHOIBLE feature cell to the app's three-valued
    vocabulary (``"+"`` / ``"-"`` / ``"0"``).

    PHOIBLE's main vocabulary is the same three values. A small
    fraction of rows use comma-separated contour values like
    ``"+,-"`` for segments that change polarity within a feature
    (tone contours, certain affricates, vowel diphthongs). This
    function is the fallback for a cell whose contour the bake does
    NOT preserve: it collapses the contour to ``"0"`` so the engine
    never sees a value outside its three-state enum.

    Contours the bake DOES preserve (any feature on a vowel, and
    ``continuant`` on an obstruent) are split instead via
    :py:func:`split_contour_value` into an ``(initial, final)`` pair
    that becomes two ordinary phases, so this collapse only applies
    to the remaining contours (tone letters, other consonant
    contours). The user can hand-edit those afterwards.
    """
    if value in ("+", "-", "0"):
        return value
    # Contour value (``"+,-"`` or similar) or empty/NA. Treat as
    # unspecified so the engine doesn't see a value outside its
    # three-state enum.
    return "0"


def split_contour_value(value: str) -> tuple[str, str] | None:
    """Return the ``(initial, final)`` pair of a PHOIBLE contour
    value, or ``None`` if ``value`` is not a contour.

    PHOIBLE encodes a contour by writing the two polarities the
    segment traverses, separated by a comma: ``"+,-"`` for a feature
    that starts ``+`` and ends ``-``. A diphthong glides between two
    vowel qualities this way; an affricate's ``continuant`` runs
    ``"-,+"`` as the stop closure releases into a fricative. Both
    polarities must be members of the app's three-valued vocabulary
    after stripping whitespace; anything else returns ``None`` so
    the caller can fall back to :py:func:`normalize_phoible_value`.
    """
    if "," not in value:
        return None
    parts = [p.strip() for p in value.split(",", 1)]
    if len(parts) != 2:
        return None
    initial, final = parts
    if initial not in ("+", "-", "0") or final not in ("+", "-", "0"):
        return None
    return initial, final


def initial_phase_value(value: str) -> str:
    """The ``+``/``-``/``0`` state a PHOIBLE cell STARTS in.

    A contour cell (``"+,-"``) classifies by its initial state, so any
    test that reads a major-class feature to decide a segment's CLASS
    (is it a vowel? an obstruent?) must read the initial phase, never
    the raw cell: ``"+,-" == "+"`` is ``False``, which would misread a
    falling diphthong's contoured ``syllabic`` as non-vowel and a
    prenasalized consonant's contoured ``sonorant`` as non-sonorant. A
    plain cell falls back to :py:func:`normalize_phoible_value`.
    """
    contour = split_contour_value(value)
    return (
        contour[0] if contour is not None else normalize_phoible_value(value)
    )
