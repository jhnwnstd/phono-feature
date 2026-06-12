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
#: The geometry reads these so the chart asks for the rendered
#: pixel height instead of the canonical-button-size theoretical
#: max; before that, PHOIBLE inventories like !XU/UPSID (12-stack)
#: requested 931 px while the CSS-rendered chart only needed
#: ~250 px, forcing the panel-body to scroll unnecessarily.
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
    ``"ultra"`` and applies the calculated heights via
    ``calc(var(--seg-btn-h) - 4px)`` / ``- 8px``. Desktop calls this
    helper directly to set ``setFixedHeight`` on each stacked
    button. Without parity here, a 7-deep stack renders 28 px
    taller on desktop than web (canonical 26 px vs dense 22 px),
    causing the chart layout to look "totally different" even
    though both renderers consume the same shared geometry.
    """
    if stack_depth >= DENSITY_TIER_ULTRA_THRESHOLD:
        return DENSITY_TIER_ULTRA_BTN_H
    if stack_depth >= DENSITY_TIER_DENSE_THRESHOLD:
        return DENSITY_TIER_DENSE_BTN_H
    return SEG_BTN_H


# Backward-compat alias for the previous private name. Internal
# call-sites below still use this; external imports should use the
# public ``effective_button_height_px``.
_effective_button_height_px = effective_button_height_px


#: Vertical breathing room between adjacent populated rows. Picked
#: to read as a row break without overweighting the chart's chrome.
_VOWEL_ROW_GAP_PX: int = 6

#: Vertical padding (top + bottom combined) around the row content
#: so the silhouette's top edge can cut through the Close row's
#: button centres without clipping their tops.
_VOWEL_DATA_AREA_VERTICAL_PADDING_PX: int = SEG_BTN_H


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
    inter_cell_gap_px = 2.0
    rows: dict[int, list[int]] = {}
    for idx, c in enumerate(cells):
        rows.setdefault(c.row, []).append(idx)
    updated: dict[int, float] = {}
    for row_indices in rows.values():
        # Group cells by chart_x within tiny epsilon.
        groups: dict[int, list[int]] = {}
        for idx in row_indices:
            key = round(cells[idx].chart_x * 1000)
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
                    half_a = (
                        _cell_horizontal_button_count(a) * BTN_W
                        + max(0, _cell_horizontal_button_count(a) - 1)
                        * VOWEL_PAIR_GAP_PX
                    ) / 2.0
                    half_b = (
                        _cell_horizontal_button_count(b) * BTN_W
                        + max(0, _cell_horizontal_button_count(b) - 1)
                        * VOWEL_PAIR_GAP_PX
                    ) / 2.0
                    needed = (half_a + half_b + inter_cell_gap_px) / 2.0
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
    definition the height sizing, the confinement box math, and the
    pipeline's row-depth pre-pass all share; it used to exist twice
    (here and inline in the orchestrator) and could drift.
    """
    if kind in PAIR_DISPLAY_KINDS:
        return 1
    if kind == VowelCellDisplayKind.CONTRAST_SET:
        return (n_entries + 1) // 2
    return n_entries


