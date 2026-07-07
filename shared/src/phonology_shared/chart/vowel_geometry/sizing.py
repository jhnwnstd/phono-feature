"""Chart-level natural size and size-floor policies (layer 4e).

Given a set of positioned cells and a row plan, compute the chart's
preferred data-area size in pixels: the width that fits every row's
button + gap requirements without overlap, and the height that fits
every row's rendered content stack. Then apply two floors:

* **Aspect ceiling** (``VOWEL_SILHOUETTE_MAX_ASPECT``): sparse
  inventories (5-vowel Spanish) get an aspect cap so they don't
  render 2-3x as wide as the canonical 10:7 silhouette. Growing
  ``natural_h`` pulls the aspect back down; dense inventories at or
  below the ceiling are unaffected.
* **Row-fit floor** (per-row content height + inter-row gaps):
  guarantees every row's proportional slot covers its rendered
  content at natural size.

Both floors only ever grow ``natural_h``, so applying them in
sequence satisfies both.

Cell-blind ONLY at the sizing solver's own edges: it reads cell
objects to compute widths, but every cell-level arithmetic (widths,
heights, box rects) delegates to :py:mod:`.cell_boxes`. The
silhouette is untouched here; the pipeline calls this after the
outline is sized and combines the results.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from phonology_shared.chart.vowel_geometry.cell_boxes import (
    _VOWEL_DATA_AREA_VERTICAL_PADDING_PX,
    _VOWEL_ROW_GAP_PX,
    _INTER_ANCHOR_GAP_PX,
    _cell_height_px,
    _cell_horizontal_button_count,
    _cell_pair_offset_px,
    _cell_width_px,
)
from phonology_shared.chart.vowel_geometry.model import (
    VowelChartCell,
    VowelChartSilhouette,
)
from phonology_shared.chart.vowel_geometry.rows import RowPlan
from phonology_shared.chart.vowel_geometry.space import col_to_slot
from phonology_shared.chart.vowel_space import _HEIGHT_Y
from phonology_shared.presentation.chart_style import (
    VOWEL_SILHOUETTE_MAX_ASPECT,
)
from phonology_shared.presentation.constants import BTN_W
from phonology_shared.presentation.layout import (
    SEG_BTN_H,
    VOWEL_PAIR_GAP_PX,
    VOWEL_PAIR_SEPARATOR_PX,
)


@dataclass(frozen=True)
class SizedChart:
    """The silhouette after extent growth, plus the settled natural
    size the confinement pass and the renderers' sizing hints
    consume. Produced by the pipeline's ``_fit_outline_and_size``
    stage and its post-finalize refit."""

    silhouette: VowelChartSilhouette
    natural_w: int
    natural_h: int


def natural_data_area_size(
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


def apply_size_floors(
    natural_w: int, natural_h: int, row_plan: RowPlan
) -> tuple[int, int]:
    """Grow ``natural_h`` to satisfy the aspect ceiling and the
    per-row content-fit floor. Both only ever grow the height, never
    shrink either dimension, so this is safe to call multiple times
    over the pipeline (e.g. once inside ``_fit_outline_and_size`` and
    once after the post-finalize refit).
    """
    sil_y_span = _HEIGHT_Y["Open"] - _HEIGHT_Y["Close"]  # 0.90
    if sil_y_span <= 0:
        return natural_w, natural_h
    current_sil_h = sil_y_span * natural_h
    if current_sil_h > 0:
        aspect = natural_w / current_sil_h
        if aspect > VOWEL_SILHOUETTE_MAX_ASPECT:
            needed_sil_h = natural_w / VOWEL_SILHOUETTE_MAX_ASPECT
            natural_h = int(math.ceil(needed_sil_h / sil_y_span))
    rows_px = sum(row_plan.weight[ri] for ri in row_plan.rows)
    gaps_px = (len(row_plan.rows) - 1) * _VOWEL_ROW_GAP_PX
    row_fit_h = int(math.ceil((rows_px + gaps_px) / sil_y_span))
    natural_h = max(natural_h, row_fit_h)
    return natural_w, natural_h
