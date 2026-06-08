"""Vowel-chart visual policy: every constant the renderers consume.

The vowel chart's chrome (title, axis labels, silhouette outline,
diphthong arrows) and behaviour (focused / show-all opacity, lift
geometry) need to render the same on the desktop's Qt widget and
the web's DOM / SVG. Before this module the two renderers held
parallel literals that quietly drifted: title font 8pt-Bold (Qt)
vs 11px / 600 (CSS), arrow stroke 1.75 px vs 0.6 SVG user-units,
focused opacity 1.0 vs 0.95, etc. An audit surfaced ~25 visible
mismatches; this module centralises them so both renderers consume
the same numbers via direct import (desktop) or the build-time
relay into CSS custom properties (web).

The audit's choice of canonical value adopts the web's recent
tuning for PHOIBLE-scale inventories where the values diverged.
The desktop renderer reads from here directly; the web's CSS
reads via custom properties baked into ``dist/index.html`` by
``web/scripts/build.py``.

Categories:

* :data:`VOWEL_CHART_TITLE_*` -- font, weight, letter-spacing,
  padding for the "VOWELS" title row.
* :data:`VOWEL_CHART_COL_LABEL_*` -- col header tracking + font.
* :data:`VOWEL_CHART_ROW_LABEL_*` -- row label font + gutter width.
* :data:`VOWEL_CHART_CONTRAST_SET_*` -- 2x2 contrast-set spacing.
* :data:`VOWEL_SILHOUETTE_*` -- trapezoid outline stroke + alpha.
* :data:`VOWEL_CHART_DATA_MIN_H_PX` -- floor below which the data
  area refuses to compress further (small inventories like Spanish).
* :data:`DIPHTHONG_ARROW_*` -- per-arrow stroke, opacity, arrowhead
  size, control-point lift formula.

Pairing each constant with a docstring naming the divergence it
closes lets the next contributor see why the literal was lifted
rather than just where it landed.
"""

from __future__ import annotations

from phonology_shared.presentation.constants import (
    BTN_W,
    FONT_SIZE_LABEL_PX,
)
from phonology_shared.presentation.layout import (
    SEG_BTN_H,
    SPACING_PX,
    VOWEL_PAIR_GAP_PX,
)

# ---------------------------------------------------------------------------
# Title chrome
# ---------------------------------------------------------------------------

#: Font-size (px) for the "VOWELS" / language title rendered above
#: the trapezoid. Pre-audit desktop used 8pt (Qt) which at 96 DPI
#: rounds to ~10.7 px and scales with DPR; web used 11 px pinned via
#: the shared ``FONT_SIZE_LABEL_PX`` token. Both now read this.
VOWEL_CHART_TITLE_FONT_PX: int = FONT_SIZE_LABEL_PX

#: Font weight for the title. Desktop used ``QFont.Weight.Bold``
#: (~700); web used CSS ``font-weight: 600``. We standardise on
#: 600 (semibold) -- web's choice, slightly lighter, more in
#: keeping with axis labels in IPA charts.
VOWEL_CHART_TITLE_FONT_WEIGHT: int = 600

#: Letter-spacing (px) applied to the title. Desktop assembled
#: ``letter-spacing: 1px`` inline; web's CSS specified 0.5 px.
#: Picking the web's value: tighter tracking matches the rest of
#: the chart's label spacing ladder.
VOWEL_CHART_TITLE_LETTER_SPACING_PX: float = 0.5

#: Padding tuple ``(top, right, bottom, left)`` in px around the
#: title text. Desktop used ``(2, 2, 0, 2)`` (no bottom); web used
#: ``(--space-xs, 2px, --space-xs, 2px)`` which resolves to
#: ``(4, 2, 4, 2)``. Adopting the web's symmetric padding so the
#: title-to-column-headers gap is consistent.
VOWEL_CHART_TITLE_PADDING_PX: tuple[int, int, int, int] = (
    SPACING_PX["xs"],
    2,
    SPACING_PX["xs"],
    2,
)

#: Height (px) of the title strip / chrome row above the trapezoid.
#: Pre-relay only the desktop had this as a literal (``_TITLE_H =
#: 20``); the web sized it intrinsically via ``grid-template-rows:
#: auto auto 1fr``. The chrome height is what the desktop reserves
#: for the title row regardless of the title text length. Adopting
#: 20 px as the canonical value lets the web's grid use the same
#: min-height so cells above the trapezoid land at the same y on
#: both UIs (especially relevant after the title font change
#: shifted the intrinsic height by ~1-2 px).
VOWEL_CHART_TITLE_H_PX: int = 20


# ---------------------------------------------------------------------------
# Column headers (Front / Central / Back)
# ---------------------------------------------------------------------------

