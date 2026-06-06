"""PHOIBLE column-name → app feature-name mapping.

PHOIBLE 2.0 ships 36 SPE-style feature columns; our app exposes
24 canonical names. The overlap is ~13 features that map one-for-
one (`syllabic` → `Syllabic`); two require semantic aliasing
(`periodicGlottalSource` → `Voice`, `click` → `Velaric`); the
remaining PHOIBLE-only columns pass through under PHOIBLE's own
lowercase names so users see exactly what PHOIBLE specifies and
can drop columns they do not want via the editor's column-remove
gesture.

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
    "tone": "HighTone",
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


#: Identity columns PHOIBLE carries that are NOT feature values;
#: the bake script consumes these for the inventory index but
#: never bakes them into per-segment bundles.
PHOIBLE_IDENTITY_COLUMNS: tuple[str, ...] = (
    "InventoryID",
    "Glottocode",
    "ISO6393",
    "LanguageName",
    "SpecificDialect",
    "GlyphID",
    "Phoneme",
    "Allophones",
    "Marginal",
    "SegmentClass",
    "Source",
)


def normalize_phoible_value(value: str) -> str:
    """Coerce a PHOIBLE feature cell to the app's three-valued
    vocabulary (``"+"`` / ``"-"`` / ``"0"``).

    PHOIBLE's main vocabulary is the same three values. A small
    fraction of rows use comma-separated contour values like
    ``"+,-"`` for segments that change polarity within a feature
    (tone contours, certain affricates). The app's engine assumes
    a single value per (segment, feature), so we normalize contours
    to ``"0"`` here; the user can hand-edit afterwards if they need
    precise contour modelling. The bake script logs the count.
    """
    if value in ("+", "-", "0"):
        return value
    # Contour value (``"+,-"`` or similar) or empty/NA. Treat as
    # unspecified so the engine doesn't see a value outside its
    # three-state enum.
    return "0"
