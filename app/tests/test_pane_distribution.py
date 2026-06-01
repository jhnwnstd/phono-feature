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
    # land at content + cushion; seg gets the rest. Literal numbers
    # so a bump to FEAT_CUSHION_PX (40 -> something else) trips here.
    seg_w, feat_w = layout.distribute_pane_widths(
        1440, seg_content_w=500, feat_content_w=600
    )
    assert feat_w == 640  # 600 + FEAT_CUSHION_PX (40)
    assert seg_w == 800


def test_distribute_feat_clamped_to_min_when_content_tiny() -> None:
    seg_w, feat_w = layout.distribute_pane_widths(
        1440, seg_content_w=500, feat_content_w=100
    )
    # FEAT_MIN_W = 480 (bumped from 380 so long card titles fit
    # on one line in the two-column feature panel).
    assert feat_w == 480
    assert seg_w == 1440 - 480


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
    assert feat_w == 740  # 700 + FEAT_CUSHION_PX (40)
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


def test_vowel_width_is_constant_natural() -> None:
    # The chart is a fixed phonetic visualisation; it returns its
    # natural width regardless of pane width. Literal 320 so a bump
    # to VOWEL_NATURAL_W is caught here.
    for seg_pane_w in (0, 100, 480, 1200, 3840):
        assert layout.vowel_chart_width(seg_pane_w) == 320


def test_vowel_natural_width_fits_label_column() -> None:
    # The chart's natural width has to clear: 6 button columns
    # (BTN_W + BTN_GAP each) + a label-column gutter wide enough
    # for the longest row label ("Near-close" at ~60 px in
    # Noto Sans 7pt). 320 covers that with breathing room.
    btn_strip = 6 * (33 + 4)  # six button cols + five gaps + trailing
    assert layout.VOWEL_NATURAL_W >= btn_strip + 64


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
    # Width floor is now 1120 (vowel-safe minimum) instead of 1400.
    w, h = layout.recommended_initial_window_size(1366, 768)
    assert w == 1120  # MIN_FIRST_LAUNCH_W (vowel-safe floor)
    assert h == 900  # MIN_FIRST_LAUNCH_H


def test_initial_size_at_default_fraction_on_large_screen() -> None:
    w, h = layout.recommended_initial_window_size(3840, 2160)
    # 80 % of 3840 = 3072; 80 % of 2160 = 1728 — both well above floor.
    assert w == 3072
    assert h == 1728


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
    # 1920×1080 monitor: 80% = 1536×864. Width floor 1400 doesn't
    # bind (1536 > 1400); height floor 900 binds because 864 < 900.
    w, h = layout.recommended_initial_window_size(1920, 1080)
    assert w == 1536
    assert h == 900  # MIN_FIRST_LAUNCH_H


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


def test_layout_css_emits_all_height_constants() -> None:
    """The generated ``dist/layout.css`` must emit every height-
    related constant the desktop uses, so the web grid can apply
    the same numbers via ``var(--*)``. A new constant in
    ``layout.py`` without a corresponding emission in
    ``generate_layout_css`` would cause the two UIs to drift.
    Read the ``build.py`` source as a syntactic check (no need
    to actually run the build for this test).
    """
    from pathlib import Path

    build_py = (
        Path(__file__).resolve().parents[2] / "web" / "scripts" / "build.py"
    )
    contents = build_py.read_text(encoding="utf-8")
    # Every layout-module height constant we expect emitted as a
    # CSS variable. New constants must be appended here AND emitted
    # in ``generate_layout_css``.
    for var_name, py_name in [
        ("--seg-btn-h", "SEG_BTN_H"),
        ("--seg-btn-row-h", "SEG_BTN_ROW_H"),
        ("--seg-group-header-h", "SEG_GROUP_HEADER_H"),
        ("--feat-row-h", "FEAT_ROW_H"),
        ("--feat-card-chrome-h", "FEAT_CARD_CHROME_H"),
        ("--panel-chrome-v", "PANEL_CHROME_V"),
        ("--min-top-pane-h", "MIN_TOP_PANE_H"),
        ("--min-feat-card-w", "MIN_FEAT_CARD_W"),
    ]:
        assert var_name in contents, (
            f"build.py:generate_layout_css does not emit {var_name}; "
            f'add a line like ``f"  {var_name}: {{mod.{py_name}}}px;"``'
        )
        assert f"mod.{py_name}" in contents, (
            f"build.py:generate_layout_css does not reference "
            f"layout.{py_name}; the {var_name} variable cannot be "
            f"derived without it"
        )