#: Font-size (px) for the column-header labels. Pre-audit desktop
#: used 7 pt (Qt); web used 11 px pinned via shared token. Both
#: now read this.
VOWEL_CHART_COL_LABEL_FONT_PX: int = FONT_SIZE_LABEL_PX

#: Letter-spacing (px) on column headers. Pre-audit desktop used
#: 0 (nothing); web applied 0.5 px. The 0.5 px tracking makes the
#: column headers read as axis labels rather than body text.
VOWEL_CHART_COL_LABEL_LETTER_SPACING_PX: float = 0.5


# ---------------------------------------------------------------------------
# Row labels (Close / Near-close / ... / Open)
# ---------------------------------------------------------------------------

#: Font-size (px) for the row labels. Pre-audit desktop used 7 pt;
#: web used the shared label token (11 px).
VOWEL_CHART_ROW_LABEL_FONT_PX: int = FONT_SIZE_LABEL_PX

#: Font weight for the row labels. Pre-audit desktop used Qt
#: ``Normal`` (400); web used ``font-weight: 500`` with the
#: rationale that axis labels read as lighter than headings.
#: Adopting web's 500 so the axis-label rhythm matches.
VOWEL_CHART_ROW_LABEL_FONT_WEIGHT: int = 500

#: Fixed gutter width (px) reserved for the row-label column. Web
#: used ``minmax(60px, auto)`` (60 px floor, grows); desktop used
#: fixed 72 px. Standardising on 72 px because "Near-close" and
#: "Open-mid" labels fit comfortably with breathing room. Web
#: switches from ``minmax(60px, auto)`` to a fixed 72 px column.
VOWEL_CHART_ROW_LABEL_GUTTER_PX: int = 72

#: Pixel gap between a row label's right edge and the silhouette's
#: slanted left edge at that row. Pre-relay desktop used 10 px
#: (``_ROW_LABEL_GAP_PX``); web used ``var(--space-md) + 2px`` =
#: 10 px after the spacing-ladder resolved. The values matched by
#: coincidence; pinning the canonical 10 px here so future tweaks
#: to ``SPACING_PX["md"]`` don't silently desync the two UIs.
VOWEL_CHART_ROW_LABEL_GAP_PX: int = 10


# ---------------------------------------------------------------------------
# Cell positioning math (pair-shift)
# ---------------------------------------------------------------------------

#: Half-stride (px) the renderer shifts a paired cell off its
#: backness anchor so the unrounded mate sits left and the rounded
#: mate sits right. Pre-relay desktop computed this inline as
#: ``(BTN_W + VOWEL_PAIR_GAP_PX) // 2`` (integer floor) and the
#: CSS repeated ``(var(--seg-btn-w) + var(--vowel-pair-gap)) / 2``
#: in three transform rules. The math is the same today but a
#: future ``BTN_W`` bump (different font, denser layout) would
#: silently break the rounded/unrounded tangency contract on one
#: side until everyone resynced. Single source here.
VOWEL_PAIR_SHIFT_PX: float = (BTN_W + VOWEL_PAIR_GAP_PX) / 2


# ---------------------------------------------------------------------------
# Stack inter-button gap (vertical)
# ---------------------------------------------------------------------------

#: Pixel gap between vertically stacked buttons inside a single
#: ``STACK``-display-kind cell. Both renderers consume this:
#: desktop calls ``QVBoxLayout.setSpacing`` with it, web's CSS
#: reads ``--vowel-cell-stack-gap`` baked from it, and the
#: geometry's ``natural_data_height_px`` math reads it via the
#: re-export at
#: :py:data:`phonology_shared.chart.vowels_layout.VOWEL_CELL_STACK_GAP_PX`.
#: Lives here (presentation layer) rather than in the chart
#: module so build.py can bake it without dragging the chart/
#: import chain into the build script.
VOWEL_CELL_STACK_GAP_PX: int = 1


# ---------------------------------------------------------------------------
# Contrast-set grid (3-4 entries differing on 2+ display features)
# ---------------------------------------------------------------------------

#: Row-gap (px) inside a contrast-set 2x2 grid. Pre-audit desktop
#: used 1 px; web used the shared ``VOWEL_PAIR_GAP_PX`` (2 px) on
#: both axes. Adopting 2 px so the grid reads as a 2x2 with
#: balanced spacing on each axis. Column gap already uses
#: ``VOWEL_PAIR_GAP_PX``; this constant pins the row axis to the
#: same value.
VOWEL_CHART_CONTRAST_SET_ROW_GAP_PX: int = 2


# ---------------------------------------------------------------------------
# Silhouette (trapezoid outline + container floor)
# ---------------------------------------------------------------------------

