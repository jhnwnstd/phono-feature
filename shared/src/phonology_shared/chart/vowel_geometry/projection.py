"""Anchor -> data-x projection under a converged-bottom slant (layer 4c).

Maps abstract backness anchors into the silhouette at a given display
y. SILHOUETTE-DRIVEN: for every anchor, projection is a linear
interpolation between two silhouette-defined endpoints:

* At ``top_y``: the FRONT and BACK columns sit at
  ``front_anchor_at_top`` and ``back_anchor`` respectively. An
  anchor's chart_x = interp between them at the anchor's relative
  position in ``[front, back]`` space.
* At ``bottom_y``: the FRONT column sits at
  ``front_anchor_at_bottom`` and the BACK column sits at
  :py:func:`~silhouette.back_col_at_bottom`. Same interp.
* Between top_y and bottom_y: linear in y.

INFORMATIONAL CONSEQUENCE for lone-central-low inventories (Spanish,
Japanese, Korean, ... -- 82.5% of PHOIBLE per the survey in
``web/scripts/phoible_cache/``): the aggressive shrink solver drives
``bottom_width`` low, so ``front_anchor_at_bottom`` moves rightward
toward the apex. The FRONT column guide slants strongly rightward
(large delta) and the CENTRAL column guide slants mildly rightward
(smaller delta) toward the same silhouette. The two guides
CONVERGE at bottom (visual distance decreases) without meeting at a
single point, encoding that the front-central distinction is deforming
but the columns still occupy distinguishable regions. Only when a
back-low vowel would witness a genuine front-central-back low
contrast (rare in PHOIBLE) does the classic trapezoid layout render.

THE PARALLELISM INVARIANT: because the projection reads the SAME
column-at-y positions the silhouette left / right edges are built
from (edges = columns +/- ``extent_norm``), an anchor's projection
is offset from its silhouette edge by a per-y constant extent.
Interior column lines therefore run parallel to exterior silhouette
edges on both sides.

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
    """Silhouette-driven projection of an abstract backness anchor;
    piecewise-linear at bottom_y for a lone-central-low silhouette.

    See the module docstring for the geometry + information-theoretic
    rationale. Linear-in-y between the two endpoints; parallelism to
    the outer silhouette edges holds by construction on both sides.
    """
    at_top = silhouette.front_anchor_at_top + (
        (anchor_x - _FRONT_ANCHOR) / _ANCHOR_SPAN
    ) * (silhouette.back_anchor - silhouette.front_anchor_at_top)

    front_bot = silhouette.front_anchor_at_bottom
    back_bot = back_col_at_bottom(silhouette)
    r = (anchor_x - _FRONT_ANCHOR) / _ANCHOR_SPAN
    at_bot = front_bot + r * (back_bot - front_bot)

    if silhouette.bottom_y == silhouette.top_y:
        return at_top
    t = (y - silhouette.top_y) / (silhouette.bottom_y - silhouette.top_y)
    return at_top * (1.0 - t) + at_bot * t
