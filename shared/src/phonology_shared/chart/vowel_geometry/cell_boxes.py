"""Content-driven pixel boxes for vowel cells (layer 3).

How big a rendered cell is, purely from its own content: button
counts, stack depths, the density-tier button heights, the rendered
box rectangle both renderers draw, and the natural data-area size
derived from the boxes. Box math never sees the outline; relating
boxes to the outline is the pipeline's job alone, which is the
structural fix for the buttons-escaped-the-outline class of bug.

May import :py:mod:`.model`, :py:mod:`.classifier`, :py:mod:`.space`,
the inference layer, and presentation constants; must not import
``slots``, ``outline``, ``furniture``, or ``pipeline``. See the
package docstring for the layer table.
"""

from __future__ import annotations

import math

from phonology_shared.chart.vowel_geometry.classifier import (
    PAIR_DISPLAY_KINDS,
)
from phonology_shared.chart.vowel_geometry.model import VowelChartCell
from phonology_shared.chart.vowel_geometry.space import (
    col_to_slot,
    horizontal_button_count as _horizontal_button_count_impl,
)
from phonology_shared.chart.vowels import VowelCellDisplayKind
from phonology_shared.presentation.chart_style import VOWEL_CELL_STACK_GAP_PX
from phonology_shared.presentation.constants import BTN_W
from phonology_shared.presentation.layout import (
    SEG_BTN_H,
    VOWEL_PAIR_GAP_PX,
    VOWEL_PAIR_SEPARATOR_PX,
)


def horizontal_button_count(
    kind: VowelCellDisplayKind,
    entries: tuple[str, ...],
    grid: tuple[tuple[int, int], ...],
) -> int:
    """Convenience wrapper over :py:func:`space.horizontal_button_count`
    with :py:data:`PAIR_DISPLAY_KINDS` (the classifier-owned frozenset)
    bound as the pair-kinds predicate. The one call site every
    consumer inside ``vowel_geometry`` uses, so box math, the shrink
    solver's row width demands, and the slot assigner cannot disagree
    on how wide a cell draws.
    """
    return _horizontal_button_count_impl(
        kind, entries, grid, pair_display_kinds=PAIR_DISPLAY_KINDS
    )


#: Two spacing regimes, deliberately distinct so the chart reads its
#: phonology at a glance: a rounded / unrounded PAIR (two mates on the
#: SAME backness anchor) is the tightest thing on the chart, and any
#: two cells at DIFFERENT backness anchors sit strictly farther apart
#: than that, so a lone central vowel (the Open row's central /a/ ~ /ä/
#: beside the front pair /a ɶ/) never reads as a fourth pair member.
#:
#: * ``VOWEL_PAIR_GAP_PX`` (2 px) is the WITHIN-pair daylight: the two
#:   mates render a fixed pixel shift apart regardless of chart width.
#: * ``_INTER_ANCHOR_GAP_PX`` is the BETWEEN-anchor minimum daylight the
#:   width solver guarantees, sized to the canonical inter-backness
#:   ``VOWEL_PAIR_SEPARATOR_PX`` so cross-column spacing in a pinched
#:   Open row matches cross-column spacing everywhere else; and, being
#:   the separator, is comfortably wider than the within-pair gap. This
#:   is the same floor ``_min_row_width_for_meta`` already uses for the
#:   shrink pass, so the grow and shrink passes now agree on how far
#:   apart distinct backness columns sit.

#: Gap (px) between vertically stacked segment buttons. Canonical
#: home lives in ``phonology_shared.presentation.chart_style`` as
#: ``VOWEL_CELL_STACK_GAP_PX`` (presentation layer, so build.py can
#: bake it without dragging chart/ imports); aliased to the
#: module-private spelling this file's box math reads.
_VOWEL_CELL_STACK_GAP_PX: int = VOWEL_CELL_STACK_GAP_PX

#: Density tiers: per-button height when a cell's stack reaches the
#: threshold entry count. SINGLE SOURCE for all three consumers:
#: this module's ``natural_data_height_px`` computation, the web's
#: CSS rules (relayed by build.py as ``--vowel-cell-dense-h`` /
#: ``--vowel-cell-ultra-h``), and the web's per-cell tier choice in
#: main.js (thresholds relayed in the ``chart-style`` inline JSON).
#: The geometry sizes its natural-height request from these so it
#: asks for what the renderer actually draws; sized from the
#: canonical button height instead, a 12-deep stack (PHOIBLE
#: !Xu / UPSID) requests 931 px where the rendered chart needs only
#: ~250 px, forcing the panel body to scroll for nothing.
DENSITY_TIER_DENSE_THRESHOLD: int = 5
DENSITY_TIER_DENSE_BTN_H: int = SEG_BTN_H - 4  # 22 px
DENSITY_TIER_ULTRA_THRESHOLD: int = 10
DENSITY_TIER_ULTRA_BTN_H: int = SEG_BTN_H - 8  # 18 px


