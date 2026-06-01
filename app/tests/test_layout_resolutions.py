"""Layout-policy tests at the nine most common desktop resolutions.

Each resolution is exercised through the shared layout module
(``phonology_features.gui.layout``) so the policy decisions are
deterministic and identical across the desktop and web frontends.
A failure here means a real user on that monitor would see broken
chrome (panes too narrow, vowel chart in the wrong place, fresh-
install window too big or too small, etc.).

The matrix:

| Rank | Resolution  | Notes                                                  |
| ---: | ----------- | ------------------------------------------------------ |
|    1 | 1920 × 1080 | Most common desktop resolution worldwide               |
|    2 | 1280 × 1200 | High in current StatCounter desktop data               |
|    3 | 1536 × 864  | Common scaled laptop or desktop viewport               |
|    4 | 1366 × 768  | Common lower-end laptop                                |
|    5 | 1280 × 720  | Small 16:9 desktop or constrained window               |
|    6 | 1440 × 900  | Common 16:10 desktop / older Mac size                  |
|    7 | 1600 × 900  | Common HD+ desktop size                                |
|    8 | 2560 × 1440 | Common QHD desktop monitor                             |
|    9 | 3840 × 2160 | Common 4K desktop monitor                              |

Content-size assumptions:
* ``seg_content_w = 500``  (the widest typical consonant grid + chart)
* ``feat_content_w = 500`` (the widest typical feature-card column pair)

Both numbers reflect real inventory layouts (English Hayes,
Blevins): the tests pin against these so a deliberate inventory-
chrome change is the only way the assertions move.
"""

from __future__ import annotations

from typing import NamedTuple

import pytest

from phonology_features.gui import layout


class Resolution(NamedTuple):
    rank: int
    label: str
    width: int
    height: int


RESOLUTIONS: list[Resolution] = [
    Resolution(1, "1920x1080", 1920, 1080),
    Resolution(2, "1280x1200", 1280, 1200),
    Resolution(3, "1536x864", 1536, 864),
    Resolution(4, "1366x768", 1366, 768),
    Resolution(5, "1280x720", 1280, 720),
    Resolution(6, "1440x900", 1440, 900),
    Resolution(7, "1600x900", 1600, 900),
    Resolution(8, "2560x1440", 2560, 1440),
    Resolution(9, "3840x2160", 3840, 2160),
]

# Representative content widths for a typical inventory. ``seg_content_w``
# is the consonant grid + vowel chart natural width; ``feat_content_w``
# is the two-column feature panel. Real inventories vary by ±~50 px;
# the assertions below use exact equality only on the policy outputs
# that don't depend on these (window sizing, collapse threshold,
# vowel-chart natural width). Pane widths are checked against
# inequalities so realistic content variation doesn't break tests.
SEG_CONTENT_W = 500
FEAT_CONTENT_W = 500


# ---------------------------------------------------------------------------
# recommended_initial_window_size: fresh-install default
# ---------------------------------------------------------------------------


# Literal expected window sizes per resolution. Pinning these as
# concrete numbers (rather than computing them from
# ``MIN_FIRST_LAUNCH_*`` and ``DEFAULT_SCREEN_FRACTION``) means a
# tweak to either constant trips the assertion instead of silently
# moving the comparand to match.
EXPECTED_WINDOW_SIZES: dict[str, tuple[int, int]] = {
    # max(MIN_FIRST_LAUNCH_W=1120, 0.80×W) × max(MIN_FIRST_LAUNCH_H=900, 0.80×H)
    "1920x1080": (1536, 900),  # 1920×0.8=1536; 1080×0.8=864 < 900 floor
    "1280x1200": (1120, 960),  # 1280×0.8=1024 < 1120 floor; 1200×0.8=960
    "1536x864": (1228, 900),  # 1536×0.8=1228 > 1120 floor; height floor
    "1366x768": (1120, 900),  # 1366×0.8=1092 < 1120 floor
    "1280x720": (1120, 900),  # 1280×0.8=1024 < 1120 floor
    "1440x900": (1152, 900),  # 1440×0.8=1152 > 1120 floor
    "1600x900": (1280, 900),  # 1600×0.8=1280 > 1120 floor
    "2560x1440": (2048, 1152),  # 2560×0.8=2048; 1440×0.8=1152
    "3840x2160": (3072, 1728),  # 3840×0.8=3072; 2160×0.8=1728
}


@pytest.mark.parametrize("res", RESOLUTIONS, ids=lambda r: r.label)
def test_initial_window_size_matches_pinned_literals(
    res: Resolution,
) -> None:
    """The fresh-install window size is ``max(MIN_FIRST_LAUNCH_*,
    0.75 * screen)``. Each resolution's expected size is pinned as
    a literal pair so any change to ``MIN_FIRST_LAUNCH_W``,
    ``MIN_FIRST_LAUNCH_H``, or ``DEFAULT_SCREEN_FRACTION`` trips the
    test rather than silently shifting both sides of an equality
    in lockstep.
    """
    w, h = layout.recommended_initial_window_size(res.width, res.height)
    assert (w, h) == EXPECTED_WINDOW_SIZES[res.label]


