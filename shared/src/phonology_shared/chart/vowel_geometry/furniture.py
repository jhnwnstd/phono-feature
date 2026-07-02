"""External labels and chart chrome (layer 5: furniture).

Row labels, column headers, and the diphthong overlay. Everything
here is INFORMED BY the chart's structure (which
rows exist, where their anchors sit, what the outline looks like)
but never DEPENDS ON button positions: labels anchor to the outline
at their own y, headers project pure backness anchors, and arrow
endpoints project logical slots. That one-way relationship is the
fix for the labels-follow-the-buttons class of bug; it is enforced
by ``shared/tests/test_vowel_geometry_boundaries.py``
(``VowelChartCell`` is a forbidden name in this module).
"""

from __future__ import annotations

from collections.abc import Mapping

from phonology_shared.chart.vowel_geometry.display_slots import (
    _BACKNESS_SLOT_ORDER,
)
from phonology_shared.chart.vowel_geometry.model import (
    VowelChartColHeader,
    VowelChartRow,
    VowelChartSilhouette,
)
from phonology_shared.chart.vowel_geometry.outline import (
    RowPlan,
    project_anchor_x,
    silhouette_left_at_y,
    silhouette_right_at_y,
)
from phonology_shared.chart.vowel_space import (
    _BACKNESS_X,
    COL_LABELS,
    ROW_LABELS,
)
from phonology_shared.chart.vowels import VowelPlacement
from phonology_shared.presentation.layout import SEG_BTN_H


def build_col_headers(
    silhouette: VowelChartSilhouette,
) -> tuple[VowelChartColHeader, ...]:
    """Column headers sit at the silhouette's top edge so they line
    up with the topmost populated row's cells. Their chart_x is the
    topmost row's projected backness anchor (front migrates inward
    as the silhouette narrows; central shifts toward the back anchor
    too; back stays flush with the vertical right edge).

    ``COL_LABELS`` and ``_BACKNESS_SLOT_ORDER`` are index-aligned
    (front, central, back), so the zip below pairs each header
    label with its anchor key.
    """
    return tuple(
        VowelChartColHeader(
            label=label,
            chart_x=project_anchor_x(
                silhouette,
                _BACKNESS_X[anchor_key],
                silhouette.top_y,
            ),
            # Same anchor at the BOTTOM edge so renderers can draw the
            # column guide as a line that slants with the column (the
            # front/central columns migrate inward as the trapezoid
            # narrows; back is the fixed point, so its two values match
            # and the guide stays vertical).
            chart_x_bottom=project_anchor_x(
                silhouette,
                _BACKNESS_X[anchor_key],
                silhouette.bottom_y,
            ),
        )
        for label, anchor_key in zip(COL_LABELS, _BACKNESS_SLOT_ORDER)
    )


def label_midpoint_norm(
    chart_y: float,
    tier: str,
    data_height_px: float,
    row_content_height_px: float = SEG_BTN_H,
) -> float:
    """The normalised y a row label centres on.

    Middle / only rows centre on the row's ``chart_y``. Top and
    bottom rows anchor their cells' EDGE on ``chart_y`` and grow
    inward, so a label drawn at ``chart_y`` lines up with the row's
    edge, not its vertical centre; shifting it inward by half the
    row's CONTENT height re-centres it on the rendered content.
    ``row_content_height_px`` is that content height (the row's
    tallest cell: one button for a plain / pair row, but TWO
    button-rows for a 2x2 contrast set, or N for a deep stack), so a
    Close / Open row carrying a contrast set or stack centres on the
    whole block instead of just its first button row. Defaults to a
    single button height so a plain row is unchanged.
    ``data_height_px`` is the data area's pixel height the shift is
    taken against, so the shift is exactly
    ``row_content_height_px / 2`` rendered pixels.

    THE SINGLE definition of the close/open label-centring shift,
    used by both renderers so it cannot drift between them: the
    desktop calls it with its live data-area height every layout
    pass; the web consumes the value baked here onto
    :py:attr:`VowelChartRow.label_y` (its data area renders at the
    natural height). Implementing it separately per renderer is what
    left the web's Close / Open labels uncentred.
    """
    if data_height_px <= 0:
        return chart_y
    half_content_norm = (row_content_height_px / 2.0) / data_height_px
    if tier == "top":
        return chart_y + half_content_norm
    if tier == "bottom":
        return chart_y - half_content_norm
    return chart_y


def _label_y_for(row: int, row_plan: RowPlan, natural_h: int) -> float:
    """:py:func:`label_midpoint_norm` for a planned row at natural
    size; bakes :py:attr:`VowelChartRow.label_y`. The silhouette edge
    fields are evaluated at this same y, so a label's gap to the
    outline stays constant regardless of where the row's buttons
    land inside it (label placement is divorced from cell position).

    ``row_plan.weight`` is the row's content height in px (its tallest
    cell), so a Close / Open row holding a 2-row contrast set or a deep
    stack centres its label on the whole block, not just the first row.
    """
    return label_midpoint_norm(
        row_plan.display_y[row],
        row_plan.tier[row],
        natural_h,
        row_plan.weight[row],
    )


def build_rows(
    row_plan: RowPlan,
    silhouette: VowelChartSilhouette,
    natural_h: int,
) -> tuple[VowelChartRow, ...]:
    """The rows tuple, with per-row label anchors baked against the
    FINAL silhouette. Must run after outline growth, sizing, and
    confinement so the baked ``label_y`` and edge fields match what
    the renderers draw.
    """
    label_y_by_row = {
        ri: _label_y_for(ri, row_plan, natural_h) for ri in row_plan.rows
    }
    return tuple(
        VowelChartRow(
            logical_row=ri,
            label=ROW_LABELS[ri],
            chart_y=row_plan.display_y[ri],
            tier=row_plan.tier[ri],
            slot_height_norm=row_plan.slot_height[ri],
            label_y=label_y_by_row[ri],
            content_height_px=row_plan.weight[ri],
            silhouette_left=silhouette_left_at_y(
                silhouette, label_y_by_row[ri]
            ),
            silhouette_right=silhouette_right_at_y(
                silhouette, label_y_by_row[ri]
            ),
        )
        for ri in row_plan.rows
    )


def build_diphthong_segments(
    placements: Mapping[str, VowelPlacement],
) -> tuple[str, ...]:
    """The inventory's diphthong segment names: one per placement
    whose ``secondary`` is non-null (a PHOIBLE contour vowel with
    distinct endpoints; the placer's degeneracy filter has already
    dropped contours that collapse to a single cell). Order is the
    insertion order of ``placements`` so diff-driven tests stay
    reproducible.

    These segments are deliberately NOT placed in the trapezoid; the
    renderers list them as labelled chips below the vowel space.
    """
    return tuple(
        seg
        for seg, placement in placements.items()
        if placement.secondary is not None
    )
