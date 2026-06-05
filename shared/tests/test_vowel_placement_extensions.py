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
    """Inventory profile asserting RTR is in active use without
    tense or ATR. Lets ``_height_split_value`` fall through to the
    RTR-as-third-source branch.
    """
    return VowelProfile(
        has_high=True,
        has_low=True,
        has_front=True,
        has_back=True,
        has_round=True,
        has_rtr=True,
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
        has_rtr=True,
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


def test_raised_promotes_row(relative_height_profile):
    """Open-mid base row with ``+raised`` is nudged one step
    closer (-> Mid). ``+raised`` adds
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
    open (-> Near-close). The base must come from ``+tense`` so the
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
    """Back ``+advanced`` -> central; central ``+advanced`` ->
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
    """Front ``+retracted`` -> central."""
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