def _cell_vertical_depth(cell: VowelChartCell) -> int:
    """:py:func:`vertical_depth` for an already-built cell."""
    return vertical_depth(cell.display_kind, len(cell.entries))


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
    n_h = _cell_horizontal_button_count(cell)
    ww = n_h * BTN_W + (n_h - 1) * VOWEL_PAIR_GAP_PX
    depth = _cell_vertical_depth(cell)
    eff_h = _effective_button_height_px(depth)
    wh = depth * eff_h + (depth - 1) * _VOWEL_CELL_STACK_GAP_PX
    left = (
        cell.chart_x * dw
        - ww / 2.0
        + cell.pair_side * cell.pair_shift_px
        + cell.nudge_px
    )
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

    rows_in_use: set[int] = {c.row for c in cells}
    max_row_w = 2 * BTN_W + VOWEL_PAIR_GAP_PX
    # Pair-side shift gap: cells with pair_side != 0 sit offset
    # from their canonical chart_x by their ``pair_shift_px``. The
    # rightmost cell's actual pixel extent therefore reaches
    # ``chart_x * dw + pair_shift + cell_w/2``, which is what the
    # data-area width must accommodate.
    for ri in rows_in_use:
        # Slot button-count summation (the legacy bound). Kept as
        # a floor so single-slot rows still have minimum sensible
        # width.
        slot_buttons: dict[int, int] = {0: 0, 1: 0, 2: 0}
        for c in cells:
            if c.row != ri:
                continue
            slot = _COL_TO_SLOT[c.col]
            slot_buttons[slot] += _cell_horizontal_button_count(c)
        populated_slots = [s for s, n in slot_buttons.items() if n > 0]
        if not populated_slots:
            continue
        slot_widths = [
            slot_buttons[s] * BTN_W
            + max(0, slot_buttons[s] - 1) * VOWEL_PAIR_GAP_PX
            for s in populated_slots
        ]
        row_w = sum(slot_widths) + (len(populated_slots) - 1) * (
            VOWEL_PAIR_SEPARATOR_PX
        )
        max_row_w = max(max_row_w, row_w)
        # Slot-sum alone underestimates when chart_x positions
        # push a cell past either edge of [0, dw]; solve for the
        # ``dw`` that keeps every cell's projected extent inside.
        row_cells = [c for c in cells if c.row == ri]
        cell_geom: list[tuple[float, float, float]] = (
            []
        )  # (chart_x, pair_off, half_w)
        for c in row_cells:
            cell_half_w = (
                _cell_horizontal_button_count(c) * BTN_W
                + max(0, _cell_horizontal_button_count(c) - 1)
                * VOWEL_PAIR_GAP_PX
            ) / 2.0
            pair_offset = c.pair_shift_px * c.pair_side + c.nudge_px
            cell_geom.append((c.chart_x, pair_offset, cell_half_w))
            if c.chart_x < 1.0:
                right_extent = pair_offset + cell_half_w
                if right_extent > 0:
                    needed = right_extent / (1.0 - c.chart_x)
                    max_row_w = max(max_row_w, int(math.ceil(needed)))
            if c.chart_x > 0.0:
                left_extent = cell_half_w - pair_offset
                if left_extent > 0:
                    needed = left_extent / c.chart_x
                    max_row_w = max(max_row_w, int(math.ceil(needed)))
        # Inter-cell non-overlap: every pair of cells in this row
        # must fit without their pixel boxes intersecting. Bound:
        #   (xb - xa) * dw + (off_b - off_a) >= half_a + half_b + gap
        # When ``xa < xb`` (different anchors) solve for ``dw``.
        # When ``xa == xb`` the constraint becomes
        # ``off_b - off_a >= half_a + half_b + gap`` and is dw-
        # independent; we cannot fix it by widening the chart.
        # Two cells at the same anchor with opposite pair_side
        # and both wider than a single button (typical PHOIBLE
        # pair-display at the back-rounded column) trigger this
        # static overlap; the renderer accepts it for now.
        inter_cell_gap_px = 2.0
        for i in range(len(cell_geom)):
            xa, oa, ha = cell_geom[i]
            for j in range(i + 1, len(cell_geom)):
                xb, ob, hb = cell_geom[j]
                if xa < xb:
                    chart_x_diff = xb - xa
                    needed_px = ha + hb + oa - ob + inter_cell_gap_px
                elif xb < xa:
                    chart_x_diff = xa - xb
                    needed_px = ha + hb + ob - oa + inter_cell_gap_px
                else:
                    continue
                if needed_px > 0:
                    needed_dw = needed_px / chart_x_diff
                    max_row_w = max(max_row_w, int(math.ceil(needed_dw)))

    # Height: per-row max stack depth, plus inter-row gaps and
    # vertical padding for the silhouette's top/bottom offset.
    # Density-tier-aware: when the deepest cell in a row crosses
    # the dense / ultra threshold, its rendered per-button height
    # shrinks (matching the CSS rules). The natural-height request
    # tracks the actual rendered height so the chart asks for what
    # the renderer will draw, not the canonical-button theoretical
    # max.
    row_heights: list[int] = []
    for ri in sorted(rows_in_use):
        depth = 1
        for c in cells:
            if c.row != ri:
                continue
            cell_depth = _cell_vertical_depth(c)
            if cell_depth > depth:
                depth = cell_depth
        per_btn_h = _effective_button_height_px(depth)
        row_heights.append(
            depth * per_btn_h + max(0, depth - 1) * _VOWEL_CELL_STACK_GAP_PX
        )

    total_h = sum(row_heights) + (len(row_heights) - 1) * _VOWEL_ROW_GAP_PX
    total_h += _VOWEL_DATA_AREA_VERTICAL_PADDING_PX
    return max_row_w, total_h
