"""External labels and chart chrome (layer 5: furniture).

Row labels, column headers, height-tier bands, and the diphthong
overlay. Everything here is INFORMED BY the chart's structure (which
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
    effective_anchor_x,
)
from phonology_shared.chart.vowel_geometry.model import (
    VowelChartBand,
    VowelChartColHeader,
    VowelChartDiphthong,
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
    _HEIGHT_Y,
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
        )
        for label, anchor_key in zip(COL_LABELS, _BACKNESS_SLOT_ORDER)
    )


def label_midpoint_norm(
    chart_y: float, tier: str, data_height_px: float
) -> float:
    """The normalised y a row label centres on.

    Middle / only rows centre on the row's ``chart_y``. Top and
    bottom rows anchor their cells' EDGE on ``chart_y`` and grow
    inward, so a label drawn at ``chart_y`` lines up with the
    stack's edge, not its first button row; shifting it inward by
    half a button height re-centres it on the anchor button row.
    ``data_height_px`` is the data area's pixel height the shift is
    taken against, so the shift is exactly ``SEG_BTN_H / 2`` rendered
    pixels.

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
    half_btn_norm = (SEG_BTN_H / 2.0) / data_height_px
    if tier == "top":
        return chart_y + half_btn_norm
    if tier == "bottom":
        return chart_y - half_btn_norm
    return chart_y


def _label_y_for(row: int, row_plan: RowPlan, natural_h: int) -> float:
    """:py:func:`label_midpoint_norm` for a planned row at natural
    size; bakes :py:attr:`VowelChartRow.label_y`. The silhouette edge
    fields are evaluated at this same y, so a label's gap to the
    outline stays constant regardless of where the row's buttons
    land inside it (label placement is divorced from cell position).
    """
    return label_midpoint_norm(
        row_plan.display_y[row], row_plan.tier[row], natural_h
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
            silhouette_left=silhouette_left_at_y(
                silhouette, label_y_by_row[ri]
            ),
            silhouette_right=silhouette_right_at_y(
                silhouette, label_y_by_row[ri]
            ),
        )
        for ri in row_plan.rows
    )


def build_diphthong_overlay(
    placements: Mapping[str, VowelPlacement],
    row_plan: RowPlan,
    silhouette: VowelChartSilhouette,
    open_front_populated: bool,
) -> tuple[VowelChartDiphthong, ...]:
    """Diphthong rendering hints: one entry per placement whose
    ``secondary`` is non-null, with both endpoints projected through
    the same silhouette + row-distribution math the populated cells
    use, so an arrow whose secondary lands on an unpopulated slot
    still gets a valid endpoint. Order is stable across builds
    (insertion order of ``placements``) so diff-driven tests stay
    reproducible.
    """

    def _project(ri: int, ci: int) -> tuple[float, float]:
        # Rows outside the populated set fall back to the canonical
        # row y from ``_HEIGHT_Y`` so a glide targeting an empty
        # tier still points at a sensible vertical position; the
        # silhouette may not visually extend there, but the arrow
        # geometry stays defined. Bounds are guaranteed at the
        # source: every placement row and col, secondaries
        # included, comes through ``_vowel_grid_pos_normalized``,
        # whose post-conditions pin ``0 <= row < len(ROW_LABELS)``
        # and ``0 <= col < 9``, and the snap pass only retargets to
        # occupied cells in that same range.
        if ri in row_plan.display_y:
            cy = row_plan.display_y[ri]
        else:
            cy = _HEIGHT_Y[ROW_LABELS[ri]]
        anchor_x = effective_anchor_x(ri, ci, open_front_populated)
        return project_anchor_x(silhouette, anchor_x, cy), cy

    out: list[VowelChartDiphthong] = []
    for seg, placement in placements.items():
        if placement.secondary is None:
            continue
        primary_x, primary_y = _project(placement.row, placement.col)
        secondary_x, secondary_y = _project(
            placement.secondary.row, placement.secondary.col
        )
        out.append(
            VowelChartDiphthong(
                segment=seg,
                primary_row=placement.row,
                primary_col=placement.col,
                secondary_row=placement.secondary.row,
                secondary_col=placement.secondary.col,
                primary_chart_x=primary_x,
                primary_chart_y=primary_y,
                secondary_chart_x=secondary_x,
                secondary_chart_y=secondary_y,
            )
        )
    return tuple(out)


def build_bands(
    rows: tuple[VowelChartRow, ...],
    silhouette: VowelChartSilhouette,
) -> tuple[VowelChartBand, ...]:
    """Height-tier bands: one stripe per populated row, clamped to
    the silhouette's vertical span, with ``tinted`` alternating so
    the every-other-row rhythm is decided once here rather than
    recomputed by each renderer.
    """
    row_ys = tuple(r.chart_y for r in rows)
    out: list[VowelChartBand] = []
    n_rows = len(row_ys)
    for i, y in enumerate(row_ys):
        above = (row_ys[i - 1] + y) / 2 if i > 0 else silhouette.top_y
        below = (
            (y + row_ys[i + 1]) / 2 if i < n_rows - 1 else silhouette.bottom_y
        )
        out.append(
            VowelChartBand(
                top_norm=above, bottom_norm=below, tinted=i % 2 == 0
            )
        )
    return tuple(out)
