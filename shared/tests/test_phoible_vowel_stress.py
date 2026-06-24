"""PHOIBLE vowel-placement stress-test bank.

PHOIBLE bundles a wide tail of vowel systems that the bundled
inventories (English / Hayes / General) do not exercise: small
3-vowel systems, dense 28-vowel systems with multiple diphthongs,
glide-final contours, ATR splits in West African languages. None
of these existed in the test suite before the diphthong wiring
landed, so a quiet regression in the placement code could break
them invisibly.

This module loads ~8 representative PHOIBLE inventories spanning
small / medium / large vowel counts and including known diphthong
languages, then drives them through :py:func:`compute_placements`
and asserts that:

* The default Open-mid Central anchor does NOT swallow most vowels
  (catches mass underspecification).
* Where the bake snapshot records a vowel diphthong, the placement
  carries the ``DIPHTHONG`` flag and a non-null ``secondary``.
* No two distinct diphthong segments end up sharing the exact
  ``(primary_cell, secondary_cell)`` pair (catches arrow overlay
  collisions).

The bank is parametrised so a future PHOIBLE re-bake that breaks a
single inventory surfaces here with the failing language named.

Skipped when the PHOIBLE bake snapshot is absent (e.g. a desktop
checkout that never ran ``web/scripts/bake_phoible.py``); the file
``_phoible_data.generated.json`` is gitignored on purpose.
"""

from __future__ import annotations

import pytest

from phonology_shared.chart.vowel_space import ROW_LABELS
from phonology_shared.chart.vowels import (
    PlacementFlag,
    compute_placements,
    detect_vowel_profile,
)

# ``phoible_provider`` comes from shared/tests/conftest.py and
# handles the "snapshot not baked" skip in one place.


# The stress bank. Each entry is ``(language, source_short)``; we
# look up the inventory id at runtime so the test stays robust to
# bake-snapshot renumbering. Picked to span vowel-system shapes:
#
# - Japanese PHOIBLE: 5 vowels, no diphthongs (small monophthong system)
# - Yoruba UPSID: 11 vowels, no diphthongs (mid-size ATR system)
# - Spanish PHOIBLE: 12 vowels, 7 diphthongs (Romance with rich glides)
# - German PHOIBLE: 19 vowels, 3 diphthongs (Germanic with /aɪ aʊ ɔʏ/)
# - Vietnamese PHOIBLE: 16 vowels, 3 diphthongs (tonal language)
# - Thai PHOIBLE: 21 vowels, 3 diphthongs (long-vowel pairs)
# - Korean PHOIBLE: 28 vowels, 12 diphthongs (largest in the bank)
# - Mandarin SPA: 12 vowels, 0 diphthongs (cross-source coverage)
STRESS_BANK: list[tuple[str, str]] = [
    ("Japanese", "PHOIBLE"),
    ("Yoruba", "UPSID"),
    ("Spanish", "PHOIBLE"),
    ("German", "PHOIBLE"),
    ("Vietnamese", "PHOIBLE"),
    ("Thai", "PHOIBLE"),
    ("Korean", "PHOIBLE"),
    ("Mandarin Chinese", "SPA"),
]


def _find_inventory_id(
    phoible_provider, language: str, source_short: str
) -> str | None:
    """Look up an inventory id by language + source short label.
    Returns ``None`` when the (language, source) pair is not in the
    snapshot so the test parametrisation skips it rather than
    failing for a release-level data shift."""
    for descriptor in phoible_provider.list_inventories(language):
        if descriptor.source_short == source_short:
            return descriptor.id
    return None


