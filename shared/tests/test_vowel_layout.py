"""Vowel-chart placement contract tests.

The placement code looks up canonical lowercase feature names
(``high``, ``low``, ``front``, etc.) inside each feature bundle.
Inventory JSON typically uses PascalCase keys (``High``, ``Low``).
``gui.vowel_layout`` is case-insensitive at its entry, so callers
can pass either form. These tests lock that contract in:

* PascalCase and lowercase inputs MUST produce identical placements
  for every vowel of every bundled inventory.

* On the real English inventory, no vowel may collapse to the
  Open-mid Central default cell unless the inventory genuinely
  underspecifies that vowel. This catches the original "all vowels
  fall through to default" regression where wrong-case keys made
  the entire vowel chart degenerate to a single cell.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from phonology_shared.engine.feature_engine import FeatureEngine
from phonology_shared.engine.inventory import Inventory
from phonology_shared.render.vowel_layout import (
    VowelProfile,
    compute_placements,
    detect_vowel_profile,
    vowel_grid_pos,
)

INVENTORIES_DIR = (
    Path(__file__).resolve().parents[2] / "desktop" / "inventories"
)


def _engine(name: str) -> FeatureEngine:
    path = INVENTORIES_DIR / name
    if not path.exists():
        pytest.skip(f"inventory not present: {name}")
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    return FeatureEngine(Inventory.parse(raw, source=str(path)))


def _vowel_segs(engine: FeatureEngine) -> list[str]:
    return [
        s for s in engine.segments if engine.segments[s].get("Syllabic") == "+"
    ]


@pytest.mark.parametrize(
    "inv_filename",
    [
        "english_features.json",
        "general_features.json",
        "hayes_features.json",
    ],
)
def test_vowel_placement_case_insensitive(inv_filename: str) -> None:
    """vowel_grid_pos and detect_vowel_profile must produce the
    same output whether the caller passes raw (PascalCase) feats or
    normalized (lowercase) feats."""
    engine = _engine(inv_filename)
    vowels = _vowel_segs(engine)
    if not vowels:
        pytest.skip(f"{inv_filename} has no vowels")
    raw_feats = {s: dict(engine.segments[s]) for s in vowels}
    lower_feats = {
        s: {k.lower(): v for k, v in bundle.items()}
        for s, bundle in raw_feats.items()
    }
    raw_profile = detect_vowel_profile(vowels, raw_feats)
    lower_profile = detect_vowel_profile(vowels, lower_feats)
    assert raw_profile == lower_profile, (
        f"profile differs between raw and normalized keys: "
        f"{raw_profile} vs {lower_profile}"
    )
    for seg in vowels:
        raw_p = vowel_grid_pos(raw_feats[seg], raw_profile)
        lower_p = vowel_grid_pos(lower_feats[seg], lower_profile)
        assert (
            raw_p == lower_p
        ), f"/{seg}/ placement differs: raw={raw_p}, lower={lower_p}"


def test_english_vowels_not_all_in_default_cell() -> None:
    """Regression: with case-insensitive lookup wired correctly, the
    English vowel chart MUST spread vowels across multiple cells.
    The original bug had every vowel landing in (row=3, col=2) =
    Open-mid Central because the lookups missed PascalCase keys.
    """
    engine = _engine("english_features.json")
    vowels = _vowel_segs(engine)
    assert vowels, "English should have vowels"
    seg_feats = {s: dict(engine.segments[s]) for s in vowels}
    profile = detect_vowel_profile(vowels, seg_feats)
    placements = [vowel_grid_pos(seg_feats[s], profile) for s in vowels]
    unique_cells = {(p.row, p.col) for p in placements}
    # English has ~13 vowels spanning ~9 cells in the IPA chart.
    # Anything under 4 unique cells means the case-sensitivity bug
    # is back (or the bundled inventory was rewritten unrecognizably).
    assert len(unique_cells) >= 4, (
        f"English vowels collapsed into {len(unique_cells)} cell(s); "
        f"case-insensitive placement appears broken. Cells: {unique_cells}"
    )


# compute_placements: shared cell-grouping helper


def test_compute_placements_general_tier_two_mid_splits_schwa_from_open_mid():
    """The General inventory's ə (ATR=0) and ɜ (ATR=-) historically
    collapsed onto the same Open-mid Central cell because the Tier 1
    height inference could not tell them apart. The Tier 2 Mid
    display policy now lifts ə onto the Mid row (logical row 3,
    inserted between Close-mid and Open-mid) while ɜ stays on
    Open-mid (logical row 4), so the renderer no longer stacks them.
    """
    engine = _engine("general_features.json")
    vowels = _vowel_segs(engine)
    seg_feats = {s: dict(engine.segments[s]) for s in vowels}
    profile = detect_vowel_profile(vowels, seg_feats)
    occupied, placements = compute_placements(vowels, profile, seg_feats)
    # ə now lives on the Mid row; ɜ stays on Open-mid.
    assert occupied.get((3, 2)) == ["ə"]
    assert occupied.get((4, 2)) == ["ɜ"]
    assert placements["ə"].height.value == "Mid"
    assert placements["ɜ"].height.value == "Open-mid"


def test_compute_placements_orders_by_confidence_desc():
    """Within a collision cell, the highest-confidence vowel sorts
    first so the desktop renders it on top and the web stacks it at
    the top of the visible stack."""
    engine = _engine("general_features.json")
    vowels = _vowel_segs(engine)
    seg_feats = {s: dict(engine.segments[s]) for s in vowels}
    profile = detect_vowel_profile(vowels, seg_feats)
    occupied, placements = compute_placements(vowels, profile, seg_feats)
    for key, segs_in_cell in occupied.items():
        if len(segs_in_cell) < 2:
            continue
        confidences = [placements[s].confidence for s in segs_in_cell]
        # Sorted in DESCENDING confidence order.
        assert confidences == sorted(
            confidences, reverse=True
        ), f"cell {key} not sorted by confidence desc: {confidences}"


# Constants: immutability


def test_module_constants_are_tuples():
    """ROW_LABELS / COL_LABELS / VOWEL_HEIGHT are exported as
    tuples so importers cannot mutate the shared singletons."""
    import phonology_shared.render.vowel_layout as vl

    assert isinstance(vl.ROW_LABELS, tuple)
    assert isinstance(vl.COL_LABELS, tuple)
    assert isinstance(vl.VOWEL_HEIGHT, tuple)
    # Spot-check shape so a future re-shape is a deliberate break.
    # Seven height tiers since the Tier 2 Mid row landed between
    # Close-mid and Open-mid.
    assert len(vl.ROW_LABELS) == 7
    assert "Mid" in vl.ROW_LABELS
    assert vl.COL_LABELS == ("Front", "Central", "Back")


# PascalCase normalization


def test_pascal_case_feats_match_lowercase(profile):
    """The placement code accepts either PascalCase or lowercase
    keys; both must produce identical results so callers passing
    raw inventory feats are not silently routed to the default
    cell."""
    pascal = vowel_grid_pos(
        {"High": "+", "Low": "-", "Front": "+", "Round": "-"},
        profile,
    )
    lower = vowel_grid_pos(
        {"high": "+", "low": "-", "front": "+", "round": "-"},
        profile,
    )
    assert pascal == lower


# compute_placements: sort order within a collision cell


def test_compute_placements_sort_segment_ascending_within_tier(profile):
    """Within a confidence tier, segments sort in ASCENDING string
    order so collision-cell ordering is stable and predictable.
    The prior implementation used ``reverse=True`` on the whole
    sort tuple, which silently reversed segment order too."""
    # Three vowels at the same placement, same confidence: alphabetical
    # ASCending order must come out of compute_placements.
    feats = {
        "a": {"high": "-", "low": "+"},  # Open central
        "b": {"high": "-", "low": "+"},
        "c": {"high": "-", "low": "+"},
    }
    occupied, _placements = compute_placements(["c", "a", "b"], profile, feats)
    # All three should land in the same cell.
    [cell] = occupied.values()
    assert cell == [
        "a",
        "b",
        "c",
    ], f"expected alphabetical ASC within tier, got {cell}"


# _infer_rounding: distinct reasons for [-round] vs no round


def test_inferred_rounding_reason_distinguishes_explicit_negative(profile):
    """An explicit ``[-round]`` should produce a different reason
    string than an entirely absent Round feature, so audits / UI
    tooltips can tell the difference between "explicitly unrounded"
    and "unspecified for rounding"."""
    explicit_neg = vowel_grid_pos(
        {"high": "+", "low": "-", "front": "+", "round": "-"},
        profile,
    )
    no_round = vowel_grid_pos(
        {"high": "+", "low": "-", "front": "+"},
        profile,
    )
    assert "[-round]" in explicit_neg.reason
    assert "no round specified" in no_round.reason
    assert explicit_neg.reason != no_round.reason


# _infer_backness: explicit [-front] handling


def test_negative_front_with_no_back_marks_low_confidence(profile):
    """``[-front]`` alone is ambiguous between central and back.
    Conservative default to central with LOW confidence and a
    reason that surfaces the ambiguity, matching the documented
    chart-placement policy."""
    placement = vowel_grid_pos(
        {"high": "-", "low": "-", "front": "-"},
        profile,
    )
    assert "[-front]" in placement.reason
    # Either "unresolved" or "ambiguous" wording; the test names
    # the policy intent rather than the exact string.
    assert "unresolved" in placement.reason or "ambiguous" in placement.reason


def test_negative_front_with_negative_back_is_more_confident_than_front_alone(
    profile,
):
    """``[-front, -back]`` is the canonical central spec; ``[-front]``
    alone is genuinely ambiguous between central and back. Pin
    height AND rounding unambiguously so the overall placement
    confidence reflects only the backness inference (top-level
    confidence is min(height, backness, rounding))."""
    both = vowel_grid_pos(
        {
            "high": "+",
            "low": "-",
            "front": "-",
            "back": "-",
            "round": "-",
        },
        profile,
    )
    front_only = vowel_grid_pos(
        {"high": "+", "low": "-", "front": "-", "round": "-"},
        profile,
    )
    assert both.confidence > front_only.confidence
    # And the explicit-both case lands at central (col 2), not back.
    assert both.col == 2


# _height_split_value: tense/ATR conflict handling


def test_tense_atr_agreement_uses_either(profile):
    """When tense and ATR are both present and agree, the close
    placement applies and the reason notes the source."""
    p_tense = vowel_grid_pos(
        {"high": "+", "low": "-", "front": "+", "tense": "+"},
        profile,
    )
    p_atr = vowel_grid_pos(
        {"high": "+", "low": "-", "front": "+", "atr": "+"},
        profile,
    )
    p_both = vowel_grid_pos(
        {"high": "+", "low": "-", "front": "+", "tense": "+", "atr": "+"},
        profile,
    )
    # All three land at Close (row 0).
    assert p_tense.row == p_atr.row == p_both.row == 0


def test_tense_overrides_conflicting_atr(profile):
    """When tense and ATR disagree, tense wins (a documented
    inventory-policy choice) and the reason string records the
    override so the choice is auditable."""
    placement = vowel_grid_pos(
        {"high": "+", "low": "-", "front": "+", "tense": "+", "atr": "-"},
        profile,
    )
    # tense=+, atr=- -> tense wins -> Close (row 0)
    assert placement.row == 0
    assert "overrides" in placement.reason


@pytest.fixture
def profile():
    """Default profile with every feature considered active. Tests
    that don't care about the fallback gating can use this."""
    return VowelProfile(
        has_front=True,
        has_back=True,
        has_high=True,
        has_low=True,
        has_round=True,
        has_labial=True,
        has_atr=True,
        has_tense=True,
        has_coronal=True,
        has_syllabic=True,
        has_consonantal=True,
    )


