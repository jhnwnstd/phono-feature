"""Placement-extension behaviour: RTR as a third height-split
source, ``raised`` / ``lowered`` as row refiners, and
``advanced`` / ``retracted`` / ``centralized`` / ``peripheral``
as column refiners.

None of the bundled inventories exercise these features today;
:py:mod:`test_vowel_layout` already guards the baseline placements
for inventories that lack the new features, and the regression
snapshot in :py:mod:`test_vowel_chart_collision_decisions` confirms
no bundled-inventory placement moved.
"""

from __future__ import annotations

import pytest

from phonology_shared.chart.vowels import (
    ROW_LABELS,
    PlacementFlag,
    PlacementPolicy,
    VowelProfile,
    vowel_grid_pos,
)


@pytest.fixture
def rtr_profile() -> VowelProfile:
    """Inventory profile asserting RTR is CONTRASTIVELY in active
    use without tense or ATR. Lets ``_height_split_value`` fall
    through to the RTR-as-third-source branch.

    Sets ``has_rtr_contrast=True`` alongside ``has_rtr=True`` so
    the contrast-gating logic in ``_height_split_value`` treats
    RTR as a real source (mirrors what
    :py:func:`detect_vowel_profile` returns on an inventory that
    actually contrasts RTR).
    """
    return VowelProfile(
        has_high=True,
        has_low=True,
        has_front=True,
        has_back=True,
        has_round=True,
        has_rtr=True,
        has_rtr_contrast=True,
    )


@pytest.fixture
def atr_plus_rtr_profile() -> VowelProfile:
    return VowelProfile(
        has_high=True,
        has_low=True,
        has_front=True,
        has_back=True,
        has_round=True,
        has_atr=True,
        has_atr_contrast=True,
        has_rtr=True,
        has_rtr_contrast=True,
    )


@pytest.fixture
def relative_height_profile() -> VowelProfile:
    return VowelProfile(
        has_high=True,
        has_low=True,
        has_front=True,
        has_back=True,
        has_round=True,
        has_tense=True,
        has_tense_contrast=True,
        has_raised=True,
        has_lowered=True,
    )


@pytest.fixture
def relative_backness_profile() -> VowelProfile:
    return VowelProfile(
        has_high=True,
        has_low=True,
        has_front=True,
        has_back=True,
        has_round=True,
        has_advanced=True,
        has_retracted=True,
        has_centralized=True,
        has_peripheral=True,
    )


def test_rtr_drives_height_split_when_no_tense_or_atr(rtr_profile):
    """A high vowel with ``+rtr`` lands at Near-close (the
    ``[-atr]``-equivalent slot); the same vowel with ``-rtr`` lands
    at Close.
    """
    positive = vowel_grid_pos(
        {"high": "+", "low": "-", "front": "+", "rtr": "+", "round": "-"},
        rtr_profile,
    )
    negative = vowel_grid_pos(
        {"high": "+", "low": "-", "front": "+", "rtr": "-", "round": "-"},
        rtr_profile,
    )
    assert ROW_LABELS[positive.row] == "Near-close"
    assert ROW_LABELS[negative.row] == "Close"


def test_rtr_inverted_relative_to_atr(atr_plus_rtr_profile):
    """``atr=+`` alone and ``atr=+, rtr=-`` land on the same row
    (no divergence). ``atr=+, rtr=+`` records
    :py:attr:`PlacementFlag.SPLIT_SOURCE_DIVERGENCE` because the
    inverted RTR (``-``) disagrees with the ATR.
    """
    atr_only = vowel_grid_pos(
        {"high": "+", "low": "-", "front": "+", "atr": "+", "round": "-"},
        atr_plus_rtr_profile,
    )
    atr_plus_rtr_agree = vowel_grid_pos(
        {
            "high": "+",
            "low": "-",
            "front": "+",
            "atr": "+",
            "rtr": "-",
            "round": "-",
        },
        atr_plus_rtr_profile,
    )
    atr_plus_rtr_disagree = vowel_grid_pos(
        {
            "high": "+",
            "low": "-",
            "front": "+",
            "atr": "+",
            "rtr": "+",
            "round": "-",
        },
        atr_plus_rtr_profile,
    )
    assert atr_only.row == atr_plus_rtr_agree.row
    assert (
        PlacementFlag.SPLIT_SOURCE_DIVERGENCE not in atr_plus_rtr_agree.flags
    )
    assert PlacementFlag.SPLIT_SOURCE_DIVERGENCE in atr_plus_rtr_disagree.flags


