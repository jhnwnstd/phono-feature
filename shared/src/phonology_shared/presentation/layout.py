"""Pure-Python layout helpers shared by desktop and web. One
definition of which feature group goes in which column; one
LPT-balancing algorithm. Edits propagate to both UIs through the
build relay.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

# ``web/scripts/build.py`` prepends the shared-src path to
# ``sys.path`` before importing this module, so the top-level form
# is safe for both desktop (workspace install) and web (Pyodide
# bundling); no cycle exists.
from phonology_shared.presentation.constants import BTN_GAP, BTN_W

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
    rearranged into ``n_spillover_cols`` columns at the bottom: the
    pair sits side-by-side, so the saved vertical space lets the
    remaining single-column groups fit comfortably above.

    ``group_heights`` is the natural per-group height (header + button
    rows) at the current pane width, in display units (px on web,
    QGridLayout-row heights on desktop). They're both monotonic, so
    the algorithm doesn't care which. ``available_height`` is the
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
# Geometry-aware segment-pane layout.
#
# The dead space we reclaim is the rectangle below
# ``max(main_flow_bottom, chart_bottom)``, a function of both the
# chart's height and how many groups stayed in the main flow.
# Column assignment uses LPT bin-packing for minimal spillover
# height, but renders groups in source order so the user reads
# top-to-bottom without surprise. The smallest ``k`` (groups in
# spillover) that fits wins, preserving "spill only the tail."
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SegLayoutPlan:
    """Complete segment-pane layout decision returned by
    :py:func:`plan_seg_layout`.

    ``main_groups`` lists the names that stay in the single-column
    main flow at the top of the pane; ``spillover_groups`` lists the
    names that fall into the spillover region below the main flow and
    the vowel chart. ``n_spillover_cols`` is the number of columns in
    that region (0 means no spillover). ``spillover_column_assignment``
    is parallel to ``spillover_groups`` and gives each group's
    destination column (0-indexed); when rendering, walk
    ``spillover_groups`` in order and place each at the bottom of its
    assigned column so the user reads top-to-bottom in column-major
    order. ``spillover_rect`` is ``(x, y, w, h)`` of the spillover
    region in pane-local pixel coordinates so the desktop can place
    the spillover container precisely (web reads it for parity).
    """

    main_groups: tuple[str, ...]
    spillover_groups: tuple[str, ...]
    n_spillover_cols: int
    spillover_column_assignment: tuple[int, ...]
    spillover_rect: tuple[int, int, int, int]


def plan_seg_layout(
    group_names: Sequence[str],
    group_heights: Sequence[int],
    group_widths: Sequence[int],
    *,
    pane_w: int,
    pane_h: int,
    chart_rect: tuple[int, int, int, int] | None,
    min_col_w: int,
    max_spillover_cols: int = 4,
    spillover_gutter: int = 8,
) -> SegLayoutPlan:
    """Compute the complete segment-pane layout (main flow + spillover)
    given the pane size, the vowel chart's local rect, and per-group
    natural heights and widths.

    Algorithm (six small steps, each independently testable):

    1. **Compute the spillover rectangle.** Always full-width, sits
       below ``max(main_flow_bottom, chart_bottom)``. ``chart_rect``
       is ``(x, y, w, h)`` in pane coords or ``None`` for "no chart
       blocks the bottom" (stacked-below or empty inventories).

    2. **Pick ``n_spillover_cols``.** ``min(max_spillover_cols, max(1,
       spillover_w // (min_col_w + spillover_gutter)))``. Floor at 1
       so a narrow pane still has somewhere for spillover to land; cap
       at ``max_spillover_cols`` (default 4) so a 1600 px pane doesn't
       fan groups out incoherently.

    3. **Sweep candidate spill sizes from smallest to largest.** Start
       with ``k = 0`` (no spillover); if the whole main flow fits in
       ``pane_h``, accept. Otherwise try ``k = 1, 2, ...`` and pick
       the smallest ``k`` that fits. This matches the historical
       "spill only the tail" semantics.

    4. **Pack the ``k`` spilled groups via LPT.** Sort by descending
       natural height; assign each to the currently-shortest column.
       The column with the largest total height sets the spillover's
       bounding height. Source order is preserved at render time --
       the assignment tuple records column membership, not display
       order.

    5. **Reject plans that overflow a column's width.** Each spillover
       column gets width
       ``(spillover_w - (n_cols - 1) * gutter) // n_cols``. A group
       whose natural width exceeds that is unspillable for this
       ``n_cols``; the sweep skips ``k`` values that would put it in
       spillover (effectively pinning it to main flow).

    6. **Fall back to "all main, scroll" on no fit.** If no ``k`` makes
       the layout fit in ``pane_h``, the returned plan has every
       group in ``main_groups`` and empty spillover. The caller's
       internal ``QScrollArea`` then handles the overflow.
    """
    n = len(group_names)
    if not (n == len(group_heights) == len(group_widths)):
        raise ValueError(
            "group_names, group_heights, group_widths must be the same"
            f" length; got {n}, {len(group_heights)}, {len(group_widths)}"
        )

    empty_plan = SegLayoutPlan(
        main_groups=tuple(group_names),
        spillover_groups=(),
        n_spillover_cols=0,
        spillover_column_assignment=(),
        spillover_rect=(0, 0, 0, 0),
    )

    if n == 0 or pane_h <= 0 or pane_w <= 0:
        return empty_plan

    chart_bottom = (
        chart_rect[1] + chart_rect[3] if chart_rect is not None else 0
    )

    # Step 2: pick spillover column count from the full pane width.
    # Spillover always claims the full pane width (sits below both
    # main flow and chart), so it doesn't depend on which groups are
    # spilled; it's a property of the pane.
    n_cols_max = max(
        1, (pane_w + spillover_gutter) // (min_col_w + spillover_gutter)
    )
    n_cols = min(max_spillover_cols, n_cols_max)
    col_w = (pane_w - (n_cols - 1) * spillover_gutter) // n_cols

    def spillover_for(k: int) -> tuple[int, list[int], int]:
        """Return ``(bounding_h, assignment_in_source_order,
        rejected_flag)`` for spilling the last ``k`` groups.

        ``rejected_flag`` is non-zero when one of the spilled groups
        is too wide for ``col_w``; the caller skips this ``k``.
        """
        spill_indices = list(range(n - k, n))
        # Width check first; if any group is too wide, this k is
        # infeasible regardless of how heights pack.
        for idx in spill_indices:
            if group_widths[idx] > col_w:
                return 0, [], 1
        # LPT bin-packing by descending height. ``order`` is indices
        # into ``spill_indices`` sorted by height descending; stable
        # tie-break by source order so identical-height groups keep
        # natural ordering.
        order = sorted(
            range(k),
            key=lambda i: (-group_heights[spill_indices[i]], i),
        )
        col_heights = [0] * n_cols
        assignment = [0] * k
        for i in order:
            target_col = min(range(n_cols), key=lambda c: col_heights[c])
            assignment[i] = target_col
            col_heights[target_col] += group_heights[spill_indices[i]]
        bounding = max(col_heights) if col_heights else 0
        return bounding, assignment, 0

    def main_flow_h_for(k: int) -> int:
        return sum(group_heights[: n - k])

    def total_h_for(k: int, spillover_bound: int) -> int:
        main_bottom = main_flow_h_for(k)
        spill_top = max(main_bottom, chart_bottom)
        return spill_top + spillover_bound

    # Step 3+6: try k=0 first (no spillover); if it fits, done.
    # Then sweep upward looking for the smallest k that fits.
    if main_flow_h_for(0) <= pane_h and chart_bottom <= pane_h:
        return empty_plan

    best_plan: SegLayoutPlan | None = None
    for k in range(1, n + 1):
        bounding, assignment, rejected = spillover_for(k)
        if rejected:
            continue
        if total_h_for(k, bounding) <= pane_h:
            spill_top = max(main_flow_h_for(k), chart_bottom)
            best_plan = SegLayoutPlan(
                main_groups=tuple(group_names[: n - k]),
                spillover_groups=tuple(group_names[n - k :]),
                n_spillover_cols=n_cols,
                spillover_column_assignment=tuple(assignment),
                spillover_rect=(0, spill_top, pane_w, bounding),
            )
            break

    # Step 6 fallback: no k made the layout fit; let the caller scroll.
    return best_plan if best_plan is not None else empty_plan


# ---------------------------------------------------------------------------
# Adaptive window layout: single source of truth for both frontends.
#
# Every layout decision below is consumed by:
#   * the desktop, by calling these functions directly from
#     ``geometry_controller`` / ``main_window``.
#   * the web, by ``web/scripts/build.py:generate_layout_css`` baking the
#     constants into a CSS custom-property file (``dist/layout.css``)
#     that ``style.css`` then references.
#
# Drift between the two UIs is impossible without breaking the parity
# test in ``desktop/tests/test_pane_distribution.py``.
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
# Threshold at which the feature panel switches to compact row
# density so a high-feature inventory fits without scrolling. At
# 22 active features the worst-balanced column is ~12 rows; one
# row beyond that and the natural-height panel starts to overflow
# the typical 440-px top-pane budget at 720p. Tuned conservatively
# so Hayes (28) goes compact, Default-33 goes compact, and shorter
# inventories (Spanish ~16) stay comfortable. Lives here (not in
# ``main_window.py``) so a future web parity implementation reads
# the same number rather than re-inventing it.
FEAT_COMPACT_THRESHOLD: int = 22
# Worst-case vowel chart width used by responsive-layout math
# (``should_stack_vowels``, ``min_vowel_safe_window_w``,
# ``would_overflow`` against the seg pane). Sized to cover the
# widest PHOIBLE inventory (max ~302 px natural data width +
# chrome ≈ 384 px) with comfortable slack.
#
# NOTE: this is a LAYOUT-MATH reference, NOT a per-render floor.
# The actual rendered chart width is content-driven per renderer
# via ``VOWEL_CHART_W_FLOOR`` in ``web/main.js`` and
# ``desktop/.../gui/vowel_chart.py``; a small inventory renders
# narrower than this constant. Keeping the layout math
# conservative (assume worst case) preserves the stack-breakpoint
# invariant: at ``VOWEL_STACK_W``, even the widest possible chart
# fits side-by-side with the minimum consonant strip.
VOWEL_NATURAL_W: int = 440

# Canonical minimum width (px) for the rendered vowel chart on
# EITHER platform. The shared geometry + chrome math agrees
# cross-renderer, but each platform's final rendering can need a
# small adjustment for box-model / border / sub-pixel quirks.
# The pattern:
#
#   shared:  MIN_VOWEL_CHART_W_PX (this constant)
#   web:     VOWEL_CHART_W_FLOOR = MIN + WEB_VOWEL_CHART_W_ADJ
#   desktop: VOWEL_CHART_W_FLOOR = MIN + DESKTOP_VOWEL_CHART_W_ADJ
#
# Both renderers default their ``ADJ`` to 0 today (the shared
# value is the canonical choice). Tune the renderer-side ``ADJ``
# (NOT this constant) when one platform needs a small visual
# nudge: a scrollbar gutter on the web, a Qt frame on the
# desktop, etc.
#
# Sized so the trapezoid + row-label gutter + chrome still read
# as the canonical IPA chart for the smallest bundled inventory.
# Above this floor the chart is content-driven (``max(floor,
# natural_data_width_px + chrome)``).
# Bumped from 320 to 380 to envelope the no-overlap-driven natural
# widths after the inter-cell constraint kicked in: Hayes Universal
# now requests 290 px data + 84 px chrome = 374 px chart-width
# minimum (was 232 + 84 = 316 px pre-constraint).
MIN_VOWEL_CHART_W_PX: int = 380
# Within each backness (front, central, back), the unrounded/rounded
# vowel pair sits in two grid columns. ``VOWEL_PAIR_GAP_PX`` is the
# gap between the two mates: small enough to read as a pair, not as
# unrelated symbols. ``VOWEL_PAIR_SEPARATOR_PX`` is the extra width
# inserted between adjacent pairs (front-rnd <-> central-unr,
# central-rnd <-> back-unr) so the boundary between backness columns
# stays visually distinct. Both UIs consume these via the relay; the
# placement code in ``vowel_layout.py`` still emits a 6-column index
# (0..5) and the renderers translate to physical grid columns.
VOWEL_PAIR_GAP_PX: int = 2
VOWEL_PAIR_SEPARATOR_PX: int = 14
# Below this seg-pane width, the chart drops below the consonants
# instead of floating beside them. Picked so a 3-column-of-buttons
# consonant area still fits next to a min-width chart.
VOWEL_STACK_W: int = 680
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
# Per-row strides inside the analysis pane (selection-chip strip +
# tab bar + outer padding). Shared so desktop and web reserve the
# same height for the floor.
ANALYSIS_SELECTION_STRIP_H: int = 38
ANALYSIS_TAB_BAR_H: int = 36
ANALYSIS_OUTER_PADDING_H: int = 54
# Pane must reliably show at least four minimal feature specs.
ANALYSIS_MIN_VISIBLE_ROWS: int = 4


def analysis_content_floor_h() -> int:
    """Analysis pane's minimum height for the four-feature-spec
    requirement. Read by the Qt splitter floor and baked into the
    web's ``--min-analysis-h``.
    """
    return (
        ANALYSIS_SELECTION_STRIP_H
        + ANALYSIS_TAB_BAR_H
        + ANALYSIS_MIN_VISIBLE_ROWS * FEAT_ROW_H
        + ANALYSIS_OUTER_PADDING_H
    )


# Preferred analysis-pane height. Identical to the floor since the
# floor is the four-row comfortable minimum; kept as a distinct name
# so existing callers reading "preferred" semantics stay valid. The
# ``MIN_ANALYSIS_H`` constant is preserved for back-compat (web build
# relays it as ``--min-analysis-h``); the value is now computed.
# A function call would be cleaner but module-level CSS-relay code
# reads this as a literal, so it stays a module-level int.
MIN_ANALYSIS_H: int = (
    38  # ANALYSIS_SELECTION_STRIP_H, inline to keep type 'int'
    + 36  # ANALYSIS_TAB_BAR_H
    + 4 * 31  # ANALYSIS_MIN_VISIBLE_ROWS * FEAT_ROW_H
    + 54  # ANALYSIS_OUTER_PADDING_H
)
# Splitter-only degenerate-case cap when the window is too short
# even for ``analysis_content_floor_h()``. Widgets must not read
# this directly.
HARD_MIN_ANALYSIS_H: int = 60
# Degenerate-case floor for the top pane (real minimum is
# content-driven via the seg_grid / feature_panel helpers).
MIN_TOP_PANE_H: int = 200

# ---------------------------------------------------------------------------
# Raw per-row dimensions shared by desktop (Qt) and web (CSS).
# Centralised so the per-row stride can't drift across renderers.
# ---------------------------------------------------------------------------

SEG_BTN_H: int = 26
SEG_BTN_ROW_H: int = 30  # SEG_BTN_H + BTN_GAP
# Manner-class group header strip above each consonant group.
SEG_GROUP_HEADER_H: int = 22

# Per-feature-row: ``FeatureRow`` is 30 px (24-px buttons + 3+3 margins)
# with 1 px inter-row spacing. Sum is the stride for height math.
FEAT_ROW_H: int = 31
# Feature card chrome: card top margin (6) + title (14) + bottom (6).
FEAT_CARD_CHROME_H: int = 26
# Feature-row button + badge dimensions. Two density tiers: NORMAL
# is the everyday case, COMPACT shrinks vertical breathing room for
# inventories near the 40-feature cap. Both renderers (desktop
# QPushButton sizing + web ``--feat-btn-*`` / ``--feat-badge-*``)
# consume these values; ``generate_layout_css`` emits the NORMAL
# CSS vars so a single edit here updates both. ``BADGE_W`` is wider
# than ``BTN_W`` so the "+" / "-" badge can host the slightly wider
# numeric values without truncation at small sizes.
FEAT_BTN_W: int = 28
FEAT_BTN_H: int = 24
FEAT_BADGE_W: int = 30
FEAT_BTN_W_COMPACT: int = 26
FEAT_BTN_H_COMPACT: int = 22
FEAT_BADGE_W_COMPACT: int = 28

# Spacing ladder. The web's ``--space-*`` custom properties and the
# desktop's QSS / QLayout literals consume these. Five tiers cover
# the everyday cases; everything else should compose from them.
SPACING_PX: dict[str, int] = {
    "xs": 4,
    "sm": 6,
    "md": 8,
    "lg": 12,
    "xl": 16,
}

# Border-radius tokens. ``sm`` for chip-like inline controls,
# ``md`` for buttons / cards, ``lg`` for the largest containers.
RADIUS_PX: dict[str, int] = {
    "sm": 4,
    "md": 6,
    "lg": 8,
}

# Top-bar control heights. ``TOOLBAR_BTN_H`` is the inventory
# combo / picker buttons; ``PANEL_CLEAR_BTN_H`` is the small
# clear-button shown in the panel header strip.
TOOLBAR_BTN_H: int = 32
PANEL_CLEAR_BTN_H: int = 22

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

# Vertical-split safety cap: the analysis pane never grows beyond
# this fraction of the vsplit total via any code path. User splitter
# drags are bounded by per-pane minimums; this constant exists for
# any future auto-grow path that wants a single canonical ceiling.
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
    + FEAT_CUSHION_PX)``, content-driven, so it stays "relatively
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


def vowel_chart_width() -> int:
    """Worst-case vowel chart width used by responsive-layout
    math (``should_stack_vowels``, ``min_vowel_safe_window_w``).

    DEPRECATED for renderer use: the rendered chart width is now
    content-driven per renderer, sized as
    ``max(VOWEL_CHART_W_FLOOR, natural_data_width_px + chrome)``
    in ``web/main.js`` and ``desktop/.../gui/vowel_chart.py``. A
    small inventory's chart is much narrower than this function's
    return value. Use it for outer-layout reservations (worst-case
    "does the chart fit in the seg pane?") only.

    Kept as a named accessor so the test suite + layout helpers
    have a single symbol to import; equivalent to reading
    ``VOWEL_NATURAL_W`` directly.
    """
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

    * Cap at ``total - analysis_content_floor_h()`` so the analysis
      pane always keeps its four-row comfortable floor, regardless
      of how tall the top content wants to be.
    * If the window is so short that even that cap would push top
      below ``MIN_TOP_PANE_H``, fall back to the absolute
      ``HARD_MIN_ANALYSIS_H`` cap; the analysis pane temporarily
      shrinks past its comfortable floor on these worst-case window
      sizes (acceptable degenerate behaviour).
    * Floor at ``MIN_TOP_PANE_H`` so the feature cards always have
      usable height even when the top pane would otherwise vanish.

    Both UIs honour this. Desktop calls it from
    ``geometry_controller.apply_splitter_sizes``; web encodes the
    same constants via the generated ``layout.css`` properties so
    the policy can't drift between frontends.
    """
    comfortable_cap = total - analysis_content_floor_h()
    if comfortable_cap >= MIN_TOP_PANE_H:
        top_h = min(top_need_h, comfortable_cap)
    else:
        # Window too short for both top and analysis floors; fall back
        # to the absolute analysis floor so top stays usable.
        top_h = min(top_need_h, total - HARD_MIN_ANALYSIS_H)
    return max(top_h, MIN_TOP_PANE_H)


def best_segment_n_cols(group_size: int, max_cols: int) -> int:
    """Pick a column count for laying out one manner-class group's
    segment buttons that avoids a last row with a single orphan.

    For ``group_size <= max_cols`` the whole group fits in one row,
    so we return ``group_size`` (no orphan possible). Otherwise the
    final row carries ``group_size % n_cols`` buttons. A remainder
    of 1 is the worst case (one button on a line by itself), so
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
    # Theoretical fallback: every remainder was 1 somehow.
    # ``group_size % 2`` is 0 or 1, so n_cols=2 above already covers
    # every group_size > 2; we only reach here for group_size in
    # {2, 3} where the loop short-circuits anyway.
    return max_cols


# ---------------------------------------------------------------------------
# Content-driven height helpers: predict the natural height each top
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
#   "clip":        hard-cut via ``overflow: hidden`` / Qt clip.
#   "scroll":      show a scrollbar.
#   "shrink-font": re-render at a smaller font-size (seg buttons
#                  use this via the rasterizer's font-shrink loop).
#   "reflow":      engage an alternative layout (spillover, stack).
#   "hide":        drop the region (e.g. tooltip when no source).
#
# Adding a region: add the entry below, then cite it in the widget's
# constructor and the test in ``desktop/tests/test_size_policies.py``.
# ---------------------------------------------------------------------------

OverflowStrategy = Literal[
    "clip",
    "scroll",
    "shrink-font",
    "reflow",
    "hide",
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


REGION_CONSTRAINTS: Mapping[str, RegionConstraint] = {
    # Segment button: fixed-size content floor sourced directly
    # from ``constants.BTN_W`` (the single source of truth). The
    # rasterizer downscales wide glyphs (k+͡x+, ɡ+͡ɣ+) so they fit
    # inside the 33×26 outline without expanding it.
    "seg_btn": RegionConstraint(
        min_w=BTN_W,
        pref_w=BTN_W,
        max_w=BTN_W,
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
    # width across pane sizes; height grows with row count. The
    # vertical floor leaves enough room for the title + column
    # header chrome + six populated height tiers without the
    # trapezoid silhouette getting squashed against the top / bottom
    # edges. Eight ``SEG_BTN_ROW_H`` slots is a comfortable floor:
    # roughly two extra rows of breathing room above what the six
    # vowel tiers alone would need.
    "vowel_chart": RegionConstraint(
        min_w=VOWEL_NATURAL_W,
        pref_w=VOWEL_NATURAL_W,
        max_w=VOWEL_NATURAL_W,
        min_h=8 * SEG_BTN_ROW_H,
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
    # Analysis panel: floor is the comfortable four-row minimum from
    # ``analysis_content_floor_h``; the same value the web locks via
    # ``--min-analysis-h``. The pane is non-resizable; its tabs
    # scroll their content internally when overflow occurs.
    # ``HARD_MIN_ANALYSIS_H`` is reserved for the worst-case-window
    # degenerate path inside ``top_pane_height`` and MUST NOT be used
    # as a widget min.
    "analysis_panel": RegionConstraint(
        min_w=SEG_MIN_W + FEAT_MIN_W,
        pref_w=None,
        max_w=None,
        min_h=MIN_ANALYSIS_H,
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
# overlap?". The predicates below answer the latter; they consume
# only the relevant content metrics and the available space.
#
# Threshold helpers (``should_stack_vowels`` etc.) stay as fast paths
# for the shipped-inventory shapes; the predicates are the underlying
# truth and asserted to agree at the boundary in
# ``test_layout_stress.py``.
# ---------------------------------------------------------------------------


def would_overflow(
    container_w: int,
    children_natural_w: Sequence[int],
    gap: int = 0,
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
    needed = (
        sum(children_natural_w) + max(0, len(children_natural_w) - 1) * gap
    )
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
        from phonology_shared.presentation.constants import FONT_SIZE_MIN_PX

        min_px = FONT_SIZE_MIN_PX
    if text_w_px <= max_w_px:
        return False
    fit_px = current_px * max_w_px / text_w_px
    return fit_px < min_px


def aspect_out_of_range(
    w: int,
    h: int,
    lo: float,
    hi: float,
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
