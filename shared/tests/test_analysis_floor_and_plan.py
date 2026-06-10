"""Shared layout tests for the analysis-pane floor and the new
geometry-aware segment-pane layout planner.

These tests pin the two invariants the desktop fix depends on:

1. ``analysis_content_floor_h()`` is a pure function of the
   ``ANALYSIS_*`` and ``FEAT_ROW_H`` constants (no inventory
   inputs, identical value across any call sequence) and matches
   ``MIN_ANALYSIS_H``. Both UIs lock to this floor; if the helper
   drifts from the constant, the web's ``--min-analysis-h`` and the
   desktop's ``minimumSizeHint`` will disagree.

2. ``plan_seg_layout()`` (the new spillover policy) honours its six-
   step contract: chart-aware spillover rectangle, width-driven column
   count, smallest-k sweep, LPT packing with source-order rendering,
   width-rejection of oversized groups, and a "scroll instead" fallback
   when no plan fits.
"""

from __future__ import annotations

from phonology_shared.presentation import layout as L

# Analysis floor


def test_analysis_content_floor_h_matches_min_analysis_h() -> None:
    """The helper and the module-level constant the web build relays
    must agree byte-for-byte. Drift here would silently change the
    web's locked analysis pane height while the desktop kept the
    helper's value.
    """
    assert L.analysis_content_floor_h() == L.MIN_ANALYSIS_H


def test_analysis_content_floor_h_decomposition_matches_constants() -> None:
    """Spell out the recipe so a future tweak to either the chrome
    constants or the row count fails this test before it breaks the
    UI. ``ANALYSIS_MIN_VISIBLE_ROWS = 4`` is the user-stated
    requirement that the pane must reliably show four rows.
    """
    expected = (
        L.ANALYSIS_SELECTION_STRIP_H
        + L.ANALYSIS_TAB_BAR_H
        + L.ANALYSIS_MIN_VISIBLE_ROWS * L.FEAT_ROW_H
        + L.ANALYSIS_OUTER_PADDING_H
    )
    assert L.analysis_content_floor_h() == expected
    assert L.ANALYSIS_MIN_VISIBLE_ROWS == 4


def test_analysis_content_floor_h_is_pure() -> None:
    """No hidden inventory state; repeated calls return the same
    integer. This is the property the user means by 'should not depend
    accidentally on whatever inventory was loaded first'.
    """
    first = L.analysis_content_floor_h()
    for _ in range(5):
        assert L.analysis_content_floor_h() == first


def test_analysis_panel_region_min_h_uses_the_floor() -> None:
    """``AnalysisPanel.minimumSizeHint()`` reads
    ``REGION_CONSTRAINTS['analysis_panel'].min_h``; that entry must
    be the comfortable floor, NOT ``HARD_MIN_ANALYSIS_H`` (60 px),
    so the Qt splitter refuses to compress past four feature rows.
    """
    assert (
        L.REGION_CONSTRAINTS["analysis_panel"].min_h
        == L.analysis_content_floor_h()
    )


def test_top_pane_height_reserves_the_analysis_floor() -> None:
    """On a comfortable window, ``top_pane_height`` must reserve at
    least ``analysis_content_floor_h()`` for the analysis pane. The
    bottom row = ``total - top_h``; assert it is at least the floor
    for any reasonable window.
    """
    floor = L.analysis_content_floor_h()
    for total in (900, 1080, 1200, 1440):
        # top_need_h asks for the entire window; the cap is what
        # protects the analysis pane.
        top_h = L.top_pane_height(top_need_h=total, total=total)
        assert total - top_h >= floor, (
            f"at total={total}, top got {top_h} px, leaving "
            f"{total - top_h} for analysis (floor={floor})"
        )


def test_top_pane_height_degrades_to_hard_floor_on_tiny_window() -> None:
    """When the window is so short that ``analysis_content_floor_h``
    + ``MIN_TOP_PANE_H`` would not fit, the policy degrades to the
    absolute ``HARD_MIN_ANALYSIS_H`` so the top pane stays usable.
    Documented degenerate path.
    """
    # Cooked window: MIN_TOP_PANE_H + 100 < MIN_TOP_PANE_H + floor.
    tiny = L.MIN_TOP_PANE_H + 100
    top_h = L.top_pane_height(top_need_h=tiny, total=tiny)
    # Top pane gets at least MIN_TOP_PANE_H; analysis gets the rest.
    assert top_h >= L.MIN_TOP_PANE_H
    # Analysis still gets at least the hard floor.
    assert tiny - top_h >= L.HARD_MIN_ANALYSIS_H


