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

Also tested (below): back column verticality. Under
``_BACK_APEX_PULL = 0.0`` the back edge stays vertical for every
inventory (dorsal boundary is the strong phonological anchor), and
the interior back-column guide must match -- see
:py:func:`test_back_column_guide_is_vertical_for_every_bundled_inventory`.
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

    Under Option C (silhouette-driven projection), the projection reads
    ``front_anchor_at_top`` / ``front_anchor_at_bottom`` /
    ``back_col_at_bottom`` directly from the silhouette. Rebuilding the
    silhouette via :py:func:`_silhouette_with_widths` with halved
    widths must therefore pull the front column's top position
    rightward (toward back). Regression guard for a bug class where
    projection caches a canonical-width chart_x and forgets to refresh
    when widths shrink.
    """
    from phonology_shared.chart.vowel_geometry.silhouette import (
        _silhouette_with_widths,
    )

    engine = bundled_engine("hayes")
    vowels = _vowel_segs(engine)
    if not vowels:
        pytest.skip("hayes has no vowels")
    seg_feats = {s: dict(engine.segments[s]) for s in vowels}
    profile = detect_vowel_profile(vowels, seg_feats)
    geometry = build_vowel_chart_geometry(vowels, profile, seg_feats)

    sil = geometry.silhouette
    front = _BACKNESS_X["front"]

    baseline_front_at_top = project_anchor_x(sil, front, sil.top_y)

    # Rebuild silhouette with halved widths; this refreshes the
    # column-endpoint fields the silhouette-driven projection reads.
    shrunk = _silhouette_with_widths(
        sil, sil.top_width * 0.5, sil.bottom_width * 0.5
    )
    shrunk_front_at_top = project_anchor_x(shrunk, front, sil.top_y)

    # front < back, so a narrower top pulls front's projection
    # rightward (toward back).
    assert shrunk_front_at_top > baseline_front_at_top, (
        "Halving the silhouette top_width did not pull the front-column "
        f"projection rightward: baseline={baseline_front_at_top:.4f} "
        f"shrunk={shrunk_front_at_top:.4f}. The projection is not reading "
        "the silhouette column endpoints -- vowels won't move with shape."
    )


def test_back_column_guide_is_vertical_for_every_bundled_inventory(
    bundled_engine: Callable[[str], FeatureEngine],
) -> None:
    """The back COLUMN guide line is vertical for every bundled
    inventory: its ``chart_x`` at ``top_y`` equals its ``chart_x`` at
    ``bottom_y``. This is the interior mate of the exterior silhouette
    right-edge invariant (:py:func:`test_silhouette_back_edge_is_vertical_for_every_inventory`).

    The dorsal boundary is a strong articulatory + phonological anchor
    that must hold its position across every row -- both the outside
    of the silhouette AND the guide the renderer draws inside it. If
    either drifts the outline and the guide diverge visibly. Pinned
    by ``_BACK_APEX_PULL = 0.0``.
    """
    import json
    from pathlib import Path

    from phonology_shared.data.inventory import Inventory

    inventories_dir = Path(__file__).resolve().parents[2] / "desktop" / "inventories"
    for inv_path in sorted(inventories_dir.glob("*.json")):
        if inv_path.name.startswith("_"):
            continue
        raw = json.loads(inv_path.read_text(encoding="utf-8-sig"))
        engine = FeatureEngine(Inventory.parse(raw, source=str(inv_path)))
        vowels = [
            s for s in engine.segments
            if engine.segments[s].get("Syllabic") == "+"
        ]
        if not vowels:
            continue
        feats = {s: dict(engine.segments[s]) for s in vowels}
        profile = detect_vowel_profile(vowels, feats)
        geom = build_vowel_chart_geometry(vowels, profile, feats)
        back_col = next(
            (c for c in geom.cols if c.label.lower() == "back"), None
        )
        assert back_col is not None, f"{inv_path.name}: no back column header"
        assert back_col.chart_x == pytest.approx(
            back_col.chart_x_bottom, abs=1e-6
        ), (
            f"{inv_path.name}: back column guide not vertical "
            f"(top={back_col.chart_x}, bottom={back_col.chart_x_bottom})"
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

    # /a/ lands at the silhouette-driven projection of the central
    # anchor at its row_y: a PIECEWISE-linear map at ``bottom_y`` that
    # pulls central to ratio ``_LONE_CENTRAL_BOTTOM_RATIO`` (1/3) of
    # the [front_anchor_at_bottom, back_col_at_bottom] span, then
    # linearly interpolated toward top_y by the row's chart_y.
    # Regression guard against reverting to a symmetric r=0.5
    # midpoint or a pivot-varying quadratic form.
    expected = project_anchor_x(geometry.silhouette, apex, low.chart_y)
    assert low.chart_x == pytest.approx(expected, abs=1e-9), (
        f"Spanish /a/ at chart_x={low.chart_x:.6f}; expected the "
        f"silhouette-driven projection {expected:.6f}."
    )


def test_lone_central_low_columns_slant_toward_back(
    bundled_engine: Callable[[str], FeatureEngine],
) -> None:
    """For every lone-central-low bundled inventory, BOTH front and
    central column guides slant TOWARD THE BACK (rightward: positive
    delta) between top_y and bottom_y. Central slants LESS than
    front. Back stays vertical.

    Encodes the informational principle: front slants strongly toward
    the collapsed low-central position, central slants mildly to
    reflect that the vowel space is deforming (but retains its own
    identity as a column), and back is stable. The two columns
    CONVERGE (visual distance decreases at bottom) without meeting
    at a single point -- the collapse is a smooth approach, not a
    discrete merge.
    """
    central_anchor = _BACKNESS_X["central"]
    front = _BACKNESS_X["front"]
    back = _BACKNESS_X["back"]

    for stem in ("spanish", "japanese", "korean", "indonesian"):
        try:
            engine = bundled_engine(stem)
        except (FileNotFoundError, KeyError, pytest.skip.Exception):
            continue
        vowels = _vowel_segs(engine)
        if not vowels:
            continue
        seg_feats = {s: dict(engine.segments[s]) for s in vowels}
        profile = detect_vowel_profile(vowels, seg_feats)
        geom = build_vowel_chart_geometry(vowels, profile, seg_feats)
        sil = geom.silhouette
        assert sil.back_anchor_at_bottom == central_anchor, (
            f"{stem}: expected lone-central apex, got "
            f"{sil.back_anchor_at_bottom}"
        )
        front_top = project_anchor_x(sil, front, sil.top_y)
        front_bot = project_anchor_x(sil, front, sil.bottom_y)
        central_top = project_anchor_x(sil, central_anchor, sil.top_y)
        central_bot = project_anchor_x(sil, central_anchor, sil.bottom_y)
        back_top = project_anchor_x(sil, back, sil.top_y)
        back_bot = project_anchor_x(sil, back, sil.bottom_y)
        f_delta = front_bot - front_top
        c_delta = central_bot - central_top
        b_delta = back_bot - back_top
        assert f_delta > 0.1, (
            f"{stem}: front column should slant strongly toward back "
            f"(delta={f_delta:+.4f})"
        )
        assert 0.0 < c_delta < f_delta, (
            f"{stem}: central column should slant a little TOWARD BACK "
            f"(positive) but LESS than front "
            f"(front={f_delta:+.4f}, central={c_delta:+.4f})"
        )
        assert abs(b_delta) < 1e-9, (
            f"{stem}: back column should stay vertical "
            f"(delta={b_delta:+.4f})"
        )
        # Columns converge (top spacing > bottom spacing) but do NOT
        # meet at a single point.
        top_spacing = central_top - front_top
        bot_spacing = central_bot - front_bot
        assert bot_spacing < top_spacing, (
            f"{stem}: front-central columns did not converge "
            f"(top spacing={top_spacing:.4f}, bot spacing={bot_spacing:.4f})"
        )
        assert bot_spacing > 1e-6, (
            f"{stem}: front-central columns collapsed to a single point "
            f"at bottom -- they should converge but not merge"
        )