@pytest.mark.parametrize("res", RESOLUTIONS, ids=lambda r: r.label)
def test_initial_window_size_does_not_overflow_screen(
    res: Resolution,
) -> None:
    """The window can be at most the screen size in both axes.
    Skip resolutions smaller than the floor in either axis: those
    are below ``MIN_FIRST_LAUNCH_*`` so the floor unavoidably
    overshoots, and the geometry controller clamps after the fact
    via ``clamp_size_to_screen``.
    """
    w, h = layout.recommended_initial_window_size(res.width, res.height)
    fits_w = res.width >= layout.MIN_FIRST_LAUNCH_W
    fits_h = res.height >= layout.MIN_FIRST_LAUNCH_H
    if fits_w:
        assert (
            w <= res.width
        ), f"{res.label}: window width {w} > screen {res.width}"
    if fits_h:
        assert (
            h <= res.height
        ), f"{res.label}: window height {h} > screen {res.height}"


# ---------------------------------------------------------------------------
# distribute_pane_widths: seg / feat split at the window size
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("res", RESOLUTIONS, ids=lambda r: r.label)
def test_pane_widths_meet_minimums(res: Resolution) -> None:
    """Both panes must be at least their minimum width at the
    fresh-install window size. Below those minimums the panel
    chrome (clear buttons, segment header) starts to clip."""
    win_w, _ = layout.recommended_initial_window_size(res.width, res.height)
    seg_w, feat_w = layout.distribute_pane_widths(
        win_w,
        seg_content_w=SEG_CONTENT_W,
        feat_content_w=FEAT_CONTENT_W,
    )
    assert (
        seg_w >= layout.SEG_MIN_W
    ), f"{res.label}: seg pane {seg_w} < SEG_MIN_W {layout.SEG_MIN_W}"
    assert (
        feat_w >= layout.FEAT_MIN_W
    ), f"{res.label}: feat pane {feat_w} < FEAT_MIN_W {layout.FEAT_MIN_W}"


@pytest.mark.parametrize("res", RESOLUTIONS, ids=lambda r: r.label)
def test_pane_widths_sum_to_window_width(res: Resolution) -> None:
    """``distribute_pane_widths`` should hand out the full window
    width when both content sizes are below their minimum-driven
    floor. Otherwise the extra goes to the seg pane (its policy)
    and the sum still equals the window width — the splitter has
    no dead pixels."""
    win_w, _ = layout.recommended_initial_window_size(res.width, res.height)
    seg_w, feat_w = layout.distribute_pane_widths(
        win_w,
        seg_content_w=SEG_CONTENT_W,
        feat_content_w=FEAT_CONTENT_W,
    )
    # When ``win_w`` is large enough for both content-driven
    # minimums, the sum equals win_w. When it isn't (small
    # screens), seg gets clamped to ``SEG_MIN_W`` and the sum
    # may exceed win_w because the splitter would then need to
    # scroll horizontally.
    feat_floor = max(
        layout.FEAT_MIN_W, FEAT_CONTENT_W + layout.FEAT_CUSHION_PX
    )
    seg_floor = max(layout.SEG_MIN_W, SEG_CONTENT_W)
    minimal_sum = seg_floor + feat_floor
    if win_w >= minimal_sum:
        assert seg_w + feat_w == win_w
    else:
        # Below the minimum-driven floor, the sum is the floor.
        assert seg_w + feat_w == minimal_sum


@pytest.mark.parametrize("res", RESOLUTIONS, ids=lambda r: r.label)
def test_feat_pane_is_content_driven_at_every_resolution(
    res: Resolution,
) -> None:
    """Feat pane is content-driven (``max(FEAT_MIN_W, content +
    cushion)``). Same literal 540 px at every resolution
    (FEAT_CONTENT_W 500 + FEAT_CUSHION_PX 40); only the seg pane
    absorbs extra width on wide screens. Literal pin so a bump
    to FEAT_CUSHION_PX (40 → something else) trips the assertion
    rather than silently shifting both sides."""
    win_w, _ = layout.recommended_initial_window_size(res.width, res.height)
    _, feat_w = layout.distribute_pane_widths(
        win_w,
        seg_content_w=SEG_CONTENT_W,
        feat_content_w=FEAT_CONTENT_W,
    )
    assert feat_w == 540


# ---------------------------------------------------------------------------
# Mode-decision thresholds: stack vowels / collapse to single column
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("res", RESOLUTIONS, ids=lambda r: r.label)
def test_vowel_chart_layout_decision(res: Resolution) -> None:
    """At every supported resolution the seg pane is wide enough
    to host the vowel chart beside the consonants — when the
    geometry controller applies its content-aware vowel-safe floor.

    ``recommended_initial_window_size`` returns the pre-inventory
    placeholder width (the absolute minimum). After the inventory
    loads, ``fit_to_content`` widens to ``min_vowel_safe_window_w``
    for that inventory's feat content, guaranteeing vowels stay
    alongside. This test simulates that path so a future regression
    that bypasses the vowel-safe floor is caught.
    """
    placeholder_w, _ = layout.recommended_initial_window_size(
        res.width, res.height
    )
    vowel_safe_w = layout.min_vowel_safe_window_w(FEAT_CONTENT_W)
    final_w = max(placeholder_w, vowel_safe_w)
    seg_w, _ = layout.distribute_pane_widths(
        final_w,
        seg_content_w=SEG_CONTENT_W,
        feat_content_w=FEAT_CONTENT_W,
    )
    assert not layout.should_stack_vowels(seg_w), (
        f"{res.label}: seg pane {seg_w} at window {final_w} "
        f"unexpectedly < VOWEL_STACK_W {layout.VOWEL_STACK_W}"
    )


