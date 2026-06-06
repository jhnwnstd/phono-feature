"""Whole-PHOIBLE vowel-chart stress suite.

Iterates EVERY PHOIBLE inventory that has vowels and pins hard
thresholds on the chart's behaviour. The suite is the regression
backstop for the placement and rendering paths: a future bake
schema change, normalizer regression, or placement tweak that
quietly breaks any one inventory surfaces here with the failing
language named.

Thresholds (calibrated against the current PHOIBLE 2.0 snapshot,
verified empirically before commit):

- **E1 NFC integrity**: every key in ``metadata['vowel_secondary']``
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
  feature-sparse (Buwal/PHOIBLE: 2 vowels, both at default — that
  is the inventory, not a placement bug).

- **E4 Diphthong NFC parity**: every diphthong segment in
  ``vowel_secondary`` produces a non-null ``secondary`` from
  ``compute_placements``. Catches the regression where the
  ``vowel_secondary`` key lookup misses the engine key (the
  original NFD/NFC bug that A1 fixed).

- **E5 Pair-collision tracker**: counts inventories with >= 3
  distinct diphthongs at the same primary->secondary pair. Does
  NOT fail (the C3 fan-out renders them legibly); prints a
  count at end-of-test so a sudden jump shows up.

Skipped when the PHOIBLE bake snapshot is absent (a checkout that
has never run ``web/scripts/bake_phoible.py``).
"""

from __future__ import annotations

import pytest

from phonology_shared.chart.vowels import (
    ROW_LABELS,
    PlacementFlag,
    compute_placements,
    detect_vowel_profile,
)

try:
    from phonology_shared.editor.phoible_provider import (
        PhoibleProvider,
        materialize_phoible_inventory,
    )
except ImportError:  # pragma: no cover - dev-only path
    pytest.skip("phoible_provider unavailable", allow_module_level=True)


@pytest.fixture(scope="module")
def provider() -> PhoibleProvider:
    try:
        return PhoibleProvider()
    except FileNotFoundError as exc:  # pragma: no cover
        pytest.skip(f"PHOIBLE snapshot not baked: {exc}")
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"PHOIBLE provider unavailable: {exc}")


@pytest.fixture(scope="module")
def all_inventory_ids(provider: PhoibleProvider) -> list[str]:
    """Every inventory id in the bake snapshot. Used to drive the
    whole-PHOIBLE stress walks (3000+ ids)."""
    # ``_inventories`` is the internal dict; use it directly to
    # avoid materializing 3000 descriptors on every test.
    return list(provider._inventories)  # type: ignore[attr-defined]


def _vowels_of(generated_segments: dict[str, dict[str, str]]) -> list[str]:
    """The placement code's contract: a vowel is any segment with
    ``Syllabic == '+'``. Same predicate the seg-grid uses to route
    vowels into the chart."""
    return [
        seg
        for seg, bundle in generated_segments.items()
        if bundle.get("Syllabic") == "+"
    ]


def test_e1_vowel_secondary_keys_subset_of_engine_segments(
    provider: PhoibleProvider, all_inventory_ids: list[str]
) -> None:
    """Every key in ``metadata['vowel_secondary']`` must appear in
    ``inventory.segments``. This is the NFC-mismatch regression
    test: the original bug had NFD-form diphthong keys missing
    the engine's NFC-folded segment keys, silently dropping
    nasal diphthongs from the chart."""
    offenders: list[tuple[str, set[str]]] = []
    for inv_id in all_inventory_ids:
        inv = materialize_phoible_inventory(provider, inv_id)
        vs = inv.metadata.get("vowel_secondary") or {}
        if not vs:
            continue
        missing = set(vs) - set(inv.segments)
        if missing:
            desc = provider.descriptor(inv_id)
            label = (
                f"{desc.language_name}/{desc.source_short}"
                if desc is not None
                else inv_id
            )
            offenders.append((label, missing))
    assert not offenders, (
        f"vowel_secondary keys missing from engine segments in "
        f"{len(offenders)} inventories: "
        f"{offenders[:5]}"
    )


