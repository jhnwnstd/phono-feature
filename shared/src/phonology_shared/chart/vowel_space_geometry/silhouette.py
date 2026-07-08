"""The silhouette: the boundary authority (layer 4).

Owns the :py:class:`~model.VowelChartSilhouette` dataclass's geometry:
the canonical and inventory-adapted trapezoid (:py:func:`vowel_silhouette`),
the corner-arithmetic primitive (:py:func:`_silhouette_corners`), the
rounded-corner polygon and the edge-at-y evaluators both renderers
anchor labels to, and the cascade (:py:func:`silhouette_for_data_width`)
that recomputes corners for the actual rendered width so the outline
wraps the outermost cells flush at any size.

THE RULE THAT KEEPS THIS LAYER HONEST: this module knows nothing about
cells. ``VowelChartCell`` is a forbidden name here; relating actual cell
boxes to the silhouette (extent growth, confinement) happens only in the
pipeline. Enforced by
``shared/tests/test_vowel_geometry_boundaries.py``.

The web mirrors several functions in JS (``_silhouetteForDataWidth``,
``_roundedSilhouettePolygonPoints``, ``_cornersFromAnchors``,
``_apexBackColumnAtBottom``, ``_insetSilhouetteForDraw`` in
``web/main.js``) plus the ``_BACK_APEX_PULL`` constant. Change the
math here and those ports must change in the same commit.
"""

from __future__ import annotations

import math
from dataclasses import replace
from typing import NamedTuple

from phonology_shared.chart.vowel_space_geometry.model import VowelChartSilhouette
from phonology_shared.chart.vowel_space import (
    _BACKNESS_X,
    _HEIGHT_Y,
    _PAIR_OUTER_EXTENT,
    ROW_LABELS,
    TRAPEZOID_BOTTOM_WIDTH,
    TRIANGLE_BOTTOM_WIDTH,
)
from phonology_shared.chart.vowels import VowelChartShape
from phonology_shared.presentation.chart_style import (
    VOWEL_SILHOUETTE_CORNER_RADIUS_FRAC,
    VOWEL_SILHOUETTE_INSET_PX,
)
from phonology_shared.presentation.constants import BTN_W
from phonology_shared.presentation.layout import VOWEL_PAIR_GAP_PX

#: Converged-bottom back-side pull. THE BACK EDGE STAYS VERTICAL --
#: the dorsal / back boundary is a strong articulatory and phonological
#: anchor, so it holds its position at ``back_anchor`` across every
#: row. Only the front boundary tapers inward as height lowers. Under
#: a lone-central-low inventory the front-low corner collapses toward
#: the apex, giving a RIGHT-LEANING WEDGE (vertical back wall,
#: slanted front edge) rather than a symmetric triangle. Under a
#: lone-back-low inventory (German /ɑ/, Turkish /ɑ/) the sole low
#: vowel already sits flush against the vertical back wall, so no
#: wedge reshape is needed and the classic-trapezoid path handles it.
#:
#: A positive value would pull the back column partially toward the
#: apex; kept at ``0.0`` to keep the wall vertical for every
#: inventory, matching the phonological asymmetry that ``[+low,
#: +front]`` is the least stable place and ``[+back]`` is the most.
_BACK_APEX_PULL: float = 0.0


def _apex_back_column_at_bottom(
    back: float, canonical_apex: float, bottom_width: float
) -> float:
    """Where the back COLUMN lands at ``bottom_y`` when a converged
    silhouette targets ``canonical_apex`` (the sole populated Open-row
    column's anchor, e.g. central for Spanish).

    The back column pulls only ``_BACK_APEX_PULL`` of the way from
    ``back`` toward ``canonical_apex``, then that pulled position is
    scaled by ``bottom_width`` relative to ``back`` (so a wider
    ``bottom_width`` slants the back edge less; at ``bottom_width=1``
    the back column stays at ``back``). Consumed by every silhouette
    builder (``vowel_silhouette``, ``_silhouette_with_widths``) so
    the same value flows into ``VowelChartSilhouette.back_anchor_at_bottom``,
    which the projection and the outline right edge both read.
    """
    back_pull_pivot = back - _BACK_APEX_PULL * (back - canonical_apex)
    return back_pull_pivot + bottom_width * (back - back_pull_pivot)


