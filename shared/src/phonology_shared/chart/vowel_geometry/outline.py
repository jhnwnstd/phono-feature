"""The vowel-space outline: the boundary authority (layer 4).

Owns the silhouette dataclass's geometry: the canonical and
inventory-adapted trapezoid (:py:func:`vowel_silhouette`), the
two-stage shrink solver, the rounded-corner polygon and the
edge-at-y evaluators both renderers anchor labels to, and the
cascade (:py:func:`silhouette_for_data_width`) that recomputes
corners for the actual rendered width so the outline wraps the
outermost cells flush at any size.

THE RULE THAT KEEPS THIS LAYER HONEST: this module knows nothing
about cells. ``VowelChartCell`` is a forbidden name here; the shrink
solver consumes abstract ``(anchor, pair_side, is_pair)`` width
demands, never cell objects. Relating actual cell boxes to the
outline (extent growth, confinement) happens only in the pipeline.
Enforced by ``shared/tests/test_vowel_geometry_boundaries.py``.

The web mirrors two functions in JS (``_silhouetteForDataWidth`` and
``_roundedSilhouettePolygonPoints`` in ``web/main.js``); change the
math here and those ports must change in the same commit.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, replace

from phonology_shared.chart.vowel_geometry.model import VowelChartSilhouette
from phonology_shared.chart.vowel_space import (
    _BACKNESS_X,
    _CANONICAL_CONTENT_W_PX,
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
from phonology_shared.presentation.layout import (
    VOWEL_PAIR_GAP_PX,
    VOWEL_PAIR_SEPARATOR_PX,
)

#: Reference content width (px) used to convert cell pixel sizes
#: into the normalised ``[0, 1]`` coordinate space the silhouette
#: lives in. Single definition lives in :py:mod:`.vowels` next to
#: the anchor derivation so cell-extent math stays consistent with
#: chart_x.
_VOWEL_CONTENT_W_PX: float = _CANONICAL_CONTENT_W_PX

#: How aggressively the silhouette's top_width and bottom_width
#: shrink toward each row's minimum-required width. ``0.0`` keeps
#: the canonical widths; ``1.0`` would consume all per-row slack.
#: Stage 1 uses this against the most-constrained row's slack;
#: Stage 2 reuses it as the per-row consumption ceiling so the same
#: aggression governs both passes. Both the silhouette outline and
#: the back-anchored cell projection use the resulting widths, so
#: cells follow the silhouette by construction with no drift.
_VOWEL_SHRINK_FACTOR: float = 0.3

#: Hard cap on how much Stage 2 may tilt the trapezoid, expressed
#: as a fraction of the canonical slant ``canonical_top_width -
#: canonical_bottom_width``. Stage 1 preserves the canonical
#: proportions; Stage 2 then asks: with the new narrower trapezoid,
#: is there still slack at the top OR the bottom that pure uniform
#: shrink missed? If so, top and bottom are nudged inward by
#: DIFFERENT amounts (changing the slant).
#:
#: CURRENTLY 0.0, WHICH DISABLES STAGE 2. Asymmetric reshaping
#: makes the silhouette read differently per inventory (each one
#: tilts the canonical trapezoid by its own amount), defeating the
#: chart's at-a-glance familiarity. With Stage 2 off, every
#: inventory's silhouette is the canonical Close-to-Open trapezoid
#: (no shrink for sparse inventories) or a UNIFORMLY scaled copy of
#: it (small uniform shrink for dense inventories that still need
#: cells to fit); the slant is constant across the entire bundled +
#: PHOIBLE set.
#:
#: ``1.0`` would let the slant double (or invert). A regression
#: test in test_vowel_silhouette_shrink.py pins the 0.0 so
#: re-enabling the asymmetric tweak is a deliberate edit, not a
#: drive-by.
_VOWEL_SLANT_CHANGE_CAP_FRAC: float = 0.0

#: Minimum visual separation between adjacent cells in the same
#: row (expressed as a fraction of the canonical content width).
#: Matches the inter-pair separator on the canonical 3-slot
#: layout, so two pinched-together slots end up with the same
#: comfortable gap as canonical adjacent pairs.
_VOWEL_MIN_CELL_GAP_NORM: float = VOWEL_PAIR_SEPARATOR_PX / _VOWEL_CONTENT_W_PX


def vowel_silhouette(
    shape: VowelChartShape,
    top_logical_row: int = 0,
    bottom_logical_row: int | None = None,
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
    """
    if bottom_logical_row is None:
        bottom_logical_row = len(ROW_LABELS) - 1
    front = _BACKNESS_X["front"]
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
    front_at_top = back + top_row_width * (front - back)
    front_at_bottom = back + bottom_row_width * (front - back)
    y_anchor_top = _HEIGHT_Y["Close"]
    y_anchor_bottom = _HEIGHT_Y["Open"]
    return VowelChartSilhouette(
        shape=shape,
        top_y=y_anchor_top,
        bottom_y=y_anchor_bottom,
        top_left=front_at_top - pair_outer,
        # ``top_right`` / ``bottom_right`` are the canonical back-
        # edge position in normalised x: the back anchor plus the
        # pair-outer extent so the line sits where a back-rounded
        # mate's outer right edge WOULD be. Renderers multiply by
        # the data-area width; on charts wider than the canonical
        # content width the line drifts slightly past the button,
        # which is the intended visual spacing.
        top_right=back + pair_outer,
        bottom_left=front_at_bottom - pair_outer,
        bottom_right=back + pair_outer,
        top_width=top_row_width,
        bottom_width=bottom_row_width,
        # Cell-extent fields (cascade source). Renderers position
        # the silhouette edges at ``anchor * dw ± cell_outer_extent_px``
        # so the silhouette wraps the outer cell edge flush at ANY
        # data width, not just the canonical 232 px.
        front_anchor_at_top=front_at_top,
        front_anchor_at_bottom=front_at_bottom,
        back_anchor=back,
        # Constant pixel offset from a paired cell's centre to its
        # outer edge: ``pair_shift`` (centre-to-mate-centre / 2)
        # plus half a button width. This is the px adjustment the
        # renderer adds to ``anchor * dw`` so the silhouette is
        # flush with the outer cell edge at ANY data width.
        cell_outer_extent_px=int(
            round((BTN_W + VOWEL_PAIR_GAP_PX) / 2.0 + BTN_W / 2.0)
        ),
    )


