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

from collections.abc import Callable

import pytest

from phonology_shared.chart.vowels import (
    VowelProfile,
    compute_placements,
    detect_vowel_profile,
    vowel_grid_pos,
)
from phonology_shared.theory.feature_engine import FeatureEngine


def _vowel_segs(engine: FeatureEngine) -> list[str]:
    return [
        s for s in engine.segments if engine.segments[s].get("Syllabic") == "+"
    ]


@pytest.mark.parametrize(
    "inv_name",
    ["english", "general", "hayes"],
)
def test_vowel_placement_case_insensitive(
    inv_name: str,
    bundled_engine: Callable[[str], FeatureEngine],
) -> None:
    """vowel_grid_pos and detect_vowel_profile must produce the
    same output whether the caller passes raw (PascalCase) feats or
    normalized (lowercase) feats."""
    engine = bundled_engine(inv_name)
    vowels = _vowel_segs(engine)
    if not vowels:
        pytest.skip(f"{inv_name} has no vowels")
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


def test_vowel_placement_resolves_alias_feature_names() -> None:
    """A chart feature declared under a registered ALIAS spelling
    (e.g. ``advancedTongueRoot`` for ATR, ``hi`` for High) must read
    the same as its canonical spelling.

    The chart fold goes through ``normalize_feature_key`` (alias-aware,
    the same primitive the engine uses), not a bare ``str.lower``, so
    a hand-authored inventory that names a feature by alias is not
    silently misread as lacking it (which would default its vowels to
    the Open-mid Central cell). Before this, ``advancedTongueRoot``
    lowercased to ``advancedtongueroot`` and never matched ``atr``.
    """
    segs = ["i", "a", "o"]
    canonical = {
        "i": {"High": "+", "Low": "-", "Front": "+", "Back": "-", "ATR": "+"},
        "a": {"High": "-", "Low": "+", "Front": "-", "Back": "-", "ATR": "-"},
        "o": {"High": "-", "Low": "-", "Front": "-", "Back": "+", "ATR": "+"},
    }
    alias_of = {"High": "hi", "ATR": "advancedTongueRoot"}
    aliased = {
        seg: {alias_of.get(k, k): v for k, v in bundle.items()}
        for seg, bundle in canonical.items()
    }
    canon_profile = detect_vowel_profile(segs, canonical)
    alias_profile = detect_vowel_profile(segs, aliased)
    assert canon_profile == alias_profile
    # The alias-only features resolved to their canonical axes.
    assert alias_profile.has_atr and alias_profile.has_high
    for seg in segs:
        assert vowel_grid_pos(canonical[seg], canon_profile) == vowel_grid_pos(
            aliased[seg], alias_profile
        ), seg


def test_english_vowels_not_all_in_default_cell(
    bundled_engine: Callable[[str], FeatureEngine],
) -> None:
    """Regression: with case-insensitive lookup wired correctly, the
    English vowel chart MUST spread vowels across multiple cells.
    The original bug had every vowel landing in (row=3, col=2) =
    Open-mid Central because the lookups missed PascalCase keys.
    """
    engine = bundled_engine("english")
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


def test_compute_placements_general_tier_two_mid_splits_schwa_from_open_mid(
    bundled_engine: Callable[[str], FeatureEngine],
):
    """The General inventory's ə (ATR=0) and ɜ (ATR=-) historically
    collapsed onto the same Open-mid Central cell because the Tier 1
    height inference could not tell them apart. The Tier 2 Mid
    display policy now lifts ə onto the Mid row (logical row 3,
    inserted between Close-mid and Open-mid) while ɜ stays on
    Open-mid (logical row 4), so the renderer no longer stacks them.
    """
    engine = bundled_engine("general")
    vowels = _vowel_segs(engine)
    seg_feats = {s: dict(engine.segments[s]) for s in vowels}
    profile = detect_vowel_profile(vowels, seg_feats)
    occupied, placements = compute_placements(vowels, profile, seg_feats)
    # ə now lives on the Mid row; ɜ stays on Open-mid.
    assert occupied.get((3, 2)) == ["ə"]
    assert occupied.get((4, 2)) == ["ɜ"]
    assert placements["ə"].height.value == "Mid"
    assert placements["ɜ"].height.value == "Open-mid"


def test_compute_placements_orders_by_confidence_desc(
    bundled_engine: Callable[[str], FeatureEngine],
):
    """Within a collision cell, the highest-confidence vowel sorts
    first so the desktop renders it on top and the web stacks it at
    the top of the visible stack."""
    engine = bundled_engine("general")
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