class _SilhouetteCorners(NamedTuple):
    """Return type for :py:func:`_silhouette_corners`. The four
    outline corners plus the two front-anchor cell-projection
    intermediates renderers cache."""

    top_left: float
    top_right: float
    bottom_left: float
    bottom_right: float
    front_anchor_at_top: float
    front_anchor_at_bottom: float


def back_col_at_bottom(silhouette: VowelChartSilhouette) -> float:
    """Where the back column lands at ``silhouette.bottom_y``. THE
    single derivation shared by the outline right edge and the
    projection layer, so interior and exterior stay parallel on the
    back side by construction.

    ``back_anchor_at_bottom`` on the silhouette carries the canonical
    apex position for a converged bottom (e.g. central for Spanish)
    or ``None`` for a classic trapezoid. This helper folds in the
    ``_BACK_APEX_PULL`` policy and the ``bottom_width`` scaling.
    """
    apex = silhouette.back_anchor_at_bottom
    if apex is None:
        return silhouette.back_anchor
    return _apex_back_column_at_bottom(
        silhouette.back_anchor, apex, silhouette.bottom_width
    )


def _corners_from_anchors(
    *,
    front_anchor_at_top: float,
    front_anchor_at_bottom: float,
    back_anchor: float,
    back_anchor_at_bottom: float | None,
    bottom_width: float,
    extent_norm: float,
    front_extent_norm: float,
) -> _SilhouetteCorners:
    """Apply per-side pixel-extent offsets to pre-computed anchor
    positions to yield the four outline corners.

    The back-side pivot at bottom is derived from
    ``back_anchor_at_bottom`` (the canonical apex, ``None`` for
    classic trapezoid) via :py:func:`_apex_back_column_at_bottom`,
    with the same ``bottom_width`` the projection reads. So the
    outline's right edge and the back column projection at
    ``bottom_y`` both land at the same base position (differing only
    by ``extent_norm``), guaranteeing back-side parallelism.

    Called by the render cascade (:py:func:`silhouette_for_data_width`
    when the anchor positions are already baked on the silhouette
    and only the extents are new at a live ``dw``) and by the
    pipeline's outline extent grower (when cells demand larger
    per-side reserves than the canonical pair-outer default).
    """
    if back_anchor_at_bottom is None:
        back_edge_at_bot = back_anchor
    else:
        back_edge_at_bot = _apex_back_column_at_bottom(
            back_anchor, back_anchor_at_bottom, bottom_width
        )
    return _SilhouetteCorners(
        top_left=front_anchor_at_top - front_extent_norm,
        top_right=back_anchor + extent_norm,
        bottom_left=front_anchor_at_bottom - front_extent_norm,
        bottom_right=back_edge_at_bot + extent_norm,
        front_anchor_at_top=front_anchor_at_top,
        front_anchor_at_bottom=front_anchor_at_bottom,
    )


def _silhouette_corners(
    *,
    top_width: float,
    bottom_width: float,
    back: float,
    apex: float | None,
    extent_norm: float,
    front_extent_norm: float,
) -> _SilhouetteCorners:
    """Single source of truth for building the silhouette's corner
    arithmetic FROM WIDTHS. Every function that constructs a
    silhouette from row widths + apex (canonical
    :py:func:`vowel_silhouette`, shrink post-process
    :py:func:`_silhouette_with_widths`) reduces to a call here.

    Computes the front-column position at ``top_y`` and ``bottom_y``
    from the widths, then delegates the "apply extents" step to
    :py:func:`_corners_from_anchors`. The back-column position at
    ``bottom_y`` is derived inside :py:func:`_corners_from_anchors`
    from the same ``apex`` + ``bottom_width`` combination the
    projection layer reads via :py:func:`back_col_at_bottom`, so
    interior and exterior lines stay parallel on the back side.
    """
    front = _BACKNESS_X["front"]
    front_at_top = back + top_width * (front - back)
    front_pivot_at_bot = back if apex is None else apex
    front_at_bottom = (
        front_pivot_at_bot + bottom_width * (front - front_pivot_at_bot)
    )
    return _corners_from_anchors(
        front_anchor_at_top=front_at_top,
        front_anchor_at_bottom=front_at_bottom,
        back_anchor=back,
        back_anchor_at_bottom=apex,
        bottom_width=bottom_width,
        extent_norm=extent_norm,
        front_extent_norm=front_extent_norm,
    )