def _min_row_width_for_meta(
    row_cells: list[tuple[float, int, bool]],
) -> float:
    """Lower bound on ``row_width`` such that the row's cells do
    not overlap given back-anchored projection.

    Each tuple is ``(anchor_x, pair_side, is_long_pair)`` where
    ``anchor_x`` is the cell's EFFECTIVE backness anchor (after any
    Open-row central migration); the cell's horizontal extent is
    its half-width plus its pair-side offset from the row's
    projected anchor. With back-anchored projection
    ``chart_x = back + W * (anchor - back)``, the distance between
    two cells at adjacent anchors scales linearly with ``W``; this
    function solves for the minimum ``W`` such that every adjacent
    pair has at least ``_VOWEL_MIN_CELL_GAP_NORM`` between them
    (zero if a single cell occupies the row).
    """
    if len(row_cells) < 2:
        return 0.0
    pair_shift = (BTN_W + VOWEL_PAIR_GAP_PX) / 2.0 / _VOWEL_CONTENT_W_PX
    single_half = (BTN_W / 2.0) / _VOWEL_CONTENT_W_PX
    long_pair_half = (
        (2 * BTN_W + VOWEL_PAIR_GAP_PX) / 2.0 / _VOWEL_CONTENT_W_PX
    )
    sorted_meta = sorted(row_cells, key=lambda c: c[0])
    min_w = 0.0
    for (anchor_a, ps_a, lp_a), (anchor_b, ps_b, lp_b) in zip(
        sorted_meta, sorted_meta[1:]
    ):
        if anchor_b <= anchor_a:
            # Same backness slot; pair_side handles separation.
            continue
        half_a = long_pair_half if lp_a else single_half
        half_b = long_pair_half if lp_b else single_half
        # Center distance at row_width=W = W*(anchor_b - anchor_a)
        # + (ps_b - ps_a) * pair_shift. For non-overlap with a
        # min visible gap, this must be >= half_a + half_b + gap.
        required = (
            _VOWEL_MIN_CELL_GAP_NORM
            + half_a
            + half_b
            - (ps_b - ps_a) * pair_shift
        )
        w_req = required / (anchor_b - anchor_a)
        if w_req > min_w:
            min_w = w_req
    return max(0.0, min(1.0, min_w))