# ---------------------------------------------------------------------------
# Render-ready geometry tests (Phase: vowel surface refactor).
#
# These pin the contract that the shared
# :py:func:`build_vowel_chart_geometry` produces a payload both
# Qt and the web bridge can iterate without re-deriving placement,
# tooltip text, or physical coordinates.
# ---------------------------------------------------------------------------


def test_logical_col_offset_skips_spacer_tracks() -> None:
    """``logical_col_offset(c)`` for c in 0..5 must never land on
    the spacer-track columns 3 or 6. The Qt-physical column
    (= VOWEL_LABEL_GRID_COL + offset = 0 + offset) is exactly the
    offset; the resulting set is {1, 2, 4, 5, 7, 8}.
    """
    from phonology_shared.render.vowel_layout import (
        VOWEL_LABEL_GRID_COL,
        logical_col_offset,
    )

    physicals = {
        VOWEL_LABEL_GRID_COL + logical_col_offset(c) for c in range(6)
    }
    assert physicals == {1, 2, 4, 5, 7, 8}


def test_chart_geometry_omits_empty_rows() -> None:
    """``build_vowel_chart_geometry`` skips height tiers that have
    no occupied cell. Without this, the web renderer would emit a
    "Close" row label for an inventory with no close vowels.
    """
    from phonology_shared.render.vowel_layout import (
        build_vowel_chart_geometry,
    )

    engine = _engine("english_features.json")
    vowel_segs = _vowel_segs(engine)
    seg_feats = {s: dict(engine.segments[s]) for s in vowel_segs}
    profile = detect_vowel_profile(vowel_segs, seg_feats)
    geometry = build_vowel_chart_geometry(vowel_segs, profile, seg_feats)

    populated_in_cells = {cell.row for cell in geometry.cells}
    rows_in_geometry = {row.logical_row for row in geometry.rows}
    assert populated_in_cells == rows_in_geometry, (
        "geometry.rows must match the set of logical rows that"
        " appear in geometry.cells; an empty row would mislead the"
        " renderer into emitting a stray row label"
    )
    # Rows are listed in ascending logical-row order with
    # contiguous grid_row values starting at VOWEL_FIRST_DATA_GRID_ROW.
    from phonology_shared.render.vowel_layout import (
        VOWEL_FIRST_DATA_GRID_ROW,
    )

    expected_grid_rows = [
        VOWEL_FIRST_DATA_GRID_ROW + i for i in range(len(geometry.rows))
    ]
    assert [r.grid_row for r in geometry.rows] == expected_grid_rows


