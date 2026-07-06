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
    centre directly on ``chart_y`` -- no per-row content-height offset
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
            content_height_px=row_plan.weight[ri],
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
