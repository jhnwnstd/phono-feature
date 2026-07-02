"""Pins the rounded silhouette polygon-points helper.

``rounded_silhouette_polygon_points`` is the shared source for the
"soft modern" silhouette redesign: each corner of the trapezoid /
triangle is replaced by ``segments_per_corner + 1`` points
interpolated along a quadratic Bezier so the CSS clip-path reads
as gently rounded. Both renderers consume the same helper output:
web bakes the points string into a CSS variable; desktop uses the
same ``VOWEL_SILHOUETTE_CORNER_RADIUS_FRAC`` constant to build its
``QPainterPath`` with native ``quadTo`` calls.

These tests pin the helper's contract: shape (4 corners), point
count, ordering, and clamp behaviour on tiny edges.
"""

from __future__ import annotations

from phonology_shared.chart.vowel_geometry import (
    VowelChartSilhouette,
    rounded_silhouette_polygon_points,
    vowel_silhouette,
)
from phonology_shared.chart.vowels import VowelChartShape
from phonology_shared.presentation.chart_style import (
    VOWEL_SILHOUETTE_CORNER_RADIUS_FRAC,
)


def _parse_points(points_str: str) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for entry in points_str.split(","):
        entry = entry.strip()
        if not entry:
            continue
        xs, ys = entry.split()
        assert xs.endswith("%") and ys.endswith("%")
        out.append((float(xs[:-1]), float(ys[:-1])))
    return out


def test_canonical_trapezoid_emits_expected_point_count() -> None:
    """A canonical trapezoid with the default segments_per_corner
    (5) emits ``4 * (5 + 1) = 24`` points: one set per corner."""
    sil = vowel_silhouette(VowelChartShape.TRAPEZOID)
    pts_str = rounded_silhouette_polygon_points(
        sil, VOWEL_SILHOUETTE_CORNER_RADIUS_FRAC
    )
    pts = _parse_points(pts_str)
    assert len(pts) == 24


def test_canonical_trapezoid_points_inside_unit_box() -> None:
    """Every emitted point must lie within the silhouette's
    bounding box (in percent). Catches a bug where the bezier
    interpolation overshoots the corner."""
    sil = vowel_silhouette(VowelChartShape.TRAPEZOID)
    pts_str = rounded_silhouette_polygon_points(
        sil, VOWEL_SILHOUETTE_CORNER_RADIUS_FRAC
    )
    pts = _parse_points(pts_str)
    # All points fit inside the [0%, 100%] x [0%, 100%] box (the
    # silhouette is itself fully inside [0, 1] in normalised
    # coords, and the helper only INSETS at corners, never
    # extends).
    for x, y in pts:
        assert 0.0 <= x <= 100.0, f"x={x} outside [0, 100]"
        assert 0.0 <= y <= 100.0, f"y={y} outside [0, 100]"


def test_segments_per_corner_controls_point_count() -> None:
    """``segments_per_corner`` is exposed as a kwarg so callers can
    tune the smoothness. Each corner adds ``segments_per_corner + 1``
    points."""
    sil = vowel_silhouette(VowelChartShape.TRAPEZOID)
    pts_3 = _parse_points(
        rounded_silhouette_polygon_points(
            sil, VOWEL_SILHOUETTE_CORNER_RADIUS_FRAC, segments_per_corner=3
        )
    )
    pts_7 = _parse_points(
        rounded_silhouette_polygon_points(
            sil, VOWEL_SILHOUETTE_CORNER_RADIUS_FRAC, segments_per_corner=7
        )
    )
    assert len(pts_3) == 4 * (3 + 1)
    assert len(pts_7) == 4 * (7 + 1)