def vowel_silhouette(
    shape: VowelChartShape,
    top_logical_row: int = 0,
    bottom_logical_row: int | None = None,
    open_apex_backness: str | None = None,
) -> VowelChartSilhouette:
    """Compute the silhouette for an inventory whose populated
    rows span ``top_logical_row`` to ``bottom_logical_row``
    (inclusive, indices into :py:data:`ROW_LABELS`).

    Defaults reproduce the canonical 7-row Close-to-Open silhouette
    (used by :py:func:`web/scripts/build.py` to bake fallback CSS
    variables). Inventory-adaptive callers pass the actual
    populated row range so the silhouette top and bottom widths
    track the IPA narrowness of the rows actually rendered: an
    inventory whose lowest row is Open-mid carries a wider bottom
    edge than one with a true Open vowel.

    The silhouette top edge always sits at the Close anchor
    (``_HEIGHT_Y["Close"]``) and the bottom edge at the Open anchor
    (``_HEIGHT_Y["Open"]``) so the data area is fully used
    regardless of which rows are populated; the
    inventory-adaptive part is only the widths at those edges.

    ``open_apex_backness`` ("front", "central", "back", or None) is
    set by the placement plan when the lowest populated row has cells
    in exactly one backness column, and only fires today for the
    ``"central"`` case. When set, the silhouette's FRONT-column
    position at ``bottom_y`` collapses toward that column's canonical
    apex (the front edge slants inward), while the BACK edge stays
    vertical at ``back_anchor`` per the ``_BACK_APEX_PULL = 0.0``
    policy. The four bottom-edge corners are repositioned so the
    outline hugs the sole low vowel rather than advertising empty
    flanks the inventory does not contrast.
    """
    if bottom_logical_row is None:
        bottom_logical_row = len(ROW_LABELS) - 1
    back = _BACKNESS_X["back"]
    pair_outer = _PAIR_OUTER_EXTENT
    bottom_width_canonical = (
        TRIANGLE_BOTTOM_WIDTH
        if shape == VowelChartShape.TRIANGLE
        else TRAPEZOID_BOTTOM_WIDTH
    )
    top_logical_y = _HEIGHT_Y[ROW_LABELS[top_logical_row]]
    bottom_logical_y = _HEIGHT_Y[ROW_LABELS[bottom_logical_row]]
    top_row_width = 1.0 - (1.0 - bottom_width_canonical) * top_logical_y
    bottom_row_width = 1.0 - (1.0 - bottom_width_canonical) * bottom_logical_y
    apex: float | None = (
        _BACKNESS_X[open_apex_backness]
        if open_apex_backness in _BACKNESS_X
        else None
    )
    corners = _silhouette_corners(
        top_width=top_row_width,
        bottom_width=bottom_row_width,
        back=back,
        apex=apex,
        extent_norm=pair_outer,
        front_extent_norm=pair_outer,
    )
    return VowelChartSilhouette(
        shape=shape,
        top_y=_HEIGHT_Y["Close"],
        bottom_y=_HEIGHT_Y["Open"],
        top_left=corners.top_left,
        top_right=corners.top_right,
        bottom_left=corners.bottom_left,
        bottom_right=corners.bottom_right,
        top_width=top_row_width,
        bottom_width=bottom_row_width,
        # Cell-extent fields (cascade source). Renderers position
        # the silhouette edges at ``anchor * dw ± cell_outer_extent_px``
        # so the silhouette wraps the outer cell edge flush at ANY
        # data width, not just the canonical 232 px.
        front_anchor_at_top=corners.front_anchor_at_top,
        front_anchor_at_bottom=corners.front_anchor_at_bottom,
        back_anchor=back,
        # The canonical apex position (e.g. ``central`` = 0.5 for
        # Spanish) for a converged silhouette, or ``None`` for a
        # classic trapezoid. The back column's actual position at
        # ``bottom_y`` is derived from this and ``bottom_width`` via
        # :py:func:`back_col_at_bottom`, which the projection layer
        # and the outline back edge both read.
        back_anchor_at_bottom=apex,
        # Constant pixel offset from a paired cell's centre to its
        # outer edge: ``pair_shift`` (centre-to-mate-centre / 2)
        # plus half a button width.
        cell_outer_extent_px=int(
            round((BTN_W + VOWEL_PAIR_GAP_PX) / 2.0 + BTN_W / 2.0)
        ),
    )