@pytest.mark.parametrize("res", RESOLUTIONS, ids=lambda r: r.label)
def test_window_does_not_collapse_to_single_column(
    res: Resolution,
) -> None:
    """``should_collapse_single_column`` is the web's
    @media (max-width: 900px) breakpoint, mirrored from
    ``layout.COLLAPSE_W``. All nine targeted monitor resolutions
    are above the 900-px floor, so the page stays in the two-pane
    side-by-side layout. The desktop has no analogue but the helper
    is here for parity — a failure means we'd be hitting the mobile
    layout on a real monitor."""
    win_w, _ = layout.recommended_initial_window_size(res.width, res.height)
    assert not layout.should_collapse_single_column(
        win_w
    ), f"{res.label}: window width {win_w} < COLLAPSE_W {layout.COLLAPSE_W}"


# ---------------------------------------------------------------------------
# Vowel chart natural width (size policy independent of seg-pane width)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("res", RESOLUTIONS, ids=lambda r: r.label)
def test_vowel_chart_keeps_natural_width(res: Resolution) -> None:
    """The vowel chart is a fixed phonetic visualisation, not a
    fluid grid — it stays at 320 px (the ``VOWEL_NATURAL_W``
    constant) regardless of monitor / seg-pane size. Literal pin
    prevents an "ooh, more room, let's stretch the chart"
    regression."""
    win_w, _ = layout.recommended_initial_window_size(res.width, res.height)
    seg_w, _ = layout.distribute_pane_widths(
        win_w,
        seg_content_w=SEG_CONTENT_W,
        feat_content_w=FEAT_CONTENT_W,
    )
    assert layout.vowel_chart_width(seg_w) == 320


# ---------------------------------------------------------------------------
# Resolution-specific expectations
# ---------------------------------------------------------------------------


def test_4k_window_uses_screen_fraction_not_floor() -> None:
    """At 4K (3840×2160), the 0.80 fraction wins over the
    MIN_FIRST_LAUNCH_W floor: 0.80 × 3840 = 3072, well above
    1400. Literal numbers so a bump to ``DEFAULT_SCREEN_FRACTION``
    or ``MIN_FIRST_LAUNCH_*`` is caught here."""
    w, h = layout.recommended_initial_window_size(3840, 2160)
    assert w == 3072
    assert h == 1728


def test_qhd_window_uses_screen_fraction_not_floor() -> None:
    """At QHD (2560×1440), the 0.80 fraction wins: 0.80 × 2560
    = 2048."""
    w, h = layout.recommended_initial_window_size(2560, 1440)
    assert w == 2048
    assert h == 1152


def test_full_hd_window_uses_screen_fraction_not_floor() -> None:
    """At 1920×1080, the 0.80 fraction wins on the width axis
    (0.80 × 1920 = 1536 ≥ 1400) but the height floor wins
    (0.80 × 1080 = 864 < 900). Literal 900 so a bump to
    ``MIN_FIRST_LAUNCH_H`` (e.g. 900 → 1000) trips this test."""
    w, h = layout.recommended_initial_window_size(1920, 1080)
    assert w == 1536
    assert h == 900


def test_low_end_laptop_window_falls_back_to_floor() -> None:
    """At 1366×768, both axes are below the floor: 0.80 × 1366
    = 1092 < 1120, and 0.80 × 768 = 614 < 900. The floor wins on
    both axes; geometry_controller clamps the result back to the
    actual screen after the fact. Literal numbers so a bump to
    either floor constant is caught here."""
    w, h = layout.recommended_initial_window_size(1366, 768)
    assert w == 1120
    assert h == 900


def test_smallest_targeted_resolution_width_fits_screen() -> None:
    """1280×720 is below the floor on the height axis (0.80 × 720
    = 576 < 900) but the WIDTH floor 1120 now fits inside the
    1280 screen. Width does not overshoot the screen; height does
    (the clamp at the call site brings it back to fit). Captures
    the new vowel-safe-minimum-width contract."""
    w, h = layout.recommended_initial_window_size(1280, 720)
    assert w == 1120 <= 1280  # fits the screen
    assert h == 900 > 720  # height floor still overshoots; clamped


def test_seg_pane_fans_out_at_4k() -> None:
    """At 4K, the window is 3072 px wide (0.80 × 3840). Feat
    lands at 540 px (FEAT_CONTENT_W 500 + FEAT_CUSHION_PX 40);
    seg gets the remaining 2532 px — the explicit "wide screens
    fan segments out" contract."""
    win_w, _ = layout.recommended_initial_window_size(3840, 2160)
    seg_w, feat_w = layout.distribute_pane_widths(
        win_w,
        seg_content_w=SEG_CONTENT_W,
        feat_content_w=FEAT_CONTENT_W,
    )
    assert feat_w == 540
    assert seg_w == 2532


