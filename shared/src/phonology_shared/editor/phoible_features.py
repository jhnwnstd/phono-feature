# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Required Notice: Copyright 2026 John Winstead,
# https://github.com/jhnwnstd/phono-feature
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


def phoible_row_to_tiers(
    row: Mapping[str, str],
) -> dict[str, tuple[str, ...]]:
    """Convert one raw PHOIBLE feature row into canonical per-feature
    TIERS ``{app_feature: (value, ...)}``.

    This is the PHOIBLE adapter: the single place that encodes PHOIBLE's
    facts and commits to nothing above them. It knows the app feature
    names (:py:data:`PHOIBLE_TO_APP_FEATURE`), the ``+`` / ``-`` / ``0``
    alphabet, the comma-separated contour convention, and the rule that a
    feature which does not change is written single-valued (so there is
    never a constant ``"+,+"`` contour). Each feature maps to the
    VERBATIM sequence of values PHOIBLE states, in order; nothing is
    flattened, reduced, or aligned here.

    A PHOIBLE column that is empty or ``"NA"`` is source SILENCE and is
    omitted, which is distinct from a stated ``"0"`` (an asserted
    not-applicable, kept as ``("0",)``). :py:func:`ValueError` is raised
    on a token outside the alphabet or a constant contour, so a
    malformed source row surfaces instead of being silently patched.
    """
    tiers: dict[str, tuple[str, ...]] = {}
    for phoible_col, app_name in PHOIBLE_TO_APP_FEATURE.items():
        raw = row.get(phoible_col, "")
        if raw in ("", "NA"):
            continue  # source silence: distinct from a stated "0"
        parts = tuple(p.strip() for p in raw.split(","))
        bad = [p for p in parts if p not in ("+", "-", "0")]
        if bad:
            raise ValueError(
                f"{app_name}: value(s) {bad!r} outside the +/-/0 alphabet"
            )
        if len(parts) > 1 and len(set(parts)) == 1:
            raise ValueError(
                f"{app_name}: constant contour {parts!r}; PHOIBLE writes "
                "a single value for a feature that does not change"
            )
        tiers[app_name] = parts
    return tiers


def tiers_to_cells(
    tiers: Mapping[str, tuple[str, ...]],
) -> dict[str, str]:
    """Round-trip a tier map back to PHOIBLE-style cells: join each
    sequence with commas, a singleton staying single. Order preserved, so
    ``("-", "+")`` re-emits ``"-,+"`` and never ``"+,-"``."""
    return {
        feat: (vals[0] if len(vals) == 1 else ",".join(vals))
        for feat, vals in tiers.items()
    }


#: Features whose value SEQUENCE is a genuine intra-segmental timeline the
#: source encodes as a temporal contour, split by major class. PHOIBLE's
#: own convention (dev FEATURES; Moran & McCloy 2019) writes a temporal
#: contour on a MANNER feature for a consonant (a stop closure releasing
#: into a fricative writes ``continuant``/``delayedRelease``; a
#: prenasalized stop writes ``nasal``/``sonorant``) and on a QUALITY
#: feature for a vowel (a diphthong glides through ``high``/``front``/...).
#: A comma on any OTHER feature is a secondary articulation the source
#: composed from a base plus a diacritic (``kʷ`` writes ``labial`` as
#: ``-,+`` = base ``k`` then the ``ʷ`` modification, ``aˤ`` writes
#: ``retractedTongueRoot`` for pharyngealization), which co-occurs and is
#: NOT a timeline. Reading this split is a formal statement about the
#: source's encoding, not a phonetic claim about what the features mean.
_CONSONANT_PHASE_FEATURES: frozenset[str] = frozenset(
    {
        "Consonantal",
        "Sonorant",
        "Continuant",
        "Nasal",
        "DelRel",
        "Approximant",
        "Tap",
        "Trill",
        "Lateral",
    }
)
_VOWEL_PHASE_FEATURES: frozenset[str] = frozenset(
    {"Syllabic", "High", "Low", "Front", "Back", "Tense", "ATR"}
)


def partition_tiers(
    tiers: Mapping[str, tuple[str, ...]],
) -> tuple[dict[str, str], dict[str, tuple[str, ...]]]:
    """Split a verbatim tier map into a single-value PRIMARY bundle and the
    GENUINE contour sequences, resolving secondary articulations formally.

    Returns ``(primary, genuine)``. ``primary`` gives every feature one
    value; ``genuine`` holds only the features whose sequence is a real
    intra-segmental timeline (:py:data:`_CONSONANT_PHASE_FEATURES` on a
    consonant, :py:data:`_VOWEL_PHASE_FEATURES` on a vowel), so a consumer
    reading ``genuine`` sees a phase boundary ONLY where the source
    licensed one. A feature that varies but is NOT phase-forming is a
    secondary articulation (a lone ``kʷ`` ``labial`` ``-,+`` or a
    pharyngealized vowel's ``retractedTongueRoot``): it never appears in
    ``genuine`` and its ``primary`` value is the source's stated modified
    value (the sequence's last), so the segment stays single-phase and a
    query does not see a spurious base polarity.

    Major class is read existentially: a segment is a vowel iff SOME phase
    is ``[+syllabic]``, so a rising diphthong (``i̯a``, whose onset is
    the non-syllabic glide) is still a vowel and keeps its quality glide.
    A phase-forming feature's ``primary`` value is its onset (index 0), an
    arbitrary but total anchor; the authoritative reading is ``genuine``.
    """
    is_vowel = "+" in tiers.get("Syllabic", ())
    phase_forming = (
        _VOWEL_PHASE_FEATURES if is_vowel else _CONSONANT_PHASE_FEATURES
    )
    primary: dict[str, str] = {}
    genuine: dict[str, tuple[str, ...]] = {}
    for feat, tier in tiers.items():
        if len(tier) == 1:
            primary[feat] = tier[0]
        elif feat in phase_forming:
            genuine[feat] = tier
            primary[feat] = tier[0]  # onset anchor; genuine is authoritative
        else:
            # Secondary articulation: co-occurring, not a timeline. Keep
            # the source's stated (modified) value and create no phase.
            primary[feat] = tier[-1]
    return primary, genuine
