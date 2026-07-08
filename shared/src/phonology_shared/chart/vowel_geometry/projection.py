"""Anchor -> data-x projection under a converged-bottom slant (layer 4c).

Maps abstract backness anchors into the silhouette at a given display
y. SILHOUETTE-DRIVEN: for every anchor, projection is a linear
interpolation between two silhouette-defined endpoints:

* At ``top_y``: the FRONT and BACK columns sit at
  ``front_anchor_at_top`` and ``back_anchor`` respectively. An
  anchor's chart_x = interp between them at anchor's relative
  position in ``[front, back]`` space.
* At ``bottom_y``: the FRONT column sits at
  ``front_anchor_at_bottom`` and the BACK column sits at
  :py:func:`~silhouette.back_col_at_bottom`
  (``_BACK_APEX_PULL``-pulled + ``bottom_width``-scaled for converged,
  else ``back_anchor``). Same interp.
* Between: linear in y.

THE PARALLELISM INVARIANT: because the projection reads the same
column-at-y positions the silhouette left / right edges are built
from (edges = columns +/- ``extent_norm``), an anchor's projection
is offset from its silhouette edge by a per-y constant extent.
Interior column guide lines therefore run parallel to exterior
silhouette edges at every y, converged bottom included.

This unifies two things the pipeline used to disagree about: the
projection's "where does back land at bottom" (used to fully
converge to apex) and the silhouette's "where does back land at
bottom" (only pulled ``_BACK_APEX_PULL``). Now they read the same
value, so cells at the back column sit FLUSH with the silhouette
right edge instead of drifting inside it by ~25% of chart width on
converged inventories. The regression guard lives in
``shared/tests/test_vowel_space_parallelism.py``.

Cell-blind: consumes only the silhouette + an abstract anchor + y;
the slot assigner has already picked each cell's canonical anchor
before we ever get here.
"""

from __future__ import annotations

from phonology_shared.chart.vowel_geometry.model import VowelChartSilhouette
from phonology_shared.chart.vowel_geometry.silhouette import (
    back_col_at_bottom,
)
from phonology_shared.chart.vowel_space import _BACKNESS_X


def width_at_y(silhouette: VowelChartSilhouette, y: float) -> float:
    """Linear interp between the silhouette's top and bottom widths
    at display y. Kept for the column-header emitter and legacy
    consumers; the projection itself no longer reads this (it
    interpolates silhouette-driven endpoints instead).
    """
    if silhouette.bottom_y == silhouette.top_y:
        return silhouette.top_width
    t = (y - silhouette.top_y) / (silhouette.bottom_y - silhouette.top_y)
    return silhouette.top_width * (1.0 - t) + silhouette.bottom_width * t


_FRONT_ANCHOR: float = _BACKNESS_X["front"]
_BACK_ANCHOR: float = _BACKNESS_X["back"]
_ANCHOR_SPAN: float = _BACK_ANCHOR - _FRONT_ANCHOR


def project_anchor_x(
    silhouette: VowelChartSilhouette, anchor_x: float, y: float
) -> float:
    """Silhouette-driven projection of an abstract backness anchor.

    The anchor's position in the phonological ``[front, back]`` span
    (as ``ratio = (anchor - front) / (back - front)``) is the SAME
    ratio it lands at within the silhouette's ``[front_column,
    back_column]`` span at each of ``top_y`` and ``bottom_y``. Then
    linear in y between the two endpoints. So the interior column
    lines and the exterior silhouette edges share the same slope on
    both sides -- interior/exterior parallelism holds by construction.
    """
    ratio = (anchor_x - _FRONT_ANCHOR) / _ANCHOR_SPAN
    at_top = silhouette.front_anchor_at_top + ratio * (
        silhouette.back_anchor - silhouette.front_anchor_at_top
    )
    at_bot = silhouette.front_anchor_at_bottom + ratio * (
        back_col_at_bottom(silhouette) - silhouette.front_anchor_at_bottom
    )
    if silhouette.bottom_y == silhouette.top_y:
        return at_top
    t = (y - silhouette.top_y) / (silhouette.bottom_y - silhouette.top_y)
    return at_top * (1.0 - t) + at_bot * t
