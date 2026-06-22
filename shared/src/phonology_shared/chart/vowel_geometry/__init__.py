"""Vowel-chart geometry, decomposed by conceptual layer.

How a vowel inventory becomes pixels, and which module answers
which question. The layers exist so that "where does a segment
belong" (inference), "how is a cell arranged" (display slots),
"how big is a cell" (boxes), "where is the boundary" (outline),
and "where do the labels sit" (furniture) can never silently
couple; the buttons-escaped-the-outline and labels-hug-the-outline
bugs both came from exactly such hidden coupling.

THE LAYER TABLE (dependency rules enforced by
``shared/tests/test_vowel_geometry_boundaries.py``):

================  =====================================  =====================
Module            Owns                                   Must never know
================  =====================================  =====================
chart/vowels.py   logical placement: feature bundles to  pixels, the outline
(layer 1)         (row, col, confidence, flags)
display_slots     display kinds, pair ordering, pair     pixels, the outline
(layer 2)         sides, effective backness anchors
cell_boxes        box sizes, density tiers, pair-shift   the outline
(layer 3)         conflicts, natural data-area size
outline           silhouette, shrink solver, edge        cells
(layer 4)         evaluators, polygon, cascade,          (``VowelChartCell``
                  row distribution                       is a forbidden name)
furniture         row labels, column headers, bands,     cell positions
(layer 5)         diphthong overlay                      (reads rows +
                                                         outline only)
pipeline          orchestration; the ONLY place boxes    n/a (imports all)
(cross-layer)     meet the outline (extent growth,
                  confinement)
================  =====================================  =====================

``model`` holds the seven frozen wire dataclasses every layer may
import; they are the complete renderer contract, flattened for the
web by ``view_models._vowel_chart_summary`` and pinned by
``test_wire_payload_completeness.py``.

THE PROPOSE-THEN-CONFINE PIPELINE (see ``pipeline`` for the stage
functions): inference proposes logical slots; display_slots
arranges them; the outline solves the boundary from the rows'
abstract width demands; projection maps anchors into it; the
outline then GROWS its reserved edge extent to wrap the widest
front-most / back-most cells (no chart width can absorb a
back-anchor overhang, because the back edge moves with the
anchor); finally residual overhangs (slant, corner arcs, renderer
rounding) are nudged inward as per-cell pixel offsets. Nudges are
shift-only and must never feed back into the solved size: folded
into the anchor instead, near-coincident anchors look separable by
widening and the width solver inflates dense PHOIBLE charts to
several times their natural width.

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

THE CASCADE INVARIANT (``outline.silhouette_for_data_width``):
cells render at ``anchor * dw + sign * extent_px``, so the
silhouette's corner fields must be recomputed for the ACTUAL
rendered width or the outline and the outermost cells drift apart.
Both renderers re-derive the polygon per rendered width: the
desktop calls the Python helper directly; the web mirrors it in JS.

JS PORT PARITY: ``web/main.js`` ports ``_silhouetteForDataWidth``
and ``_roundedSilhouettePolygonPoints`` from ``outline``; the
density-tier values relay through ``layout.css`` variables and the
``chart-style`` inline JSON baked by ``web/scripts/build.py``.
Changing the outline math or the density ladder means updating
those surfaces in the same commit.

FOUNDATION: the coordinate system this package projects onto (row
and backness anchors, trapezoid widths, axis adjacency) lives in
``chart/vowel_space.py``; ``outline``, ``display_slots``, and
``furniture`` import those constants from there, not from the
inference module. ``vowel_space`` -> {this package, ``chart.vowels``}
is the dependency direction: the coordinate system is the low layer
both rendering and inference sit on.
"""

from phonology_shared.chart.vowel_geometry.cell_boxes import (
    DENSITY_TIER_DENSE_BTN_H,
    DENSITY_TIER_DENSE_THRESHOLD,
    DENSITY_TIER_ULTRA_BTN_H,
    DENSITY_TIER_ULTRA_THRESHOLD,
    effective_button_height_px,
)
from phonology_shared.chart.vowel_geometry.display_slots import (
    PAIR_DISPLAY_KINDS,
)
from phonology_shared.chart.vowel_geometry.furniture import (
    label_midpoint_norm,
)
from phonology_shared.chart.vowel_geometry.model import (
    VOWEL_CHART_TITLE,
    VowelChartBand,
    VowelChartCell,
    VowelChartColHeader,
    VowelChartDiphthong,
    VowelChartGeometry,
    VowelChartRow,
    VowelChartSilhouette,
)
from phonology_shared.chart.vowel_geometry.outline import (
    rounded_silhouette_polygon_points,
    silhouette_for_data_width,
    silhouette_left_at_y,
    silhouette_right_at_y,
    vowel_silhouette,
)
from phonology_shared.chart.vowel_geometry.pipeline import (
    build_vowel_chart_geometry,
)

__all__ = [
    "DENSITY_TIER_DENSE_BTN_H",
    "DENSITY_TIER_DENSE_THRESHOLD",
    "DENSITY_TIER_ULTRA_BTN_H",
    "DENSITY_TIER_ULTRA_THRESHOLD",
    "PAIR_DISPLAY_KINDS",
    "VOWEL_CHART_TITLE",
    "VowelChartBand",
    "VowelChartCell",
    "VowelChartColHeader",
    "VowelChartDiphthong",
    "VowelChartGeometry",
    "VowelChartRow",
    "VowelChartSilhouette",
    "build_vowel_chart_geometry",
    "effective_button_height_px",
    "label_midpoint_norm",
    "rounded_silhouette_polygon_points",
    "silhouette_for_data_width",
    "silhouette_left_at_y",
    "silhouette_right_at_y",
    "vowel_silhouette",
]