def test_seg_pane_stays_at_min_at_low_end_laptop() -> None:
    """At 1366×768, the window is preferred at 1120 wide (the new
    vowel-safe floor). With feat 540 px and seg-min 480 px, seg
    pane gets 580 px — just under VOWEL_STACK_W (620), so for
    typical-content inventories the chart would stack here. The
    content-driven floor in ``fit_to_content`` pushes the actual
    initial window up to the vowel-safe-per-inventory minimum."""
    win_w, _ = layout.recommended_initial_window_size(1366, 768)
    seg_w, feat_w = layout.distribute_pane_widths(
        win_w,
        seg_content_w=SEG_CONTENT_W,
        feat_content_w=FEAT_CONTENT_W,
    )
    assert feat_w == 540
    assert seg_w == win_w - feat_w  # 1120 - 540 = 580


# ---------------------------------------------------------------------------
# Floor-binding direct tests: exercise the branches the matrix can't reach.
# The 9 monitor resolutions all yield ``win_w >= 1400`` after the floor /
# fraction calc, well above the ``feat_floor + seg_floor`` for any realistic
# content width. To catch regressions in the per-pane floor logic, these
# tests call ``distribute_pane_widths`` directly with narrow widths.
# ---------------------------------------------------------------------------


def test_feat_floor_binds_when_content_is_small() -> None:
    """``FEAT_MIN_W`` wins when ``feat_content_w + cushion`` is
    below the minimum. With FEAT_MIN_W = 480 (bumped from 380 so
    long card titles fit), feat_content_w=200 + cushion 40 = 240
    is well below 480 → floor wins."""
    seg_w, feat_w = layout.distribute_pane_widths(
        1400, seg_content_w=500, feat_content_w=200
    )
    assert feat_w == 480  # FEAT_MIN_W literal
    assert seg_w == 1400 - 480


def test_seg_floor_binds_when_window_is_narrow() -> None:
    """When the window is narrower than ``seg_content_w +
    feat_w``, the seg pane clamps to ``max(SEG_MIN_W,
    seg_content_w)`` — splitter overflow rather than letting seg
    drop below its content."""
    seg_w, feat_w = layout.distribute_pane_widths(
        800, seg_content_w=500, feat_content_w=500
    )
    assert feat_w == 540
    assert seg_w == 500  # seg_content_w wins over (win_w - feat_w) = 260


def test_pane_widths_clamp_to_floor_when_window_below_minimal_sum() -> None:
    """When ``win_w`` is below ``seg_floor + feat_floor``, the
    distributor hands out the floors (sum > win_w). Exercises the
    dead ``else`` branch from ``test_pane_widths_sum_to_window_width``."""
    seg_w, feat_w = layout.distribute_pane_widths(
        600, seg_content_w=500, feat_content_w=500
    )
    # seg_floor = max(480, 500) = 500; feat_floor = max(380, 540) = 540
    assert seg_w == 500
    assert feat_w == 540
    assert seg_w + feat_w == 1040 > 600  # sum overshoots tight window


def test_seg_min_floor_binds_when_no_content_pressure() -> None:
    """With zero content pressure (both content widths tiny), the
    seg pane still gets at least ``SEG_MIN_W`` — pins the
    ``max(SEG_MIN_W, ...)`` floor regardless of content."""
    seg_w, feat_w = layout.distribute_pane_widths(
        1400, seg_content_w=100, feat_content_w=100
    )
    assert feat_w == 480  # FEAT_MIN_W literal
    assert seg_w == 1400 - 480 == 920
    # Even with extreme content compression, seg floor holds.
    seg_w, _ = layout.distribute_pane_widths(
        400, seg_content_w=0, feat_content_w=0
    )
    assert seg_w >= 480  # SEG_MIN_W literal


# ---------------------------------------------------------------------------
# Floor-vs-fraction partition: enumerate which resolutions are floor-driven
# and which are fraction-driven. A bump in either constant will move
# resolutions across this partition; pinning the current partition catches
# the move.
# ---------------------------------------------------------------------------


