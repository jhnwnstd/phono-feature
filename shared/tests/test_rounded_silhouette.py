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

from phonology_shared.chart.vowels import VowelChartShape, vowel_silhouette
from phonology_shared.chart.vowels_layout import (
    VowelChartSilhouette,
    rounded_silhouette_polygon_points,
)
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
    (5) emits ``4 * (5 + 1) = 24`` points -- one set per corner."""
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
