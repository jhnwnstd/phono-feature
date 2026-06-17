"""Content-driven pixel boxes for vowel cells (layer 3).

How big a rendered cell is, purely from its own content: button
counts, stack depths, the density-tier button heights, the rendered
box rectangle both renderers draw, the pair-shift conflict resolver,
and the natural data-area size derived from the boxes. Box math
never sees the outline; relating boxes to the outline is the
pipeline's job alone, which is the structural fix for the
buttons-escaped-the-outline class of bug.

May import :py:mod:`.model`, :py:mod:`.display_slots`, the inference
layer, and presentation constants; must not import ``outline``,
``furniture``, or ``pipeline``. See the package docstring for the
layer table.
"""

from __future__ import annotations

import math
from dataclasses import replace

from phonology_shared.chart.vowel_geometry.display_slots import (
    _COL_TO_SLOT,
    PAIR_DISPLAY_KINDS,
)
from phonology_shared.chart.vowel_geometry.model import VowelChartCell
from phonology_shared.chart.vowels import VowelCellDisplayKind
from phonology_shared.presentation.chart_style import (
    VOWEL_CELL_STACK_GAP_PX,
    VOWEL_PAIR_SHIFT_PX,
)
from phonology_shared.presentation.constants import BTN_W
from phonology_shared.presentation.layout import (
    SEG_BTN_H,
    VOWEL_PAIR_GAP_PX,
    VOWEL_PAIR_SEPARATOR_PX,
)

#: Gap (px) between vertically stacked segment buttons. Canonical
#: home lives in ``phonology_shared.presentation.chart_style`` as
#: ``VOWEL_CELL_STACK_GAP_PX`` (presentation layer, so build.py can
#: bake it without dragging chart/ imports); imported in the top
#: import block. The private alias below is kept for consumers of
#: the old name.
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


#: Compat alias for the pre-rename private spelling, re-exported by
#: the ``vowels_layout`` facade for legacy import sites.
_effective_button_height_px = effective_button_height_px


#: Vertical breathing room between adjacent populated rows. Picked
#: to read as a row break without overweighting the chart's chrome.
_VOWEL_ROW_GAP_PX: int = 6

#: Vertical padding (top + bottom combined) around the row content
#: so the silhouette's top edge can cut through the Close row's
#: button centres without clipping their tops.
_VOWEL_DATA_AREA_VERTICAL_PADDING_PX: int = SEG_BTN_H

#: Minimum visible daylight (px) between two cells in the same row.
#: Shared by the pair-shift conflict resolver and the width solver
#: so "tangent" means the same thing in both.
_INTER_CELL_GAP_PX: float = 2.0


def _cell_horizontal_button_count(cell: VowelChartCell) -> int:
    """Horizontal button count contributed by ``cell``. PAIR /
    CONTRAST_SET cells take 2, STACK takes 1. Module-level so both
    the conflict resolver and the natural-size calc share one
    definition."""
    if cell.display_kind in PAIR_DISPLAY_KINDS:
        return 2
    if cell.display_kind == VowelCellDisplayKind.CONTRAST_SET:
        return 2
    return 1


def _cell_width_px(cell: VowelChartCell) -> int:
    """Rendered pixel width of the cell's button block: ``n``
    buttons side by side with the pair gap between them. The one
    width formula every consumer shares (the box rect, the conflict
    resolver, the natural sizing, the pipeline's extent growth) so
    "how wide is this cell" can never fork."""
    n_h = _cell_horizontal_button_count(cell)
    return n_h * BTN_W + (n_h - 1) * VOWEL_PAIR_GAP_PX


def _anchor_group_key(chart_x: float) -> int:
    """Quantised anchor identity: cells whose ``chart_x`` agree to
    the nearest thousandth share a backness anchor. The conflict
    resolver and the confinement pass group by this key so
    same-anchor cells are handled as one column and pair tangency
    survives any shift applied to the group."""
    return round(chart_x * 1000)


def _cell_pair_offset_px(cell: VowelChartCell) -> float:
    """Signed horizontal offset (px) from the cell's anchor to its
    rendered centre: the pair-side shift plus the confinement nudge.
    The one offset formula the box rect, the natural sizing, and the
    pipeline's extent growth share, so "how far is this cell pushed
    off its anchor" can never fork (the vertical-axis mate of
    :py:func:`_cell_width_px`)."""
    return cell.pair_side * cell.pair_shift_px + cell.nudge_px