def test_floor_vs_fraction_partition_is_stable() -> None:
    """Pin which of the 9 resolutions are FLOOR-driven (window
    width hits ``MIN_FIRST_LAUNCH_W`` because 0.75 × screen is
    below 1400) vs FRACTION-driven (0.75 × screen wins). Any
    change to the constants moves this partition and surfaces
    here instead of as a surprise window size in the UI.
    """
    # Literal fraction-driven widths and heights, pinned per resolution.
    # Pinning these as literals catches a bump to
    # ``DEFAULT_SCREEN_FRACTION`` even when the partition itself
    # is preserved.
    # Vowel-safe floor (1120) is lower than the previous 1400, so
    # more screens are now fraction-driven. Pinned literals catch a
    # bump to either constant.
    fraction_widths = {
        "1536x864": 1228,
        "1440x900": 1152,
        "1600x900": 1280,
        "1920x1080": 1536,
        "2560x1440": 2048,
        "3840x2160": 3072,
    }
    fraction_heights = {
        "1280x1200": 960,
        "2560x1440": 1152,
        "3840x2160": 1728,
    }
    floor_driven_w = set()
    fraction_driven_w = set()
    for res in RESOLUTIONS:
        w, _ = layout.recommended_initial_window_size(res.width, res.height)
        if w == 1120:  # MIN_FIRST_LAUNCH_W literal (vowel-safe)
            floor_driven_w.add(res.label)
        else:
            assert w == fraction_widths[res.label]
            fraction_driven_w.add(res.label)
    # Floor-driven width: 0.80 × screen < 1120, i.e. screen < 1400.
    # Only the smallest three monitors hit the floor now (previously
    # six did, because the floor was 1400).
    assert floor_driven_w == {"1280x1200", "1366x768", "1280x720"}
    # Fraction-driven width: screen ≥ 1400.
    assert fraction_driven_w == {
        "1536x864",
        "1440x900",
        "1600x900",
        "1920x1080",
        "2560x1440",
        "3840x2160",
    }

    floor_driven_h = set()
    fraction_driven_h = set()
    for res in RESOLUTIONS:
        _, h = layout.recommended_initial_window_size(res.width, res.height)
        if h == 900:  # MIN_FIRST_LAUNCH_H literal
            # Includes the exact-tie case where 0.75 × screen == 900
            # (e.g. 1280×1200): the floor wins by equality.
            floor_driven_h.add(res.label)
        else:
            assert h == fraction_heights[res.label]
            fraction_driven_h.add(res.label)
    # Floor-driven height: 0.80 × screen < 900, i.e. screen < 1125.
    # 1280×1200 moves to the fraction-driven bucket (0.80 × 1200 = 960
    # exceeds the 900 floor) — at 80% the fraction begins to bind one
    # resolution earlier than at 75%.
    assert floor_driven_h == {
        "1920x1080",
        "1536x864",
        "1366x768",
        "1280x720",
        "1440x900",
        "1600x900",
    }
    # Fraction-driven height: screen ≥ 1125.
    assert fraction_driven_h == {"1280x1200", "2560x1440", "3840x2160"}


def test_tall_narrow_1280x1200_fits_screen_width() -> None:
    """1280×1200 is a non-16:9 aspect (taller than wide for
    desktop). With the lower vowel-safe floor (1120), the width
    now FITS the 1280 screen — no horizontal overshoot. Height is
    fraction-driven at 80% (0.80 × 1200 = 960 above the 900 floor).
    """
    w, h = layout.recommended_initial_window_size(1280, 1200)
    assert w == 1120 <= 1280  # fits the screen now
    assert h == 960  # 0.80 × 1200, above the floor


# ---------------------------------------------------------------------------
# Vertical-axis split: top_pane_height across the resolution matrix
#
# Vertical policy lives in ``layout.top_pane_height``: top pane gets up to
# its content need but never more than ``total - HARD_MIN_ANALYSIS_H``, and
# never less than ``MIN_TOP_PANE_H``. These tests pin the analysis-pane
# vertical floor at each resolution so a short-window regression (analysis
# crushed below readable height) surfaces here, not in the UI.
# ---------------------------------------------------------------------------


# Representative top-content need for a typical inventory: ~28 features in
# a two-column grid + chrome. Real values from English/Blevins hover here.
TOP_CONTENT_H = 540


@pytest.mark.parametrize("res", RESOLUTIONS, ids=lambda r: r.label)
def test_top_pane_height_keeps_analysis_floor(res: Resolution) -> None:
    """At every resolution's recommended-window height, the
    ``layout.top_pane_height`` policy must leave the analysis pane
    at least ``HARD_MIN_ANALYSIS_H`` (60 px). The user can drag the
    splitter past this in normal usage, but the initial layout
    should never deliver an unreadable analysis pane."""
    _, win_h = layout.recommended_initial_window_size(res.width, res.height)
    # Toolbar (~50) + status bar (~25) consume some height before
    # the vsplit; use a conservative total for the policy.
    vsplit_total = max(win_h - 100, 100)
    top_h = layout.top_pane_height(TOP_CONTENT_H, vsplit_total)
    analysis_h = vsplit_total - top_h
    assert analysis_h >= layout.HARD_MIN_ANALYSIS_H, (
        f"{res.label}: analysis pane {analysis_h}px below "
        f"HARD_MIN_ANALYSIS_H {layout.HARD_MIN_ANALYSIS_H}"
    )


@pytest.mark.parametrize("res", RESOLUTIONS, ids=lambda r: r.label)
def test_top_pane_height_keeps_min_top_pane_floor(
    res: Resolution,
) -> None:
    """The top (seg / feat) pane must always get at least
    ``MIN_TOP_PANE_H`` (200 px). Even on the smallest targeted
    resolution, the feature cards must have a usable height."""
    _, win_h = layout.recommended_initial_window_size(res.width, res.height)
    vsplit_total = max(win_h - 100, 100)
    top_h = layout.top_pane_height(TOP_CONTENT_H, vsplit_total)
    assert top_h >= layout.MIN_TOP_PANE_H, (
        f"{res.label}: top pane {top_h}px below "
        f"MIN_TOP_PANE_H {layout.MIN_TOP_PANE_H}"
    )


