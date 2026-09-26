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
_CONSONANT_MANNER_PHASE_FEATURES: frozenset[str] = frozenset(
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
_VOWEL_QUALITY_PHASE_FEATURES: frozenset[str] = frozenset(
    {"Syllabic", "High", "Low", "Front", "Back", "Tense", "ATR"}
)

#: Duration is phase-forming for BOTH major classes, so it joins each set
#: below rather than sitting in either. A comma here is not a base plus a
#: diacritic; it is the source stating how long each part of the segment
#: is, which is the same kind of fact as a manner or quality contour. A
#: long-first diphthong (``iːe``, ``long = "+,-"``), a long-last one
#: (``iaː``, ``"-,+"``) and a geminate affricate (``t̟ːɕ̟``) all say it.
#:
#: Left out of both sets originally, duration fell to the secondary-
#: articulation branch, which keeps the LAST value. That reads correctly
#: for a diacritic overlay, where the last value IS the modified one, and
#: backwards for a timeline: ``iːe`` stored ``Long = "-"`` and answered
#: NO to ``[+long]`` in strict AND wildcard, while ``iaː`` stored ``"+"``
#: and answered yes. Identical source encodings, opposite answers, decided
#: only by which phase happened to be long (32 of PHOIBLE's 79 ``long``
#: contours are the ``"+,-"`` shape). Collapsing here is not faithfulness
#: to the source; it asserts a duration for a phase the source gave a
#: different one.
#:
#: Safe to phase: every duration sequence PHOIBLE states already agrees in
#: length with the manner or quality contour beside it, so this adds no
#: :py:class:`~phonology_shared.data.tiers.Misaligned` segment and moves
#: none from one phase to two (verified corpus-wide; pinned by
#: ``test_phoible_adapter.py``).
_DURATION_PHASE_FEATURES: frozenset[str] = frozenset({"Long", "Short"})

_CONSONANT_PHASE_FEATURES: frozenset[str] = (
    _CONSONANT_MANNER_PHASE_FEATURES | _DURATION_PHASE_FEATURES
)
_VOWEL_PHASE_FEATURES: frozenset[str] = (
    _VOWEL_QUALITY_PHASE_FEATURES | _DURATION_PHASE_FEATURES
)


def partition_tiers(
    tiers: Mapping[str, tuple[str, ...]],
) -> tuple[dict[str, str], dict[str, tuple[str, ...]]]:
    """Split a verbatim tier map into a single-value PRIMARY bundle and the
    GENUINE contour sequences, resolving secondary articulations formally.

    Returns ``(primary, genuine)``. ``primary`` gives every feature one
    value; ``genuine`` holds only the features whose sequence is a real
    intra-segmental timeline, so a consumer reading ``genuine`` sees a
    phase boundary ONLY where the source licensed one.

    A sequence qualifies two ways, and NEITHER asks what the feature
    means:

    1. **By name.** The feature is phase-forming for the segment's major
       class (:py:data:`_CONSONANT_PHASE_FEATURES` on a consonant,
       :py:data:`_VOWEL_PHASE_FEATURES` on a vowel, each already
       including :py:data:`_DURATION_PHASE_FEATURES`). This encodes
       PHOIBLE's stated convention about where it writes contours.
    2. **By length agreement.** Those features fix a phase count ``n``
       for this segment; any OTHER sequence of length exactly ``n`` is a
       column of that same timeline. ``/tx/`` states ``continuant`` and
       ``delayedRelease`` over 2 phases and ``coronal`` over 2, so the
       closure really is coronal and the release really is not.

    Everything else is a secondary articulation (a lone ``kʷ``
    ``labial`` ``-,+``, a pharyngealized vowel's
    ``retractedTongueRoot``): it never appears in ``genuine`` and its
    ``primary`` value is the source's stated modified value (the
    sequence's last), so the segment stays single-phase and a query does
    not see a spurious base polarity.

    Rule 2 needs rule 1 to have fired FIRST, on some other feature. That
    is the whole discriminator: ``/kʷ/`` collapses not because ``labial``
    is a place feature but because nothing else in ``/kʷ/`` contours, so
    there is no independently established structure for its sequence to
    agree with. Two sequences that both fail rule 1 never bootstrap each
    other: ``/ŋm/`` (``labial -,+`` against ``dorsal +,-``) stays
    collapsed, because a doubly-articulated segment and a two-phase one
    are indistinguishable by length alone and the source composes the
    former exactly the way it composes ``/kʷ/``.

    An admitted sequence has length ``n`` by construction, so it can
    never be the tier that makes the segment
    :py:class:`~phonology_shared.data.tiers.Misaligned`, and a ``"0"``
    inside one stays properly partial: that phase simply does not value
    the feature, rather than being handed the last phase's value.

    Major class is read existentially: a segment is a vowel iff SOME phase
    is ``[+syllabic]``, so a rising diphthong (``i̯a``, whose onset is
    the non-syllabic glide) is still a vowel and keeps its quality glide.
    A phase-forming feature's ``primary`` value is its onset (index 0), an
    arbitrary but total anchor; the authoritative reading is ``genuine``.

    Major class selects only which SUBSTANTIVE dimension may contour
    (manner for a consonant, quality for a vowel). Duration contours on
    either, so it is phase-forming in both branches; see
    :py:data:`_DURATION_PHASE_FEATURES` for why it must not collapse.
    """
    is_vowel = "+" in tiers.get("Syllabic", ())
    phase_forming = (
        _VOWEL_PHASE_FEATURES if is_vowel else _CONSONANT_PHASE_FEATURES
    )
    # The phase count the source establishes INDEPENDENTLY of any one
    # non-phase-forming feature: the common length of the contours that
    # are phase-forming by name. Defined only when there is at least one
    # and they agree, which is what makes it evidence rather than a
    # guess. ``None`` for a single-phase segment (nothing to agree with)
    # and for a ragged one (the source already underdetermines the
    # timeline, so it cannot license anything).
    core_lengths = {
        len(t) for f, t in tiers.items() if len(t) > 1 and f in phase_forming
    }
    n = core_lengths.pop() if len(core_lengths) == 1 else None

    def is_timeline(feat: str, tier: tuple[str, ...]) -> bool:
        """The two ways a sequence qualifies (see the docstring above).
        By NAME: phase-forming for this major class. By LENGTH
        AGREEMENT: the source fixed an ``n``-phase structure without
        this feature and then stated exactly ``n`` values for it, so it
        is a column of that same timeline. Neither arm asks what the
        feature MEANS, and the second cannot fire unless the first
        already did on some other feature."""
        return feat in phase_forming or (n is not None and len(tier) == n)

    primary: dict[str, str] = {}
    genuine: dict[str, tuple[str, ...]] = {}
    for feat, tier in tiers.items():
        if len(tier) == 1:
            primary[feat] = tier[0]
        elif is_timeline(feat, tier):
            genuine[feat] = tier
            primary[feat] = tier[0]  # onset anchor; genuine is authoritative
        else:
            # Secondary articulation: co-occurring, not a timeline. Keep
            # the source's stated (modified) value and create no phase.
            primary[feat] = tier[-1]
    return primary, genuine
