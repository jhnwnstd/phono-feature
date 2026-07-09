"""External labels and chart chrome (layer 5: furniture).

Row labels, column headers, and the diphthong chip list. Everything
here is INFORMED BY the chart's structure (which
rows exist, where their anchors sit, what the outline looks like)
but never DEPENDS ON button positions: labels anchor to the outline
at their own y and headers project pure backness anchors. That
one-way relationship is the fix for the labels-follow-the-buttons
class of bug; it is enforced
by ``shared/tests/test_vowel_geometry_boundaries.py``
(``VowelChartCell`` is a forbidden name in this module).
"""

from __future__ import annotations

from collections.abc import Mapping

from phonology_shared.chart.vowel_space_geometry.column_scheme import (
    backness_slot_order as _BACKNESS_SLOT_ORDER,
)
from phonology_shared.chart.vowel_space_geometry.model import (
    VowelChartColHeader,
    VowelChartRow,
    VowelChartSilhouette,
)
from phonology_shared.chart.vowel_space_geometry.projection import project_anchor_x
from phonology_shared.chart.vowel_space_geometry.rows import RowPlan
from phonology_shared.chart.vowel_space_geometry.silhouette import (
    silhouette_left_at_y,
)
from phonology_shared.chart.vowel_space import (
    _BACKNESS_X,
    COL_LABELS,
    ROW_LABELS,
)
from phonology_shared.chart.vowels import VowelPlacement


def build_col_headers(
    silhouette: VowelChartSilhouette,
) -> tuple[VowelChartColHeader, ...]:
    """Column headers sit at the silhouette's top edge (label centres
    on ``chart_x``); the column GUIDE line runs between the pair of
    anchor positions extrapolated past the silhouette's top and
    bottom edges (``guide_x_at_y0`` and ``guide_x_at_y1``).
    ``COL_LABELS`` and ``_BACKNESS_SLOT_ORDER`` are index-aligned
    (front, central, back).
    """
    span = (silhouette.bottom_y - silhouette.top_y) or 1.0
    headers: list[VowelChartColHeader] = []
    for label, anchor_key in zip(COL_LABELS, _BACKNESS_SLOT_ORDER):
        anchor = _BACKNESS_X[anchor_key]
        chart_x = project_anchor_x(silhouette, anchor, silhouette.top_y)
        chart_x_bottom = project_anchor_x(
            silhouette, anchor, silhouette.bottom_y
        )
        # Extrapolate the (top_y, bottom_y) segment to y=0 and y=1 so
        # a downstream renderer just draws between these endpoints;
        # the clip inside the trapezoid trims the ends.
        slope = (chart_x_bottom - chart_x) / span
        headers.append(
            VowelChartColHeader(
                label=label,
                chart_x=chart_x,
                chart_x_bottom=chart_x_bottom,
                guide_x_at_y0=chart_x - slope * silhouette.top_y,
                guide_x_at_y1=chart_x_bottom + slope * (1.0 - silhouette.bottom_y),
            )
        )
    return tuple(headers)


def build_rows(
    row_plan: RowPlan,
    silhouette: VowelChartSilhouette,
    natural_h: int,
) -> tuple[VowelChartRow, ...]:
    """The rows tuple, with per-row label anchors baked against the
    FINAL silhouette. Must run after outline growth, sizing, and
    confinement so the baked edge fields match what the renderers draw.

    ``chart_y`` is now the cell CENTRE for every row (the pipeline's
    ``_finalize_row_plan`` pulled the extreme rows' centres inward so
    their edges hug the silhouette top / bottom). Labels therefore
    centre directly on ``chart_y``; no per-row content-height offset
    is needed, so ``label_y == chart_y`` is baked as an alias for wire
    compatibility while the JS bridge switches over.
    """
    del natural_h  # unused after label offset dropped; kept in signature for callers
    return tuple(
        VowelChartRow(
            logical_row=ri,
            label=ROW_LABELS[ri],
            chart_y=row_plan.display_y[ri],
            slot_height_norm=row_plan.slot_height[ri],
            label_y=row_plan.display_y[ri],
            silhouette_left=silhouette_left_at_y(
                silhouette, row_plan.display_y[ri]
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