def effective_button_height_px(stack_depth: int) -> int:
    """Per-button rendered height for a stack of ``stack_depth``
    entries. Matches the CSS density-tier ladder so the geometry's
    natural-height computation tracks the actual rendered height.

    Both renderers consume this to keep their per-button sizing in
    lockstep with the geometry's ``natural_data_height_px``
    request. Web CSS reads ``data-cell-density="dense"`` or
    ``"ultra"`` and applies the same heights via
    ``calc(var(--seg-btn-h) - 4px)`` / ``- 8px``; desktop calls
    this helper directly to set ``setFixedHeight`` on each stacked
    button. Without the parity a 7-deep stack renders 28 px taller
    on desktop than on the web (canonical 26 px vs dense 22 px)
    and the two charts visibly disagree despite consuming the same
    shared geometry.
    """
    if stack_depth >= DENSITY_TIER_ULTRA_THRESHOLD:
        return DENSITY_TIER_ULTRA_BTN_H
    if stack_depth >= DENSITY_TIER_DENSE_THRESHOLD:
        return DENSITY_TIER_DENSE_BTN_H
    return SEG_BTN_H


#: Vertical breathing room between adjacent populated rows. Picked
#: to read as a row break without overweighting the chart's chrome.
_VOWEL_ROW_GAP_PX: int = 6

#: Vertical padding (top + bottom combined) around the row content
#: so the silhouette's top edge can cut through the Close row's
#: button centres without clipping their tops.
_VOWEL_DATA_AREA_VERTICAL_PADDING_PX: int = SEG_BTN_H

#: Minimum visible daylight (px) between two SAME-anchor cells (a
#: rounded / unrounded pair): the tangency target the pair-shift
#: conflict resolver keeps two mates at. Distinct from the wider
#: between-anchor floor below; see the two-regime note at the top of
#: this module.
_INTER_CELL_GAP_PX: float = float(VOWEL_PAIR_GAP_PX)

#: Minimum visible daylight (px) between two DIFFERENT-anchor cells
#: (distinct backness columns). The canonical inter-backness
#: separator, strictly wider than the within-pair gap above, so the
#: width solver spreads distinct columns apart even in a pinched Open
#: row. Matches the shrink pass's ``_VOWEL_MIN_CELL_GAP_NORM``.
_INTER_ANCHOR_GAP_PX: float = float(VOWEL_PAIR_SEPARATOR_PX)


def _cell_horizontal_button_count(cell: VowelChartCell) -> int:
    """Horizontal button count contributed by ``cell``. Delegates to
    :py:func:`horizontal_button_count`, the ONE definition of cell
    width in buttons (a PAIR kind lays every entry in one row, so a
    3-entry phonation capsule is 3 wide, not the 2 a hand-coded pair
    rule used to claim), so the box math here and the shrink solver's
    row width demands can never disagree."""
    return horizontal_button_count(cell.display_kind, cell.entries, cell.grid)


def _cell_width_px(cell: VowelChartCell) -> int:
    """Rendered pixel width of the cell's button block: ``n``
    buttons side by side with the pair gap between them. The one
    width formula every consumer shares (the box rect, the conflict
    resolver, the natural sizing, the pipeline's extent growth) so
    "how wide is this cell" can never fork."""
    n_h = _cell_horizontal_button_count(cell)
    return n_h * BTN_W + (n_h - 1) * VOWEL_PAIR_GAP_PX


def _cell_pair_offset_px(cell: VowelChartCell) -> float:
    """Signed horizontal offset (px) from the cell's anchor to its
    rendered centre: the pair-side shift plus the confinement nudge.
    The one offset formula the box rect, the natural sizing, and the
    pipeline's extent growth share, so "how far is this cell pushed
    off its anchor" can never fork (the vertical-axis mate of
    :py:func:`_cell_width_px`)."""
    return cell.pair_side * cell.pair_shift_px + cell.nudge_px


