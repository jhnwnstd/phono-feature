"""Pin the canonical suprasegmental-feature set.

The 2024 CLTS vector paper and the autosegmental tradition both
single out tone, stress, and length as belonging on a tier separate
from the segmental core. The codebase encodes that judgement in
:py:data:`phonology_shared.presentation.constants.SUPRASEGMENTAL_FEATURES`
and consumes it in two places:

- the tone-phoneme guard in
  :py:func:`phonology_shared.chart.consonants.is_member`
- the Prosodic display group in
  :py:data:`phonology_shared.presentation.constants.FEATURE_GROUPS`

These tests pin three contracts:

- The suprasegmental set covers tone, stress, length, and laryngeal
  register columns. A future refactor that drops a column or adds
  a new one must update both the set and these assertions.
- Every suprasegmental column also appears in the Prosodic display
  group, so the panel never silently surfaces a tone row under a
  segmental section.
- Every suprasegmental column appears in :py:data:`FEATURE_ORDER`,
  so display-order code never trails one of them at the end of the
  list as an "unknown" feature.

The set itself follows the principle from the autosegmental
tradition: keep the segmental core small and uniform, lift
suprasegmental concerns to a separate tier.
"""

from __future__ import annotations

from phonology_shared.presentation.constants import (
    FEATURE_GROUPS,
    FEATURE_ORDER,
    SUPRASEGMENTAL_FEATURES,
)


def test_suprasegmental_set_is_immutable() -> None:
    """``SUPRASEGMENTAL_FEATURES`` is a ``frozenset`` so consumers
    can rely on it being safe to share without defensive copies."""
    assert isinstance(SUPRASEGMENTAL_FEATURES, frozenset)


def test_suprasegmental_set_covers_canonical_columns() -> None:
    """Tone, stress, length, and register columns must all appear.
    A future refactor that drops one of these has to deliberately
    edit this test."""
    expected = {
        "Tone",
        "HighTone",
        "UpperRegister",
        "Stress",
        "Long",
        "Short",
    }
    assert SUPRASEGMENTAL_FEATURES == expected, (
        f"SUPRASEGMENTAL_FEATURES drifted; expected {sorted(expected)}, "
        f"got {sorted(SUPRASEGMENTAL_FEATURES)}"
    )


def test_every_suprasegmental_lives_in_prosodic_group() -> None:
    """The feature panel groups suprasegmentals under ``Prosodic``.
    A column that's listed as suprasegmental but rendered under a
    segmental group (e.g. Manner) would mislead the user about
    which tier the row belongs to."""
    prosodic = next(
        feats for title, feats in FEATURE_GROUPS if title == "Prosodic"
    )
    for feat in SUPRASEGMENTAL_FEATURES:
        assert feat in prosodic, (
            f"{feat} is in SUPRASEGMENTAL_FEATURES but not in the "
            f"Prosodic display group; the panel would render it in "
            f"the wrong section"
        )


def test_every_suprasegmental_has_a_display_order_slot() -> None:
    """Display-order code (``sort_features``) trails unknown
    features at the end. A suprasegmental column dropping out of
    ``FEATURE_ORDER`` would silently end up there, breaking the
    expected Prosodic-group layout."""
    feature_order_set = set(FEATURE_ORDER)
    for feat in SUPRASEGMENTAL_FEATURES:
        assert feat in feature_order_set, (
            f"{feat} is in SUPRASEGMENTAL_FEATURES but missing from "
            f"FEATURE_ORDER; sort_features would treat it as unknown"
        )


def test_no_segmental_anchor_leaked_into_suprasegmental_set() -> None:
    """Sanity check the other direction: classic segmental anchors
    (place, manner, vowel-quality columns) must not appear in the
    suprasegmental set. A leak here would route real consonants
    through the tone-phoneme guard in
    ``phonology_shared.chart.consonants.is_member`` and misclassify
    them."""
    segmental_anchors = {
        "Consonantal",
        "Syllabic",
        "Sonorant",
        "Continuant",
        "Voice",
        "Nasal",
        "Lateral",
        "Trill",
        "Tap",
        "High",
        "Low",
        "Back",
        "Front",
        "Round",
        "ATR",
        "Tense",
    }
    leaked = SUPRASEGMENTAL_FEATURES & segmental_anchors
    assert (
        not leaked
    ), f"segmental anchors leaked into SUPRASEGMENTAL_FEATURES: {leaked}"