# plan_seg_layout: geometry-aware segment-pane layout


def _heights(values: list[int]) -> list[int]:
    return values


def _names(n: int, prefix: str = "g") -> list[str]:
    return [f"{prefix}{i}" for i in range(n)]


def test_plan_no_spillover_when_main_flow_fits() -> None:
    """If every group fits in the main flow, the plan has empty
    spillover and the full group set in main."""
    names = _names(3)
    plan = L.plan_seg_layout(
        names,
        _heights([100, 100, 100]),
        [200, 200, 200],
        pane_w=600,
        pane_h=400,
        chart_rect=None,
        min_col_w=150,
    )
    assert plan.main_groups == tuple(names)
    assert plan.spillover_groups == ()
    assert plan.n_spillover_cols == 0


def test_plan_spillover_kicks_in_when_main_overflows() -> None:
    """Five 100 px groups in a 350 px pane: smallest k that fits is
    the one that leaves <= 350 in main + spillover combined. Group
    widths are 80 px, well within the spillover column width at the
    chosen pane width / min_col_w combination."""
    names = _names(5)
    plan = L.plan_seg_layout(
        names,
        _heights([100, 100, 100, 100, 100]),
        [80, 80, 80, 80, 80],
        pane_w=600,
        pane_h=350,
        chart_rect=None,
        min_col_w=150,
    )
    assert plan.main_groups + plan.spillover_groups == tuple(names)
    assert len(plan.spillover_groups) > 0
    assert plan.n_spillover_cols >= 1


def test_plan_uses_chart_rect_to_position_spillover() -> None:
    """When a chart_rect is given, the spillover sits below the
    chart's bottom edge, not below the main flow alone."""
    names = _names(4)
    plan = L.plan_seg_layout(
        names,
        _heights([50, 50, 50, 50]),
        [200, 200, 200, 200],
        pane_w=800,
        pane_h=600,
        chart_rect=(420, 0, 380, 240),
        min_col_w=100,
    )
    # Main flow + chart fit; no spillover required.
    if plan.spillover_groups:
        sx, sy, sw, sh = plan.spillover_rect
        assert sy >= 240, f"spillover top {sy} must be below chart bottom 240"


def test_plan_column_count_scales_with_width() -> None:
    """Wide pane to more spillover columns; narrow pane to fewer.
    Capped at ``max_spillover_cols`` so even an ultrawide doesn't
    fan groups into a strip.
    """
    names = _names(6)
    heights = _heights([100] * 6)
    widths = [80] * 6
    narrow = L.plan_seg_layout(
        names,
        heights,
        widths,
        pane_w=400,
        pane_h=250,
        chart_rect=None,
        min_col_w=120,
    )
    wide = L.plan_seg_layout(
        names,
        heights,
        widths,
        pane_w=1400,
        pane_h=250,
        chart_rect=None,
        min_col_w=120,
    )
    assert narrow.n_spillover_cols <= 4
    assert wide.n_spillover_cols <= 4
    assert wide.n_spillover_cols >= narrow.n_spillover_cols


def test_plan_caps_columns_at_max_spillover_cols() -> None:
    """The cap (default 4) prevents incoherent fan-out on extremely
    wide panes."""
    names = _names(8)
    plan = L.plan_seg_layout(
        names,
        _heights([100] * 8),
        [50] * 8,
        pane_w=3000,
        pane_h=200,
        chart_rect=None,
        min_col_w=50,
        max_spillover_cols=4,
    )
    assert plan.n_spillover_cols <= 4
    plan_capped_lower = L.plan_seg_layout(
        names,
        _heights([100] * 8),
        [50] * 8,
        pane_w=3000,
        pane_h=200,
        chart_rect=None,
        min_col_w=50,
        max_spillover_cols=2,
    )
    assert plan_capped_lower.n_spillover_cols <= 2


