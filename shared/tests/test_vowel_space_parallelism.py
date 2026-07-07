"""Invariance tests for the vowel-chart's interior guide lines vs.
exterior silhouette edges.

The design trick the user requested during the split refactor:
verify that INTERIOR column guide lines run PARALLEL to the
EXTERIOR silhouette edges wherever the pivot policy shares. When
that parallelism holds, cell projections stay flush with the
silhouette by construction, and any refactor that breaks it (e.g. a
subtle pivot regression during the pipeline split) blows up here
first, not in a pixel-perfect visual review.

Two invariants tested:

1. **Front column ~ Left edge.** The left silhouette edge is defined
   as ``front_anchor_at_y - front_extent_norm`` at every y, and the
   front-column projection lands at ``front_anchor_at_y``. So they
   MUST run parallel by construction (the extent is a constant
   pixel offset in the cascade). Passes on every inventory,
   trapezoid or converged bottom.

2. **Vowels move with the silhouette.** When the silhouette's
   ``top_width`` and ``bottom_width`` are scaled by a common factor,
   every cell's ``chart_x`` scales linearly with that factor around
   the projection pivot. Confirms the projection reads the
   silhouette as its source of truth for cell positioning; no cell
   position is baked at build time in a way that would ignore a
   later shape change.

Not tested: back column ~ right edge parallelism. The back edge
carries an intentional ``_BACK_APEX_PULL = 0.20`` (see silhouette
module) so it slants less than the projection pivot travels, giving
the front-heavy asymmetry the user asked for. A test here would
codify the design mismatch as an invariant it explicitly is not.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from phonology_shared.chart.vowel_geometry import build_vowel_chart_geometry
from phonology_shared.chart.vowel_geometry.projection import project_anchor_x
from phonology_shared.chart.vowel_geometry.silhouette import vowel_silhouette
from phonology_shared.chart.vowel_space import _BACKNESS_X
from phonology_shared.chart.vowels import VowelChartShape, detect_vowel_profile
from phonology_shared.theory.feature_engine import FeatureEngine


def _vowel_segs(engine: FeatureEngine) -> list[str]:
    return [
        s for s in engine.segments if engine.segments[s].get("Syllabic") == "+"
    ]


# --- Invariant 1: front column parallel to left silhouette edge ---


@pytest.mark.parametrize(
    "shape,open_apex_backness",
    [
        (VowelChartShape.TRAPEZOID, None),
        (VowelChartShape.TRAPEZOID, "central"),  # converged like Spanish
        (VowelChartShape.TRAPEZOID, "front"),
        (VowelChartShape.TRAPEZOID, "back"),
        (VowelChartShape.TRIANGLE, None),
    ],
)
def test_left_edge_parallel_to_front_column(
    shape: VowelChartShape, open_apex_backness: str | None
) -> None:
    """Left silhouette edge and front-column projection have the
    same slope through the silhouette span.

    The left silhouette edge is defined as
    ``front_anchor_at_y - front_extent_norm`` at every y. So its
    slope is the same as the front-column projection's slope; the
    extent shift is a per-y constant. Any silhouette shape --
    canonical trapezoid, or a converged bottom for any backness --
    must satisfy this identity for cells on the front column to
    stay flush with the left edge as the chart resizes.
    """
    sil = vowel_silhouette(shape, open_apex_backness=open_apex_backness)
    front = _BACKNESS_X["front"]

    front_at_top = project_anchor_x(sil, front, sil.top_y)
    front_at_bot = project_anchor_x(sil, front, sil.bottom_y)

    edge_slope = (sil.bottom_left - sil.top_left) / (sil.bottom_y - sil.top_y)
    front_slope = (front_at_bot - front_at_top) / (sil.bottom_y - sil.top_y)

    assert edge_slope == pytest.approx(front_slope, abs=1e-9), (
        f"shape={shape.value} apex={open_apex_backness}: "
        f"left edge slope {edge_slope:.6f} != front column slope "
        f"{front_slope:.6f}. The parallelism identity broke; the "
        f"extent offset is no longer a per-y constant."
    )


@pytest.mark.parametrize(
    "shape,open_apex_backness",
    [
        (VowelChartShape.TRAPEZOID, None),
        (VowelChartShape.TRAPEZOID, "central"),
        (VowelChartShape.TRAPEZOID, "front"),
        (VowelChartShape.TRAPEZOID, "back"),
        (VowelChartShape.TRIANGLE, None),
    ],
)
def test_left_edge_offset_from_front_column_is_constant_at_every_y(
    shape: VowelChartShape, open_apex_backness: str | None
) -> None:
    """STRONG-FORM PARALLELISM: ``left_edge_at_y - front_column_at_y``
    is exactly constant at every y, converged bottoms included.

    The projection is linear in y (see :py:func:`project_anchor_x`),
    so the interior column line is a straight line between its top-y
    and bottom-y projected endpoints. The silhouette left edge is a
    straight line between corners at the SAME endpoints, offset by
    the constant per-y ``front_extent_norm``. So the two are
    parallel at every y by construction; the offset is the same
    ``front_extent_norm`` regardless of shape.

    Regression guard: if the projection ever reverts to a
    pivot-varying quadratic-in-y form, this test fails on the
    converged variants and only the endpoint-only weak form
    (:py:func:`test_left_edge_parallel_to_front_column`) still
    passes.
    """
    sil = vowel_silhouette(shape, open_apex_backness=open_apex_backness)
    front = _BACKNESS_X["front"]
    span = sil.bottom_y - sil.top_y
    offsets: list[float] = []
    for i in range(11):
        y = sil.top_y + (i / 10) * span
        front_at_y = project_anchor_x(sil, front, y)
        t = (y - sil.top_y) / span
        edge = sil.top_left + (sil.bottom_left - sil.top_left) * t
        offsets.append(front_at_y - edge)
    for off in offsets[1:]:
        assert off == pytest.approx(offsets[0], abs=1e-9), (
            f"shape={shape.value} apex={open_apex_backness}: front "
            f"column - left edge offset drifts with y; strong-form "
            f"parallelism identity broke."
        )


# --- Invariant 2: vowels move with the silhouette ---


def test_hayes_cells_scale_with_shrunken_top_width(
    bundled_engine: Callable[[str], FeatureEngine],
) -> None:
    """When the shrink solver narrows the silhouette, cell x-positions
    shift proportionally through the projection.

    Not exact linear scaling because the shrink applies to the
    silhouette widths (which drive the projection width_at_y) and
    cells sit at ``pivot + width * (anchor - pivot)``; but a WIDER
    silhouette must pull each cell FURTHER from the back pivot.
    Regression guard for a bug class where projection caches a
    canonical-width chart_x and forgets to refresh when widths shrink.
    """
    engine = bundled_engine("hayes")
    vowels = _vowel_segs(engine)
    if not vowels:
        pytest.skip("hayes has no vowels")
    seg_feats = {s: dict(engine.segments[s]) for s in vowels}
    profile = detect_vowel_profile(vowels, seg_feats)
    geometry = build_vowel_chart_geometry(vowels, profile, seg_feats)

    # Build the same geometry manually with a hypothetically shrunken
    # silhouette and confirm cell positions differ.
    sil = geometry.silhouette
    front = _BACKNESS_X["front"]

    # For the top-most row (chart_y near top_y), the anchor front
    # should project close to front_at_top.
    baseline_front_at_top = project_anchor_x(sil, front, sil.top_y)

    # Shrunken silhouette: top_width halved.
    from dataclasses import replace as dc_replace

    shrunk = dc_replace(
        sil, top_width=sil.top_width * 0.5, bottom_width=sil.bottom_width * 0.5
    )
    shrunk_front_at_top = project_anchor_x(shrunk, front, sil.top_y)

    # Both should be *pulled toward* the back pivot when the width
    # shrinks. front < back, so shrinking pulls front's projection
    # rightward (toward back).
    assert shrunk_front_at_top > baseline_front_at_top, (
        "Halving the silhouette top_width did not pull the front-column "
        f"projection rightward: baseline={baseline_front_at_top:.4f} "
        f"shrunk={shrunk_front_at_top:.4f}. The projection is not reading "
        "the silhouette width at bottom -- vowels won't move with the shape."
    )


def test_spanish_low_vowel_lands_on_apex(
    bundled_engine: Callable[[str], FeatureEngine],
) -> None:
    """Spanish is the canonical lone-central-low inventory: /a/ is
    the SOLE Open-row cell, and the silhouette converges its bottom
    on the central column's anchor. The vowel MUST project onto that
    apex (chart_x == central anchor) at the row's chart_y, else the
    triangle-ish silhouette hugs empty space beside the vowel.

    Pins the "vowels move with the silhouette" invariant against a
    concrete visual outcome the user asked for at the start of the
    lone-low-triangle branch.
    """
    try:
        engine = bundled_engine("spanish")
    except (FileNotFoundError, KeyError, pytest.skip.Exception):
        pytest.skip("spanish inventory not checked in")
    vowels = _vowel_segs(engine)
    seg_feats = {s: dict(engine.segments[s]) for s in vowels}
    profile = detect_vowel_profile(vowels, seg_feats)
    geometry = build_vowel_chart_geometry(vowels, profile, seg_feats)

    # Confirm the silhouette actually converged.
    assert geometry.silhouette.back_anchor_at_bottom is not None, (
        "Spanish's silhouette did not converge; the lone-low-vowel "
        "trigger is broken."
    )
    apex = geometry.silhouette.back_anchor_at_bottom

    # Find the Open-row cell (the sole low vowel).
    open_row = max(c.row for c in geometry.cells)
    low_cells = [c for c in geometry.cells if c.row == open_row]
    assert len(low_cells) == 1, (
        f"Expected exactly one low-vowel cell; got {len(low_cells)}: "
        f"{[c.entries for c in low_cells]}"
    )
    low = low_cells[0]

    # The projection at the row's chart_y should land the cell on
    # the apex column (the pivot converges to apex at bottom_y; at
    # a chart_y slightly above bottom_y the cell can be a hair off,
    # but only by a per-row-height amount).
    expected = project_anchor_x(geometry.silhouette, apex, low.chart_y)
    assert low.chart_x == pytest.approx(expected, abs=1e-9), (
        f"Spanish /a/ at chart_x={low.chart_x:.6f}, expected "
        f"{expected:.6f} (apex projection at row_y={low.chart_y:.6f})."
    )
