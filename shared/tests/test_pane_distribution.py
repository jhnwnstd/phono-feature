"""Tests for the adaptive-window-layout helpers in
:py:mod:`phonology_shared.presentation.layout`.

These functions are the single source of truth that both the desktop
(Qt splitter sizing in ``geometry_controller``) and the web (CSS
custom properties baked by ``web/scripts/build.py`` into
``dist/layout.css``) consume. Drift between the two UIs is impossible
without breaking these assertions.
"""

from __future__ import annotations

from phonology_shared.presentation import layout

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
    # natural width regardless of pane width. Tripwire on the
    # exact value so a future bump to VOWEL_NATURAL_W lands as a
    # deliberate test edit, not a silent drift.
    for seg_pane_w in (0, 100, 480, 1200, 3840):
        assert layout.vowel_chart_width(seg_pane_w) == 440


def test_vowel_natural_width_fits_label_column() -> None:
    # The chart's natural width has to clear: 6 button columns
    # (BTN_W + BTN_GAP each) + a label-column gutter wide enough
    # for the longest row label ("Near-close" at ~60 px in
    # Noto Sans 7pt) + breathing room around the trapezoid
    # silhouette.
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
    assert w == layout.MIN_FIRST_LAUNCH_W  # vowel-safe floor
    assert h == 900  # MIN_FIRST_LAUNCH_H


def test_initial_size_at_default_fraction_on_large_screen() -> None:
    w, h = layout.recommended_initial_window_size(3840, 2160)
    # 80 % of 3840 = 3072 exceeds the ultrawide cap
    # (CONTENT_MAX_W_ABS = 2400) so the cap wins on the width axis.
    # Height stays at 80 % of 2160 = 1728 (vertical eye-travel
    # is fine; only the horizontal axis gets capped).
    assert w == 2400
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