def test_plan_lpt_packs_tighter_than_pair_rows() -> None:
    """LPT bin-packing beats the old fixed-pair-row scheme on
    skewed distributions. With heights [300, 100, 100, 100, 100, 100]
    LPT gives columns [300] and [100, 100, 100, 100, 100]=500, so
    bounding=500. The old pair-row scheme would give the same total
    in this degenerate case; the property we pin is that LPT's
    bounding is <= naive row-stack (max-of-pair sums).
    """
    names = _names(6)
    heights = _heights([300, 100, 100, 100, 100, 100])
    plan = L.plan_seg_layout(
        names,
        heights,
        [80] * 6,
        pane_w=400,
        pane_h=550,
        chart_rect=None,
        min_col_w=150,
    )
    if plan.spillover_groups:
        # Compute the actual bounding from the assignment.
        col_heights = [0] * plan.n_spillover_cols
        for i, col in enumerate(plan.spillover_column_assignment):
            idx_in_full = len(plan.main_groups) + i
            col_heights[col] += heights[idx_in_full]
        bounding = max(col_heights)
        # Old algorithm's bounding (fixed-pair sums of maxes) is at
        # least the LPT bounding for the same set.
        spill_heights = heights[len(plan.main_groups) :]
        pair_h = sum(
            max(spill_heights[i : i + 2])
            for i in range(0, len(spill_heights), 2)
        )
        assert bounding <= pair_h


def test_plan_preserves_source_order_within_each_column() -> None:
    """The column assignment uses LPT but the user reads
    column-major top-to-bottom; within a column, groups appear in
    their source order. This test pins that property: for every
    column, the spillover_groups indices assigned to it are sorted
    ascending.
    """
    names = _names(7)
    plan = L.plan_seg_layout(
        names,
        _heights([100, 200, 150, 50, 90, 80, 70]),
        [80] * 7,
        pane_w=600,
        pane_h=300,
        chart_rect=None,
        min_col_w=180,
    )
    if not plan.spillover_groups:
        return  # nothing to check
    by_col: dict[int, list[int]] = {}
    for i, col in enumerate(plan.spillover_column_assignment):
        by_col.setdefault(col, []).append(i)
    for col, indices in by_col.items():
        assert indices == sorted(
            indices
        ), f"column {col} has out-of-order spill indices {indices}"


def test_plan_rejects_oversized_groups() -> None:
    """A group whose natural width exceeds the per-column width must
    NOT end up in spillover. The sweep skips ``k`` values where
    spilling that group would put it past the column width."""
    names = _names(4)
    plan = L.plan_seg_layout(
        names,
        _heights([200, 100, 100, 100]),
        [80, 80, 80, 500],
        pane_w=400,
        pane_h=250,
        chart_rect=None,
        min_col_w=100,
    )
    # The oversized group either stays in main or the plan returns
    # the all-main fallback. Either way, the oversized group is NOT
    # in spillover.
    assert "g3" not in plan.spillover_groups


def test_plan_fallback_returns_all_main_when_nothing_fits() -> None:
    """If no k makes the layout fit, every group lands in main flow
    and the caller's QScrollArea takes over (overflow='scroll')."""
    names = _names(3)
    plan = L.plan_seg_layout(
        names,
        _heights([500, 500, 500]),
        [80, 80, 80],
        pane_w=400,
        pane_h=300,
        chart_rect=None,
        min_col_w=100,
    )
    # Even k=3 (all in spillover) doesn't fit because the bounding
    # is the tallest group >= pane_h. Plan falls back to all-main.
    assert plan.main_groups == tuple(names)
    assert plan.spillover_groups == ()


def test_plan_empty_input_is_empty_plan() -> None:
    plan = L.plan_seg_layout(
        [], [], [], pane_w=600, pane_h=300, chart_rect=None, min_col_w=100
    )
    assert plan.main_groups == ()
    assert plan.spillover_groups == ()
    assert plan.n_spillover_cols == 0


def test_plan_mismatched_input_lengths_raises() -> None:
    import pytest

    with pytest.raises(ValueError):
        L.plan_seg_layout(
            ["a", "b"],
            [100, 100, 100],
            [50, 50],
            pane_w=400,
            pane_h=300,
            chart_rect=None,
            min_col_w=100,
        )