def _grid_cols_rows(grid: tuple[tuple[int, int], ...]) -> tuple[int, int]:
    """``(n_cols, n_rows)`` occupied by a CONTRAST_SET's ``(col, row)``
    slots: one past the max index on each axis. A base-centred set is a
    single row (``var | base | var``) -> ``(3, 1)``; a complete 2x2 ->
    ``(2, 2)``. Empty grid falls back to the canonical 2x2 footprint."""
    if not grid:
        return (2, 2)
    return (
        max(col for col, _row in grid) + 1,
        max(row for _col, row in grid) + 1,
    )


def vertical_depth(
    kind: VowelCellDisplayKind,
    n_entries: int,
    grid: tuple[tuple[int, int], ...] = (),
) -> int:
    """Vertical row count a cell of ``kind`` with ``n_entries``
    contributes. PAIR kinds are 1 row; CONTRAST_SET is driven by its
    ``grid`` extent (a single-row base-centred set is 1, a 2x2 is 2),
    falling back to ``ceil(entries / 2)`` when no grid is supplied; STACK
    is ``len(entries)``. The single definition shared by the height
    sizing, the confinement box math, and the pipeline's row-depth
    pre-pass, so the three can never disagree on how tall a cell renders.
    """
    if kind in PAIR_DISPLAY_KINDS:
        return 1
    if kind == VowelCellDisplayKind.CONTRAST_SET:
        if grid:
            return _grid_cols_rows(grid)[1]
        return (n_entries + 1) // 2
    return n_entries


def content_height_px(
    kind: VowelCellDisplayKind,
    n_entries: int,
    grid: tuple[tuple[int, int], ...] = (),
) -> int:
    """Rendered pixel height of a cell's button block: ``depth``
    button rows at the density-tier height with the stack gap
    between them.

    NOT monotonic in entry count: a 10-entry stack renders SHORTER
    than a 9-entry one because the ultra tier drops the per-button
    height from 22 to 18 px. Per-row maxima must therefore compare
    heights via this function, never raw depths; comparing depths
    lets the 9-deep cell overflow a slot sized for the 10-deep one.
    """
    depth = vertical_depth(kind, n_entries, grid)
    eff_h = effective_button_height_px(depth)
    return depth * eff_h + (depth - 1) * _VOWEL_CELL_STACK_GAP_PX


def _cell_height_px(cell: VowelChartCell) -> int:
    """:py:func:`content_height_px` for an already-built cell. The
    vertical mate of :py:func:`_cell_width_px`: the one height
    formula the box rect, the natural sizing, and the pipeline's
    row weighting share."""
    return content_height_px(cell.display_kind, len(cell.entries), cell.grid)


def _cell_box_px(
    cell: VowelChartCell, dw: int, dh: int
) -> tuple[float, float, float, float]:
    """The cell's rendered button box ``(left, top, right, bottom)``
    in data-area pixels at the given rendered size.

    Mirrors BOTH renderers' placement math (desktop
    ``_layout_children``; web ``.vowel-chart-cell`` CSS): centre at
    ``chart_x * dw`` plus the signed pair shift, width from the
    horizontal button count, height from the stack depth at the
    density-tier button height. ``chart_y`` is the CELL CENTRE for
    every row (the pipeline's ``_finalize_row_plan`` nudges the
    extreme rows' centres inward so their edges hug the silhouette
    top / bottom), so the box uniformly centre-anchors on it. The
    confinement pass and the containment tests use this one
    definition, so "inside the outline" is judged against the same
    boxes the renderers draw.
    """
    ww = _cell_width_px(cell)
    wh = _cell_height_px(cell)
    left = cell.chart_x * dw - ww / 2.0 + _cell_pair_offset_px(cell)
    cy = cell.chart_y * dh
    top = cy - wh / 2.0
    return left, top, left + ww, top + wh