def _compute_shrunken_widths(
    cells_meta_by_row: Mapping[int, list[tuple[float, int, bool]]],
    display_y_by_row: Mapping[int, float],
    top_y: float,
    bottom_y: float,
    canonical_top_width: float,
    canonical_bottom_width: float,
) -> tuple[float, float]:
    """Compute shrunken silhouette ``(top_width, bottom_width)`` in
    two conceptual stages.

    **Stage 1 (uniform shrink).** Both widths drop by the same
    amount, set by the most-constrained row's slack between its
    canonical row_width and its minimum-required row_width. The
    trapezoid keeps its canonical proportions while pulling inward
    as a whole; the slant stays constant.

    **Stage 2 (slant tweak).** With Stage 1's narrower trapezoid in
    hand, rows that still have slack let us nudge the top OR the
    bottom further inward by DIFFERENT amounts. This changes the
    slant; :py:data:`_VOWEL_SLANT_CHANGE_CAP_FRAC` caps the change
    so the result still reads as the canonical IPA trapezoid.

    Both stages share the same ``_min_row_width_for_meta`` floor and
    the same ``_VOWEL_SHRINK_FACTOR`` aggression so a future tuning
    of either touches both passes consistently.
    """
    if _VOWEL_SHRINK_FACTOR <= 0.0:
        return canonical_top_width, canonical_bottom_width
    span = bottom_y - top_y
    if span <= 0:
        return canonical_top_width, canonical_bottom_width
    row_data: list[tuple[float, float]] = []
    for r, meta in cells_meta_by_row.items():
        if r not in display_y_by_row:
            continue
        t = (display_y_by_row[r] - top_y) / span
        row_data.append((t, _min_row_width_for_meta(meta)))
    if not row_data:
        return canonical_top_width, canonical_bottom_width
    stage1_top, stage1_bot = _stage1_uniform_shrink(
        row_data, canonical_top_width, canonical_bottom_width
    )
    return _stage2_slant_tweak(
        row_data,
        stage1_top,
        stage1_bot,
        canonical_top_width,
        canonical_bottom_width,
    )


def _stage1_uniform_shrink(
    row_data: list[tuple[float, float]],
    canonical_top_width: float,
    canonical_bottom_width: float,
) -> tuple[float, float]:
    """Stage 1: pull top and bottom inward by the same amount,
    bounded by the most-constrained row. Preserves the canonical
    slant.
    """
    min_slack = float("inf")
    for t, min_w in row_data:
        canonical_row_w = (
            canonical_top_width * (1.0 - t) + canonical_bottom_width * t
        )
        slack = canonical_row_w - min_w
        if slack < min_slack:
            min_slack = slack
    if min_slack <= 0 or min_slack == float("inf"):
        return canonical_top_width, canonical_bottom_width
    consume = _VOWEL_SHRINK_FACTOR * min_slack
    return (
        max(0.0, canonical_top_width - consume),
        max(0.0, canonical_bottom_width - consume),
    )