def test_chart_geometry_cell_grid_col_avoids_spacer_tracks() -> None:
    """Every cell's ``grid_col`` must be a non-spacer track (1, 2,
    4, 5, 7, or 8). A regression that maps a logical col onto a
    spacer would silently render the button under a hidden track
    in CSS and overlap a spacer label in Qt.
    """
    from phonology_shared.render.vowel_layout import (
        build_vowel_chart_geometry,
    )

    engine = _engine("general_features.json")
    vowel_segs = _vowel_segs(engine)
    seg_feats = {s: dict(engine.segments[s]) for s in vowel_segs}
    profile = detect_vowel_profile(vowel_segs, seg_feats)
    geometry = build_vowel_chart_geometry(vowel_segs, profile, seg_feats)

    for cell in geometry.cells:
        assert cell.grid_col in {1, 2, 4, 5, 7, 8}, (
            f"cell at logical ({cell.row}, {cell.col}) landed on"
            f" spacer column {cell.grid_col}"
        )


# ---------------------------------------------------------------------------
# Paper-recommended semantic hardening:
# four-state values, tightened fallbacks, per-axis evidence, flag-based
# disambiguation between conflict-anchor, default-anchor, and direct spec.
# ---------------------------------------------------------------------------


def test_feature_state_distinguishes_zero_from_absent() -> None:
    """Hayes (2009) treats ``"0"`` as a deliberate "don't care" value
    distinct from a missing key. The shared four-state model must
    preserve that distinction.
    """
    from phonology_shared.render.vowel_layout import (
        FeatureState,
        _feature_state,
    )

    assert _feature_state({"front": "+"}, "front") is FeatureState.POS
    assert _feature_state({"front": "-"}, "front") is FeatureState.NEG
    assert _feature_state({"front": "0"}, "front") is FeatureState.ZERO
    assert _feature_state({}, "front") is FeatureState.ABSENT