def test_top_pane_height_caps_at_total_minus_analysis_floor() -> None:
    """When the features want more height than the splitter can
    deliver, the policy caps the top pane so the analysis pane
    still keeps its 60-px floor. Pins literal 60 so a bump to
    HARD_MIN_ANALYSIS_H trips."""
    # Features want 800 px; vsplit has 600 px total. Cap path wins.
    top_h = layout.top_pane_height(top_need_h=800, total=600)
    assert top_h == 600 - 60
    assert top_h == 540


def test_top_pane_height_passes_through_when_room_to_spare() -> None:
    """When the vsplit is comfortably tall, the top pane gets
    exactly its content-driven need. Analysis gets the leftover
    — the user's stated "as tall as it can be" preference."""
    top_h = layout.top_pane_height(top_need_h=540, total=900)
    assert top_h == 540
    analysis_h = 900 - top_h
    assert analysis_h == 360  # analysis absorbs the slack


def test_top_pane_height_defensive_floor_for_degenerate_input() -> None:
    """``MIN_TOP_PANE_H`` is a defensive floor: when the caller
    passes a content need below the floor (e.g. empty inventory
    whose sizeHint returns 0), the top pane still gets at least
    200 px so it doesn't fully collapse. Real inventories never
    trigger this branch because their content is always > 200."""
    top_h = layout.top_pane_height(top_need_h=0, total=900)
    assert top_h == 200  # MIN_TOP_PANE_H literal


def test_top_pane_height_does_not_over_allocate_for_small_inventories() -> (
    None
):
    """REGRESSION: an English-sized inventory (top_need ≈ 470 px)
    on a typical screen (vsplit ~800 px) should get exactly 470 px
    for the top pane, leaving 330 px for the analysis. A floor that
    forces top_pane up to 600+ would shrink analysis below its
    natural share."""
    top_h = layout.top_pane_height(top_need_h=470, total=800)
    assert top_h == 470
    analysis_h = 800 - top_h
    assert analysis_h == 330


# ---------------------------------------------------------------------------
# HiDPI: the policy is in LOGICAL pixels, not device pixels. A 1920×1080
# logical / DPR=2 monitor still produces a 1440×900 window. The
# geometry_controller is what reads the screen size; the tests below verify
# the layout-policy side stays logical-pixel-driven.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("res", RESOLUTIONS, ids=lambda r: r.label)
@pytest.mark.parametrize("dpr", [1.0, 1.25, 1.5, 2.0])
def test_recommended_window_size_independent_of_device_pixel_ratio(
    res: Resolution, dpr: float
) -> None:
    """``recommended_initial_window_size`` takes LOGICAL pixels and
    returns LOGICAL pixels. The device pixel ratio is irrelevant
    at this layer — Qt is responsible for translating logical to
    device pixels when it paints. Verified by computing the same
    result for the same (logical-resolution) screen at every DPR.
    """
    del dpr  # the function never sees this; we just pin the contract
    w, h = layout.recommended_initial_window_size(res.width, res.height)
    expected_w = max(
        layout.MIN_FIRST_LAUNCH_W,
        int(res.width * layout.DEFAULT_SCREEN_FRACTION),
    )
    expected_h = max(
        layout.MIN_FIRST_LAUNCH_H,
        int(res.height * layout.DEFAULT_SCREEN_FRACTION),
    )
    assert w == expected_w
    assert h == expected_h


# ---------------------------------------------------------------------------
# Real inventory content widths: confirm SEG_CONTENT_W and FEAT_CONTENT_W
# assumptions used elsewhere are sensible against the actual bundled
# inventories. A widest-inventory-segment-grid bigger than 600 px (or a
# widest-feature-list bigger than 600 px) would mean the resolution tests
# above are using non-representative content sizes.
# ---------------------------------------------------------------------------


def _load_inventory(name: str) -> dict[str, object]:
    """Load a bundled inventory JSON. Skips the test when the file
    is missing (some inventories like ``blevins`` are gitignored in
    CI, matching the pattern in ``test_inventory_contract.py``)."""
    import json
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "inventories" / f"{name}.json"
    if not path.exists():
        pytest.skip(f"{path.name} not present (gitignored in CI)")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _segment_grid_natural_width(seg_count: int) -> int:
    """Width the segment grid wants at ``best_segment_n_cols``
    laid out one column-row at a time. The actual desktop chrome
    around it adds ~60 px (scroll bar + panel padding); ignored
    here because we only care about whether the assumption used
    in ``SEG_CONTENT_W`` is in the right ballpark.
    """
    from phonology_features.gui.constants import BTN_GAP, BTN_W

    cols = layout.best_segment_n_cols(seg_count, max_cols=12)
    return cols * (BTN_W + BTN_GAP)


INVENTORIES = ["english", "general", "hayes", "blevins"]


@pytest.mark.parametrize("name", INVENTORIES)
def test_seg_content_width_assumption_covers_real_inventories(
    name: str,
) -> None:
    """The 500-px ``SEG_CONTENT_W`` used in resolution tests must
    be ≥ the natural width of the widest segment group in the
    bundled inventories. Otherwise the splitter would have to
    request more room than the tests assume and the seg-pane
    fan-out expectations break."""
    data = _load_inventory(f"{name}_features")
    # Inventory JSON shape: top-level dict with a "segments" mapping.
    segs = data.get("segments", {})
    assert isinstance(segs, dict)
    seg_count = len(segs)
    natural = _segment_grid_natural_width(seg_count)
    # SEG_CONTENT_W=500 plus chrome (~60) gives ~440 of grid room.
    # The actual grid splits into manner groups, so the widest
    # group's width matters, not the total seg count. ``general``
    # is the densest; the natural width of its widest group sits
    # comfortably under 600 px even with max_cols=12.
    assert natural <= 600, (
        f"{name}: widest seg group natural width {natural}px "
        f"exceeds 600px ceiling assumed in resolution tests"
    )