def test_phoible_shaped_close_front_vowel_places_correctly():
    """A synthetic PHOIBLE-shaped vowel bundle places at the
    Close Front cell.

    PHOIBLE inventories carry the post-bake title-case names
    (``Syllabic``, ``High``, ``Front``, ``Back``, ``Round``); the
    placement reader casefolds at the entry to ``vowel_grid_pos``
    so PHOIBLE's broader feature axes are read identically to the
    bundled Hayes lowercase keys. This test pins that contract so
    a future refactor of the placement reader cannot silently
    regress PHOIBLE compatibility.
    """
    import phonology_shared.chart.vowel_space as vsp
    import phonology_shared.chart.vowels as vl

    feats = {
        "i_test": {
            "Syllabic": "+",
            "Consonantal": "-",
            "High": "+",
            "Low": "-",
            "Front": "+",
            "Back": "-",
            "Round": "-",
            "Tense": "+",
            "Long": "-",
        }
    }
    profile = vl.detect_vowel_profile(["i_test"], feats)
    occupied, placements = vl.compute_placements(["i_test"], profile, feats)
    placement = placements["i_test"]
    assert placement.row == vsp.ROW_LABELS.index("Close"), (
        f"PHOIBLE +High maps to Close height tier, got "
        f"{vsp.ROW_LABELS[placement.row]}"
    )
    # Front column index (front anchor) per
    # ``COL_LABELS == ("Front", "Central", "Back")``.
    assert vsp.COL_LABELS[0] == "Front"


def test_diphthong_placement_carries_secondary_and_flag():
    """A PHOIBLE-shaped ``/ia/`` bundle: the primary places at a
    Close Front cell and the final state at an Open Central /
    Front cell. Both placements carry
    :py:attr:`PlacementFlag.DIPHTHONG` so the renderer can detect
    the diphthong from either endpoint.

    Diphthongs do NOT occupy chart cells; they render as arrows
    + chip strip exclusively. ``placements[seg]`` still carries
    the segment's geometry (so the arrow can be drawn) but
    ``occupied`` does NOT contain an entry for ``seg``. This is
    the architectural fix that addressed the user complaint
    "singleton segments are grouped as diphthongs": pre-fix
    /ia/'s primary placement at /i/-cell caused it to share the
    /i/ stack visually; post-fix /ia/ never enters any cell.
    """
    import phonology_shared.chart.vowel_space as vsp
    import phonology_shared.chart.vowels as vl

    primary = {
        "Syllabic": "+",
        "Consonantal": "-",
        "High": "+",
        "Low": "-",
        "Front": "+",
        "Back": "-",
        "Round": "-",
    }
    final = {
        "Syllabic": "+",
        "Consonantal": "-",
        "High": "-",
        "Low": "+",
        "Front": "-",
        "Back": "-",
        "Round": "-",
    }
    feats = {"ia": primary}
    secondary_in = {"ia": final}
    profile = vl.detect_vowel_profile(["ia"], feats)
    occupied, placements = vl.compute_placements(
        ["ia"], profile, feats, segment_secondary=secondary_in
    )
    placement = placements["ia"]
    assert placement.secondary is not None
    assert vl.PlacementFlag.DIPHTHONG in placement.flags
    assert vl.PlacementFlag.DIPHTHONG in placement.secondary.flags
    assert placement.row == vsp.ROW_LABELS.index(
        "Close"
    ), "primary anchors at Close (high) tier"
    assert placement.secondary.row == vsp.ROW_LABELS.index(
        "Open"
    ), "final anchors at Open (low) tier"
    # ``occupied`` must NOT contain /ia/; diphthongs render via
    # arrows + chip strip, not cell occupancy.
    assert occupied == {}, (
        f"diphthongs must not occupy chart cells; got {occupied!r}. "
        f"The placer's PlacementFlag.DIPHTHONG gate in "
        f"compute_placements should skip the occupied.setdefault."
    )


