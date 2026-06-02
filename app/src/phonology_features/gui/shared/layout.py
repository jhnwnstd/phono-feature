"""Pure-Python layout helpers shared by the desktop GUI and the
web app.

Nothing in this module imports Qt or anything browser-specific. The
desktop reads it directly; the web app picks it up via the build
script's renderer relay (web/scripts/build.py copies this file into
the Pyodide bundle, where api.py exposes it through the JS bridge).

That way: one definition of which group goes in which column. Edits
to the pin constants or the LPT algorithm propagate to both UIs on
next launch / next web build.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

# Pins are conventional in IPA chart layouts: place-of-articulation
# features (Major Class, Place) sit on the left, manner-of-
# articulation (Manner) on the right. Everything else goes wherever
# the LPT step puts it.
LEFT_PINS: tuple[str, ...] = ("Major Class", "Place")
RIGHT_PINS: tuple[str, ...] = ("Manner",)

# Per-card overhead (header + padding) expressed in row-equivalents.
# Added to each card's row count when balancing column heights so
# many-small-cards columns aren't under-counted vs few-big-cards.
CARD_OVERHEAD: int = 1


def distribute_feature_groups(
    group_sizes: Mapping[str, int],
    *,
    group_order: Sequence[str] | None = None,
    left_pins: Sequence[str] = LEFT_PINS,
    right_pins: Sequence[str] = RIGHT_PINS,
    card_overhead: int = CARD_OVERHEAD,
) -> tuple[list[str], list[str]]:
    """Assign feature-group names to two columns.

    ``group_sizes`` maps each group name to its row count (that is,
    the number of active features in the group). Groups with size 0
    are dropped from the output; empty cards should not render.

    Returns ``(left_names, right_names)``: each is a list of group
    names in the order they should be stacked vertically in that
    column.

    Algorithm:
      1. Pin LEFT_PINS / RIGHT_PINS to their columns first.
      2. Sort the remaining groups by cost descending.
      3. LPT-greedy: add each remaining group to whichever column is
         currently shorter.

    ``group_order`` only matters for tie-breaking among unpinned
    groups of equal cost; pass the canonical FEATURE_GROUPS order
    when you care about determinism. Defaults to the iteration order
    of ``group_sizes`` (insertion order in modern Python dicts).
    """

    def cost(name: str) -> int:
        n = group_sizes.get(name, 0)
        return n + card_overhead if n > 0 else 0

    left: list[str] = []
    right: list[str] = []
    left_height = 0
    right_height = 0

    pinned: set[str] = set(left_pins) | set(right_pins)

    for name in left_pins:
        c = cost(name)
        if c > 0:
            left.append(name)
            left_height += c
    for name in right_pins:
        c = cost(name)
        if c > 0:
            right.append(name)
            right_height += c

    iteration_order = list(group_order) if group_order else list(group_sizes)
    unpinned_with_cost: list[tuple[str, int]] = []
    for name in iteration_order:
        if name in pinned:
            continue
        c = cost(name)
        if c > 0:
            unpinned_with_cost.append((name, c))
    # Sort by cost descending; ties broken by iteration order, which
    # is what ``key`` on a stable sort preserves implicitly.
    unpinned_with_cost.sort(key=lambda pair: -pair[1])

    for name, c in unpinned_with_cost:
        if left_height <= right_height:
            left.append(name)
            left_height += c
        else:
            right.append(name)
            right_height += c
    return left, right


def partition_groups_for_spillover(
    group_heights: Sequence[int],
    available_height: int,
    n_spillover_cols: int = 2,
) -> int:
    """Decide how many segment groups stay in the main single-column
    flow vs. fall into a horizontal spillover at the bottom of the
    pane.

    The segments pane in both frontends stacks manner-class groups as
    a single vertical flow. With wide inventories (General IPA being
    the canonical case), that flow overshoots the visible area.
    Instead of forcing the user to scroll, the bottom groups get
    rearranged into ``n_spillover_cols`` columns at the bottom — the
    pair sits side-by-side, so the saved vertical space lets the
    remaining single-column groups fit comfortably above.

    ``group_heights`` is the natural per-group height (header + button
    rows) at the current pane width, in display units (px on web,
    QGridLayout-row heights on desktop — they're both monotonic, so
    the algorithm doesn't care which). ``available_height`` is the
    pane's clientHeight on web / scroll-viewport height on desktop.

    Returns ``main_count``: the number of groups (from the front of
    ``group_heights``) that stay in the main flow. Indexes
    ``[main_count:]`` get the spillover. Iteratively shrinks
    ``main_count`` until the combined height of the main flow plus
    the row-packed spillover fits in ``available_height``.

    The spillover's height per row is the tallest group in that row
    (groups in a row are different manner-classes with different
    segment counts; their button grids align to the row's top so the
    row's height is dominated by the tallest member).

    Same algorithm runs in both UIs so the rearrangement happens at
    the same threshold regardless of which frontend the user is on.
    """
    n = len(group_heights)
    if n == 0 or available_height <= 0:
        return n

    def fits(main_count: int) -> bool:
        main_h = sum(group_heights[:main_count])
        spillover = group_heights[main_count:]
        spillover_h = 0
        for i in range(0, len(spillover), n_spillover_cols):
            row = spillover[i : i + n_spillover_cols]
            spillover_h += max(row)
        return (main_h + spillover_h) <= available_height

    main_count = n
    while main_count > 0 and not fits(main_count):
        main_count -= 1
    return main_count


# ---------------------------------------------------------------------------
# Adaptive window layout — single source of truth for both frontends.
#
# Every layout decision below is consumed by:
#   * the desktop, by calling these functions directly from
#     ``geometry_controller`` / ``main_window``.
#   * the web, by ``web/scripts/build.py:generate_layout_css`` baking the
#     constants into a CSS custom-property file (``dist/layout.css``)
#     that ``style.css`` then references.
#
# Drift between the two UIs is impossible without breaking the parity
# test in ``app/tests/test_pane_distribution.py``.
# ---------------------------------------------------------------------------

# Below this seg-pane width the layout collapses (vowel chart stacks
# below consonants). The seg pane never shrinks past this floor on
# either UI.
SEG_MIN_W: int = 480
# Floor for the feature pane. Sized so each of the two card columns
# inside the pane gets at least ``MIN_FEAT_CARD_W`` (220 px) after
# subtracting outer margins (28 px) and the inter-card gutter (12 px).
# Formula: 2 × 220 + 28 + 12 = 480. ``distribute_pane_widths`` lifts
# this when the inventory's natural feature-pane content asks for
# more. Earlier value of 380 caused titles like "TONGUE-ROOT /
# PHARYNGEAL" to wrap to two lines.
FEAT_MIN_W: int = 480
# Extra pixels beyond ``feat_content_w`` so feature cards don't sit
# flush against the splitter handle / panel edge.
FEAT_CUSHION_PX: int = 40
# Vowel chart natural display width: row-label gutter + 6 button
# columns (BTN_W=33, BTN_GAP=4) + a few pixels of buffer for the
# longest IPA-chart row labels ("Near-close", "Close-mid") so they
# never clip. The chart is a fixed phonetic visualisation, not a
# fluid grid, so it keeps the same width regardless of seg-pane
# size — extra horizontal space goes to consonants instead.
VOWEL_NATURAL_W: int = 320
# Within each backness (front, central, back), the unrounded/rounded
# vowel pair sits in two grid columns. ``VOWEL_PAIR_GAP_PX`` is the
# gap between the two mates -- small enough to read as a pair, not as
# unrelated symbols. ``VOWEL_PAIR_SEPARATOR_PX`` is the extra width
# inserted between adjacent pairs (front-rnd <-> central-unr,
# central-rnd <-> back-unr) so the boundary between backness columns
# stays visually distinct. Both UIs consume these via the relay; the
# placement code in ``vowel_layout.py`` still emits a 6-column index
# (0..5) and the renderers translate to physical grid columns.
VOWEL_PAIR_GAP_PX: int = 2
VOWEL_PAIR_SEPARATOR_PX: int = 14
# Hover-tooltip wake-up delay for vowel-chart segment buttons, in ms.
# Single source of truth for both UIs. The web reads this from the
# baked layout.css custom property; the desktop reads it from
# ``QApplication.styleHints()`` via the ``_TooltipDelayStyle``
# QProxyStyle that wraps the system style at startup. Drift between
# the two surfaces is exactly the kind of UI-behavior split this
# repo's relay architecture exists to prevent.
VOWEL_TOOLTIP_SHOW_DELAY_MS: int = 1000
# Below this seg-pane width, the chart drops below the consonants
# instead of floating beside them. Picked so a 3-column-of-buttons
# consonant area still fits next to a min-width chart.
VOWEL_STACK_W: int = 620
# Total-viewport threshold below which the page-level grid collapses to
# a single column (web ``@media (max-width: ...)`` matches this). The
# media query is hardcoded; a unit test pins it to this constant.
COLLAPSE_W: int = 900
# First-launch window-size floor. The width is the minimum needed to
# keep the vowel chart alongside (not stacked below) the consonant
# grid: ``VOWEL_STACK_W`` (620 px floor for the seg pane to host the
# chart side-by-side) plus the minimum feat-pane width (480 px) plus
# the splitter handle and a few pixels of safety margin = 1120 px.
# At this floor, ``distribute_pane_widths`` gives the seg pane just
# enough room for vowels-alongside; anything narrower would force
# the chart to stack. Bigger inventories get a content-driven size
# above this floor via ``fit_to_content``; smaller inventories sit
# at the floor so vowels still display correctly.
MIN_FIRST_LAUNCH_W: int = VOWEL_STACK_W + FEAT_MIN_W + 20
MIN_FIRST_LAUNCH_H: int = 900
# Fresh-install window size = this fraction of the primary screen's
# available geometry, floored at ``MIN_FIRST_LAUNCH_*``. 80% gives
# the app a comfortable claim on the primary screen on first launch
# without filling it edge-to-edge; the user can resize from there.
DEFAULT_SCREEN_FRACTION: float = 0.80
# Preferred analysis-pane height when the feature pane already fits
# its content. On short windows where the features need more height,
# ``top_pane_height`` lets analysis shrink past this floor down to
# ``HARD_MIN_ANALYSIS_H``. Sized so the resting (non-expanded)
# analysis pane shows at least three minimal feature specification
# rows comfortably (selection chip strip ~30 px + tab bar ~30 px +
# three chip rows at ~30 px each + outer padding ~30 px); larger
# bundles use the expand toggle.
MIN_ANALYSIS_H: int = 252
# Absolute floor so analysis is at least its title bar + a line of
# text on the worst-case window size.
HARD_MIN_ANALYSIS_H: int = 60
# Defensive floor for the top (seg / feat) pane in
# ``top_pane_height``. The actual minimum heights are content-driven:
# ``geometry_controller.fit_to_content`` calls the new
# ``seg_grid_natural_height`` / ``feature_panel_natural_height``
# helpers below to size each panel's ``setMinimumHeight`` against
# its real inventory content. This floor is just degenerate-case
# protection (e.g. an empty inventory whose ``sizeHint`` reports 0)
# so the top pane doesn't fully collapse. The analysis pane
# absorbs everything above the content-driven need by default —
# the user's stated preference of "analysis as tall as it can be".
MIN_TOP_PANE_H: int = 200

# ---------------------------------------------------------------------------
# RAW DIMENSIONS — per-row / per-card pixel measurements shared by
# desktop (Qt) and web (CSS). These are the single source of truth
# both UIs consume; height-computation helpers below build everything
# else from them. Centralised so the per-row stride doesn't drift
# between widgets.py, geometry_controller.py, and the web stylesheet.
# ---------------------------------------------------------------------------

# Per-segment-button: fixed size set by ``widgets.SegmentButton``.
SEG_BTN_H: int = 26
# One row of the segment grid: button + ``BTN_GAP`` from constants.py.
# Imported lazily inside the helper to avoid the cross-module dep at
# module-load time.
SEG_BTN_ROW_H: int = 30  # SEG_BTN_H (26) + BTN_GAP (4)
# Manner-class group header strip above each consonant group.
SEG_GROUP_HEADER_H: int = 22

# Per-feature-row: ``FeatureRow`` is 30 px (24-px buttons + 3+3 margins)
# with 1 px inter-row spacing. Sum is the stride for height math.
FEAT_ROW_H: int = 31
# Feature card chrome: card top margin (6) + title (14) + bottom (6).
FEAT_CARD_CHROME_H: int = 26

# Outer panel chrome (top + bottom margins + the clear-button header
# strip). Same on seg and feat panels. Used as the additive overhead
# when sizing a panel's minimum height from its content.
PANEL_CHROME_V: int = 54

# Minimum width per feature card column inside the feature panel.
# Sized so the longest group title ("TONGUE-ROOT / PHARYNGEAL", at
# the card's 8pt Bold font) renders on a single line. Drives the
# new ``FEAT_MIN_W`` derivation below.
MIN_FEAT_CARD_W: int = 220

# ---------------------------------------------------------------------------
# RATIO HELPERS
#
# Convention for layout decisions in this codebase:
#
# * **Content-driven floors** are expressed in pixels (e.g.
#   ``SEG_MIN_W = 480``). The segment grid needs ~480 px to render its
#   widest manner group regardless of screen size; making that a ratio
#   would either clip on small screens or leave dead space on large
#   ones.
#
# * **Proportional decisions** are expressed as ratios in this section
#   and applied via the helpers below. Anything that asks "what fraction
#   of the available space should this take" belongs here, not as a
#   scattered ``int(0.55 * total)`` in a widget. The ratios get a
#   single canonical name; pixel values fall out of multiplying by
#   the live window/screen dimensions.
#
# When reworking display or content logic, default to a ratio helper.
# Reach for a pixel constant only when the value is content-driven
# (the floor for a fixed-resolution chart, the natural width of a
# button), not when it's a "this much of the window" decision.
# ---------------------------------------------------------------------------

# Vertical-split target for the ⤢ expand toggle: the analysis pane
# grows to this fraction of the vsplit total when the user clicks ⤢.
# Mirrors the web ``.analysis.expanded { min-height: 55vh }`` rule.
ANALYSIS_EXPAND_RATIO: float = 0.55

# Vertical-split safety cap: the analysis pane never grows beyond
# this fraction of the vsplit total via any code path. The expand
# toggle uses ``ANALYSIS_EXPAND_RATIO``; user splitter drags are
# bounded by per-pane minimums; this constant exists for any future
# auto-grow path that wants a single canonical ceiling.
ANALYSIS_MAX_RATIO: float = 0.80

# Content-width cap (ultrawide). On 3440 / 3840 / 5120 px monitors
# the segment pane would otherwise absorb every extra pixel and the
# consonant grid would fan out to 25+ columns of useless horizontal
# eye-travel. ``CONTENT_MAX_W_ABS`` is the absolute ceiling; below
# it the layout is unaffected (the existing
# ``DEFAULT_SCREEN_FRACTION`` rule still chooses the first-launch
# width). Above it the desktop window's first-launch size stops
# growing and the web's ``main.grid`` is capped via ``max-width``
# then centred with ``margin-inline: auto``. Chosen so 1920p and
# 2560p monitors are unaffected (their 80% windows fall well under
# 2400 px) but 3440p+ ultrawides see the cap bite.
CONTENT_MAX_W_ABS: int = 2400


def analysis_expand_target(vsplit_total: int) -> int:
    """The analysis-pane height the expand toggle should set, given
    the vsplit's current total height. Centralised so the desktop
    splitter swap and any future web equivalent share one source.
    """
    return int(vsplit_total * ANALYSIS_EXPAND_RATIO)


def initial_window_fraction(screen_dimension: int) -> int:
    """The proportional component of ``recommended_initial_window_size``
    on a single axis (the caller composes it with the
    ``MIN_FIRST_LAUNCH_*`` floor). Exposed so other display-sizing
    code paths can ask "what fraction of the screen does the app
    claim" without re-stating ``DEFAULT_SCREEN_FRACTION`` inline.
    """
    return int(screen_dimension * DEFAULT_SCREEN_FRACTION)


def content_max_w(screen_w: int) -> int:
    """Cap on the overall content width for the given screen.

    Returns the smaller of ``CONTENT_MAX_W_ABS`` and the screen
    width, floored at ``MIN_FIRST_LAUNCH_W`` so the cap never
    returns less than the vowel-safe first-launch floor. Below the
    absolute ceiling the cap is just the screen width (the cap
    doesn't bite); above the ceiling it stops growing. Both UIs
    honour the same number: desktop composes it inside
    ``recommended_initial_window_size``, web encodes it via the
    ``--content-max-w`` CSS variable and a ``max-width`` rule on
    ``main.grid``.
    """
    capped = min(CONTENT_MAX_W_ABS, screen_w)
    return max(MIN_FIRST_LAUNCH_W, capped)


def scaled_handle_w(dpr: float) -> int:
    """Splitter-handle pixel width scaled by the device pixel ratio.

    At 1.0× the handle stays at 4 px (the historical value). At 2.0×
    it grows to 8 px, at 3.0× to 12, so the grab target remains the
    same physical size regardless of OS scaling. Clamped to a floor
    of 4 px so a misreported sub-1.0 DPR never shrinks the handle.
    """
    effective = max(1.0, dpr)
    return max(4, round(4 * effective))


def distribute_pane_widths(
    total_w: int,
    *,
    seg_content_w: int,
    feat_content_w: int,
) -> tuple[int, int]:
    """Decide ``(seg_w, feat_w)`` splitter / grid widths for a total
    available width.

    Policy: the feature pane gets ``max(FEAT_MIN_W, feat_content_w
    + FEAT_CUSHION_PX)`` — content-driven, so it stays "relatively
    consistent" as the user requested. The segments pane absorbs the
    rest above ``SEG_MIN_W`` (or its own content width, whichever is
    larger). On wide screens this means segments fan out instead of
    leaving dead space.

    Both UIs honor the same rule: desktop calls this from
    ``geometry_controller.apply_splitter_sizes``; web encodes it via
    the CSS ``grid-template-columns: minmax(var(--seg-min-w), 1fr)
    max-content``.
    """
    feat_w = max(FEAT_MIN_W, feat_content_w + FEAT_CUSHION_PX)
    seg_floor = max(SEG_MIN_W, seg_content_w)
    seg_w = max(seg_floor, total_w - feat_w)
    return seg_w, feat_w


def vowel_chart_width(seg_pane_w: int) -> int:
    """The vowel chart's natural display width. The IPA chart is a
    fixed visualisation (one row-label column + six button columns)
    so it doesn't grow with ``seg_pane_w`` — that would just put
    empty space around the buttons and steal width from the
    consonant flow. Always returns ``VOWEL_NATURAL_W``; the
    parameter is kept for signature symmetry with
    :py:func:`should_stack_vowels` and so future per-pane growth
    rules can land here without a call-site change.

    When the seg pane is too narrow to host the chart beside the
    consonants, the caller drops to :py:func:`should_stack_vowels`
    and lays the chart out underneath instead.
    """
    del seg_pane_w  # intentionally unused
    return VOWEL_NATURAL_W


def should_stack_vowels(seg_pane_w: int) -> bool:
    """True when the seg pane is too narrow to host the vowel chart
    beside the consonants. Both UIs drop the chart below the
    consonants at the same threshold.

    The pixel threshold (``VOWEL_STACK_W``) is the canonical answer
    for shipped inventories; the constraint-failure predicate
    :py:func:`would_overflow` is the underlying reason. Both must
    agree at the boundary, asserted by
    ``test_layout_stress.py::test_vowel_stack_predicate_matches_
    threshold``. The threshold remains the fast path so this hot
    function stays branch-cheap.
    """
    return seg_pane_w < VOWEL_STACK_W


def should_collapse_single_column(total_w: int) -> bool:
    """True when the whole window is too narrow for side-by-side
    panes; the page collapses to a single vertical column. The web
    matches this via ``@media (max-width: COLLAPSE_W px)``; the
    desktop has no analogue today but the helper is here so a
    future narrow-window code path can use the same threshold.
    """
    return total_w < COLLAPSE_W


def recommended_initial_window_size(
    screen_w: int, screen_h: int
) -> tuple[int, int]:
    """Window size for a fresh install: ``DEFAULT_SCREEN_FRACTION`` of
    the primary screen, floored at
    ``(MIN_FIRST_LAUNCH_W, MIN_FIRST_LAUNCH_H)`` and capped at the
    width by ``content_max_w`` so a fresh launch on an ultrawide
    monitor doesn't open the window past the useful content cap.
    The user can still drag the window wider; the cap only governs
    the recommended first-launch size. The caller still clamps to
    the actual screen so the resize never overshoots
    (``geometry_controller.clamp_size_to_screen``).
    """
    w = max(MIN_FIRST_LAUNCH_W, int(screen_w * DEFAULT_SCREEN_FRACTION))
    w = min(w, content_max_w(screen_w))
    h = max(MIN_FIRST_LAUNCH_H, int(screen_h * DEFAULT_SCREEN_FRACTION))
    return w, h


def min_vowel_safe_window_w(feat_content_w: int) -> int:
    """Smallest window width that keeps the vowel chart side-by-side
    with the consonant grid for a given feat content size.

    The seg pane needs at least ``VOWEL_STACK_W`` (620 px) to host the
    chart alongside; below that the chart stacks under consonants.
    The feat pane's width is content-driven via ``distribute_pane_widths``
    (``max(FEAT_MIN_W, feat_content_w + FEAT_CUSHION_PX)``), so the
    minimum window width that satisfies the vowel-alongside constraint
    is ``VOWEL_STACK_W + feat_pane_w + chrome``. Plus a small safety
    margin (20 px) for splitter handle and rounding.

    Used by ``geometry_controller.fit_to_content`` to size the
    first-launch window so the user's stated "minimum width needed
    so vowels don't display under consonants" preference holds for
    whichever inventory is loaded.
    """
    feat_pane_w = max(FEAT_MIN_W, feat_content_w + FEAT_CUSHION_PX)
    return VOWEL_STACK_W + feat_pane_w + 20


def top_pane_height(top_need_h: int, total: int) -> int:
    """Decide the top (seg / feat) pane height inside the vertical
    splitter for the given content-driven need and the vsplit's
    current total height.

    Policy:

    * Cap at ``total - HARD_MIN_ANALYSIS_H`` so the analysis pane
      always keeps at least its title-bar / one-line floor, no
      matter how tall the features want to be.
    * Floor at ``MIN_TOP_PANE_H`` so a tiny window still leaves the
      feature cards a usable height, even when the cap above would
      otherwise let them shrink to nothing.

    Both UIs honour this. Desktop calls it from
    ``geometry_controller.apply_splitter_sizes``; web encodes the
    same constants via the generated ``layout.css`` properties so
    the policy can't drift between frontends.
    """
    top_h = min(top_need_h, total - HARD_MIN_ANALYSIS_H)
    return max(top_h, MIN_TOP_PANE_H)


def best_segment_n_cols(group_size: int, max_cols: int) -> int:
    """Pick a column count for laying out one manner-class group's
    segment buttons that avoids a last row with a single orphan.

    For ``group_size <= max_cols`` the whole group fits in one row,
    so we return ``group_size`` (no orphan possible). Otherwise the
    final row carries ``group_size % n_cols`` buttons. A remainder
    of 1 is the worst case — one button on a line by itself — so
    we step ``n_cols`` down from ``max_cols`` until the remainder
    is either 0 (rows exactly fill) or at least 2 (no orphan).

    Lower columns mean more rows; we prefer the largest n_cols that
    avoids the orphan so the group stays compact vertically. Both
    UIs call this on every group: desktop in
    :py:class:`SegmentGridWidget._do_relayout`, web in
    ``renderSegmentGrid`` via the ``best_segment_n_cols`` bridge.
    """
    if group_size <= 0:
        return 1
    if max_cols <= 1:
        return 1
    if group_size <= max_cols:
        return group_size
    for n_cols in range(max_cols, 1, -1):
        remainder = group_size % n_cols
        if remainder == 0 or remainder >= 2:
            return n_cols
    # Theoretical fallback — every remainder was 1 somehow.
    # ``group_size % 2`` is 0 or 1, so n_cols=2 above already covers
    # every group_size > 2; we only reach here for group_size in
    # {2, 3} where the loop short-circuits anyway.
    return max_cols


# ---------------------------------------------------------------------------
# Content-driven height helpers — predict the natural height each top
# pane will take BEFORE Qt lays it out. Lets ``geometry_controller``
# pick the right ``setMinimumHeight`` values from inventory metadata
# alone, and lets the cross-product test prove that no bundled
# inventory triggers an internal scrollbar above the 720p floor.
# ---------------------------------------------------------------------------


def seg_pane_n_cols(seg_pane_w: int) -> int:
    """Column count the segment grid uses at the given pane width.

    Mirrors ``widgets.SegmentGridWidget._compute_n_cols`` so height
    computation here predicts the same layout Qt will actually run.
    Both UIs base their grid on this single function: the web's
    container-query CSS uses the same numbers via the relay.
    """
    from phonology_features.gui.shared.constants import BTN_GAP, BTN_W

    # Per-button stride is button width plus the inter-button gap.
    cols = (seg_pane_w + BTN_GAP) // (BTN_W + BTN_GAP)
    # The widget's own MAX_COLS=30 cap; replicated here so this
    # function is the canonical answer even when the widget is not
    # available (web build, headless tests).
    return max(1, min(int(cols), 30))


def seg_grid_natural_height(
    consonant_group_sizes: Sequence[int],
    cols: int,
) -> int:
    """Pixel height the consonant grid wants when laid out at
    ``cols`` columns per group.

    Each manner-class group contributes ``SEG_GROUP_HEADER_H``
    (22 px) plus ``ceil(N / best_n_cols) × SEG_BTN_ROW_H`` (30 px)
    for its button rows, where ``best_n_cols`` is the orphan-avoiding
    column count from ``best_segment_n_cols(N, cols)``. Caller passes
    the per-group counts; this helper sums them.

    Used by desktop ``geometry_controller.fit_to_content`` to set the
    seg-pane ``setMinimumHeight`` and by the web's seg-pane CSS
    via the constants relay.
    """
    total = 0
    for size in consonant_group_sizes:
        if size <= 0:
            continue
        n_cols = best_segment_n_cols(size, cols)
        rows = math.ceil(size / n_cols)
        total += SEG_GROUP_HEADER_H + rows * SEG_BTN_ROW_H
    return total


def feature_panel_natural_height(
    card_row_counts: Sequence[int],
    *,
    group_order: Sequence[str] | None = None,
    group_names: Sequence[str] | None = None,
) -> int:
    """Pixel height the two-column feature panel wants given a list
    of card row counts.

    Uses ``distribute_feature_groups`` to balance left vs right
    column, then returns the taller column's height plus
    ``PANEL_CHROME_V``. Each card contributes
    ``FEAT_CARD_CHROME_H + rows × FEAT_ROW_H``.

    Caller can pass ``group_names`` to honour the LEFT_PINS /
    RIGHT_PINS convention; if omitted, falls back to greedy
    distribution by row count alone.
    """
    if not card_row_counts:
        return PANEL_CHROME_V
    if group_names is None:
        # Fallback: name the groups numerically; LPT distribution
        # by row count, no pins.
        group_names = [f"_g{i}" for i in range(len(card_row_counts))]
    sizes: dict[str, int] = dict(
        zip(group_names, card_row_counts, strict=True)
    )
    left_names, right_names = distribute_feature_groups(
        sizes, group_order=group_order
    )

    def column_h(names: Sequence[str]) -> int:
        return sum(
            FEAT_CARD_CHROME_H + sizes[name] * FEAT_ROW_H for name in names
        )

    return max(column_h(left_names), column_h(right_names)) + PANEL_CHROME_V


# ---------------------------------------------------------------------------
# REGION CONSTRAINT TABLE
#
# Single declarative source of truth for each visible region's size
# contract. Qt widgets cite their entry through ``setSizePolicy`` /
# ``setMinimumSize`` / ``setMaximumSize`` (see Phase C). The web
# build relays ``REGION_CONSTRAINTS`` into CSS custom properties so
# ``style.css`` rules read the same numbers (see
# ``generate_layout_css`` in ``web/scripts/build.py``).
#
# An entry's ``min_*`` is the floor below which content stops being
# usable. ``pref_*`` is the natural size when content drives layout
# (``None`` means "use sizeHint / intrinsic"). ``max_*`` is the
# ceiling above which extra space is wasted (``None`` = unbounded).
# ``overflow`` names the documented strategy when natural content
# would exceed ``max_*``:
#
#   "clip"        — hard-cut via ``overflow: hidden`` / Qt clip.
#   "scroll"      — show a scrollbar.
#   "shrink-font" — re-render at a smaller font-size (seg buttons
#                   use this via the rasterizer's font-shrink loop).
#   "reflow"      — engage an alternative layout (spillover, stack).
#   "hide"        — drop the region (e.g. tooltip when no source).
#
# Adding a region: add the entry below, then cite it in the widget's
# constructor and the test in ``app/tests/test_size_policies.py``.
# ---------------------------------------------------------------------------

OverflowStrategy = Literal[
    "clip", "scroll", "shrink-font", "reflow", "hide",
]


@dataclass(frozen=True)
class RegionConstraint:
    """A region's size contract: floor, natural size, ceiling, and
    documented overflow strategy. ``pref_*`` and ``max_*`` may be
    ``None`` to mean "intrinsic / unbounded" respectively. All
    numeric fields are in CSS pixels (web) / device-independent
    pixels (Qt).
    """

    min_w: int
    pref_w: int | None
    max_w: int | None
    min_h: int
    pref_h: int | None
    max_h: int | None
    overflow: OverflowStrategy


# Imported lazily inside the dict expression to avoid a cyclic
# module-load between constants.py and layout.py at the test layer.
def _btn_w() -> int:
    from phonology_features.gui.shared.constants import BTN_W

    return BTN_W


REGION_CONSTRAINTS: Mapping[str, RegionConstraint] = {
    # Segment button: fixed-size content floor. The rasterizer
    # downscales wide glyphs (k+͡x+, ɡ+͡ɣ+) so they fit inside the
    # 33×26 outline without expanding it.
    "seg_btn": RegionConstraint(
        min_w=_btn_w(),
        pref_w=_btn_w(),
        max_w=_btn_w(),
        min_h=SEG_BTN_H,
        pref_h=SEG_BTN_H,
        max_h=SEG_BTN_H,
        overflow="shrink-font",
    ),
    # Segment grid: floor below which the consonant grid can't host
    # its widest manner row; height is content-driven (no pref/max)
    # and falls back to spillover when natural height exceeds the
    # pane area.
    "seg_grid": RegionConstraint(
        min_w=SEG_MIN_W,
        pref_w=None,
        max_w=None,
        min_h=SEG_GROUP_HEADER_H + SEG_BTN_ROW_H,
        pref_h=None,
        max_h=None,
        overflow="reflow",
    ),
    # Vowel chart: fixed phonetic visualisation, kept at its natural
    # width across pane sizes; height grows with row count.
    "vowel_chart": RegionConstraint(
        min_w=VOWEL_NATURAL_W,
        pref_w=VOWEL_NATURAL_W,
        max_w=VOWEL_NATURAL_W,
        min_h=4 * SEG_BTN_ROW_H,
        pref_h=None,
        max_h=None,
        overflow="clip",
    ),
    # Feature card: one column inside the two-column feature panel.
    # ``MIN_FEAT_CARD_W`` is the floor that keeps the longest group
    # title ("TONGUE-ROOT / PHARYNGEAL") on a single line.
    "feature_card": RegionConstraint(
        min_w=MIN_FEAT_CARD_W,
        pref_w=None,
        max_w=None,
        min_h=FEAT_CARD_CHROME_H + FEAT_ROW_H,
        pref_h=None,
        max_h=None,
        overflow="reflow",
    ),
    # Feature panel: two-column layout; floor accommodates two
    # ``MIN_FEAT_CARD_W`` columns plus chrome.
    "feature_panel": RegionConstraint(
        min_w=FEAT_MIN_W,
        pref_w=None,
        max_w=None,
        min_h=FEAT_CARD_CHROME_H + 4 * FEAT_ROW_H + PANEL_CHROME_V,
        pref_h=None,
        max_h=None,
        overflow="scroll",
    ),
    # Analysis panel: floor lets analysis collapse to a tab-bar +
    # one line; preferred height shows ~3 minimal feature-spec rows.
    # The expand toggle bypasses ``pref_h`` up to
    # ``ANALYSIS_MAX_RATIO`` of the vsplit (see
    # ``analysis_expand_target``).
    "analysis_panel": RegionConstraint(
        min_w=SEG_MIN_W + FEAT_MIN_W,
        pref_w=None,
        max_w=None,
        min_h=HARD_MIN_ANALYSIS_H,
        pref_h=MIN_ANALYSIS_H,
        max_h=None,
        overflow="scroll",
    ),
}


# ---------------------------------------------------------------------------
# CONTENT-DRIVEN BREAKPOINT PREDICATES
#
# Layout decisions historically keyed off pixel thresholds
# (``VOWEL_STACK_W = 620``, ``COLLAPSE_W = 900``). Thresholds are
# cheap and explicit but answer the wrong question: "is the window
# narrower than 620 px?" instead of "would my content actually
# overlap?". The predicates below answer the latter -- they consume
# only the relevant content metrics and the available space.
#
# Threshold helpers (``should_stack_vowels`` etc.) stay as fast paths
# for the shipped-inventory shapes; the predicates are the underlying
# truth and asserted to agree at the boundary in
# ``test_layout_stress.py``.
# ---------------------------------------------------------------------------


def would_overflow(
    container_w: int, children_natural_w: Sequence[int], gap: int = 0,
) -> bool:
    """True when laying the children out in one row would exceed
    ``container_w``. Used to decide whether to reflow / spillover /
    stack before the visual collision happens.

    Empty children always fit; negative ``container_w`` is treated
    as zero. ``gap`` is the inter-child spacing (Qt layout spacing /
    CSS gap); a final trailing gap is NOT included since most layouts
    only emit gaps BETWEEN children.

    >>> would_overflow(800, [480, 320], gap=8)
    True
    >>> would_overflow(810, [480, 320], gap=10)
    True
    >>> would_overflow(820, [480, 320], gap=10)
    False
    """
    if not children_natural_w:
        return False
    needed = sum(children_natural_w) + max(0, len(children_natural_w) - 1) * gap
    return needed > max(0, container_w)


def font_below_min(
    text_w_px: int,
    max_w_px: int,
    current_px: int,
    min_px: int | None = None,
) -> bool:
    """True when shrinking the font to make ``text_w_px`` fit inside
    ``max_w_px`` would drop below the readability floor. Formalises
    the rasterizer's font-shrink loop in ``web/main.js`` so the same
    predicate is available to Qt-side text-fit logic.

    The shrink scales the font linearly: the size at which the text
    just fits is ``current_px * max_w_px / text_w_px``. The
    predicate is true when that size is below ``min_px``.

    ``min_px`` defaults to ``FONT_SIZE_MIN_PX`` from constants.py;
    pulled lazily to avoid a load-time cycle.
    """
    if min_px is None:
        from phonology_features.gui.shared.constants import FONT_SIZE_MIN_PX

        min_px = FONT_SIZE_MIN_PX
    if text_w_px <= max_w_px:
        return False
    fit_px = current_px * max_w_px / text_w_px
    return fit_px < min_px


def aspect_out_of_range(
    w: int, h: int, lo: float, hi: float,
) -> bool:
    """True when the ``w/h`` aspect ratio falls outside ``[lo, hi]``.

    Useful for "the layout breaks at extreme aspect ratios" gates:
    the content is fine if it's somewhere between portrait phone
    (lo ~ 0.4) and ultrawide (hi ~ 3.5). Degenerate ``h <= 0`` is
    treated as out-of-range.
    """
    if h <= 0:
        return True
    ratio = w / h
    return ratio < lo or ratio > hi