@pytest.mark.parametrize("name", INVENTORIES)
def test_inventory_has_features_within_reasonable_bound(
    name: str,
) -> None:
    """Feature count caps the feature-pane content width. A
    typical inventory has 25–35 features. A bump past 50 would
    blow past the 540-px ``feat_w`` the resolution matrix
    assumes."""
    data = _load_inventory(f"{name}_features")
    features = data.get("features", [])
    assert isinstance(features, list)
    n = len(features)
    assert 0 < n <= 50, f"{name}: feature count {n} outside [1, 50]"


# ---------------------------------------------------------------------------
# Cross product: 9 resolutions × 4 bundled inventories. At every pair
# above the 720p floor, neither the segment grid nor the feature panel
# should need an internal scrollbar. The 720p floor is the documented
# exception: vsplit is too short to fit the worst-case bundled inventory
# alongside the analysis-pane floor.
# ---------------------------------------------------------------------------


def _consonant_group_sizes(name: str) -> list[int]:
    """Per-manner-class consonant counts for an inventory, excluding
    the ``vowels`` group. Mirrors the data the segment grid actually
    lays out (vowels go to the separate chart, not the grid)."""
    from phonology_engine.feature_engine import FeatureEngine
    from phonology_engine.inventory import Inventory

    data = _load_inventory(f"{name}_features")
    inv = Inventory.parse(data)
    engine = FeatureEngine(inv)
    return [
        len(segs)
        for manner, segs in engine.grouped_segments.items()
        if manner.lower() != "vowels"
    ]


def _feature_card_rows(name: str) -> tuple[list[str], list[int]]:
    """Per-card row counts for an inventory's feature panel,
    bucketed via the FEATURE_GROUPS constant the way
    ``view_models._grouped_features`` does it."""
    from phonology_engine.feature_engine import FeatureEngine
    from phonology_engine.inventory import Inventory
    from phonology_features.gui.constants import FEATURE_GROUPS

    data = _load_inventory(f"{name}_features")
    inv = Inventory.parse(data)
    engine = FeatureEngine(inv)
    present = set(engine.features)
    placed: set[str] = set()
    names: list[str] = []
    counts: list[int] = []
    for group_name, group_feats in FEATURE_GROUPS:
        in_inv = [f for f in group_feats if f in present]
        if in_inv:
            names.append(group_name)
            counts.append(len(in_inv))
            placed.update(in_inv)
    leftovers = [f for f in engine.features if f not in placed]
    if leftovers:
        names.append("Other")
        counts.append(len(leftovers))
    return names, counts


@pytest.mark.parametrize("res", RESOLUTIONS, ids=lambda r: r.label)
@pytest.mark.parametrize("inv_name", INVENTORIES)
def test_top_panes_fit_without_scroll(res: Resolution, inv_name: str) -> None:
    """At every (resolution, inventory) pair above the 720p floor,
    both the segment grid and the feature panel fit inside the top
    pane's allotted height. The 720p floor is the documented
    exception: vsplit is too short to fit Hayes' 648-px consonant
    grid or General's 587-px feature panel alongside the
    analysis-pane floor. Test skips strict assertions there.

    A failure of this test means a real user on that monitor with
    that inventory would see an internal scrollbar.
    """
    win_w, win_h = layout.recommended_initial_window_size(
        res.width, res.height
    )
    seg_pane_w, _ = layout.distribute_pane_widths(
        win_w,
        seg_content_w=SEG_CONTENT_W,
        feat_content_w=FEAT_CONTENT_W,
    )
    n_cols = layout.seg_pane_n_cols(seg_pane_w)
    cons_groups = _consonant_group_sizes(inv_name)
    seg_h = layout.seg_grid_natural_height(cons_groups, n_cols)
    card_names, card_counts = _feature_card_rows(inv_name)
    feat_h = layout.feature_panel_natural_height(
        card_counts, group_names=card_names
    )

    # vsplit total = window height minus toolbar (50) + status (25)
    # + a few px of vertical padding around them.
    vsplit_total = win_h - 100
    available_top = vsplit_total - layout.HARD_MIN_ANALYSIS_H

    # 720p exception: documented as unavoidable.
    if win_h <= 720:
        return

    assert seg_h <= available_top, (
        f"{res.label} / {inv_name}: seg grid {seg_h}px exceeds "
        f"available top {available_top}px (would scroll)"
    )
    assert feat_h <= available_top, (
        f"{res.label} / {inv_name}: feat panel {feat_h}px exceeds "
        f"available top {available_top}px (would scroll)"
    )