def test_back_minus_falls_back_to_front_only_when_inventory_lacks_front(
    profile,
):
    """The paper's diagnosed bug: the prior ``[-back]`` rule fired
    whenever the SEGMENT lacked ``front``, even on inventories that
    use ``front`` elsewhere. Now the fallback only fires when the
    INVENTORY has no ``front`` feature at all; with ``front`` in the
    profile, ``[-back]`` alone anchors central with
    ``UNDERSPECIFIED``.
    """
    from phonology_shared.render.vowel_layout import (
        PlacementFlag,
        VowelProfile,
    )

    # Inventory uses front: -back alone should NOT promote to front.
    has_front_profile = profile  # full active profile
    p1 = vowel_grid_pos(
        {"high": "+", "low": "-", "back": "-", "round": "-"},
        has_front_profile,
    )
    assert p1.backness is not None
    assert p1.backness.value == "central"
    assert PlacementFlag.UNDERSPECIFIED in p1.flags
    assert PlacementFlag.DEFAULT_ANCHOR in p1.flags

    # Inventory truly lacks front: now the fallback is honest.
    no_front_profile = VowelProfile(
        has_front=False,
        has_back=True,
        has_high=True,
        has_low=True,
        has_round=True,
    )
    p2 = vowel_grid_pos(
        {"high": "+", "low": "-", "back": "-", "round": "-"},
        no_front_profile,
    )
    assert p2.backness is not None
    assert p2.backness.value == "front"
    assert PlacementFlag.FALLBACK in p2.flags
    assert PlacementFlag.PROFILE_GATED in p2.flags