def test_negative_rtr_does_not_force_positive_atr_equivalence(
    atr_plus_rtr_profile,
) -> None:
    """``rtr=-`` alone (with ``atr=0`` or with ``atr=-``) does NOT
    drive a divergence flag. Theory: ``+rtr`` (retracted tongue
    root) DOES imply ``-atr`` so the inversion fires there; ``-rtr``
    (not retracted) does NOT imply ``+atr``; a vowel can be
    neither advanced nor retracted. PHOIBLE encodes most non-
    ATR-system vowels as ``atr=- rtr=-``, which under the prior
    rule fired SPLIT_SOURCE_DIVERGENCE on every PHOIBLE inventory's
    every vowel because the inversion ``-rtr to +atr-equiv``
    disagreed with the explicit ``atr=-``. The diagnostic in
    ``test_phoible_vowel_placement_distribution`` surfaced this
    one-line bug.
    """
    # atr alone (no rtr): no divergence (single source).
    atr_minus_no_rtr = vowel_grid_pos(
        {
            "high": "+",
            "low": "-",
            "front": "+",
            "atr": "-",
            "round": "-",
        },
        atr_plus_rtr_profile,
    )
    assert PlacementFlag.SPLIT_SOURCE_DIVERGENCE not in atr_minus_no_rtr.flags

    # atr=- AND rtr=-: NEITHER carries direction info; no
    # divergence. (The bug: previously fired because ``-rtr`` was
    # being inverted to ``+atr-equiv``.)
    atr_and_rtr_both_minus = vowel_grid_pos(
        {
            "high": "+",
            "low": "-",
            "front": "+",
            "atr": "-",
            "rtr": "-",
            "round": "-",
        },
        atr_plus_rtr_profile,
    )
    assert (
        PlacementFlag.SPLIT_SOURCE_DIVERGENCE
        not in atr_and_rtr_both_minus.flags
    )

    # rtr=- alone with no atr: no divergence either (single source
    # and it carries no positive ATR claim).
    rtr_minus_no_atr = vowel_grid_pos(
        {
            "high": "+",
            "low": "-",
            "front": "+",
            "rtr": "-",
            "round": "-",
        },
        atr_plus_rtr_profile,
    )
    assert PlacementFlag.SPLIT_SOURCE_DIVERGENCE not in rtr_minus_no_atr.flags


def test_uniform_polarity_split_source_does_not_drive_divergence() -> None:
    """When a split-source feature (``tense`` / ``atr`` / ``rtr``)
    has only ONE polarity across the inventory, treat that polarity
    as semantically vacuous for divergence detection. The
    ``has_<feat>_contrast`` profile flags carry the inventory-level
    contrast fact (mirrors ``has_long_contrast``).

    Theory: a PHOIBLE inventory often codes every vowel ``tense=+``
    and every vowel ``atr=-`` because both features are stored
    columns even when the inventory makes no contrast on them.
    The old rule ("tense and atr disagree on this vowel") fired
    SPLIT_SOURCE_DIVERGENCE on every vowel of such inventories.
    The new rule: only count a source's value as a real source-
    claim when the inventory contrasts on that feature.

    Pinned by passing a profile with ``has_tense_contrast=False``
    + ``has_atr_contrast=False`` to ``vowel_grid_pos``; the
    divergence flag must NOT fire on a vowel whose ``tense=+
    atr=-`` would have triggered it under the old rule.
    """
    no_contrast_profile = VowelProfile(
        has_high=True,
        has_low=True,
        has_front=True,
        has_back=True,
        has_round=True,
        has_tense=True,
        has_atr=True,
        # Both polarities-only-once: the inventory carries the
        # feature columns but makes no contrast on either.
        has_tense_contrast=False,
        has_atr_contrast=False,
    )
    p = vowel_grid_pos(
        {
            "high": "+",
            "low": "-",
            "front": "+",
            "tense": "+",
            "atr": "-",
            "round": "-",
        },
        no_contrast_profile,
    )
    assert PlacementFlag.SPLIT_SOURCE_DIVERGENCE not in p.flags

    # And the inverse: when the inventory DOES contrast on both,
    # the existing detector keeps firing (this is the genuine-
    # conflict case the existing test_rtr_inverted_relative_to_atr
    # already covers in its disagree branch).
    contrast_profile = VowelProfile(
        has_high=True,
        has_low=True,
        has_front=True,
        has_back=True,
        has_round=True,
        has_tense=True,
        has_atr=True,
        has_tense_contrast=True,
        has_atr_contrast=True,
    )
    p2 = vowel_grid_pos(
        {
            "high": "+",
            "low": "-",
            "front": "+",
            "tense": "+",
            "atr": "-",
            "round": "-",
        },
        contrast_profile,
    )
    assert PlacementFlag.SPLIT_SOURCE_DIVERGENCE in p2.flags