def _resolve_pair_shift_conflicts(
    cells: list[VowelChartCell],
) -> list[VowelChartCell]:
    """Set ``cell.pair_shift_px`` to a per-cell value where the
    canonical ``VOWEL_PAIR_SHIFT_PX`` would not keep two paired
    cells tangent.

    Same-chart_x + opposite pair_side pairs are placed at
    ``cx*dw ± pair_shift_px``. They overlap iff the sum of their
    half-widths exceeds ``2 * pair_shift_px``. The canonical
    shift (17.5 px) is sized for single buttons; two long_pair
    cells (68 px each) overshoot by ~33 px. Elevating
    ``pair_shift_px`` on both members to
    ``(half_a + half_b + gap) / 2`` makes them tangent.
    """
    canonical = float(VOWEL_PAIR_SHIFT_PX)
    rows: dict[int, list[int]] = {}
    for idx, c in enumerate(cells):
        rows.setdefault(c.row, []).append(idx)
    updated: dict[int, float] = {}
    for row_indices in rows.values():
        groups: dict[int, list[int]] = {}
        for idx in row_indices:
            key = _anchor_group_key(cells[idx].chart_x)
            groups.setdefault(key, []).append(idx)
        for grouped in groups.values():
            if len(grouped) < 2:
                continue
            # Only adjacent opposite-side cells need elevation;
            # iterate all pairs in the group.
            for i_idx, ai in enumerate(grouped):
                for bi in grouped[i_idx + 1 :]:
                    a, b = cells[ai], cells[bi]
                    if a.pair_side * b.pair_side >= 0:
                        continue
                    half_a = _cell_width_px(a) / 2.0
                    half_b = _cell_width_px(b) / 2.0
                    needed = (half_a + half_b + _INTER_CELL_GAP_PX) / 2.0
                    if needed <= canonical:
                        continue
                    for k in (ai, bi):
                        cur = updated.get(k, 0.0)
                        if needed > cur:
                            updated[k] = needed
    if not updated:
        return cells
    return [
        replace(c, pair_shift_px=updated[idx]) if idx in updated else c
        for idx, c in enumerate(cells)
    ]


def vertical_depth(kind: VowelCellDisplayKind, n_entries: int) -> int:
    """Vertical row count a cell of ``kind`` with ``n_entries``
    contributes. PAIR kinds are 1 row; CONTRAST_SET is
    ``ceil(entries / 2)``; STACK is ``len(entries)``. The single
    definition shared by the height sizing, the confinement box
    math, and the pipeline's row-depth pre-pass, so the three can
    never disagree on how tall a cell renders.
    """
    if kind in PAIR_DISPLAY_KINDS:
        return 1
    if kind == VowelCellDisplayKind.CONTRAST_SET:
        return (n_entries + 1) // 2
    return n_entries


def _cell_vertical_depth(cell: VowelChartCell) -> int:
    """:py:func:`vertical_depth` for an already-built cell."""
    return vertical_depth(cell.display_kind, len(cell.entries))


def content_height_px(kind: VowelCellDisplayKind, n_entries: int) -> int:
    """Rendered pixel height of a cell's button block: ``depth``
    button rows at the density-tier height with the stack gap
    between them.

    NOT monotonic in entry count: a 10-entry stack renders SHORTER
    than a 9-entry one because the ultra tier drops the per-button
    height from 22 to 18 px. Per-row maxima must therefore compare
    heights via this function, never raw depths; comparing depths
    lets the 9-deep cell overflow a slot sized for the 10-deep one.
    """
    depth = vertical_depth(kind, n_entries)
    eff_h = effective_button_height_px(depth)
    return depth * eff_h + (depth - 1) * _VOWEL_CELL_STACK_GAP_PX


def _cell_height_px(cell: VowelChartCell) -> int:
    """:py:func:`content_height_px` for an already-built cell. The
    vertical mate of :py:func:`_cell_width_px`: the one height
    formula the box rect, the natural sizing, and the pipeline's
    row weighting share."""
    return content_height_px(cell.display_kind, len(cell.entries))


def _cell_box_px(
    cell: VowelChartCell, tier: str, dw: int, dh: int
) -> tuple[float, float, float, float]:
    """The cell's rendered button box ``(left, top, right, bottom)``
    in data-area pixels at the given rendered size.

    Mirrors BOTH renderers' placement math (desktop
    ``_layout_children``; web ``--pair-side`` / ``data-row-tier``
    CSS): centre at ``chart_x * dw`` plus the signed pair shift,
    width from the horizontal button count, height from the stack
    depth at the density-tier button height, and the row-tier
    vertical anchoring (top rows hang DOWN from chart_y, bottom
    rows rise UP, middle / only centre). The confinement pass and
    the containment tests use this one definition, so "inside the
    outline" is judged against the same boxes the renderers draw.
    """
    ww = _cell_width_px(cell)
    wh = _cell_height_px(cell)
    left = cell.chart_x * dw - ww / 2.0 + _cell_pair_offset_px(cell)
    cy = cell.chart_y * dh
    if tier == "top":
        top = cy
    elif tier == "bottom":
        top = cy - wh
    else:
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
            slot = _COL_TO_SLOT[c.col]
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
                    needed_px = ha + hb + oa - ob + _INTER_CELL_GAP_PX
                elif xb < xa:
                    chart_x_diff = xa - xb
                    needed_px = ha + hb + ob - oa + _INTER_CELL_GAP_PX
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