def _quad_bezier_1d(
    p_in: float, ctrl: float, p_out: float, t: float, one_minus_t: float
) -> float:
    """One coordinate of a quadratic Bezier at parameter ``t``.

    ``one_minus_t`` is passed in rather than recomputed: the corner
    evaluators derive it FIRST (via sqrt) and ``t`` from it, and
    ``1.0 - (1.0 - x)`` is not bit-identical to ``x`` in floating
    point. The polygon string, the edge evaluators, and the JS
    ports must agree to the last bit for the parity tests to hold,
    so every caller hands over its exact ``(t, one_minus_t)`` pair.
    """
    return (
        one_minus_t * one_minus_t * p_in
        + 2.0 * one_minus_t * t * ctrl
        + t * t * p_out
    )


def rounded_silhouette_polygon_points(
    silhouette: VowelChartSilhouette,
    radius_frac: float,
    *,
    segments_per_corner: int = 5,
) -> str:
    """Return a CSS ``clip-path: polygon()`` points string that
    approximates the silhouette's outline with rounded corners.

    The 4-corner polygon is replaced by ``4 *
    (segments_per_corner + 1)`` points: at each corner, two
    "inset" points sit ``radius_frac`` along each adjacent edge,
    and the corner itself is approximated by a quadratic Bezier
    curve between those inset points with the corner as control.
    Sampling the curve at ``segments_per_corner + 1`` equally-
    spaced ``t`` values yields a visually smooth round.

    Used by ``build.py`` to bake a CSS variable consumed by the
    web's ``clip-path: polygon(var(--vowel-<shape>-rounded-points))``.
    Desktop's ``QPainterPath`` consumer uses the same
    ``radius_frac`` source but calls Qt's native ``quadTo`` per
    corner so the desktop path stays free of polygon-interpolation
    artefacts. Both renderers share the radius source so their
    corner rounding stays in lockstep.
    """
    # CCW traversal so the polygon interior sits on the right of
    # each directed edge. Top-left -> bottom-left -> bottom-right
    # -> top-right matches the silhouette's polygon definition
    # used elsewhere in this file.
    corners: tuple[tuple[float, float], ...] = (
        (silhouette.top_left, silhouette.top_y),
        (silhouette.bottom_left, silhouette.bottom_y),
        (silhouette.bottom_right, silhouette.bottom_y),
        (silhouette.top_right, silhouette.top_y),
    )
    n = len(corners)
    points: list[tuple[float, float]] = []
    for i in range(n):
        prev = corners[(i - 1) % n]
        curr = corners[i]
        nxt = corners[(i + 1) % n]
        # Unit vectors from ``curr`` toward each neighbour.
        dx_in = prev[0] - curr[0]
        dy_in = prev[1] - curr[1]
        len_in = math.hypot(dx_in, dy_in) or 1.0
        dx_in /= len_in
        dy_in /= len_in
        dx_out = nxt[0] - curr[0]
        dy_out = nxt[1] - curr[1]
        len_out = math.hypot(dx_out, dy_out) or 1.0
        dx_out /= len_out
        dy_out /= len_out
        # Inset points sit ``radius_frac`` along each edge from the
        # corner. Clamp the radius so a very short edge can't push
        # the inset past the edge's midpoint (would overlap the
        # adjacent corner's arc).
        r_in = min(radius_frac, len_in * 0.45)
        r_out = min(radius_frac, len_out * 0.45)
        p_in = (
            curr[0] + r_in * dx_in,
            curr[1] + r_in * dy_in,
        )
        p_out = (
            curr[0] + r_out * dx_out,
            curr[1] + r_out * dy_out,
        )
        # Quadratic Bezier sampled at ``segments_per_corner + 1``
        # equally-spaced t values. The corner itself is the control
        # point; t=0 emits ``p_in``, t=1 emits ``p_out``.
        for s in range(segments_per_corner + 1):
            t = s / segments_per_corner
            one_minus_t = 1.0 - t
            bx = _quad_bezier_1d(p_in[0], curr[0], p_out[0], t, one_minus_t)
            by = _quad_bezier_1d(p_in[1], curr[1], p_out[1], t, one_minus_t)
            points.append((bx, by))
    return ", ".join(f"{x * 100:.3f}% {y * 100:.3f}%" for x, y in points)