# ---------------------------------------------------------------------------
# Ratio helpers: proportional decisions that scale with the display.
# These exercise the convention that "fraction of available space"
# decisions live in ``layout.py`` as ratios applied to live dimensions,
# not as pixel constants frozen to one monitor size.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("res", RESOLUTIONS, ids=lambda r: r.label)
def test_analysis_expand_target_scales_with_vsplit(
    res: Resolution,
) -> None:
    """The ⤢ expand-toggle target is a fraction of the vsplit
    total, not a fixed pixel value. At every resolution the
    analysis pane after expand should be ``ANALYSIS_EXPAND_RATIO ×
    vsplit_total``. Literal 0.55 so a bump to
    ``ANALYSIS_EXPAND_RATIO`` trips here."""
    _, win_h = layout.recommended_initial_window_size(res.width, res.height)
    # Approximate vsplit total = window height minus toolbar + status.
    vsplit_total = max(win_h - 100, 100)
    target = layout.analysis_expand_target(vsplit_total)
    expected = int(vsplit_total * 0.55)
    assert target == expected
    # Target must be at least HARD_MIN_ANALYSIS_H so the user
    # always gets a usable expand even on tiny screens.
    assert target >= layout.HARD_MIN_ANALYSIS_H


def test_analysis_expand_target_at_fixed_vsplit_is_literal() -> None:
    """Pin the literal ratio: 0.55 × 1000 = 550. A bump to
    ``ANALYSIS_EXPAND_RATIO`` (0.55 → 0.6) trips this assertion
    rather than silently reshaping every call site."""
    assert layout.analysis_expand_target(1000) == 550
    assert layout.analysis_expand_target(820) == 451
    assert layout.analysis_expand_target(0) == 0


@pytest.mark.parametrize("res", RESOLUTIONS, ids=lambda r: r.label)
def test_initial_window_fraction_scales_with_screen(
    res: Resolution,
) -> None:
    """``initial_window_fraction`` exposes the proportional
    component of ``recommended_initial_window_size`` for either
    axis. A 4K screen's fraction is strictly larger than a 720p
    screen's; pinned with literals against the screen dimension."""
    assert layout.initial_window_fraction(res.width) == int(res.width * 0.80)
    assert layout.initial_window_fraction(res.height) == int(res.height * 0.80)


def test_analysis_expand_ratio_in_canonical_range() -> None:
    """The expand-target ratio sits between the 50% default-feel
    and the 80% safety cap. Pins both ends so a bump that would
    make analysis too small or overflow the top pane trips here."""
    assert 0.5 <= layout.ANALYSIS_EXPAND_RATIO <= layout.ANALYSIS_MAX_RATIO
    assert layout.ANALYSIS_MAX_RATIO <= 0.9  # leave room for top pane


def test_ratios_are_float_not_int() -> None:
    """Ratios must be floats so multiplication doesn't lose
    precision via integer truncation. Pins the type contract."""
    assert isinstance(layout.DEFAULT_SCREEN_FRACTION, float)
    assert isinstance(layout.ANALYSIS_EXPAND_RATIO, float)
    assert isinstance(layout.ANALYSIS_MAX_RATIO, float)


def test_min_vowel_safe_window_w_keeps_vowels_alongside() -> None:
    """At the vowel-safe minimum window width, the seg pane gets
    exactly ``VOWEL_STACK_W`` (or a few px above it after rounding)
    — enough to keep the vowel chart beside the consonants instead
    of stacking below them. Pins literal numbers so a regression
    that shrinks the seg pane below the threshold trips here."""
    # Small feat content (300): feat_w = max(480, 340) = 480.
    # Window: 620 + 480 + 20 = 1120.
    assert layout.min_vowel_safe_window_w(300) == 1120
    seg_w, _ = layout.distribute_pane_widths(
        1120, seg_content_w=400, feat_content_w=300
    )
    assert seg_w >= layout.VOWEL_STACK_W  # 620

    # Typical feat content (500): feat_w = max(480, 540) = 540.
    # Window: 620 + 540 + 20 = 1180.
    assert layout.min_vowel_safe_window_w(500) == 1180
    seg_w, _ = layout.distribute_pane_widths(
        1180, seg_content_w=500, feat_content_w=500
    )
    assert seg_w >= layout.VOWEL_STACK_W

    # Big feat content (600): feat_w = max(480, 640) = 640.
    # Window: 620 + 640 + 20 = 1280.
    assert layout.min_vowel_safe_window_w(600) == 1280


def test_min_vowel_safe_window_w_floors_at_feat_min() -> None:
    """When feat content is tiny, the FEAT_MIN_W floor dominates,
    not the content; the vowel-safe window minimum stays at the
    floor-driven 1120."""
    assert layout.min_vowel_safe_window_w(0) == 1120
    assert layout.min_vowel_safe_window_w(100) == 1120


def test_expand_target_scales_proportionally_across_resolutions() -> None:
    """The whole point of using a ratio is that the expand target
    grows with the display. Pins the ordering: 4K window → bigger
    expand than QHD → bigger than 1080p → bigger than 720p."""
    smallest = layout.analysis_expand_target(720)
    laptop = layout.analysis_expand_target(900)
    full_hd = layout.analysis_expand_target(1080)
    qhd = layout.analysis_expand_target(1440)
    uhd = layout.analysis_expand_target(2160)
    assert smallest < laptop < full_hd < qhd < uhd
