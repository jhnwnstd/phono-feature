"""Tests for the adaptive-window-layout helpers in
:py:mod:`phonology_features.gui.layout`.

These functions are the single source of truth that both the desktop
(Qt splitter sizing in ``geometry_controller``) and the web (CSS
custom properties baked by ``web/scripts/build.py`` into
``dist/layout.css``) consume. Drift between the two UIs is impossible
without breaking these assertions.
"""

from __future__ import annotations

from phonology_features.gui import layout

# ---------------------------------------------------------------------------
# distribute_pane_widths
# ---------------------------------------------------------------------------


def test_distribute_seg_absorbs_extra_width_at_typical_desktop() -> None:
    # Typical 1920×1080 workspace, ~1440 px window. Feat pane should
    # land at content + cushion; seg gets the rest.
    seg_w, feat_w = layout.distribute_pane_widths(
        1440, seg_content_w=500, feat_content_w=600
    )
    assert feat_w == 600 + layout.FEAT_CUSHION_PX
    assert seg_w == 1440 - feat_w


def test_distribute_feat_clamped_to_min_when_content_tiny() -> None:
    seg_w, feat_w = layout.distribute_pane_widths(
        1440, seg_content_w=500, feat_content_w=100
    )
    assert feat_w == layout.FEAT_MIN_W
    assert seg_w == 1440 - feat_w


def test_distribute_seg_respects_floor_on_narrow_window() -> None:
    # Total below the natural seg+feat floor: seg holds at SEG_MIN_W
    # rather than shrinking below it. Caller (the splitter) is then
    # responsible for whatever scroll/hide policy it wants.
    seg_w, feat_w = layout.distribute_pane_widths(
        700, seg_content_w=300, feat_content_w=300
    )
    assert seg_w >= layout.SEG_MIN_W
    assert feat_w >= layout.FEAT_MIN_W


def test_distribute_segments_get_almost_all_4k_extra() -> None:
    # On a 4K-class window the feat pane stays modest while seg
    # soaks up the rest.
    seg_w, feat_w = layout.distribute_pane_widths(
        3000, seg_content_w=500, feat_content_w=700
    )
    assert feat_w == 700 + layout.FEAT_CUSHION_PX
    # Seg should be much larger than feat at this width.
    assert seg_w > 2 * feat_w


def test_distribute_seg_content_overrides_min() -> None:
    # If the segment content's own sizeHint is wider than the min
    # floor, seg never shrinks below that.
    seg_w, _ = layout.distribute_pane_widths(
        1000, seg_content_w=900, feat_content_w=300
    )
    assert seg_w >= 900


# ---------------------------------------------------------------------------
# vowel_chart_width
# ---------------------------------------------------------------------------


def test_vowel_clamped_to_min_when_seg_too_narrow() -> None:
    # Below the min, the function still returns the floor — caller
    # uses should_stack_vowels to decide whether to host it at all.
    assert layout.vowel_chart_width(100) == layout.VOWEL_MIN_W


def test_vowel_clamped_to_max_frac_when_seg_wide() -> None:
    seg_pane_w = 2000
    assert layout.vowel_chart_width(seg_pane_w) <= int(
        seg_pane_w * layout.VOWEL_MAX_FRAC
    )


def test_vowel_monotonic_in_seg_pane_width() -> None:
    # Wider seg pane → at-least-as-wide chart. The function is
    # piecewise: flat at the floor, then linear in seg_pane_w.
    widths = [layout.vowel_chart_width(w) for w in (300, 600, 900, 1500, 2400)]
    assert widths == sorted(widths)


def test_vowel_zero_or_negative_returns_min() -> None:
    # Defensive: pre-show seg-pane width can be 0. Caller still gets
    # a sensible value so downstream code doesn't divide by zero.
    assert layout.vowel_chart_width(0) == layout.VOWEL_MIN_W
    assert layout.vowel_chart_width(-50) == layout.VOWEL_MIN_W


# ---------------------------------------------------------------------------
# should_stack_vowels / should_collapse_single_column
# ---------------------------------------------------------------------------


def test_should_stack_vowels_at_threshold() -> None:
    assert layout.should_stack_vowels(layout.VOWEL_STACK_W - 1)
    assert not layout.should_stack_vowels(layout.VOWEL_STACK_W)
    assert not layout.should_stack_vowels(layout.VOWEL_STACK_W + 1)


