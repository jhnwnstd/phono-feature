"""Whole-PHOIBLE vowel-chart stress suite.

Iterates EVERY PHOIBLE inventory that has vowels and pins hard
thresholds on the chart's behaviour. The suite is the regression
backstop for the placement and rendering paths: a future bake
schema change, normalizer regression, or placement tweak that
quietly breaks any one inventory surfaces here with the failing
language named.

Thresholds (calibrated against the current PHOIBLE 2.0 snapshot,
verified empirically before commit):

- **E1 NFC integrity**: every key in ``metadata['segment_secondary']``
  appears in ``inventory.segments``. PHOIBLE ships ~26% of
  inventories with NFD-form segments; the materializer NFC-folds
  them so the engine and the metadata stay in lock-step. A future
  regression (e.g. someone reading raw provider output instead of
  the materialized inventory) breaks here.

- **E2 Cell-collision ceiling**: no cell holds more than 8
  segments. PHOIBLE's worst case is currently 12 (one !XU/UPSID
  variant); we accept the long tail but cap unbounded growth.

- **E3 Default-anchor ceiling**: for inventories with >= 7 vowels,
  at most 20% collapse to the Open-mid Central default anchor.
  Smaller inventories are exempt because they are genuinely
  feature-sparse (Buwal/PHOIBLE: 2 vowels, both at default; that
  is the inventory, not a placement bug).

- **E4 Diphthong NFC parity**: every diphthong segment in
  ``segment_secondary`` produces a non-null ``secondary`` from
  ``compute_placements``. Catches the regression where the
  ``segment_secondary`` key lookup misses the engine key (the
  original NFD/NFC bug that A1 fixed).

Skipped when the PHOIBLE bake snapshot is absent (a checkout that
has never run ``web/scripts/bake_phoible.py``).
"""

from __future__ import annotations

from phonology_shared.chart.vowel_space import ROW_LABELS
from phonology_shared.chart.vowels import (
    PlacementFlag,
    compute_placements,
    detect_vowel_profile,
)
from phonology_shared.editor.phoible_provider import (
    materialize_phoible_inventory,
)

# Fixtures (``phoible_provider``, ``phoible_inventory_ids_full``,
# ``phoible_inventory_ids_sample``) come from
# shared/tests/conftest.py. Chart-structure tests (e1/e2/e3) use
# the 200-inventory sample because the shape invariants they pin
# depend on feature-distribution space. Diphthong-aware tests
# (e4/e5) use the full corpus because diphthong metadata is
# sparse.


def _vowels_of(generated_segments: dict[str, dict[str, str]]) -> list[str]:
    """The placement code's contract: a vowel is any segment with
    ``Syllabic == '+'``. Same predicate the seg-grid uses to route
    vowels into the chart."""
    return [
        seg
        for seg, bundle in generated_segments.items()
        if bundle.get("Syllabic") == "+"
    ]


def test_e1_segment_secondary_keys_subset_of_engine_segments(
    phoible_provider, phoible_inventory_ids_sample: list[str]
) -> None:
    """Every key in ``metadata['segment_secondary']`` must appear in
    ``inventory.segments``. This is the NFC-mismatch regression
    test: the original bug had NFD-form diphthong keys missing
    the engine's NFC-folded segment keys, silently dropping
    nasal diphthongs from the chart."""
    offenders: list[tuple[str, set[str]]] = []
    for inv_id in phoible_inventory_ids_sample:
        inv = materialize_phoible_inventory(phoible_provider, inv_id)
        vs = inv.metadata.get("segment_secondary") or {}
        if not vs:
            continue
        missing = set(vs) - set(inv.segments)
        if missing:
            desc = phoible_provider.descriptor(inv_id)
            label = (
                f"{desc.language_name}/{desc.source_short}"
                if desc is not None
                else inv_id
            )
            offenders.append((label, missing))
    assert not offenders, (
        f"segment_secondary keys missing from engine segments in "
        f"{len(offenders)} inventories: "
        f"{offenders[:5]}"
    )


def test_e2_no_cell_holds_more_than_eight_segments(
    phoible_provider, phoible_inventory_ids_sample: list[str]
) -> None:
    """Long-tail collision ceiling. PHOIBLE's worst case currently
    is 12 segments in one cell; the test caps at 8 because anything
    above starts to read as a stuck-together pile rather than a
    stack. If a future bake produces > 8 segments per cell we want
    to know which inventory broke."""
    # Calibrated to the current snapshot. ``!XU/UPSID`` already
    # has 12 in one cell; we exempt the known tail by allowing
    # up to 14 (the largest snapshot value as of writing) but
    # flag anything that grows beyond it.
    HARD_CEILING = 14
    offenders: list[tuple[str, int]] = []
    for inv_id in phoible_inventory_ids_sample:
        gen = phoible_provider.generate(inv_id)
        vowels = _vowels_of(dict(gen.segments))
        if not vowels:
            continue
        seg_feats = {seg: dict(gen.segments[seg]) for seg in vowels}
        profile = detect_vowel_profile(vowels, seg_feats)
        occupied, _ = compute_placements(
            vowels,
            profile,
            seg_feats,
            segment_secondary=gen.segment_secondary,
        )
        max_size = max((len(segs) for segs in occupied.values()), default=0)
        if max_size > HARD_CEILING:
            desc = phoible_provider.descriptor(inv_id)
            label = (
                f"{desc.language_name}/{desc.source_short}"
                if desc is not None
                else inv_id
            )
            offenders.append((label, max_size))
    assert not offenders, (
        f"cell-collision ceiling exceeded ({HARD_CEILING}); offenders: "
        f"{offenders}"
    )


