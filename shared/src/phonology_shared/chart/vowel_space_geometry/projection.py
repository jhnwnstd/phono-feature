# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Required Notice: Copyright 2026 John Winstead,
# https://github.com/jhnwnstd/phono-feature
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

from phonology_shared.chart.vowel_space import _BACKNESS_X
from phonology_shared.chart.vowel_space_geometry.model import (
    VowelChartSilhouette,
)
from phonology_shared.chart.vowel_space_geometry.silhouette import (
    back_col_at_bottom,
)


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
_CENTRAL_ANCHOR: float = _BACKNESS_X["central"]
_BACK_ANCHOR: float = _BACKNESS_X["back"]
_ANCHOR_SPAN: float = _BACK_ANCHOR - _FRONT_ANCHOR

#: Where the CENTRAL column lands within the ``[front_bot, back_bot]``
#: span at ``bottom_y`` for a lone-central-low silhouette. ``0.5``
#: (smooth midpoint) is the classic-trapezoid default; a smaller value
#: pulls central closer to front, tightening the front-central gap
#: at bottom to reflect the collapsed low front-central distinction.
#: At ``1/3`` the bottom gap is roughly 1/3 of the top gap (was 1/2
#: under the smooth midpoint).
_LONE_CENTRAL_BOTTOM_RATIO: float = 1.0 / 3.0


def project_anchor_x(
    silhouette: VowelChartSilhouette, anchor_x: float, y: float
) -> float:
    """Silhouette-driven projection of an abstract backness anchor.

    Linear-in-y between the top and bottom endpoints; parallelism to
    the outer silhouette edges holds on both sides. At ``top_y`` the
    anchor's ``[front, back]`` ratio maps linearly onto the
    ``[front_anchor_at_top, back_anchor]`` span. At ``bottom_y`` the
    map is the same linear span EXCEPT for lone-central-low
    silhouettes, where a piecewise WARP pulls central closer to front
    at bottom: central's projected ratio drops from ``0.5`` (smooth)
    to :py:data:`_LONE_CENTRAL_BOTTOM_RATIO`, reflecting the collapsed
    low front-central distinction (no back-low vowel to witness it).
    Front and back endpoints stay at the silhouette's own column
    positions, so front-column and back-column parallelism to the
    silhouette left/right edges holds by construction under the warp.
    """
    at_top = silhouette.front_anchor_at_top + (
        (anchor_x - _FRONT_ANCHOR) / _ANCHOR_SPAN
    ) * (silhouette.back_anchor - silhouette.front_anchor_at_top)

    front_bot = silhouette.front_anchor_at_bottom
    back_bot = back_col_at_bottom(silhouette)
    if silhouette.back_anchor_at_bottom == _CENTRAL_ANCHOR:
        # Piecewise warp: central's ratio at bottom is
        # ``_LONE_CENTRAL_BOTTOM_RATIO`` (< 0.5), pulling central
        # closer to front. Linear on each side of central so front
        # and back anchors still map to r=0 and r=1 respectively.
        if anchor_x <= _CENTRAL_ANCHOR:
            r = (
                (anchor_x - _FRONT_ANCHOR)
                / (_CENTRAL_ANCHOR - _FRONT_ANCHOR)
                * _LONE_CENTRAL_BOTTOM_RATIO
            )
        else:
            r = _LONE_CENTRAL_BOTTOM_RATIO + (
                (anchor_x - _CENTRAL_ANCHOR)
                / (_BACK_ANCHOR - _CENTRAL_ANCHOR)
                * (1.0 - _LONE_CENTRAL_BOTTOM_RATIO)
            )
    else:
        r = (anchor_x - _FRONT_ANCHOR) / _ANCHOR_SPAN
    at_bot = front_bot + r * (back_bot - front_bot)

    if silhouette.bottom_y == silhouette.top_y:
        return at_top
    t = (y - silhouette.top_y) / (silhouette.bottom_y - silhouette.top_y)
    return at_top * (1.0 - t) + at_bot * t
