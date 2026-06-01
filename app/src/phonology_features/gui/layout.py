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
# Below this seg-pane width, the chart drops below the consonants
# instead of floating beside them. Picked so a 3-column-of-buttons
# consonant area still fits next to a min-width chart.
VOWEL_STACK_W: int = 620
# Total-viewport threshold below which the page-level grid collapses to
# a single column (web ``@media (max-width: ...)`` matches this). The
# media query is hardcoded; a unit test pins it to this constant.
COLLAPSE_W: int = 900
# First-launch window-size floor. Above this, the OS-screen-fraction
# rule decides; below this the floor kicks in so tiny screens still
# get a workable starting size.
MIN_FIRST_LAUNCH_W: int = 1400
MIN_FIRST_LAUNCH_H: int = 900
# Fresh-install window size = this fraction of the primary screen's
# available geometry, floored at ``MIN_FIRST_LAUNCH_*``. 80% gives
# the app a comfortable claim on the primary screen on first launch
# without filling it edge-to-edge; the user can resize from there.
DEFAULT_SCREEN_FRACTION: float = 0.80
# Preferred analysis-pane height when the feature pane already fits
# its content. On short windows where the features need more height,
# ``top_pane_height`` lets analysis shrink past this floor down to
# ``HARD_MIN_ANALYSIS_H``.
MIN_ANALYSIS_H: int = 220
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
    ``(MIN_FIRST_LAUNCH_W, MIN_FIRST_LAUNCH_H)``. The caller still
    clamps to the actual screen so the resize never overshoots
    (``geometry_controller.clamp_size_to_screen``).
    """
    w = max(MIN_FIRST_LAUNCH_W, int(screen_w * DEFAULT_SCREEN_FRACTION))
    h = max(MIN_FIRST_LAUNCH_H, int(screen_h * DEFAULT_SCREEN_FRACTION))
    return w, h


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
    from phonology_features.gui.constants import BTN_GAP, BTN_W

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