def test_tiny_edge_clamps_inset_radius() -> None:
    """When an edge is shorter than ``2 * radius_frac``, the helper
    clamps the inset to 45 % of the edge length so the corner
    rounding doesn't overshoot the adjacent corner's arc. This
    catches the pathological "very narrow trapezoid" case."""
    # Trapezoid with a very narrow horizontal extent at the
    # bottom: top edge is normal but bottom edge has length
    # < 2 * radius_frac.
    radius_frac = 0.20
    tiny = VowelChartSilhouette(
        shape=VowelChartShape.TRAPEZOID,
        top_y=0.0,
        bottom_y=1.0,
        top_left=0.0,
        top_right=1.0,
        bottom_left=0.49,
        bottom_right=0.51,
        top_width=1.0,
        bottom_width=0.02,
    )
    pts_str = rounded_silhouette_polygon_points(tiny, radius_frac)
    pts = _parse_points(pts_str)
    # Even with a huge radius vs tiny bottom edge, the helper must
    # produce a valid 24-point polygon (no NaNs, no exceptions).
    assert len(pts) == 24
    for x, y in pts:
        # No NaN / inf
        assert x == x and y == y
        assert -1.0 <= x <= 101.0  # tolerate tiny rounding


def test_traversal_is_counterclockwise() -> None:
    """Points walk corners in CCW order (top-left, bottom-left,
    bottom-right, top-right). The first emitted point sits near
    the top-left corner (after the inset)."""
    sil = vowel_silhouette(VowelChartShape.TRAPEZOID)
    pts_str = rounded_silhouette_polygon_points(
        sil, VOWEL_SILHOUETTE_CORNER_RADIUS_FRAC
    )
    pts = _parse_points(pts_str)
    # First point: near the top-left corner. ``top_left`` in
    # normalised coords -> % is ``top_left * 100``.
    expected_tl_x = sil.top_left * 100.0
    expected_tl_y = sil.top_y * 100.0
    first_x, first_y = pts[0]
    # The first point is INSET along an edge from the corner,
    # so it won't be exactly at top_left, but should be close
    # (within ~5 % of the corner).
    assert abs(first_x - expected_tl_x) < 10.0
    assert abs(first_y - expected_tl_y) < 10.0


def test_silhouette_for_data_width_flush_with_back_cell_extent() -> None:
    """The CASCADE invariant: at any data width, the silhouette's
    top-right x in pixels equals the back-rounded cell's outer
    right pixel. Pre-cascade the math drifted at non-canonical
    widths; post-cascade ``silhouette_for_data_width`` recomputes
    the corner from ``back_anchor + extent_px / dw`` so flush is
    by construction.

    Cell math: cell_right_px = anchor * dw + pair_shift_px + btn_w/2
    Silhouette: top_right_norm * dw + back_right_pixel_offset
    Cascade: top_right_norm == back_anchor + extent_px / dw
            -> top_right_norm * dw == back_anchor * dw + extent_px
    Flush iff: extent_px == pair_shift_px + btn_w/2."""
    from phonology_shared.chart.vowel_geometry import silhouette_for_data_width
    from phonology_shared.presentation.constants import BTN_W
    from phonology_shared.presentation.layout import VOWEL_PAIR_GAP_PX

    sil = vowel_silhouette(VowelChartShape.TRAPEZOID)
    pair_shift_px = (BTN_W + VOWEL_PAIR_GAP_PX) / 2
    expected_extent = pair_shift_px + BTN_W / 2
    # Test multiple data widths; the cascade must hold at all.
    for dw in (200, 232, 320, 440):
        adjusted = silhouette_for_data_width(sil, dw)
        silhouette_right_px = adjusted.top_right * dw
        cell_right_px = adjusted.back_anchor * dw + expected_extent
        assert abs(silhouette_right_px - cell_right_px) < 1.0, (
            f"At dw={dw}: silhouette_right_px={silhouette_right_px}, "
            f"cell_right_px={cell_right_px}; cascade broken"
        )


def test_silhouette_for_data_width_flush_with_front_cell_extent() -> None:
    """Mirror of the back-side invariant for the front side. At
    any data width, the silhouette's top-left x in pixels equals
    the front-unrounded cell's outer left pixel.

    Cell math: cell_left_px = anchor * dw - pair_shift_px - btn_w/2
    Silhouette: top_left_norm * dw
    Cascade: top_left_norm == front_anchor_at_top - extent_px / dw
            -> top_left_norm * dw == front_anchor_at_top * dw - extent_px
    Flush iff: extent_px == pair_shift_px + btn_w/2."""
    from phonology_shared.chart.vowel_geometry import silhouette_for_data_width
    from phonology_shared.presentation.constants import BTN_W
    from phonology_shared.presentation.layout import VOWEL_PAIR_GAP_PX

    sil = vowel_silhouette(VowelChartShape.TRAPEZOID)
    pair_shift_px = (BTN_W + VOWEL_PAIR_GAP_PX) / 2
    expected_extent = pair_shift_px + BTN_W / 2
    for dw in (200, 232, 320, 440):
        adjusted = silhouette_for_data_width(sil, dw)
        silhouette_left_px = adjusted.top_left * dw
        cell_left_px = adjusted.front_anchor_at_top * dw - expected_extent
        assert abs(silhouette_left_px - cell_left_px) < 1.0, (
            f"At dw={dw}: silhouette_left_px={silhouette_left_px}, "
            f"cell_left_px={cell_left_px}; cascade broken"
        )