def silhouette_for_data_width(
    silhouette: VowelChartSilhouette, data_w_px: int
) -> VowelChartSilhouette:
    """Return a copy of ``silhouette`` with the four corner fields
    recomputed from the cell-extent fields (``front_anchor_at_*``,
    ``back_anchor``, the two extent px fields) for the given
    rendered data width in pixels.

    THE CASCADE INVARIANT: cells render at
    ``anchor * dw + sign * extent_px`` (sign -1 for front, +1 for
    back), a mixed normalised + pixel formula. The corner fields
    are purely normalised, so they can be flush with that formula
    at exactly one width; the build bakes them at the canonical
    content width, and at any other rendered width the fixed pixel
    extent corresponds to a different normalised offset, opening a
    few pixels of drift between the outline and the outermost
    cells (the same on both sides, but the slanted front edge
    makes it visually obvious).

    Every render pass therefore calls this helper with the ``dw``
    it actually measured (web ``getBoundingClientRect``, desktop
    ``self.width()``) and rebuilds the polygon from the result via
    :py:func:`rounded_silhouette_polygon_points`; the corners then
    track the cells flush at every width by construction. The
    baked canonical-width corners stay on the geometry for
    consumers with no live width: the offline CSS fallback and the
    per-row label fields.

    A ``front_cell_outer_extent_px`` of ``0`` means "mirror the
    back extent", so the symmetric default costs no second field.
    """
    if data_w_px <= 0:
        return silhouette
    extent_norm = silhouette.cell_outer_extent_px / data_w_px
    front_extent_norm = (
        silhouette.front_cell_outer_extent_px / data_w_px
        if silhouette.front_cell_outer_extent_px
        else extent_norm
    )
    corners = _corners_from_anchors(
        front_anchor_at_top=silhouette.front_anchor_at_top,
        front_anchor_at_bottom=silhouette.front_anchor_at_bottom,
        back_anchor=silhouette.back_anchor,
        back_anchor_at_bottom=silhouette.back_anchor_at_bottom,
        bottom_width=silhouette.bottom_width,
        extent_norm=extent_norm,
        front_extent_norm=front_extent_norm,
    )
    return replace(
        silhouette,
        top_left=corners.top_left,
        bottom_left=corners.bottom_left,
        top_right=corners.top_right,
        bottom_right=corners.bottom_right,
    )


def inset_silhouette_for_draw(
    silhouette: VowelChartSilhouette,
    data_w_px: int,
    data_h_px: int,
    inset_px: float = VOWEL_SILHOUETTE_INSET_PX,
) -> VowelChartSilhouette:
    """Return a copy of ``silhouette`` grown OUTWARD by ``inset_px`` on
    every side, for DRAWING ONLY.

    :py:func:`silhouette_for_data_width` wraps the outermost cells
    flush; this pushes the *drawn* trapezoid a fixed ``inset_px`` beyond
    that flush edge, so the chips float inside a quiet field with
    breathing room instead of touching the stroke. ``inset_px`` is
    converted to normalised offsets (``/ data_w_px`` horizontally,
    ``/ data_h_px`` vertically) so the gap stays a constant pixel width
    at any rendered size.

    CRITICAL: this is a draw-time transform ONLY. It must never feed
    cell CONFINEMENT (``pipeline._confine_cells_to_outline`` ->
    :py:func:`straight_left_at_y` / :py:func:`straight_right_at_y`):
    confinement keeps using the un-inset
    :py:func:`silhouette_for_data_width` result so cells stay positioned
    against the true cell extent. If the inset leaked into confinement
    it would shove every cell ``inset_px`` inward and re-crowd the open
    rows. Callers pass this ONLY to the outline renderer, the row-label
    edge, and the diphthong-strip anchor.
    """
    if data_w_px <= 0 or data_h_px <= 0 or inset_px <= 0:
        return silhouette
    dx = inset_px / data_w_px
    dy = inset_px / data_h_px
    return replace(
        silhouette,
        top_left=silhouette.top_left - dx,
        bottom_left=silhouette.bottom_left - dx,
        top_right=silhouette.top_right + dx,
        bottom_right=silhouette.bottom_right + dx,
        top_y=silhouette.top_y - dy,
        bottom_y=silhouette.bottom_y + dy,
    )