def test_vowel_stack_w_matches_build_py_container_query() -> None:
    """The @container threshold that drops the vowel chart below
    the consonant grid lives in ``build.py``'s emitted
    ``layout.css``, not in the hand-edited ``style.css``. Pin that
    ``build.py`` does the emission so a future refactor cannot
    silently revert to a duplicated hand-edited literal.
    """
    from pathlib import Path

    build_py = (
        Path(__file__).resolve().parents[2] / "web" / "scripts" / "build.py"
    )
    contents = build_py.read_text(encoding="utf-8")
    # The literal in build.py is an f-string interpolating
    # VOWEL_STACK_W; pin the f-string skeleton plus a non-magic
    # reference to the constant.
    assert "VOWEL_STACK_W" in contents, (
        "build.py must reference layout.VOWEL_STACK_W when emitting"
        " the vowel-stack container query so the threshold tracks"
        " the constant automatically"
    )
    assert "@container (max-width:" in contents, (
        "build.py must emit the @container rule for the vowel-stack"
        " threshold"
    )

    # And the hand-edited style.css must NOT carry a literal
    # threshold, since that path used to drift from the Python
    # constant on every bump.
    style_css = Path(__file__).resolve().parents[2] / "web" / "style.css"
    style_contents = style_css.read_text(encoding="utf-8")
    assert "@container (max-width:" not in style_contents, (
        "style.css should not carry a hand-edited @container threshold;"
        " the rule belongs in build.py so it tracks VOWEL_STACK_W."
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
        # Analysis-pane sizing and ultrawide cap constants. Pinned
        # so the web ``.analysis`` rules and ``main.grid`` cap stay
        # in sync with ``layout.py`` after future edits.
        ("--min-analysis-h", "MIN_ANALYSIS_H"),
        ("--content-max-w", "CONTENT_MAX_W_ABS"),
        # Vowel-pair spacing: tighter gap inside a rounded/unrounded
        # mate pair and a wider separator between backness columns.
        # Both UIs consume these via the relay; drift would re-introduce
        # the equal-spacing problem.
        ("--vowel-pair-gap", "VOWEL_PAIR_GAP_PX"),
        ("--vowel-pair-separator", "VOWEL_PAIR_SEPARATOR_PX"),
        # Per-button stride (BTN_W / BTN_GAP). main.js reads
        # ``--seg-btn-w`` / ``--seg-btn-gap`` via
        # ``getComputedStyle`` so the JS-side per-row column math
        # consumes the same numbers the desktop QGridLayout does.
        ("--seg-btn-w", "BTN_W"),
        ("--seg-btn-gap", "BTN_GAP"),
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


def test_region_constraints_match_constants() -> None:
    """The ``seg_btn`` constraint now imports BTN_W directly at
    module load (the lazy-import / inline-literal workaround was
    removed in Stage 4 once ``web/scripts/build.py`` started
    putting ``desktop/src`` on ``sys.path`` before side-loading).
    Pin the agreement so any future re-introduction of an inline
    literal trips here.
    """
    from phonology_shared.presentation.constants import BTN_W

    seg_btn = layout.REGION_CONSTRAINTS["seg_btn"]
    assert seg_btn.min_w == BTN_W
    assert seg_btn.pref_w == BTN_W
    assert seg_btn.max_w == BTN_W


def test_region_constraints_internally_consistent() -> None:
    """Every ``RegionConstraint`` must satisfy
    ``min_w <= pref_w <= max_w`` (and the same for heights), with
    ``None`` treated as "no constraint at this end". A pref_w of 0
    or a max_w below min_w would silently produce sub-min content
    floors; pin the invariant so future edits can't sneak that in.
    """
    for key, region in layout.REGION_CONSTRAINTS.items():
        if region.pref_w is not None:
            assert (
                region.min_w <= region.pref_w
            ), f"{key}: min_w={region.min_w} > pref_w={region.pref_w}"
        if region.max_w is not None:
            assert (
                region.min_w <= region.max_w
            ), f"{key}: min_w={region.min_w} > max_w={region.max_w}"
            if region.pref_w is not None:
                assert (
                    region.pref_w <= region.max_w
                ), f"{key}: pref_w={region.pref_w} > max_w={region.max_w}"
        if region.pref_h is not None:
            assert (
                region.min_h <= region.pref_h
            ), f"{key}: min_h={region.min_h} > pref_h={region.pref_h}"
        if region.max_h is not None:
            assert (
                region.min_h <= region.max_h
            ), f"{key}: min_h={region.min_h} > max_h={region.max_h}"
            if region.pref_h is not None:
                assert (
                    region.pref_h <= region.max_h
                ), f"{key}: pref_h={region.pref_h} > max_h={region.max_h}"


def test_region_constraints_relay_into_layout_css() -> None:
    """Each ``REGION_CONSTRAINTS`` entry must produce its ``--*-min-w``
    / ``--*-min-h`` (and ``--*-max-*`` when set) CSS custom property
    in ``generate_layout_css``. Catches the next "added a region but
    forgot to extend the build" drift.
    """
    from pathlib import Path

    build_py = (
        Path(__file__).resolve().parents[2] / "web" / "scripts" / "build.py"
    )
    contents = build_py.read_text(encoding="utf-8")
    # The build iterates REGION_CONSTRAINTS at emission time; verify
    # the iteration is present so a refactor that hard-codes the list
    # is caught here.
    assert "for key, region in mod.REGION_CONSTRAINTS.items()" in contents, (
        "build.py:generate_layout_css no longer iterates "
        "REGION_CONSTRAINTS; adding a region would silently fail to "
        "emit its CSS variables"
    )


def test_font_size_ladder_relays_into_layout_css() -> None:
    """The FONT_SIZE_* ladder from constants.py drives the web's CSS
    font-size variables. Each constant must be emitted so a future
    "make body text larger" Python edit reaches the browser without
    a parallel CSS sweep.
    """
    from pathlib import Path

    from phonology_shared.presentation import constants

    build_py = (
        Path(__file__).resolve().parents[2] / "web" / "scripts" / "build.py"
    )
    contents = build_py.read_text(encoding="utf-8")
    for var_name, py_name in [
        ("--font-size-base", "FONT_SIZE_BASE_PX"),
        ("--font-size-control", "FONT_SIZE_CONTROL_PX"),
        ("--font-size-meta", "FONT_SIZE_META_PX"),
        ("--font-size-label", "FONT_SIZE_LABEL_PX"),
        ("--font-size-micro", "FONT_SIZE_MICRO_PX"),
        ("--font-size-min-px", "FONT_SIZE_MIN_PX"),
    ]:
        assert (
            var_name in contents
        ), f"build.py:generate_layout_css does not emit {var_name}"
        assert f"FONT_SIZE_{py_name.split('FONT_SIZE_')[1]}" in dir(
            constants,
        ), f"constants.py is missing {py_name}"


def test_style_css_has_no_hardcoded_analysis_height() -> None:
    """The locked analysis-pane height used to be ``220px`` literal
    twice in ``.analysis``. After the relay it lives in
    ``--min-analysis-h``; this test pins that the literal no longer
    appears so a future drift between Python and CSS fails loudly.
    """
    from pathlib import Path

    style_css = Path(__file__).resolve().parents[2] / "web" / "style.css"
    contents = style_css.read_text(encoding="utf-8")
    # The ``.analysis`` selector must reference the var, not the
    # historic 220 literal. We grep for the rule directly.
    assert "min-height: var(--min-analysis-h)" in contents, (
        "web/style.css `.analysis` no longer reads "
        "--min-analysis-h; it must consume the relayed value, "
        "not hardcode the pixel literal"
    )
    assert "min-height: 220px" not in contents, (
        "web/style.css still contains a literal `min-height: 220px`;"
        " the relayed --min-analysis-h must be the only source"
    )