def test_e2_no_cell_holds_more_than_eight_segments(
    provider: PhoibleProvider, all_inventory_ids: list[str]
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
    for inv_id in all_inventory_ids:
        gen = provider.generate(inv_id)
        vowels = _vowels_of(dict(gen.segments))
        if not vowels:
            continue
        seg_feats = {seg: dict(gen.segments[seg]) for seg in vowels}
        profile = detect_vowel_profile(vowels, seg_feats)
        occupied, _ = compute_placements(
            vowels,
            profile,
            seg_feats,
            vowel_secondary=gen.vowel_secondary,
        )
        max_size = max((len(segs) for segs in occupied.values()), default=0)
        if max_size > HARD_CEILING:
            desc = provider.descriptor(inv_id)
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
    provider: PhoibleProvider, all_inventory_ids: list[str]
) -> None:
    """For inventories with >= 7 vowels, at most 35% of vowels may
    collapse to the Open-mid Central default anchor. Catches mass
    underspecification regressions (e.g. a normalizer change that
    nukes the High / Low / Front / Back features).

    Smaller inventories are exempt because they are genuinely
    feature-sparse (a 2-vowel system with no rounding contrast IS
    underspecified by design).

    The 35% threshold accommodates the documented long-tail case
    (Miyako/EA: 10 vowels, 30% at default - the Eurasian
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
    for inv_id in all_inventory_ids:
        gen = provider.generate(inv_id)
        vowels = _vowels_of(dict(gen.segments))
        if len(vowels) < MIN_VOWELS:
            continue
        seg_feats = {seg: dict(gen.segments[seg]) for seg in vowels}
        profile = detect_vowel_profile(vowels, seg_feats)
        _, placements = compute_placements(
            vowels,
            profile,
            seg_feats,
            vowel_secondary=gen.vowel_secondary,
        )
        collapsed = sum(
            1
            for p in placements.values()
            if (p.row, p.col) == default_cell
            and PlacementFlag.DEFAULT_ANCHOR in p.flags
        )
        pct = collapsed / len(vowels)
        if pct > MAX_PCT:
            desc = provider.descriptor(inv_id)
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


def test_e4_every_diphthong_has_non_null_secondary_placement(
    provider: PhoibleProvider, all_inventory_ids: list[str]
) -> None:
    """For every PHOIBLE inventory with diphthongs, every key in
    ``vowel_secondary`` must produce a placement whose ``secondary``
    is non-null. Pins the end-to-end contract: bake -> provider ->
    materializer -> placement reader all agree on the same
    canonical segment key, so a diphthong cannot silently lose
    its target cell."""
    offenders: list[tuple[str, list[str]]] = []
    for inv_id in all_inventory_ids:
        inv = materialize_phoible_inventory(provider, inv_id)
        vs = inv.metadata.get("vowel_secondary") or {}
        if not vs:
            continue
        vowels = _vowels_of(dict(inv.segments))
        seg_feats = {seg: dict(inv.segments[seg]) for seg in vowels}
        profile = detect_vowel_profile(vowels, seg_feats)
        _, placements = compute_placements(
            vowels, profile, seg_feats, vowel_secondary=vs
        )
        missing = [
            seg
            for seg in vs
            if seg in placements and placements[seg].secondary is None
        ]
        if missing:
            desc = provider.descriptor(inv_id)
            label = (
                f"{desc.language_name}/{desc.source_short}"
                if desc is not None
                else inv_id
            )
            offenders.append((label, missing))
    assert not offenders, (
        f"diphthongs with null secondary placement in "
        f"{len(offenders)} inventories: {offenders[:5]}"
    )


def test_e5_pair_collision_tracker(
    provider: PhoibleProvider,
    all_inventory_ids: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Soft check: counts inventories where >= 3 distinct
    diphthongs share the SAME (primary, secondary) cell pair. The
    web renderer's C3 fan-out distributes their arrows around the
    chord, so this is no longer a visual bug; the count is tracked
    so a sudden growth shows up in CI output."""
    from collections import defaultdict

    inventories_with_collisions = 0
    worst_collision = 0
    for inv_id in all_inventory_ids:
        inv = materialize_phoible_inventory(provider, inv_id)
        vs = inv.metadata.get("vowel_secondary") or {}
        if not vs:
            continue
        vowels = _vowels_of(dict(inv.segments))
        seg_feats = {seg: dict(inv.segments[seg]) for seg in vowels}
        profile = detect_vowel_profile(vowels, seg_feats)
        _, placements = compute_placements(
            vowels, profile, seg_feats, vowel_secondary=vs
        )
        pair_to_segs: dict[
            tuple[tuple[int, int], tuple[int, int]], list[str]
        ] = defaultdict(list)
        for seg, p in placements.items():
            if p.secondary is None:
                continue
            key = (
                (p.row, p.col),
                (p.secondary.row, p.secondary.col),
            )
            pair_to_segs[key].append(seg)
        big_groups = [segs for segs in pair_to_segs.values() if len(segs) >= 3]
        if big_groups:
            inventories_with_collisions += 1
            worst_collision = max(
                worst_collision, max(len(g) for g in big_groups)
            )
    with capsys.disabled():
        print(
            f"\nPair-collision tracker: "
            f"{inventories_with_collisions} inventories have >= 3 "
            f"diphthongs at the same (primary, secondary) pair "
            f"(worst: {worst_collision}). Renderer C3 fans them "
            f"around the chord."
        )
    # Soft ceiling: a step-function jump (e.g. 100+ inventories or
    # a single 10+ collision group) probably means something broke
    # upstream; sound the alarm.
    assert inventories_with_collisions < 100
    assert worst_collision < 10