def straight_right_at_y(
    silhouette: VowelChartSilhouette, chart_y: float
) -> float:
    """The RIGHT edge x at ``chart_y`` along the STRAIGHT trapezoid
    side: the linear interpolation between the top-right and
    bottom-right corners, with NO rounded-corner inset. For a
    trapezoid the back edge is vertical, so this is the constant
    back-edge x at every row.

    This is the boundary cell CONFINEMENT uses: the rounded corners
    are a cosmetic stroke, not a containment edge, and confining the
    vertical back column against them shoves the top / bottom cells
    inward and breaks the column's alignment. Row LABELS instead use
    the rounded :py:func:`silhouette_right_at_y` so they hug the
    visible stroke. Both share this linear interp as their
    corner-free base.
    """
    sil = silhouette
    span_y = sil.bottom_y - sil.top_y
    if span_y <= 0:
        return sil.top_right
    t = (max(sil.top_y, min(sil.bottom_y, chart_y)) - sil.top_y) / span_y
    return sil.top_right + (sil.bottom_right - sil.top_right) * t


def straight_left_at_y(
    silhouette: VowelChartSilhouette, chart_y: float
) -> float:
    """The LEFT edge x at ``chart_y`` along the STRAIGHT (slanted)
    trapezoid side, with NO rounded-corner inset. The confinement
    boundary mate of :py:func:`straight_right_at_y`; see it for why
    cells confine to the straight edge while labels track the rounded
    :py:func:`silhouette_left_at_y`.
    """
    sil = silhouette
    span_y = sil.bottom_y - sil.top_y
    if span_y <= 0:
        return sil.top_left
    t = (max(sil.top_y, min(sil.bottom_y, chart_y)) - sil.top_y) / span_y
    return sil.top_left + (sil.bottom_left - sil.top_left) * t


def silhouette_right_at_y(
    silhouette: VowelChartSilhouette,
    chart_y: float,
    corner_radius_frac: float = VOWEL_SILHOUETTE_CORNER_RADIUS_FRAC,
) -> float:
    """Mirror of :py:func:`silhouette_left_at_y` for the back
    (right) silhouette edge. Returns the silhouette's actual RIGHT
    edge x at ``chart_y``, accounting for the top-right and
    bottom-right rounded-corner insets.

    For a canonical trapezoid the right edge is vertical (back
    anchor doesn't slant per row), so this collapses to
    ``silhouette.top_right`` (== ``silhouette.bottom_right``)
    outside the corner regions. Within the rounded corners the
    helper follows the same quadratic Bezier sampled by
    :py:func:`rounded_silhouette_polygon_points`.

    The analytic right-edge oracle: the polygon parity tests check
    the sampled outline against it, and geometry code evaluates it
    live where a back-edge x is needed (nothing bakes it per row;
    row labels hug the front edge only).
    """
    sil = silhouette
    span_y = sil.bottom_y - sil.top_y
    if span_y <= 0:
        return sil.top_right
    chart_y = max(sil.top_y, min(sil.bottom_y, chart_y))

    # Canonical (straight-edge) value, before the corner bezier.
    # For a normal trapezoid the back edge is vertical so this is
    # constant.
    canonical = straight_right_at_y(sil, chart_y)

    # Top-right corner. Prev neighbour in CCW order is bottom-right
    # (down the right edge); next neighbour is top-left (along the
    # top edge, leftward).
    tr_dx_in = sil.bottom_right - sil.top_right
    tr_dy_in = sil.bottom_y - sil.top_y
    tr_len_in = math.hypot(tr_dx_in, tr_dy_in) or 1.0
    tr_dx_in_norm = tr_dx_in / tr_len_in
    tr_dy_in_norm = tr_dy_in / tr_len_in
    tr_r_in = min(corner_radius_frac, tr_len_in * 0.45)
    tr_r_in_y_abs = abs(tr_r_in * tr_dy_in_norm)

    tr_dx_out = sil.top_left - sil.top_right
    tr_len_out = abs(tr_dx_out) or 1.0
    tr_r_out = min(corner_radius_frac, tr_len_out * 0.45)

    dy_top = chart_y - sil.top_y
    if 0 <= dy_top < tr_r_in_y_abs and tr_r_in_y_abs > 0:
        # The arc runs from p_in ON THE RIGHT EDGE (t=0, at
        # y = top_y + r_in_y) up to p_out ON THE TOP EDGE (t=1, at
        # y = top_y): y(t) = top_y + (1-t)^2 * tr_r_in_y_abs, so
        # the parameter solves as 1 - t = sqrt(dy / r). Note the
        # inversion: t GROWS as y approaches the top edge. Solving
        # t = sqrt(dy / r) instead reads the arc backwards and
        # hands the topmost row the un-rounded corner x; the
        # polygon parity tests in test_rounded_silhouette.py pin
        # the orientation.
        omt = math.sqrt(dy_top / tr_r_in_y_abs)
        omt = max(0.0, min(1.0, omt))
        t = 1.0 - omt
        x_in = sil.top_right + tr_r_in * tr_dx_in_norm  # p_in.x
        x_curr = sil.top_right
        x_out = sil.top_right - tr_r_out  # leftward
        x_corner = _quad_bezier_1d(x_in, x_curr, x_out, t, omt)
        # The right-side bezier curves LEFTWARD (inward) from the
        # corner; use the smaller of canonical vs corner.
        return min(canonical, x_corner)

    # Bottom-right corner.
    br_dx_in = sil.bottom_left - sil.bottom_right
    br_len_in = abs(br_dx_in) or 1.0
    br_r_in = min(corner_radius_frac, br_len_in * 0.45)

    br_dx_out = sil.top_right - sil.bottom_right
    br_dy_out = sil.top_y - sil.bottom_y
    br_len_out = math.hypot(br_dx_out, br_dy_out) or 1.0
    br_dx_out_norm = br_dx_out / br_len_out
    br_dy_out_norm = br_dy_out / br_len_out
    br_r_out = min(corner_radius_frac, br_len_out * 0.45)
    br_r_out_y_abs = abs(br_r_out * br_dy_out_norm)

    dy_bot = sil.bottom_y - chart_y
    if 0 <= dy_bot < br_r_out_y_abs and br_r_out_y_abs > 0:
        # Here the arc runs from p_in ON THE BOTTOM EDGE (t=0, at
        # y = bottom_y) up to p_out ON THE RIGHT EDGE (t=1, at
        # y = bottom_y - r_out_y): y(t) = bottom_y - t^2 *
        # br_r_out_y_abs, so t = sqrt(dy / r). The same orientation
        # trap as the top-right corner applies, mirrored; see the
        # comment there.
        t = math.sqrt(dy_bot / br_r_out_y_abs)
        t = max(0.0, min(1.0, t))
        omt = 1.0 - t
        x_in = sil.bottom_right - br_r_in  # leftward along bottom
        x_curr = sil.bottom_right
        x_out = sil.bottom_right + br_r_out * br_dx_out_norm
        x_corner = _quad_bezier_1d(x_in, x_curr, x_out, t, omt)
        return min(canonical, x_corner)

    return canonical