def test_central_by_spec_vs_conflict_vs_anchor_carry_distinct_flags(
    profile,
):
    """The three "central" outcomes anchor at the same screen cell
    but mean different things. Flags let downstream code distinguish
    them without parsing the free-text reason.
    """
    from phonology_shared.render.vowel_layout import PlacementFlag

    by_spec = vowel_grid_pos(
        {"high": "-", "low": "-", "front": "-", "back": "-", "round": "-"},
        profile,
    )
    by_conflict = vowel_grid_pos(
        {"high": "-", "low": "-", "front": "+", "back": "+", "round": "-"},
        profile,
    )
    by_anchor = vowel_grid_pos(
        {"high": "-", "low": "-", "round": "-"},
        profile,
    )
    assert by_spec.backness is not None and by_spec.backness.value == "central"
    assert (
        by_conflict.backness is not None
        and by_conflict.backness.value == "central"
    )
    assert (
        by_anchor.backness is not None
        and by_anchor.backness.value == "central"
    )
    assert PlacementFlag.DIRECT in by_spec.backness.flags
    assert PlacementFlag.CONFLICT in by_conflict.backness.flags
    assert PlacementFlag.DEFAULT_ANCHOR in by_conflict.backness.flags
    assert PlacementFlag.UNDERSPECIFIED in by_anchor.backness.flags
    assert PlacementFlag.DEFAULT_ANCHOR in by_anchor.backness.flags


def test_coronal_front_fallback_off_by_default(profile):
    """The paper recommends ``coronal -> front`` defaults off. The
    profile fixture has both ``has_coronal`` and ``has_front`` so
    today's gating already blocks it; flip ``has_front`` off and
    confirm the policy default still blocks the fallback.
    """
    from phonology_shared.render.vowel_layout import (
        PlacementPolicy,
        VowelProfile,
    )

    no_front_profile = VowelProfile(
        has_front=False, has_coronal=True, has_round=True
    )
    feats = {"high": "+", "low": "-", "coronal": "+", "round": "-"}
    default = vowel_grid_pos(feats, no_front_profile)
    assert default.backness is not None
    assert default.backness.value != "front"  # default OFF -> central

    # Opt-in via policy still works for callers who want it.
    opted_in = vowel_grid_pos(
        feats,
        no_front_profile,
        PlacementPolicy(allow_coronal_front_fallback=True),
    )
    assert opted_in.backness is not None
    assert opted_in.backness.value == "front"


def test_atr_tense_divergence_flag_fires_on_disagreement(profile):
    """When tense and ATR disagree, the placement carries the
    ``ATR_TENSE_DIVERGENCE`` flag so a renderer can surface the
    contention without text parsing.
    """
    from phonology_shared.render.vowel_layout import PlacementFlag

    agreeing = vowel_grid_pos(
        {
            "high": "+",
            "low": "-",
            "front": "+",
            "tense": "+",
            "atr": "+",
            "round": "-",
        },
        profile,
    )
    diverging = vowel_grid_pos(
        {
            "high": "+",
            "low": "-",
            "front": "+",
            "tense": "+",
            "atr": "-",
            "round": "-",
        },
        profile,
    )
    assert PlacementFlag.ATR_TENSE_DIVERGENCE not in agreeing.flags
    assert PlacementFlag.ATR_TENSE_DIVERGENCE in diverging.flags


