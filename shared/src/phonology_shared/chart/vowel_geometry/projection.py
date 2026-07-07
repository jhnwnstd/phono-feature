"""Anchor -> data-x projection under a converged-bottom slant (layer 4c).

Maps abstract backness anchors into the silhouette at a given display
y. Under the classic trapezoid the back edge is vertical (back is the
fixed point), so back vowels sit flush against a straight right edge
and everything to their left migrates toward it as the row narrows.
Under a converged bottom (a lone-low-vowel inventory triggered
``open_apex_backness``), the projection converges from ``back_anchor``
at ``top_y`` to ``back_anchor_at_bottom`` at ``bottom_y`` so both
edges slant inward and cells at the bottom converge on the sole low
vowel's column.

THE PARALLELISM INVARIANT: the projection is a LINEAR INTERPOLATION
in y between the top-y endpoint (``back_anchor + top_width *
(anchor - back_anchor)``) and the bottom-y endpoint (``apex +
bottom_width * (anchor - apex)`` where apex is
``back_anchor_at_bottom`` when set, else ``back_anchor``). Because
the silhouette left / right / column-guide edges are all straight
lines between corners defined by the SAME two endpoint formulas, an
anchor's projection is offset from its silhouette edge by a per-y
CONSTANT extent. Interior column guide lines therefore run parallel
to exterior silhouette edges at every y, converged bottom included,
and vowels stay flush with the silhouette as the shape reshapes.

An earlier pivot-based formulation (``pivot(y) + width(y) *
(anchor - pivot(y))`` with pivot(y) varying linearly from back to
apex) produced a QUADRATIC-in-y curve under converged bottom, so
middle-row cells drifted a few percent inside the straight silhouette
edge. The parity tests in
``shared/tests/test_vowel_space_parallelism.py`` pin the linear form.

Cell-blind: consumes only the silhouette + an abstract anchor + y;
the slot assigner has already picked each cell's canonical anchor by
this point. Cell-cell distances at any row scale linearly with the
row's ``width_at_y``, so the shrink solver's per-row width demands
keep the same meaning under either regime.
"""

from __future__ import annotations

from phonology_shared.chart.vowel_geometry.model import VowelChartSilhouette


def width_at_y(silhouette: VowelChartSilhouette, y: float) -> float:
    """Linear interp between the silhouette's top and bottom widths
    at display y. Shared by the column-header emitter and (for its
    endpoints only, at ``top_y`` / ``bottom_y``) the projection.
    """
    if silhouette.bottom_y == silhouette.top_y:
        return silhouette.top_width
    t = (y - silhouette.top_y) / (silhouette.bottom_y - silhouette.top_y)
    return silhouette.top_width * (1.0 - t) + silhouette.bottom_width * t


def _project_at_endpoint(
    anchor_x: float, pivot: float, width: float
) -> float:
    """Endpoint projection: ``pivot + width * (anchor - pivot)``.
    Used only at ``top_y`` (pivot = back_anchor, width = top_width)
    and ``bottom_y`` (pivot = back_anchor_at_bottom or back_anchor,
    width = bottom_width). Callers linear-interp between the two."""
    return pivot + width * (anchor_x - pivot)


def project_anchor_x(
    silhouette: VowelChartSilhouette, anchor_x: float, y: float
) -> float:
    """Projection of an abstract backness anchor into the silhouette
    at display y.

    LINEAR-in-y between the two endpoint projections:

    * At ``top_y``: ``back_anchor + top_width * (anchor - back_anchor)``.
      Back-anchored: the back column sits at ``back_anchor``, front
      is pulled toward it by ``top_width``.
    * At ``bottom_y``: ``apex + bottom_width * (anchor - apex)``
      where ``apex = back_anchor_at_bottom`` if set, else
      ``back_anchor``. Under converged bottom the apex is the sole
      populated Open-row column's canonical anchor, so cells at
      bottom converge on that column.
    * Between: ``at_top * (1 - t) + at_bot * t`` for
      ``t = (y - top_y) / (bottom_y - top_y)``.

    Choosing the linear-in-y interpolation over the pivot-based
    ``pivot(y) + width(y) * (anchor - pivot(y))`` formulation matters
    only under a converged bottom (where the two pivots differ):
    linear-in-y makes the projection AGREE with the silhouette
    straight-line edges at every y, so interior columns stay
    parallel to exterior edges.
    """
    top_pivot = silhouette.back_anchor
    bot_pivot = silhouette.back_anchor_at_bottom
    if bot_pivot is None:
        bot_pivot = top_pivot
    at_top = _project_at_endpoint(anchor_x, top_pivot, silhouette.top_width)
    at_bot = _project_at_endpoint(
        anchor_x, bot_pivot, silhouette.bottom_width
    )
    if silhouette.bottom_y == silhouette.top_y:
        return at_top
    t = (y - silhouette.top_y) / (silhouette.bottom_y - silhouette.top_y)
    return at_top * (1.0 - t) + at_bot * t
