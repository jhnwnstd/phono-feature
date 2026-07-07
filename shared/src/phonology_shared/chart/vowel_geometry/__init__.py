"""Vowel-chart geometry, decomposed by conceptual layer.

How a vowel inventory becomes pixels, and which module answers
which question. The layers exist so that "where does a segment
belong" (inference), "how is a cell arranged" (classifier + slot
assigner), "how big is a cell" (boxes), "where is the boundary"
(silhouette + shrink + projection + rows), and "where do the
labels sit" (furniture) can never silently couple; the
buttons-escaped-the-outline and labels-hug-the-outline bugs both
came from exactly such hidden coupling.

THE LAYER TABLE (dependency rules enforced by
``shared/tests/test_vowel_geometry_boundaries.py``):

================  =====================================  =====================
Module            Owns                                   Must never know
================  =====================================  =====================
chart/vowels.py   logical placement: feature bundles to  pixels, the silhouette
(layer 1)         (row, col, confidence, flags)
space             coordinate constants (col-to-anchor,   pixels, the silhouette
(layer 1)         Open-row index, neutral reroute maps)
classifier        display kinds, pair ordering,          pixels, coordinates
(layer 2a)        CONTRAST_SET grid layout
slots             pair sides, canonical backness         pixels, the silhouette
(layer 2b)        anchors, same-anchor pair-shift
                  conflict resolver
cell_boxes        box sizes, density tiers, natural      the silhouette
(layer 3)         data-area size
silhouette        VowelChartSilhouette dataclass,        cells
(layer 4a)        corner arithmetic, polygon, cascade,   (``VowelChartCell``
                  edge-at-y evaluators                   is a forbidden name)
shrink            two-stage width shrink solver          cells, the silhouette
(layer 4b)                                               dataclass (widths in,
                                                         widths out)
projection        anchor -> data-x under converged       cells
(layer 4c)        bottom slant
rows              row-plan distribution                  cells, the silhouette
(layer 4d)
furniture         row labels, column headers,            cell positions
(layer 5)         diphthong chip list                    (reads rows +
                                                         silhouette only)
pipeline          orchestration; the ONLY place boxes    n/a (imports all)
(cross-layer)     meet the silhouette (extent growth,
                  confinement)
================  =====================================  =====================

``model`` holds the seven frozen wire dataclasses every layer may
import; they are the complete renderer contract, flattened for the
web by ``view_models._vowel_chart_summary`` and pinned by
``test_wire_payload_completeness.py``.

THE PROPOSE-THEN-CONFINE PIPELINE (see ``pipeline`` for the stage
functions): inference proposes logical slots; the classifier picks
each cell's display kind and the slot assigner picks each cell's
pair side; the shrink solver reduces the silhouette widths to fit
the rows' abstract width demands; projection maps anchors into the
resulting silhouette; the silhouette then GROWS its reserved edge
extent to wrap the widest front-most / back-most cells (no chart
width can absorb a back-anchor overhang, because the back edge
moves with the anchor); finally residual overhangs (slant, corner
arcs, renderer rounding) are nudged inward as per-cell pixel
offsets. Nudges are shift-only and must never feed back into the
solved size: folded into the anchor instead, near-coincident
anchors look separable by widening and the width solver inflates
dense PHOIBLE charts to several times their natural width.

THE ROW-FIT INVARIANT (vertical mate of the cascade): row slots
are distributed proportional to each row's rendered content height
in PIXELS (``cell_boxes.content_height_px``, density tiers
included; raw button counts misallocate because per-button height
varies by tier), and ``pipeline._fit_outline_and_size`` floors the
natural height so the silhouette span covers the summed row
heights plus gaps. At natural size every slot therefore covers its
content; rendered SHORTER than natural, both renderers re-derive
per-button heights from ``VowelChartRow.slot_height_norm`` (down
to ``chart_style.VOWEL_BTN_MIN_H_PX``) so deep stacks shrink
instead of invading neighbouring rows.

THE CASCADE INVARIANT (``silhouette.silhouette_for_data_width``):
cells render at ``anchor * dw + sign * extent_px``, so the
silhouette's corner fields must be recomputed for the ACTUAL
rendered width or the outline and the outermost cells drift apart.
Both renderers re-derive the polygon per rendered width: the
desktop calls the Python helper directly; the web mirrors it in JS.

JS PORT PARITY: ``web/main.js`` ports ``_silhouetteForDataWidth``,
``_roundedSilhouettePolygonPoints``, ``_cornersFromAnchors``,
``_backEdgeAtBottom``, and ``_insetSilhouetteForDraw`` from
``silhouette``; the density-tier values relay through ``layout.css``
variables and the ``chart-style`` inline JSON baked by
``web/scripts/build.py``. Changing the silhouette math or the
density ladder means updating those surfaces in the same commit.

FOUNDATION: the coordinate system this package projects onto (row
and backness anchors, trapezoid widths, axis adjacency) lives in
``chart/vowel_space.py``, with the vowel-geometry-facing view (col-
to-anchor map, Open-row index, neutral reroute maps) in ``space``;
``silhouette``, ``classifier``, ``slots``, ``cell_boxes``, and
``furniture`` import their coordinate facts from ``space``, not
from the inference module. ``vowel_space`` -> {this package,
``chart.vowels``} is the dependency direction: the coordinate
system is the low layer both rendering and inference sit on.
"""

from phonology_shared.chart.vowel_geometry.cell_boxes import (
    DENSITY_TIER_DENSE_BTN_H,
    DENSITY_TIER_DENSE_THRESHOLD,
    DENSITY_TIER_ULTRA_BTN_H,
    DENSITY_TIER_ULTRA_THRESHOLD,
    effective_button_height_px,
)
from phonology_shared.chart.vowel_geometry.classifier import (
    PAIR_DISPLAY_KINDS,
)
from phonology_shared.chart.vowel_geometry.model import (
    VOWEL_CHART_TITLE,
    VowelChartCell,
    VowelChartColHeader,
    VowelChartGeometry,
    VowelChartRow,
    VowelChartSilhouette,
)
from phonology_shared.chart.vowel_geometry.pipeline import (
    build_vowel_chart_geometry,
)
from phonology_shared.chart.vowel_geometry.silhouette import (
    inset_silhouette_for_draw,
    rounded_silhouette_polygon_points,
    silhouette_for_data_width,
    silhouette_left_at_y,
    silhouette_right_at_y,
    straight_left_at_y,
    straight_right_at_y,
    vowel_silhouette,
)

__all__ = [
    "DENSITY_TIER_DENSE_BTN_H",
    "DENSITY_TIER_DENSE_THRESHOLD",
    "DENSITY_TIER_ULTRA_BTN_H",
    "DENSITY_TIER_ULTRA_THRESHOLD",
    "PAIR_DISPLAY_KINDS",
    "VOWEL_CHART_TITLE",
    "VowelChartCell",
    "VowelChartColHeader",
    "VowelChartGeometry",
    "VowelChartRow",
    "VowelChartSilhouette",
    "build_vowel_chart_geometry",
    "effective_button_height_px",
    "inset_silhouette_for_draw",
    "rounded_silhouette_polygon_points",
    "silhouette_for_data_width",
    "silhouette_left_at_y",
    "silhouette_right_at_y",
    "straight_left_at_y",
    "straight_right_at_y",
    "vowel_silhouette",
]