def _stage2_slant_tweak(
    row_data: list[tuple[float, float]],
    stage1_top: float,
    stage1_bot: float,
    canonical_top_width: float,
    canonical_bottom_width: float,
) -> tuple[float, float]:
    """Stage 2: with Stage 1's narrower trapezoid, see how much more
    width each edge can lose by nudging top and bottom independently.

    Solves a 2-variable LP that maximises ``d_top + d_bot`` (the area
    removed in this pass, modulo the constant span/2) subject to three
    families of constraints:

    1. Per-row slack. After Stage 1, each row at ``t`` still has
       ``stage1_row_w(t) - min_w`` of slack; ``_VOWEL_SHRINK_FACTOR``
       of that is the per-row consumption ceiling, matching Stage 1's
       conservativeness. ``d_top * (1 - t) + d_bot * t <= ceiling``.
    2. Slant cap. ``|d_top - d_bot| <= cap``, where ``cap`` is a
       fraction of the canonical slant magnitude. Symmetric so the
       slant may either flatten (top loses more) or steepen (bottom
       loses more) within the same budget.
    3. Box bounds. ``0 <= d_top <= stage1_top`` and analogous for
       ``d_bot``, so neither edge can run negative.

    With only two variables the optimum sits at a vertex of the
    feasible polygon, which is the intersection of two binding
    constraints. We enumerate every pair, accept feasible
    intersections, and keep the best score. With ~10 constraints
    for a 7-row chart this is O(100) trivial 2x2 solves, cheap
    enough to skip a dedicated LP dependency.
    """
    if _VOWEL_SLANT_CHANGE_CAP_FRAC <= 0.0:
        return stage1_top, stage1_bot
    canonical_slant = abs(canonical_top_width - canonical_bottom_width)
    if canonical_slant <= 0.0:
        return stage1_top, stage1_bot
    cap = _VOWEL_SLANT_CHANGE_CAP_FRAC * canonical_slant
    constraints: list[tuple[float, float, float]] = []
    for t, min_w in row_data:
        stage1_row_w = stage1_top * (1.0 - t) + stage1_bot * t
        slack = max(0.0, stage1_row_w - min_w)
        constraints.append((1.0 - t, t, _VOWEL_SHRINK_FACTOR * slack))
    constraints.append((1.0, -1.0, cap))
    constraints.append((-1.0, 1.0, cap))
    constraints.append((-1.0, 0.0, 0.0))
    constraints.append((0.0, -1.0, 0.0))
    constraints.append((1.0, 0.0, stage1_top))
    constraints.append((0.0, 1.0, stage1_bot))
    eps = 1e-9

    def feasible(d_top: float, d_bot: float) -> bool:
        return all(a * d_top + b * d_bot <= c + eps for a, b, c in constraints)

    best = (0.0, 0.0)
    best_score = 0.0
    n = len(constraints)
    for i in range(n):
        a1, b1, c1 = constraints[i]
        for j in range(i + 1, n):
            a2, b2, c2 = constraints[j]
            det = a1 * b2 - a2 * b1
            if abs(det) < 1e-12:
                continue
            d_top = (c1 * b2 - c2 * b1) / det
            d_bot = (a1 * c2 - a2 * c1) / det
            if not feasible(d_top, d_bot):
                continue
            score = d_top + d_bot
            if score > best_score:
                best_score = score
                best = (d_top, d_bot)
    d_top, d_bot = best
    return (
        max(0.0, stage1_top - d_top),
        max(0.0, stage1_bot - d_bot),
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
    return replace(
        silhouette,
        top_left=silhouette.front_anchor_at_top - front_extent_norm,
        bottom_left=silhouette.front_anchor_at_bottom - front_extent_norm,
        top_right=silhouette.back_anchor + extent_norm,
        bottom_right=silhouette.back_anchor + extent_norm,
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

    Both renderers consume this via ``VowelChartRow.silhouette_right``
    (baked per row at geometry build time) so back-edge alignment
    cues stay in lockstep with the rendered silhouette polygon.
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
    anchor + pixel offset. The back edge stays a vertical line at
    ``back`` (anchor) + ``back_right_pixel_offset`` (pixels).
    """
    front = _BACKNESS_X["front"]
    back = _BACKNESS_X["back"]
    pair_outer = _PAIR_OUTER_EXTENT
    front_at_top = back + top_width * (front - back)
    front_at_bottom = back + bottom_width * (front - back)
    return replace(
        silhouette,
        top_left=front_at_top - pair_outer,
        top_right=back + pair_outer,
        bottom_left=front_at_bottom - pair_outer,
        bottom_right=back + pair_outer,
        top_width=top_width,
        bottom_width=bottom_width,
        # Cell-extent fields stay in lockstep with the corners so
        # the cascade math (silhouette = anchor*dw +/- extent_px)
        # tracks any shrink the slant-cap policy applies.
        front_anchor_at_top=front_at_top,
        front_anchor_at_bottom=front_at_bottom,
        back_anchor=back,
    )


def width_at_y(silhouette: VowelChartSilhouette, y: float) -> float:
    """Linear interp between the silhouette's top and bottom widths
    at display y. The single projection-width definition the cell
    projection, the column headers, and the diphthong overlay all
    share, so everything lies on the silhouette slant by
    construction.
    """
    if silhouette.bottom_y == silhouette.top_y:
        return silhouette.top_width
    t = (y - silhouette.top_y) / (silhouette.bottom_y - silhouette.top_y)
    return silhouette.top_width * (1.0 - t) + silhouette.bottom_width * t


def project_anchor_x(
    silhouette: VowelChartSilhouette, anchor_x: float, y: float
) -> float:
    """Back-anchored projection of an abstract backness anchor into
    the silhouette at display y: ``back + width * (anchor - back)``.
    The back anchor is the fixed point, so the silhouette's right
    edge stays a vertical line that back vowels sit flush against;
    everything to its left migrates toward it as the row narrows.
    """
    back = _BACKNESS_X["back"]
    return back + width_at_y(silhouette, y) * (anchor_x - back)


@dataclass(frozen=True)
class RowPlan:
    """Vertical arrangement of the populated rows inside the
    silhouette span: each row's display y anchor, its slot height,
    its render tier (``top`` rows anchor their content's top edge on
    the y and grow DOWN, ``bottom`` rows grow UP, ``middle`` /
    ``only`` centre), and its weight (the row's rendered content
    height in pixels, the quantity the slots are proportional to)."""

    rows: tuple[int, ...]
    display_y: Mapping[int, float]
    slot_height: Mapping[int, float]
    tier: Mapping[int, str]
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
    two rows' content can overlap). ``display_y`` records each row's
    tier anchor: the top row's anchor at the TOP of its slot
    (``top_y``), the bottom row's at the BOTTOM of its slot
    (``bottom_y``), middle rows at their slot CENTRE. The matching
    ``tier`` string tells renderers which way the content grows -- top
    rows anchor their cells' top edge on the anchor and hang DOWN,
    bottom rows anchor their bottom edge and rise UP, middle rows
    centre -- so the cell box fills its slot without crossing the
    silhouette's top or bottom edge.

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
            tier={only: "only"},
            weight=dict(weights),
        )
    span = bottom_y - top_y
    total_weight = sum(weights[ri] for ri in populated_rows)
    display_y: dict[int, float] = {}
    slot_height: dict[int, float] = {}
    cursor = top_y
    last_index = len(populated_rows) - 1
    for i, ri in enumerate(populated_rows):
        height = weights[ri] / total_weight * span
        slot_height[ri] = height
        if i == 0:
            # Top row anchors on the silhouette's top edge.
            display_y[ri] = cursor
        elif i == last_index:
            # Bottom row anchors on the silhouette's bottom edge.
            display_y[ri] = cursor + height
        else:
            # Middle rows anchor at the centre of their slot.
            display_y[ri] = cursor + height / 2
        cursor += height
    tier = {ri: "middle" for ri in populated_rows}
    tier[populated_rows[0]] = "top"
    tier[populated_rows[-1]] = "bottom"
    return RowPlan(
        rows=populated_rows,
        display_y=display_y,
        slot_height=slot_height,
        tier=tier,
        weight=dict(weights),
    )