def test_underspec_height_inventory_does_not_crash(
    relative_backness_profile,
) -> None:
    """Synthetic inventory of 8 vowels, every one explicitly
    ``high=0 low=0`` (no height feature usable). Verifies:

    - The placer does NOT crash on any vowel.
    - Every vowel lands on the Open-mid default row (height
      underspecified to default anchor).
    - Vowels still distribute across the backness axis; the
      placer reads ``front``/``back`` even when height is fully
      absent. So the chart is not COMPLETELY collapsed to a
      single cell; just the height dimension is.

    Gap closed: previously no test exercised the "every vowel
    underspecified for height" case. The diagnostic showed a few
    small inventories (Guɗe, bana, Alawa: 3-5 vowels) actually
    hit this branch on PHOIBLE.
    """
    cases = [
        ("front_unround", {"front": "+", "back": "-", "round": "-"}),
        ("front_round", {"front": "+", "back": "-", "round": "+"}),
        ("central_unround", {"front": "-", "back": "-", "round": "-"}),
        ("central_round", {"front": "-", "back": "-", "round": "+"}),
        ("back_unround", {"front": "-", "back": "+", "round": "-"}),
        ("back_round", {"front": "-", "back": "+", "round": "+"}),
        ("front_only", {"front": "+"}),
        ("back_only", {"back": "+"}),
    ]
    placements = []
    for _label, feats in cases:
        feats_with_zero_height = {"high": "0", "low": "0", **feats}
        placement = vowel_grid_pos(
            feats_with_zero_height, relative_backness_profile
        )
        placements.append(placement)

    # Every vowel lands on the Open-mid default row.
    open_mid_row = ROW_LABELS.index("Open-mid")
    for placement in placements:
        assert placement.row == open_mid_row, (
            f"expected Open-mid row, got " f"{ROW_LABELS[placement.row]!r}"
        )
        assert PlacementFlag.DEFAULT_ANCHOR in placement.flags

    # Vowels still distribute across columns; not all in one cell.
    columns = {p.col for p in placements}
    assert len(columns) >= 3, (
        f"backness axis collapsed to {columns!r}; the placer "
        f"should still read front/back when height is absent"
    )


def test_raised_promotes_row(relative_height_profile):
    """Open-mid base row with ``+raised`` is nudged one step
    closer (to Mid). ``+raised`` adds
    :py:attr:`PlacementFlag.REFINED`.
    """
    base = vowel_grid_pos(
        {
            "high": "-",
            "low": "-",
            "front": "+",
            "tense": "-",
            "round": "-",
        },
        relative_height_profile,
    )
    raised = vowel_grid_pos(
        {
            "high": "-",
            "low": "-",
            "front": "+",
            "tense": "-",
            "round": "-",
            "raised": "+",
        },
        relative_height_profile,
    )
    assert ROW_LABELS[base.row] == "Open-mid"
    assert ROW_LABELS[raised.row] == "Mid"
    assert PlacementFlag.REFINED in raised.flags


def test_lowered_demotes_row(relative_height_profile):
    """Close base row with ``+lowered`` is nudged one step more
    open (to Near-close). The base must come from ``+tense`` so the
    underspecified Close-Mid fallback does not interfere.
    """
    base = vowel_grid_pos(
        {
            "high": "+",
            "low": "-",
            "front": "+",
            "tense": "+",
            "round": "-",
        },
        relative_height_profile,
    )
    lowered = vowel_grid_pos(
        {
            "high": "+",
            "low": "-",
            "front": "+",
            "tense": "+",
            "round": "-",
            "lowered": "+",
        },
        relative_height_profile,
    )
    assert ROW_LABELS[base.row] == "Close"
    assert ROW_LABELS[lowered.row] == "Near-close"
    assert PlacementFlag.REFINED in lowered.flags


def test_raised_and_lowered_conflict_is_noop(relative_height_profile):
    """Both ``+raised`` and ``+lowered`` set drop the nudge and
    add :py:attr:`PlacementFlag.CONFLICT`. The base row is
    preserved.
    """
    both = vowel_grid_pos(
        {
            "high": "-",
            "low": "-",
            "front": "+",
            "tense": "-",
            "round": "-",
            "raised": "+",
            "lowered": "+",
        },
        relative_height_profile,
    )
    assert ROW_LABELS[both.row] == "Open-mid"
    assert PlacementFlag.CONFLICT in both.flags
    assert PlacementFlag.REFINED not in both.flags


def test_advanced_moves_column_one_step(relative_backness_profile):
    """Back ``+advanced`` to central; central ``+advanced`` to
    front.
    """
    back_to_central = vowel_grid_pos(
        {
            "high": "+",
            "low": "-",
            "back": "+",
            "advanced": "+",
            "round": "+",
        },
        relative_backness_profile,
    )
    assert back_to_central.backness is not None
    assert back_to_central.backness.value == "central"
    assert PlacementFlag.REFINED in back_to_central.backness.flags

    central_to_front = vowel_grid_pos(
        {
            "high": "+",
            "low": "-",
            "front": "-",
            "back": "-",
            "advanced": "+",
            "round": "-",
        },
        relative_backness_profile,
    )
    assert central_to_front.backness is not None
    assert central_to_front.backness.value == "front"