def _natural_data_area_size(
    cells: tuple[VowelChartCell, ...],
) -> tuple[int, int]:
    """Derive the chart data area's preferred pixel size from the
    inventory's content.

    The chart grows along both axes so the rendered cells have room
    to breathe:

    * Width is set by the widest populated row's button + gap
      requirements. Each backness slot (front / central / back)
      contributes ``N * BTN_W + (N - 1) * VOWEL_PAIR_GAP_PX`` where
      ``N`` is the slot's button count (a PAIR cell contributes 2
      buttons horizontally; a CONTRAST_SET cell contributes 2; a
      regular single contributes 1). Slot widths are separated by
      ``VOWEL_PAIR_SEPARATOR_PX``.
    * Height is set by the populated rows' content height: each
      row contributes ``max_stack * SEG_BTN_H + (max_stack - 1) *
      stack_gap`` where ``max_stack`` is the row's deepest vertical
      depth. PAIR cells count as 1 (horizontal layout); CONTRAST_SET
      cells count as ``ceil(entries / 2)`` (2x2 or 2x1 grid). STACK
      cells count as ``len(entries)``. Rows are separated by
      ``_VOWEL_ROW_GAP_PX`` and the silhouette adds vertical
      padding above the top row and below the bottom row.
    """
    if not cells:
        # Fall back to a single canonical pair slot.
        return (
            2 * BTN_W + VOWEL_PAIR_GAP_PX,
            SEG_BTN_H + _VOWEL_DATA_AREA_VERTICAL_PADDING_PX,
        )

    cells_by_row: dict[int, list[VowelChartCell]] = {}
    for c in cells:
        cells_by_row.setdefault(c.row, []).append(c)

    max_row_w = 2 * BTN_W + VOWEL_PAIR_GAP_PX
    for row_cells in cells_by_row.values():
        # Slot button-count floor: each backness slot contributes
        # its buttons + gaps, slots are separated by the pair
        # separator. Keeps single-slot rows at a sensible minimum
        # width even when the projection constraints below are lax.
        slot_buttons: dict[int, int] = {0: 0, 1: 0, 2: 0}
        for c in row_cells:
            slot = col_to_slot[c.col]
            slot_buttons[slot] += _cell_horizontal_button_count(c)
        populated_slots = [s for s, n in slot_buttons.items() if n > 0]
        slot_widths = [
            slot_buttons[s] * BTN_W
            + max(0, slot_buttons[s] - 1) * VOWEL_PAIR_GAP_PX
            for s in populated_slots
        ]
        row_w = sum(slot_widths) + (len(populated_slots) - 1) * (
            VOWEL_PAIR_SEPARATOR_PX
        )
        max_row_w = max(max_row_w, row_w)
        # The slot floor underestimates when a cell's pixel extent
        # (pair shift + nudge + half its width past a chart_x near
        # an edge) sticks out of [0, dw]; solve each edge constraint
        # for the dw that keeps the extent inside.
        cell_geom: list[tuple[float, float, float]] = []
        for c in row_cells:
            half_w = _cell_width_px(c) / 2.0
            pair_offset = _cell_pair_offset_px(c)
            cell_geom.append((c.chart_x, pair_offset, half_w))
            if c.chart_x < 1.0:
                right_extent = pair_offset + half_w
                if right_extent > 0:
                    needed = right_extent / (1.0 - c.chart_x)
                    max_row_w = max(max_row_w, int(math.ceil(needed)))
            if c.chart_x > 0.0:
                left_extent = half_w - pair_offset
                if left_extent > 0:
                    needed = left_extent / c.chart_x
                    max_row_w = max(max_row_w, int(math.ceil(needed)))
        # Inter-cell non-overlap: every pair of cells in this row
        # must fit without their pixel boxes intersecting. Bound:
        #   (xb - xa) * dw + (off_b - off_a) >= half_a + half_b + gap
        # When ``xa < xb`` (different anchors) solve for ``dw``.
        # When ``xa == xb`` the needed separation is dw-independent
        # and widening cannot help, which is why same-anchor overlap
        # is handled by the pair-shift conflict resolver instead.
        for i in range(len(cell_geom)):
            xa, oa, ha = cell_geom[i]
            for j in range(i + 1, len(cell_geom)):
                xb, ob, hb = cell_geom[j]
                if xa < xb:
                    chart_x_diff = xb - xa
                    needed_px = ha + hb + oa - ob + _INTER_ANCHOR_GAP_PX
                elif xb < xa:
                    chart_x_diff = xa - xb
                    needed_px = ha + hb + ob - oa + _INTER_ANCHOR_GAP_PX
                else:
                    continue
                if needed_px > 0:
                    needed_dw = needed_px / chart_x_diff
                    max_row_w = max(max_row_w, int(math.ceil(needed_dw)))

    # Height: per-row max rendered cell height, plus inter-row gaps
    # and vertical padding for the silhouette's top/bottom offset.
    # Density-tier-aware via ``_cell_height_px`` (the maximum is
    # taken over HEIGHTS, not depths; see ``content_height_px`` for
    # why the two orderings disagree around the tier thresholds), so
    # the chart asks for what the renderer will draw, not the
    # canonical-button theoretical max.
    row_heights: list[int] = [
        max(_cell_height_px(c) for c in row_cells)
        for row_cells in cells_by_row.values()
    ]

    total_h = sum(row_heights) + (len(row_heights) - 1) * _VOWEL_ROW_GAP_PX
    total_h += _VOWEL_DATA_AREA_VERTICAL_PADDING_PX
    return max_row_w, total_h