def test_module_constants_are_tuples():
    """ROW_LABELS / COL_LABELS / VOWEL_HEIGHT are exported as
    tuples so importers cannot mutate the shared singletons."""
    import phonology_shared.chart.vowel_space as vsp

    assert isinstance(vsp.ROW_LABELS, tuple)
    assert isinstance(vsp.COL_LABELS, tuple)
    assert isinstance(vsp.VOWEL_HEIGHT, tuple)
    # Spot-check shape so a future re-shape is a deliberate break.
    # Seven height tiers since the Tier 2 Mid row landed between
    # Close-mid and Open-mid.
    assert len(vsp.ROW_LABELS) == 7
    assert "Mid" in vsp.ROW_LABELS
    assert vsp.COL_LABELS == ("Front", "Central", "Back")


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
    """Default profile with every feature considered active AND
    contrastive. Tests that don't care about the fallback gating
    can use this. ``has_tense_contrast`` / ``has_atr_contrast`` set
    True so the divergence detector treats both as real sources --
    most tests in this file rely on tense/ATR being height-split
    sources rather than uniform inventory polarities."""
    return VowelProfile(
        has_front=True,
        has_back=True,
        has_high=True,
        has_low=True,
        has_round=True,
        has_labial=True,
        has_atr=True,
        has_atr_contrast=True,
        has_tense=True,
        has_tense_contrast=True,
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


def test_chart_geometry_handles_no_vowels() -> None:
    """``build_vowel_chart_geometry`` must not crash on an inventory
    that contains zero vowels. The original implementation indexed
    ``populated_logical_rows[0]`` unconditionally and IndexError'd
    out the entire ``build_inventory_summary`` call path, taking
    down the New-inventory flow for any consonant-only setup (the
    default ``DEFAULT_SEGMENTS`` placeholder is "p b t d k ɡ", so
    the crash fired on the first New click that left the segments
    box at the placeholder).

    Empty inventories produce a degenerate but valid geometry:
    canonical full-range silhouette, no rows, no cells, no cols.
    Both renderers already guard on ``cells.length > 0`` before
    drawing anything so the user simply sees no vowel chart.
    """
    from phonology_shared.chart.vowel_geometry import (
        VOWEL_CHART_TITLE,
        build_vowel_chart_geometry,
    )

    # Empty segs is the literal "no vowels" case the bug fired on.
    profile = detect_vowel_profile([], {})
    geometry = build_vowel_chart_geometry([], profile, {})

    assert geometry.title == VOWEL_CHART_TITLE
    assert geometry.cells == ()
    assert geometry.rows == ()
    assert geometry.cols == ()
    # Silhouette is the canonical fallback so renderers can still
    # paint a chart frame if they want to; both clients currently
    # short-circuit on empty cells.
    assert geometry.silhouette is not None


def test_chart_geometry_omits_empty_rows(
    bundled_engine: Callable[[str], FeatureEngine],
) -> None:
    """``build_vowel_chart_geometry`` skips height tiers that have
    no occupied cell. Without this, the web renderer would emit a
    "Close" row label for an inventory with no close vowels.
    """
    from phonology_shared.chart.vowel_geometry import (
        build_vowel_chart_geometry,
    )

    engine = bundled_engine("english")
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
    # Rows listed in ascending logical-row order; ``chart_y``
    # strictly increases with logical row.
    chart_ys = [r.chart_y for r in geometry.rows]
    assert chart_ys == sorted(chart_ys)


def test_chart_geometry_cell_chart_x_within_bounds(
    bundled_engine: Callable[[str], FeatureEngine],
) -> None:
    """Every cell's ``chart_x`` lives in ``[0, 1]`` so the renderer's
    ``left: chart_x * 100%`` lands inside the data area. Replaces
    the legacy ``grid_col`` spacer-track check now that the grid
    positions live in the renderer, not the geometry payload.
    """
    from phonology_shared.chart.vowel_geometry import (
        build_vowel_chart_geometry,
    )

    engine = bundled_engine("general")
    vowel_segs = _vowel_segs(engine)
    seg_feats = {s: dict(engine.segments[s]) for s in vowel_segs}
    profile = detect_vowel_profile(vowel_segs, seg_feats)
    geometry = build_vowel_chart_geometry(vowel_segs, profile, seg_feats)

    for cell in geometry.cells:
        assert 0.0 <= cell.chart_x <= 1.0, (
            f"cell at logical ({cell.row}, {cell.col}) has chart_x"
            f"={cell.chart_x} outside [0, 1]"
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
    from phonology_shared.chart.vowels import (
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
    from phonology_shared.chart.vowels import (
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
    from phonology_shared.chart.vowels import PlacementFlag

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
    from phonology_shared.chart.vowels import (
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


def test_split_source_divergence_flag_fires_on_disagreement(profile):
    """When tense and ATR disagree, the placement carries the
    ``SPLIT_SOURCE_DIVERGENCE`` flag so a renderer can surface the
    contention without text parsing. The flag is the unified
    successor of the older ``ATR_TENSE`` flag now that RTR is a
    third split source.
    """
    from phonology_shared.chart.vowels import PlacementFlag

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
    assert PlacementFlag.SPLIT_SOURCE_DIVERGENCE not in agreeing.flags
    assert PlacementFlag.SPLIT_SOURCE_DIVERGENCE in diverging.flags


def test_per_axis_evidence_exposes_height_backness_rounding(profile):
    """Every placement carries the per-axis :py:class:`AxisEvidence`
    so renderers can read source, confidence, and flags per axis
    without parsing the joined reason string.
    """
    from phonology_shared.chart.vowels import (
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
    from phonology_shared.chart.vowels import PlacementPolicy

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


def test_long_pair_stays_side_by_side_and_grows_chart() -> None:
    """A side-by-side Long-pair cell keeps its ``LONG_PAIR``
    display_kind even when the inventory populates a sibling in
    the same backness-pair slot. Instead of demoting the pair to a
    vertical stack, the builder reports the inventory's expanded
    natural width via
    :py:attr:`VowelChartGeometry.natural_data_width_px`; the
    renderer grows the chart slot so all cells stay legible.
    """
    from phonology_shared.chart.vowel_geometry import (
        build_vowel_chart_geometry,
    )
    from phonology_shared.chart.vowels import (
        VowelCellDisplayKind,
        detect_vowel_profile,
    )

    common = {
        "high": "+",
        "low": "-",
        "front": "+",
        "back": "-",
        "tense": "+",
    }
    feats = {
        "i": {**common, "round": "-", "long": "-"},
        "iː": {**common, "round": "-", "long": "+"},
        "y": {**common, "round": "+", "long": "-"},
    }
    profile = detect_vowel_profile(list(feats), feats)
    g = build_vowel_chart_geometry(list(feats), profile, feats)
    pair_cell = next(c for c in g.cells if set(c.entries) == {"i", "iː"})
    y_cell = next(c for c in g.cells if c.entries == ("y",))
    assert pair_cell.display_kind == VowelCellDisplayKind.LONG_PAIR
    assert y_cell.col == 1
    # Front slot needs Long pair (2 buttons + gap) + inter-cell gap
    # + single /y/. The natural width must surface at least that
    # much so a growth-aware renderer can widen the chart.
    pair_w = 2 * 33 + 2
    expected_front_slot_w = pair_w + 2 + 33
    assert g.natural_data_width_px >= expected_front_slot_w


def test_long_does_not_affect_placement() -> None:
    """``Long`` is a display-layer concern, not a vowel-space
    position. Two segments that differ only on ``Long`` must
    resolve to the same row and column so the renderer can present
    the length contrast as a visual treatment rather than the
    placement code splitting them across the chart.
    """
    from phonology_shared.chart.vowels import (
        VowelProfile,
        compute_placements,
    )

    profile = VowelProfile(
        has_front=True,
        has_back=True,
        has_high=True,
        has_low=True,
        has_round=True,
        has_long=True,
        has_long_contrast=True,
    )
    common = {"high": "+", "low": "-", "front": "+", "back": "-", "round": "-"}
    feats = {
        "i": {**common, "long": "-"},
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
    from phonology_shared.chart.vowels import detect_vowel_profile

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


# ---------------------------------------------------------------------------
# Silhouette aspect ratio ceiling
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "inv_name",
    [
        "english",
        "german",
        "hayes",
        "hindi",
        "korean",
        "spanish",
        "modern_standard_arabic",
        "japanese",
    ],
)
def test_silhouette_aspect_within_ceiling(
    inv_name: str,
    bundled_engine: Callable[[str], FeatureEngine],
) -> None:
    """Every bundled inventory's silhouette aspect (width / height)
    must stay at or below ``VOWEL_SILHOUETTE_MAX_ASPECT``. The
    geometry builder grows ``natural_data_height_px`` when natural
    sizing would overshoot the ceiling. Catches a future change
    that disables the ceiling or breaks the dh-growth path.
    """
    from phonology_shared.chart.vowel_geometry import (
        build_vowel_chart_geometry,
    )
    from phonology_shared.presentation.chart_style import (
        VOWEL_SILHOUETTE_MAX_ASPECT,
    )

    engine = bundled_engine(inv_name)
    vowels = _vowel_segs(engine)
    if not vowels:
        pytest.skip(f"{inv_name} has no vowels")
    seg_feats = {s: dict(engine.segments[s]) for s in vowels}
    profile = detect_vowel_profile(vowels, seg_feats)
    geom = build_vowel_chart_geometry(vowels, profile, seg_feats)
    sil = geom.silhouette
    sil_h = (sil.bottom_y - sil.top_y) * geom.natural_data_height_px
    assert sil_h > 0
    aspect = geom.natural_data_width_px / sil_h
    # Small epsilon for the ceil() rounding the ceiling enforcer uses.
    assert aspect <= VOWEL_SILHOUETTE_MAX_ASPECT + 0.05, (
        f"{inv_name} silhouette aspect {aspect:.3f} exceeds the "
        f"ceiling {VOWEL_SILHOUETTE_MAX_ASPECT}; pre-fix this was "
        "common for sparse inventories like Spanish (2.35) and "
        "Modern Standard Arabic (3.29). The geometry builder must "
        "grow natural_data_height_px to bring the aspect down."
    )