#: Stroke width (device px) for the trapezoid silhouette outline.
#: Pre-audit desktop used 1.25 px; web used a 1 px pseudo-element
#: trick. Standardising on 1.0 px so the outline reads with the
#: same visual weight as the app-wide ``--border-thin`` token.
VOWEL_SILHOUETTE_STROKE_PX: float = 1.0

#: Alpha (0..1) for the silhouette outline color. Pre-audit
#: desktop set ``setAlpha(178)`` (~70 %); web used CSS
#: ``color-mix(70%, transparent)``. Both expressed the same intent
#: (~70 % opacity); pinning the canonical value here so neither
#: side drifts.
VOWEL_SILHOUETTE_ALPHA: float = 0.70

#: Minimum height (px) the data area refuses to compress below.
#: Web set this to ``max(8 * SEG_BTN_H, natural_data_h)`` = at
#: least 208 px so tiny inventories (5-vowel Spanish) still draw
#: a reasonable trapezoid. Desktop's floor was set via the
#: outer region's minimum, effectively ~192 px after chrome
#: subtraction. Standardising on 8 * SEG_BTN_H = 208 px.
VOWEL_CHART_DATA_MIN_H_PX: int = 8 * SEG_BTN_H


# ---------------------------------------------------------------------------
# Height-tier bands (faint horizontal stripes inside the silhouette)
# ---------------------------------------------------------------------------

#: Alpha (0..1) for the tinted band fill. Pre-audit both used
#: ``color-mix(16 %, transparent)`` / ``setAlpha(40)``; pinning so
#: the rebalance lever lives in one place.
VOWEL_BAND_ALPHA: float = 0.16


# ---------------------------------------------------------------------------
# Diphthong arrows (curved arrows from primary to secondary cell)
# ---------------------------------------------------------------------------

#: Stroke width (px) for the curved arrow path. Pre-audit desktop
#: used ``pen.setWidthF(1.75)`` (px); web used SVG
#: ``stroke-width: 0.6`` with ``vector-effect: non-scaling-stroke``
#: (also px after the no-scaling rule). The two values produced
#: visibly different visual weight (desktop's lines read as much
#: heavier). Standardising on 1.0 px.
DIPHTHONG_ARROW_STROKE_PX: float = 1.0

#: Stroke + arrowhead opacity when the arrow's source vowel has
#: focus / hover. Pre-audit desktop painted at 1.0; web rendered
#: at 0.95. Adopting 0.95 so the curve doesn't fully overdraw the
#: cell buttons it passes over.
DIPHTHONG_ARROW_FOCUSED_ALPHA: float = 0.95

#: Stroke + arrowhead opacity in "show all arrows" mode (a toggle
#: that reveals every diphthong simultaneously). Pre-audit desktop
#: painted at 0.55; web at 0.70. Adopting 0.70 so the overview
#: stays legible even when many arrows tangle.
DIPHTHONG_ARROW_SHOW_ALL_ALPHA: float = 0.70

#: Arrowhead length as a fraction of the data-area width.
#: Pre-audit desktop fixed at 7 px (proportionally tiny on wide
#: charts); web used 2.5 SVG user-units (= 2.5 % of data width).
#: Standardising on the web's scaling behaviour: arrowheads grow
#: with chart width so they stay readable on narrow and wide
#: charts alike. 0.025 maps to ~7 px on a ~280 px data area
#: (Korean PHOIBLE) and ~15 px on a wide PHOIBLE inventory.
DIPHTHONG_ARROWHEAD_LEN_FRAC: float = 0.025

#: Arrowhead half-width as a fraction of the data-area width
#: (perpendicular to the chord tangent). Combined with
#: :data:`DIPHTHONG_ARROWHEAD_LEN_FRAC`, the arrowhead is a
#: triangle whose dimensions scale with the chart.
DIPHTHONG_ARROWHEAD_HALF_FRAC: float = 0.014

#: Fraction of the chord length used as the base lift for the
#: quadratic-Bezier control point. Both renderers used 0.18 today
#: but expressed in different coordinate systems; pinning the
#: shared value here so any rebalance touches one literal.
DIPHTHONG_LIFT_CHORD_FRAC: float = 0.18

#: Cap on the lift expressed as a fraction of the data-area
#: width. Pre-audit desktop capped at 0.05 (5 %); web capped at
#: 0.08 (8 %) of the data width. Adopting 0.08 so the curve
#: has more visible arc on cross-chart diphthongs (English /aɪ/,
#: German /au/), particularly when many arrows fan out from the
#: same source cell.
DIPHTHONG_LIFT_WIDTH_FRAC_CAP: float = 0.08
