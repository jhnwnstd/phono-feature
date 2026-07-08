"""Vertical row-plan distribution (layer 4d).

Distributes populated rows across the silhouette's vertical span
proportional to per-row rendered content height. Deep stacks (Korean
PHOIBLE has 7 entries at Close-Back) get enough vertical room before
the next row starts; distributed evenly instead, they overrun their
neighbours' cells.

Cell-blind: consumes rows as opaque indices, weights as an abstract
per-row pixel-height mapping (the pipeline computes those via
``cell_boxes.content_height_px``, which is density-tier-aware). No
cell object crosses the layer boundary.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class RowPlan:
    """Vertical arrangement of the populated rows inside the
    silhouette span. ``display_y`` is the CELL CENTRE y in the
    silhouette's [0, 1] space for every row: renderers uniformly
    centre-anchor their cell boxes on it (no per-row tier). The
    pipeline's ``_finalize_row_plan`` may nudge the topmost /
    bottommost rows' centres inward after ``sized.natural_h`` is
    known, so cell edges hug the silhouette top / bottom instead
    of drifting inward as the aspect cap grows the slots. ``weight``
    is the row's rendered content height in pixels (the quantity
    the slot heights are proportional to)."""

    rows: tuple[int, ...]
    display_y: Mapping[int, float]
    slot_height: Mapping[int, float]
    weight: Mapping[int, int]


def distribute_rows(
    populated_rows: tuple[int, ...],
    weights: Mapping[int, int],
    top_y: float,
    bottom_y: float,
) -> RowPlan:
    """Distribute row anchors in the silhouette's vertical span
    PROPORTIONAL TO PER-ROW RENDERED CONTENT HEIGHT so a row with a
    tall stack (Korean PHOIBLE has 7 entries at Close-Back) gets
    enough vertical room before the next row starts; distributed
    evenly instead, a deep stack at the Close row overruns the rows
    below it and visually invades their cells.

    ``weights`` must be the rows' content heights in PIXELS (the
    pipeline computes them via ``cell_boxes.content_height_px``),
    not raw button counts: per-button height is density-tier
    dependent (26 / 22 / 18 px), so a 12-button ultra stack costs
    less per button than a 2-button canonical stack and raw counts
    over-allocate the deep row while starving its shallow
    neighbours into overlap. This module stays cell-blind: the
    weights arrive as abstract numbers.

    Each row gets a slot whose height is ``weight / total_weight`` of
    the span (so a deep stack claims proportionally more room and no
    two rows' content can overlap). ``display_y[ri]`` is the CENTRE
    of that slot: uniform for every row so renderers can uniformly
    centre-anchor their cell boxes (``top = cy - wh / 2``). The
    pipeline's ``_finalize_row_plan`` runs after ``sized.natural_h``
    is known and pulls the extreme rows' centres inward so their
    cell edges hug ``top_y`` / ``bottom_y`` instead of drifting into
    aspect-cap slack. Single-row plans just centre on the span.

    Preconditions the pipeline guarantees: ``populated_rows`` is
    non-empty (the empty inventory short-circuits before any row
    math) and every row's weight is at least one button height, so
    ``total_weight`` is never zero.
    """
    if len(populated_rows) == 1:
        only = populated_rows[0]
        return RowPlan(
            rows=populated_rows,
            display_y={only: (top_y + bottom_y) / 2},
            slot_height={only: bottom_y - top_y},
            weight=dict(weights),
        )
    span = bottom_y - top_y
    total_weight = sum(weights[ri] for ri in populated_rows)
    display_y: dict[int, float] = {}
    slot_height: dict[int, float] = {}
    cursor = top_y
    for ri in populated_rows:
        height = weights[ri] / total_weight * span
        slot_height[ri] = height
        display_y[ri] = cursor + height / 2
        cursor += height
    return RowPlan(
        rows=populated_rows,
        display_y=display_y,
        slot_height=slot_height,
        weight=dict(weights),
    )