def test_per_axis_evidence_exposes_height_backness_rounding(profile):
    """Every placement carries the per-axis :py:class:`AxisEvidence`
    so renderers can read source, confidence, and flags per axis
    without parsing the joined reason string.
    """
    from phonology_shared.render.vowel_layout import (
        AxisEvidence,
        PlacementFlag,
    )

    p = vowel_grid_pos(
        {"high": "+", "low": "-", "front": "+", "round": "+"},
        profile,
    )
    assert isinstance(p.height, AxisEvidence)
    assert isinstance(p.backness, AxisEvidence)
    assert isinstance(p.rounding, AxisEvidence)
    assert p.height.value == "Close"
    assert p.backness.value == "front"
    assert p.rounding.value == "rounded"
    # Direct specs carry the DIRECT flag on each axis.
    assert PlacementFlag.DIRECT in p.height.flags
    assert PlacementFlag.DIRECT in p.backness.flags
    assert PlacementFlag.DIRECT in p.rounding.flags


def test_split_low_by_tense_policy_knob(profile):
    """``policy.split_low_by_tense`` toggles whether ``[-tense]``
    low vowels render as Near-open or stay at Open. Default is True
    to preserve historical placements; the paper's recommended
    stricter default is False.
    """
    from phonology_shared.render.vowel_layout import PlacementPolicy

    feats = {
        "high": "-",
        "low": "+",
        "front": "-",
        "back": "-",
        "tense": "-",
        "round": "-",
    }
    default = vowel_grid_pos(feats, profile)
    paper_strict = vowel_grid_pos(
        feats, profile, PlacementPolicy(split_low_by_tense=False)
    )
    # Default: Near-open (row 5). Strict: Open (row 6). Row
    # indices reflect the 7-tier layout with Mid inserted between
    # Close-mid and Open-mid.
    assert default.row == 5
    assert paper_strict.row == 6


def test_long_pair_demotes_to_stack_when_slot_has_sibling() -> None:
    """A side-by-side Long-pair cell needs the full width of its
    backness-pair slot. When the inventory has another segment in
    the same row + backness slot, the pair cannot fit at the
    canonical anchor without overlapping its sibling, so the
    geometry builder demotes the pair to a vertical-stack cell
    (``is_long_pair=False``).
    """
    from phonology_shared.render.vowel_layout import (
        VowelProfile,
        build_vowel_chart_geometry,
        detect_vowel_profile,
    )

    common = {
        "high": "+", "low": "-", "front": "+", "back": "-",
        "tense": "+",
    }
    # Lone Long pair: both members share col 0, no sibling at
    # col 1 -> side-by-side stays.
    feats_alone = {
        "i":  {**common, "round": "-", "long": "-"},
        "iː": {**common, "round": "-", "long": "+"},
    }
    profile = detect_vowel_profile(list(feats_alone), feats_alone)
    g = build_vowel_chart_geometry(list(feats_alone), profile, feats_alone)
    pair_cell = next(c for c in g.cells if set(c.entries) == {"i", "iː"})
    assert pair_cell.is_long_pair is True

    # Add a sibling at col 1 (the rounded mate's slot) and the pair
    # demotes to a vertical stack so /y/ has its own legible
    # position.
    feats_with_sibling = {
        **feats_alone,
        "y": {**common, "round": "+", "long": "-"},
    }
    profile = detect_vowel_profile(list(feats_with_sibling), feats_with_sibling)
    g = build_vowel_chart_geometry(
        list(feats_with_sibling), profile, feats_with_sibling
    )
    pair_cell = next(c for c in g.cells if set(c.entries) == {"i", "iː"})
    assert pair_cell.is_long_pair is False
    y_cell = next(c for c in g.cells if c.entries == ("y",))
    assert y_cell.col == 1
    _ = VowelProfile  # imported for completeness; satisfies linters