def silhouette_left_at_y(
    silhouette: VowelChartSilhouette,
    chart_y: float,
    corner_radius_frac: float = VOWEL_SILHOUETTE_CORNER_RADIUS_FRAC,
) -> float:
    """Return the silhouette's actual LEFT edge x (normalised
    ``[0, 1]``) at the given ``chart_y``, accounting for
    top-left and bottom-left rounded-corner insets.

    Outside the corner regions the result is the canonical linear
    interpolation between ``top_left`` and ``bottom_left``: the
    rounded polygon's straight segment between
    ``p_out_top`` and ``p_in_bot`` IS that same line, so the
    canonical interp matches the polygon pixel-for-pixel away
    from the corners.

    Within the corner regions (chart_y within the y-extent of
    the rounded curve) the result follows the SAME quadratic
    Bezier sampled by :py:func:`rounded_silhouette_polygon_points`,
    so a row label anchored to this value lands on the rendered
    silhouette edge with no visible gap.

    Both renderers consume this via ``VowelChartRow.silhouette_left``
    (baked per row at build time); neither replicates the bezier
    math locally.
    """
    sil = silhouette
    span_y = sil.bottom_y - sil.top_y
    if span_y <= 0:
        return sil.top_left
    # Clamp y to the silhouette range; rows can sit at chart_y
    # values outside [top_y, bottom_y] for non-bracket rows but
    # the meaningful row anchors are inside.
    chart_y = max(sil.top_y, min(sil.bottom_y, chart_y))

    # Canonical linear interpolation (matches the polygon's
    # straight segment between p_out_top and p_in_bot).
    canonical = straight_left_at_y(sil, chart_y)

    # Top-left corner.
    tl_dx_out = sil.bottom_left - sil.top_left
    tl_dy_out = sil.bottom_y - sil.top_y
    tl_len_out = math.hypot(tl_dx_out, tl_dy_out) or 1.0
    tl_dx_out_norm = tl_dx_out / tl_len_out
    tl_dy_out_norm = tl_dy_out / tl_len_out
    tl_r_out = min(corner_radius_frac, tl_len_out * 0.45)
    tl_r_out_y = tl_r_out * tl_dy_out_norm

    # top edge (from top_left to top_right). For trapezoid this
    # spans most of the chart; for triangle the top edge is
    # narrower. Sets ``r_in`` for the top-left bezier.
    tl_dx_in = sil.top_right - sil.top_left
    tl_len_in = abs(tl_dx_in) or 1.0
    tl_r_in = min(corner_radius_frac, tl_len_in * 0.45)

    dy_top = chart_y - sil.top_y
    if 0 <= dy_top < tl_r_out_y and tl_r_out_y > 0:
        # Solve y(t) = top_y + t^2 * tl_r_out_y for t
        t = math.sqrt(dy_top / tl_r_out_y)
        t = max(0.0, min(1.0, t))
        omt = 1.0 - t
        x_in = sil.top_left + tl_r_in  # p_in.x
        x_curr = sil.top_left  # control point x
        x_out = sil.top_left + tl_r_out * tl_dx_out_norm  # p_out.x
        x_corner = _quad_bezier_1d(x_in, x_curr, x_out, t, omt)
        # x_corner is always >= canonical inside the corner region
        # (the bezier curves rightward of the canonical line); use
        # the corner value.
        return max(canonical, x_corner)

    # Bottom-left corner.
    bl_dx_in = sil.top_left - sil.bottom_left
    bl_dy_in = sil.top_y - sil.bottom_y
    bl_len_in = math.hypot(bl_dx_in, bl_dy_in) or 1.0
    bl_dx_in_norm = bl_dx_in / bl_len_in
    bl_dy_in_norm = bl_dy_in / bl_len_in
    bl_r_in = min(corner_radius_frac, bl_len_in * 0.45)
    bl_r_in_y_abs = abs(bl_r_in * bl_dy_in_norm)

    bl_dx_out = sil.bottom_right - sil.bottom_left
    bl_len_out = abs(bl_dx_out) or 1.0
    bl_r_out = min(corner_radius_frac, bl_len_out * 0.45)

    dy_bot = sil.bottom_y - chart_y
    if 0 <= dy_bot < bl_r_in_y_abs and bl_r_in_y_abs > 0:
        # y(t) = bottom_y + (1-t)^2 * bl_r_in_y    (bl_r_in_y is negative)
        # bottom_y - y(t) = (1-t)^2 * |bl_r_in_y|
        # 1 - t = sqrt(dy_bot / |bl_r_in_y|)
        omt = math.sqrt(dy_bot / bl_r_in_y_abs)
        omt = max(0.0, min(1.0, omt))
        t = 1.0 - omt
        x_in = sil.bottom_left + bl_r_in * bl_dx_in_norm  # p_in.x
        x_curr = sil.bottom_left  # control point
        x_out = sil.bottom_left + bl_r_out  # p_out.x
        x_corner = _quad_bezier_1d(x_in, x_curr, x_out, t, omt)
        return max(canonical, x_corner)

    return canonical