def test_silhouette_for_data_width_symmetric_front_back_offset() -> None:
    """Front and back silhouette edges should be inset/outset by
    the SAME ``cell_outer_extent_px`` from their respective
    anchors at any data width. Asymmetric offsets would
    re-introduce the original bug (front gap, back flush)."""
    from phonology_shared.chart.vowel_geometry import silhouette_for_data_width

    sil = vowel_silhouette(VowelChartShape.TRAPEZOID)
    for dw in (200, 232, 320, 440):
        adjusted = silhouette_for_data_width(sil, dw)
        front_inset = adjusted.front_anchor_at_top - adjusted.top_left
        back_outset = adjusted.top_right - adjusted.back_anchor
        assert abs(front_inset - back_outset) < 1e-9, (
            f"At dw={dw}: front_inset={front_inset}, "
            f"back_outset={back_outset}; asymmetry would surface as "
            f"visible drift between front and back cells"
        )


def _edge_x_from_polygon(
    chain: list[tuple[float, float]], y_pct: float
) -> float | None:
    """Boundary x (in percent) at ``y_pct`` by walking a polygon
    chain whose y values are nondecreasing. Returns ``None`` when
    ``y_pct`` falls outside the chain's y range."""
    for (x0, y0), (x1, y1) in zip(chain, chain[1:]):
        lo, hi = min(y0, y1), max(y0, y1)
        if lo <= y_pct <= hi:
            if hi == lo:
                return (x0 + x1) / 2.0
            t = (y_pct - y0) / (y1 - y0)
            return x0 + t * (x1 - x0)
    return None


def _assert_edge_helpers_match_polygon(sil: VowelChartSilhouette) -> None:
    """Core assertion shared by the parametrised edge tests: the
    analytic ``silhouette_left_at_y`` / ``silhouette_right_at_y``
    helpers and a densely sampled ``rounded_silhouette_polygon_points``
    describe the same boundary. The two edge helpers are mirrored
    hand-written bezier math; this is the cross-check that keeps a
    one-sided edit from silently desynchronising them from the
    polygon both renderers actually draw."""
    from phonology_shared.chart.vowel_geometry import (
        silhouette_left_at_y,
        silhouette_right_at_y,
    )

    spc = 64  # dense sampling so the polygon approximates the bezier
    pts = _parse_points(
        rounded_silhouette_polygon_points(
            sil, VOWEL_SILHOUETTE_CORNER_RADIUS_FRAC, segments_per_corner=spc
        )
    )
    per_corner = spc + 1
    # CCW traversal: top-left arc, bottom-left arc, bottom-right
    # arc, top-right arc. Left boundary = first two arcs walked
    # top to bottom; right boundary = last two arcs reversed.
    left_chain = pts[: 2 * per_corner]
    right_chain = list(reversed(pts[2 * per_corner :]))
    span = sil.bottom_y - sil.top_y
    n_samples = 80
    for i in range(n_samples + 1):
        chart_y = sil.top_y + span * i / n_samples
        y_pct = chart_y * 100.0
        expected_left = _edge_x_from_polygon(left_chain, y_pct)
        if expected_left is not None:
            got_left = silhouette_left_at_y(sil, chart_y) * 100.0
            assert abs(got_left - expected_left) < 0.2, (
                f"left edge at chart_y={chart_y:.4f}: helper "
                f"{got_left:.4f}% vs polygon {expected_left:.4f}%"
            )
        expected_right = _edge_x_from_polygon(right_chain, y_pct)
        if expected_right is not None:
            got_right = silhouette_right_at_y(sil, chart_y) * 100.0
            assert abs(got_right - expected_right) < 0.2, (
                f"right edge at chart_y={chart_y:.4f}: helper "
                f"{got_right:.4f}% vs polygon {expected_right:.4f}%"
            )