def test_long_does_not_affect_placement() -> None:
    """``Long`` is a display-layer concern, not a vowel-space
    position. Two segments that differ only on ``Long`` must
    resolve to the same row and column so the renderer can present
    the length contrast as a visual treatment rather than the
    placement code splitting them across the chart.
    """
    from phonology_shared.render.vowel_layout import (
        VowelProfile,
        compute_placements,
    )

    profile = VowelProfile(
        has_front=True, has_back=True, has_high=True, has_low=True,
        has_round=True, has_long=True, has_long_contrast=True,
    )
    common = {"high": "+", "low": "-", "front": "+", "back": "-",
              "round": "-"}
    feats = {
        "i":  {**common, "long": "-"},
        "iː": {**common, "long": "+"},
    }
    _, placements = compute_placements(list(feats), profile, feats)
    assert placements["i"].row == placements["iː"].row
    assert placements["i"].col == placements["iː"].col


def test_has_long_contrast_requires_both_polarities() -> None:
    """``profile.has_long_contrast`` is True only when the inventory
    carries at least one ``Long+`` AND at least one ``Long-`` vowel.
    The display layer reads this to decide whether to surface a
    length contrast in the rendering; placement never consults it.
    """
    from phonology_shared.render.vowel_layout import detect_vowel_profile

    contrastive = detect_vowel_profile(
        ["a", "b"],
        {
            "a": {"long": "+", "high": "+"},
            "b": {"long": "-", "high": "+"},
        },
    )
    assert contrastive.has_long is True
    assert contrastive.has_long_contrast is True
    default_only = detect_vowel_profile(
        ["a", "b"],
        {"a": {"long": "-"}, "b": {"long": "-"}},
    )
    assert default_only.has_long is True
    assert default_only.has_long_contrast is False


def test_placement_carries_normalized_coordinates(profile):
    """Every placement carries normalized ``x`` / ``y`` /
    ``pair_offset`` alongside the existing ``row`` / ``col`` grid
    coordinates. The float fields feed the trapezoid/triangle
    projection. Anchor values are derived in
    :py:func:`_derive_backness_anchors` from the layout pixel
    constants; this test pins the structural invariants rather
    than the exact numbers so tuning the pixel constants does
    not also rewrite the test.
    """
    # Close front rounded /y/: top of the chart, leftmost backness,
    # rounded so pair_offset is positive.
    close_front_rnd = vowel_grid_pos(
        {"high": "+", "low": "-", "front": "+", "back": "-", "round": "+"},
        profile,
    )
    assert close_front_rnd.row == 0
    assert close_front_rnd.col == 1
    # Anchors are insetted from 0 / 1 so paired mates do not
    # overshoot the data area on the leftmost or rightmost
    # backness. The exact values are derived; structural bounds:
    assert 0.0 < close_front_rnd.x < 0.5
    assert 0.0 <= close_front_rnd.y < 0.2
    assert close_front_rnd.pair_offset > 0.0

    # Open back unrounded /ɑ/: bottom of the chart, rightmost
    # backness, unrounded so pair_offset is negative.
    open_back_unr = vowel_grid_pos(
        {"high": "-", "low": "+", "front": "-", "back": "+", "round": "-"},
        profile,
    )
    assert 0.8 < open_back_unr.y <= 1.0
    assert 0.5 < open_back_unr.x < 1.0
    assert open_back_unr.pair_offset < 0.0

    # Unrounded and rounded mates sit on the same anchor with
    # opposite-sign offsets of equal magnitude. A projector relies
    # on this symmetry.
    assert open_back_unr.pair_offset == -close_front_rnd.pair_offset

    # Front + back anchors are symmetric around x == 0.5 so the
    # chart's vertical axis sits in the middle of the central
    # column regardless of which row.
    open_front_unr = vowel_grid_pos(
        {"high": "-", "low": "+", "front": "+", "back": "-", "round": "-"},
        profile,
    )
    assert abs((open_front_unr.x + open_back_unr.x) / 2 - 0.5) < 1e-9

    # Central anchor stays at x == 0.5 regardless of rounding so a
    # projection layer can use the anchor as the symmetry axis.
    central_unr = vowel_grid_pos(
        {"high": "-", "low": "-", "front": "-", "back": "-", "round": "-"},
        profile,
    )
    assert central_unr.x == 0.5