def _silhouette_with_widths(
    silhouette: VowelChartSilhouette,
    top_width: float,
    bottom_width: float,
) -> VowelChartSilhouette:
    """Recompute silhouette corners for new ``top_width`` /
    ``bottom_width`` while keeping shape, y bounds, and the back
    anchor + pixel offset.

    All the arithmetic lives in :py:func:`_silhouette_corners`; this
    is a thin adapter that carries the silhouette's existing extents
    forward into the new corners.
    """
    back = _BACKNESS_X["back"]
    pair_outer = _PAIR_OUTER_EXTENT
    corners = _silhouette_corners(
        top_width=top_width,
        bottom_width=bottom_width,
        back=back,
        apex=silhouette.back_anchor_at_bottom,
        extent_norm=pair_outer,
        front_extent_norm=pair_outer,
    )
    return replace(
        silhouette,
        top_left=corners.top_left,
        top_right=corners.top_right,
        bottom_left=corners.bottom_left,
        bottom_right=corners.bottom_right,
        top_width=top_width,
        bottom_width=bottom_width,
        # Cell-extent fields stay in lockstep with the corners so
        # the cascade math (silhouette = anchor*dw +/- extent_px)
        # tracks any shrink the slant-cap policy applies.
        front_anchor_at_top=corners.front_anchor_at_top,
        front_anchor_at_bottom=corners.front_anchor_at_bottom,
        back_anchor=back,
    )