def test_edge_helpers_match_polygon_canonical_trapezoid() -> None:
    _assert_edge_helpers_match_polygon(
        vowel_silhouette(VowelChartShape.TRAPEZOID)
    )


def test_edge_helpers_match_polygon_triangle() -> None:
    _assert_edge_helpers_match_polygon(
        vowel_silhouette(VowelChartShape.TRIANGLE)
    )


def test_edge_helpers_match_polygon_narrow_row_range() -> None:
    """An inventory populating only the middle tiers gets a less
    slanted silhouette; the corner regions move with it."""
    _assert_edge_helpers_match_polygon(
        vowel_silhouette(VowelChartShape.TRAPEZOID, 2, 4)
    )


def test_edge_helpers_match_polygon_shrunken_widths() -> None:
    """The shrink solver rebuilds corners via
    ``_silhouette_with_widths``; the edge helpers must track the
    rebuilt silhouette, since that is the one the geometry bakes
    into ``VowelChartRow.silhouette_left`` / ``silhouette_right``."""
    from phonology_shared.chart.vowel_geometry.outline import (
        _silhouette_with_widths,
    )

    sil = vowel_silhouette(VowelChartShape.TRAPEZOID)
    shrunk = _silhouette_with_widths(
        sil, sil.top_width * 0.85, sil.bottom_width * 0.85
    )
    _assert_edge_helpers_match_polygon(shrunk)


def test_inset_silhouette_for_draw_outsets_symmetrically() -> None:
    """The draw-only inset pushes every corner OUTWARD by exactly
    ``inset_px / data_w`` horizontally and ``inset_px / data_h``
    vertically, symmetric left/right, and is a no-op at zero inset."""
    from phonology_shared.chart.vowel_geometry import (
        inset_silhouette_for_draw,
        silhouette_for_data_width,
    )

    sil = silhouette_for_data_width(
        vowel_silhouette(VowelChartShape.TRAPEZOID), 300
    )
    inset_px = 14.0
    out = inset_silhouette_for_draw(sil, 300, 200, inset_px)
    dx = inset_px / 300
    dy = inset_px / 200
    assert abs((sil.top_left - out.top_left) - dx) < 1e-9
    assert abs((sil.bottom_left - out.bottom_left) - dx) < 1e-9
    assert abs((out.top_right - sil.top_right) - dx) < 1e-9
    assert abs((out.bottom_right - sil.bottom_right) - dx) < 1e-9
    assert abs((sil.top_y - out.top_y) - dy) < 1e-9
    assert abs((out.bottom_y - sil.bottom_y) - dy) < 1e-9
    # symmetric left vs right outset
    assert (
        abs((sil.top_left - out.top_left) - (out.top_right - sil.top_right))
        < 1e-9
    )
    # zero inset (and non-positive dims) are no-ops
    assert inset_silhouette_for_draw(sil, 300, 200, 0) == sil
    assert inset_silhouette_for_draw(sil, 0, 200, 14) == sil


def test_inset_is_draw_only_leaves_confinement_source_flush() -> None:
    """``inset_silhouette_for_draw`` must NOT be the confinement source.
    The confinement path reads ``silhouette_for_data_width`` (flush with
    the cell extent); the inset is a separate OUTSET applied only when
    drawing. This pins the separation: the flush corners and the inset
    corners differ, and the cascade helper is untouched by the inset."""
    from phonology_shared.chart.vowel_geometry import (
        inset_silhouette_for_draw,
        silhouette_for_data_width,
    )

    base = vowel_silhouette(VowelChartShape.TRAPEZOID)
    flush = silhouette_for_data_width(base, 300)
    outset = inset_silhouette_for_draw(flush, 300, 200, 14)
    # The cascade (confinement source) is unchanged and NOT inset.
    assert silhouette_for_data_width(base, 300) == flush
    assert outset.top_left < flush.top_left
    assert outset.top_right > flush.top_right