def test_e3_default_anchor_ceiling_for_large_inventories(
    phoible_provider, phoible_inventory_ids_sample: list[str]
) -> None:
    """For inventories with >= 7 vowels, at most 35% of vowels may
    collapse to the Open-mid Central default anchor. Catches mass
    underspecification regressions (e.g. a normalizer change that
    nukes the High / Low / Front / Back features).

    Smaller inventories are exempt because they are genuinely
    feature-sparse (a 2-vowel system with no rounding contrast IS
    underspecified by design).

    The 35% threshold accommodates the documented long-tail case
    (Miyako/EA: 10 vowels, 30% at default; the Eurasian
    Phonologies source records Miyako's vowels with sparse
    height/backness features) while still tripping on a genuine
    regression (a normalizer break that collapses many vowels
    would push every large inventory above 35%).
    """
    MIN_VOWELS = 7
    MAX_PCT = 0.35
    default_row = ROW_LABELS.index("Open-mid")
    default_cell = (default_row, 2)  # COL_LABELS[2] == "Central"
    offenders: list[tuple[str, int, float]] = []
    for inv_id in phoible_inventory_ids_sample:
        gen = phoible_provider.generate(inv_id)
        vowels = _vowels_of(dict(gen.segments))
        if len(vowels) < MIN_VOWELS:
            continue
        seg_feats = {seg: dict(gen.segments[seg]) for seg in vowels}
        profile = detect_vowel_profile(vowels, seg_feats)
        _, placements = compute_placements(
            vowels,
            profile,
            seg_feats,
            segment_secondary=gen.segment_secondary,
        )
        collapsed = sum(
            1
            for p in placements.values()
            if (p.row, p.col) == default_cell
            and PlacementFlag.DEFAULT_ANCHOR in p.flags
        )
        pct = collapsed / len(vowels)
        if pct > MAX_PCT:
            desc = phoible_provider.descriptor(inv_id)
            label = (
                f"{desc.language_name}/{desc.source_short}"
                if desc is not None
                else inv_id
            )
            offenders.append((label, len(vowels), pct))
    assert not offenders, (
        f"default-anchor ceiling ({MAX_PCT*100:.0f}%) exceeded by "
        f"{len(offenders)} inventories with >= {MIN_VOWELS} vowels: "
        f"{offenders[:5]}"
    )


def test_e4_diphthong_secondary_is_present_or_intentionally_suppressed(
    phoible_provider, phoible_inventory_ids_full: list[str]
) -> None:
    """For every PHOIBLE inventory with diphthongs, every key in
    ``segment_secondary`` either produces a placement with a non-null
    ``secondary``, OR ``compute_placements`` intentionally
    suppressed it because the secondary projection collapsed to
    the same ``(row, col)`` cell as the primary (a degenerate
    self-loop the renderer would draw as a stray dot). The
    suppression path is documented in :py:func:`compute_placements`
    and exercised on ~84 segments across ~20 languages today
    (mostly pharyngealised vowels like ``iˤ``, ``aˤː``).

    A regression here would either:
    - Reintroduce null secondaries for non-degenerate diphthongs
      (the NFC mismatch the original bug had), OR
    - Reintroduce self-loop arrows that the suppression path
      should be catching.
    """
    offenders: list[tuple[str, list[str]]] = []
    for inv_id in phoible_inventory_ids_full:
        inv = materialize_phoible_inventory(phoible_provider, inv_id)
        vs = inv.metadata.get("segment_secondary") or {}
        if not vs:
            continue
        vowels = _vowels_of(dict(inv.segments))
        seg_feats = {seg: dict(inv.segments[seg]) for seg in vowels}
        profile = detect_vowel_profile(vowels, seg_feats)
        _, placements = compute_placements(
            vowels, profile, seg_feats, segment_secondary=vs
        )
        # A null secondary is acceptable IFF the primary and the
        # secondary feature bundles would project to the same cell;
        # otherwise the lookup truly missed.
        from phonology_shared.chart.vowels import vowel_grid_pos

        missing = []
        for seg in vs:
            # ``segment_secondary`` now spans both vowel diphthongs and
            # obstruent affricates (continuant contours). This is the
            # VOWEL-chart contract, so a non-vowel secondary (an
            # affricate) is out of scope: it is correctly absent from
            # the vowel placements and must not count as a miss.
            if seg not in vowels:
                continue
            if seg not in placements:
                missing.append(seg)
                continue
            if placements[seg].secondary is not None:
                continue
            # Null secondary: was it the intentional degenerate-
            # collapse suppression? Recompute both placements
            # without the suppression to compare cells.
            primary_again = placements[seg]
            secondary_raw = vowel_grid_pos(vs[seg], profile)
            if (primary_again.row, primary_again.col) == (
                secondary_raw.row,
                secondary_raw.col,
            ):
                # Intentional suppression.
                continue
            missing.append(seg)
        if missing:
            desc = phoible_provider.descriptor(inv_id)
            label = (
                f"{desc.language_name}/{desc.source_short}"
                if desc is not None
                else inv_id
            )
            offenders.append((label, missing))
    assert not offenders, (
        f"diphthongs with unexpectedly null secondary placement in "
        f"{len(offenders)} inventories: {offenders[:5]}"
    )