def test_should_collapse_single_column_at_threshold() -> None:
    assert layout.should_collapse_single_column(layout.COLLAPSE_W - 1)
    assert not layout.should_collapse_single_column(layout.COLLAPSE_W)
    assert not layout.should_collapse_single_column(layout.COLLAPSE_W + 1)


# ---------------------------------------------------------------------------
# recommended_initial_window_size
# ---------------------------------------------------------------------------


def test_initial_size_floored_on_small_screen() -> None:
    # Below the floor (e.g. 1366×768 laptop), the function returns
    # the floor; ``clamp_size_to_screen`` will then trim down to fit.
    w, h = layout.recommended_initial_window_size(1366, 768)
    assert w == layout.MIN_FIRST_LAUNCH_W
    assert h == layout.MIN_FIRST_LAUNCH_H


def test_initial_size_at_75_percent_on_large_screen() -> None:
    w, h = layout.recommended_initial_window_size(3840, 2160)
    # 75 % of 3840 = 2880; 75 % of 2160 = 1620 — both well above floor.
    assert w == int(3840 * layout.DEFAULT_SCREEN_FRACTION)
    assert h == int(2160 * layout.DEFAULT_SCREEN_FRACTION)


def test_best_n_cols_single_row_when_group_fits() -> None:
    # Group fits in one row → use exactly group_size columns; no
    # row is short.
    assert layout.best_segment_n_cols(8, 12) == 8


def test_best_n_cols_avoids_orphan_at_max() -> None:
    # 13 buttons in 12 cols would leave one button alone in row 2.
    # Drop to 11 so the second row has 2 buttons.
    assert layout.best_segment_n_cols(13, 12) == 11


def test_best_n_cols_keeps_full_columns_when_no_orphan() -> None:
    # 14 buttons in 12 cols leaves 2 in the second row — fine, no
    # orphan to dodge.
    assert layout.best_segment_n_cols(14, 12) == 12


def test_best_n_cols_handles_25_segments() -> None:
    # General-IPA Plosives group has 21+; 25 in 12 cols would be
    # 12+12+1. Drop one to 11+11+3.
    assert layout.best_segment_n_cols(25, 12) == 11


def test_best_n_cols_floors_at_1() -> None:
    # Defensive: very narrow pane (max_cols=1) just lays out
    # everything in one column.
    assert layout.best_segment_n_cols(15, 1) == 1
    assert layout.best_segment_n_cols(0, 12) == 1


def test_initial_size_picks_floor_when_fraction_smaller() -> None:
    # 1920×1080 monitor: 75% = 1440×810. Width floor 1400 doesn't
    # bind; height floor 900 binds because 810 < 900.
    w, h = layout.recommended_initial_window_size(1920, 1080)
    assert w == int(1920 * layout.DEFAULT_SCREEN_FRACTION)
    assert h == layout.MIN_FIRST_LAUNCH_H


# ---------------------------------------------------------------------------
# Single-source-of-truth checkpoint:
# The web side reads these constants via the generated dist/layout.css
# (``web/scripts/build.py:generate_layout_css``). The CSS file's
# numerical values must always match the Python module. This pair of
# tests fails the moment they drift, so the build can't ship inconsistent
# numbers across the two UIs.
# ---------------------------------------------------------------------------


def test_collapse_w_matches_css_media_query() -> None:
    """The web's ``@media (max-width: 900px)`` for single-column
    collapse must use the same threshold as ``layout.COLLAPSE_W``.
    CSS media queries can't read custom properties so the literal
    lives in style.css; this test keeps the two halves in sync.
    """
    from pathlib import Path

    style_css = Path(__file__).resolve().parents[2] / "web" / "style.css"
    assert style_css.exists(), f"missing {style_css}"
    contents = style_css.read_text(encoding="utf-8")
    expected_rule = f"@media (max-width: {layout.COLLAPSE_W}px)"
    assert expected_rule in contents, (
        f"style.css media-query threshold does not match "
        f"layout.COLLAPSE_W={layout.COLLAPSE_W}; expected literal "
        f"{expected_rule!r}"
    )


def test_vowel_stack_w_matches_css_container_query() -> None:
    """Same parity check for the vowel-stack container query."""
    from pathlib import Path

    style_css = Path(__file__).resolve().parents[2] / "web" / "style.css"
    contents = style_css.read_text(encoding="utf-8")
    expected_rule = f"@container (max-width: {layout.VOWEL_STACK_W}px)"
    assert expected_rule in contents, (
        f"style.css container-query threshold does not match "
        f"layout.VOWEL_STACK_W={layout.VOWEL_STACK_W}; expected literal "
        f"{expected_rule!r}"
    )