def test_retracted_moves_column_one_step(relative_backness_profile):
    """Front ``+retracted`` to central."""
    front_to_central = vowel_grid_pos(
        {
            "high": "+",
            "low": "-",
            "front": "+",
            "retracted": "+",
            "round": "-",
        },
        relative_backness_profile,
    )
    assert front_to_central.backness is not None
    assert front_to_central.backness.value == "central"


def test_centralized_collapses_to_central(relative_backness_profile):
    """``+centralized`` collapses front and back to central."""
    front_in = vowel_grid_pos(
        {
            "high": "+",
            "low": "-",
            "front": "+",
            "centralized": "+",
            "round": "-",
        },
        relative_backness_profile,
    )
    back_in = vowel_grid_pos(
        {
            "high": "+",
            "low": "-",
            "back": "+",
            "centralized": "+",
            "round": "+",
        },
        relative_backness_profile,
    )
    assert front_in.backness is not None and back_in.backness is not None
    assert front_in.backness.value == "central"
    assert back_in.backness.value == "central"


def test_peripheral_is_tiebreak_only(relative_backness_profile):
    """Direct front ``[+peripheral]`` stays at Front (no override).
    An underspecified placement with ``-peripheral`` is nudged to
    central.
    """
    direct_front_plus = vowel_grid_pos(
        {
            "high": "+",
            "low": "-",
            "front": "+",
            "peripheral": "+",
            "round": "-",
        },
        relative_backness_profile,
    )
    assert direct_front_plus.backness is not None
    assert direct_front_plus.backness.value == "front"

    # Underspecified backness: ``[-front]`` alone with no back. Base
    # falls through to central UNDERSPECIFIED. ``-peripheral`` then
    # nudges (already central, so the base value stays "central"
    # but the tiebreak fires only for off-central bases). Validate
    # the underspecified flag flows through.
    underspecified_minus = vowel_grid_pos(
        {
            "high": "+",
            "low": "-",
            "front": "-",
            "peripheral": "-",
            "round": "-",
        },
        relative_backness_profile,
    )
    assert underspecified_minus.backness is not None
    assert underspecified_minus.backness.value == "central"


def test_advanced_and_retracted_conflict_is_noop(relative_backness_profile):
    """Both ``+advanced`` and ``+retracted`` set drop the nudge
    and add :py:attr:`PlacementFlag.CONFLICT`.
    """
    both = vowel_grid_pos(
        {
            "high": "+",
            "low": "-",
            "back": "+",
            "advanced": "+",
            "retracted": "+",
            "round": "+",
        },
        relative_backness_profile,
    )
    assert both.backness is not None
    assert both.backness.value == "back"
    assert PlacementFlag.CONFLICT in both.backness.flags


def test_policy_off_disables_height_refinement(relative_height_profile):
    """``policy.allow_relative_height_refinement=False`` restores
    the pre-extension behaviour where ``raised`` / ``lowered`` are
    silently ignored. The same input as
    :py:func:`test_raised_promotes_row` falls back to the base row.
    """
    policy = PlacementPolicy(allow_relative_height_refinement=False)
    raised = vowel_grid_pos(
        {
            "high": "-",
            "low": "-",
            "front": "+",
            "tense": "-",
            "round": "-",
            "raised": "+",
        },
        relative_height_profile,
        policy,
    )
    assert ROW_LABELS[raised.row] == "Open-mid"
    assert PlacementFlag.REFINED not in raised.flags


def test_policy_off_disables_backness_refinement(relative_backness_profile):
    """``policy.allow_relative_backness_refinement=False`` restores
    pre-extension behaviour for the column axis.
    """
    policy = PlacementPolicy(allow_relative_backness_refinement=False)
    back_no_nudge = vowel_grid_pos(
        {
            "high": "+",
            "low": "-",
            "back": "+",
            "advanced": "+",
            "round": "+",
        },
        relative_backness_profile,
        policy,
    )
    assert back_no_nudge.backness is not None
    assert back_no_nudge.backness.value == "back"


def test_policy_off_disables_rtr_split(rtr_profile):
    """``policy.allow_rtr_split=False`` makes RTR a no-op for the
    height split when neither tense nor ATR are present, restoring
    the pre-extension behaviour where the high vowel always lands
    at Close.
    """
    policy = PlacementPolicy(allow_rtr_split=False)
    positive_off = vowel_grid_pos(
        {"high": "+", "low": "-", "front": "+", "rtr": "+", "round": "-"},
        rtr_profile,
        policy,
    )
    assert ROW_LABELS[positive_off.row] == "Close"