@pytest.mark.parametrize(
    "language,source_short",
    STRESS_BANK,
    ids=[f"{lang}-{src}" for lang, src in STRESS_BANK],
)
def test_phoible_vowel_placement_does_not_collapse(
    phoible_provider, language: str, source_short: str
) -> None:
    """For every inventory in the stress bank, ensure the vowel
    placement spreads across cells rather than dumping the system
    into the Open-mid Central default. Pins that the placement
    code keeps working on the long tail of PHOIBLE vowel
    inventories."""
    inv_id = _find_inventory_id(phoible_provider, language, source_short)
    if inv_id is None:
        pytest.skip(
            f"PHOIBLE inventory not present: {language}/{source_short}"
        )
    generated = phoible_provider.generate(inv_id)
    vowels = [
        seg
        for seg, b in generated.segments.items()
        if b.get("Syllabic") == "+"
    ]
    if not vowels:
        pytest.skip(f"{language}/{source_short} has no vowels")

    seg_feats = {seg: dict(generated.segments[seg]) for seg in vowels}
    profile = detect_vowel_profile(vowels, seg_feats)
    occupied, placements = compute_placements(
        vowels,
        profile,
        seg_feats,
        segment_secondary=generated.segment_secondary,
    )

    open_mid_row = ROW_LABELS.index("Open-mid")
    central_col = 2  # COL_LABELS == ("Front", "Central", "Back")
    default_anchor = (open_mid_row, central_col)
    default_count = sum(
        1
        for p in placements.values()
        if (p.row, p.col) == default_anchor
        and PlacementFlag.DEFAULT_ANCHOR in p.flags
    )
    assert default_count <= max(1, len(vowels) // 2), (
        f"{language}/{source_short}: {default_count} of {len(vowels)} "
        f"vowels collapsed to the Open-mid Central default anchor; "
        f"placement appears broken on this inventory"
    )


@pytest.mark.parametrize(
    "language,source_short",
    [
        ("Spanish", "PHOIBLE"),
        ("German", "PHOIBLE"),
        ("Vietnamese", "PHOIBLE"),
        ("Thai", "PHOIBLE"),
        ("Korean", "PHOIBLE"),
    ],
    ids=lambda v: v,
)
def test_phoible_diphthongs_round_trip_secondary_and_flag(
    phoible_provider, language: str, source_short: str
) -> None:
    """Inventories with diphthongs in the bake snapshot must
    surface them through the placement layer: each diphthong's
    placement carries a non-null ``secondary`` and the
    ``DIPHTHONG`` flag, and no two distinct diphthongs share the
    exact ``(primary_cell, secondary_cell)`` pair (otherwise the
    SVG arrow overlay would render two arrows on top of one
    another)."""
    inv_id = _find_inventory_id(phoible_provider, language, source_short)
    if inv_id is None:
        pytest.skip(
            f"PHOIBLE inventory not present: {language}/{source_short}"
        )
    generated = phoible_provider.generate(inv_id)
    if not generated.segment_secondary:
        pytest.skip(
            f"{language}/{source_short} carries no diphthongs in the bake"
        )

    vowels = [
        seg
        for seg, b in generated.segments.items()
        if b.get("Syllabic") == "+"
    ]
    seg_feats = {seg: dict(generated.segments[seg]) for seg in vowels}
    profile = detect_vowel_profile(vowels, seg_feats)
    _, placements = compute_placements(
        vowels,
        profile,
        seg_feats,
        segment_secondary=generated.segment_secondary,
    )

    # ``segment_secondary`` now also holds obstruent affricate
    # contours, so intersect with the vowel set: a vowel diphthong is
    # a vowel that carries a secondary phase.
    diphthongs = [seg for seg in vowels if seg in generated.segment_secondary]
    assert diphthongs, "fixture invariant: this inventory has vowel diphthongs"

    seen_pairs: dict[tuple[tuple[int, int], tuple[int, int]], str] = {}
    for seg in diphthongs:
        p = placements[seg]
        assert (
            p.secondary is not None
        ), f"{language}: diphthong /{seg}/ has no secondary placement"
        assert (
            PlacementFlag.DIPHTHONG in p.flags
        ), f"{language}: diphthong /{seg}/ primary missing DIPHTHONG flag"
        assert (
            PlacementFlag.DIPHTHONG in p.secondary.flags
        ), f"{language}: diphthong /{seg}/ secondary missing DIPHTHONG flag"
        pair = ((p.row, p.col), (p.secondary.row, p.secondary.col))
        if pair in seen_pairs:
            # Same cells, different glyphs: two arrows would render
            # on top of each other. Allow only if the glyphs are
            # identical (a true duplicate that the bake already
            # de-duped above).
            assert seen_pairs[pair] == seg, (
                f"{language}: diphthongs /{seen_pairs[pair]}/ and /{seg}/ "
                f"both place at the same primary->secondary cell pair "
                f"{pair}; the arrow overlay would render them on top of "
                f"each other"
            )
        else:
            seen_pairs[pair] = seg
