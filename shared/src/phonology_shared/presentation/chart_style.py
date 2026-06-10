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
* :data:`SEG_GROUP_HEADER_*` -- consonant manner-class header
  font / weight / letter-spacing / padding.
* :data:`SEG_GROUP_GAP_PX` -- vertical gap between consecutive
  manner-class groups in the consonant grid.
* :data:`FEAT_ROW_*` -- feature-row padding, gap, button radius,
  compact-tier height + padding.
* :data:`BORDER_PX` -- border-thickness ladder for segment buttons.

Deliberately out of scope (documented divergences, not bugs):

* **Vowel chart layout** (web float vs desktop QHBoxLayout):
  the web uses CSS ``float`` so consonant rows wrap around the
  chart like text around an image; the desktop uses a fixed-width
  HBox so the chart is a sibling column. Unifying these would
  require either a position-absolute overlay on desktop or a
  grid-template-columns rewrite on web -- both are structural
  changes that go beyond a SSOT pass.
* **Feature-card chrome (--feat-card-chrome-h)**: the constant
  is relayed but not yet consumed by a CSS rule. Splitting it
  into ``--feat-card-margin-top/bottom`` + ``--feat-card-title-h``
  would let both surfaces derive 26 px from one source rather
  than reconstructing it; deferred until a feature-pane chrome
  redesign.
* **Font-size cluster** (segment-button 9pt vs 13px,
  feature-name 10pt vs 14px, etc.): Qt point sizes vs CSS pixel
  sizes is a known cross-platform impedance. The shared
  ``FONT_SIZE_*`` ladder already exists; widget-level fonts
  could migrate to it but the visual delta is small and the
  audit classified these as cosmetic.

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

#: Font-size (px) for the "VOWELS" / language title above the chart.
VOWEL_CHART_TITLE_FONT_PX: int = FONT_SIZE_LABEL_PX

#: Semibold matches axis-label rhythm in IPA charts.
VOWEL_CHART_TITLE_FONT_WEIGHT: int = 600

#: Letter-spacing (px) on the title.
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

#: Height (px) of the title strip above the trapezoid. Canonical
#: so the topmost vowel row sits at the same y on both UIs.
VOWEL_CHART_TITLE_H_PX: int = 20

#: Height (px) of the column-header strip (Front / Central / Back).
VOWEL_CHART_COL_HEADER_H_PX: int = 18

#: Right-edge padding inside the chart widget so back-column
#: cells at ``chart_x=1`` don't sit flush against the border.
VOWEL_CHART_PAD_R_PX: int = 12

#: Pixel padding inside the chart widget's bottom edge. Same
#: rationale as :data:`VOWEL_CHART_PAD_R_PX`: open vowels (lowest
#: row) shouldn't sit flush against the bottom border.
VOWEL_CHART_PAD_B_PX: int = 10


# ---------------------------------------------------------------------------
# Column headers (Front / Central / Back)
# ---------------------------------------------------------------------------

#: Font-size (px) for the column-header labels.
VOWEL_CHART_COL_LABEL_FONT_PX: int = FONT_SIZE_LABEL_PX

#: Letter-spacing (px) on column headers. 0.5 px tracking makes
#: them read as axis labels rather than body text.
VOWEL_CHART_COL_LABEL_LETTER_SPACING_PX: float = 0.5


# ---------------------------------------------------------------------------
# Row labels (Close / Near-close / ... / Open)
# ---------------------------------------------------------------------------

#: Font-size (px) for the row labels.
VOWEL_CHART_ROW_LABEL_FONT_PX: int = FONT_SIZE_LABEL_PX

#: Semibold so axis labels read lighter than the title.
VOWEL_CHART_ROW_LABEL_FONT_WEIGHT: int = 500

#: Fixed gutter width (px) for the row-label column. "Near-close"
#: and "Open-mid" fit at 72 px with breathing room.
VOWEL_CHART_ROW_LABEL_GUTTER_PX: int = 72

#: Gap (px) between a row label's right edge and the silhouette's
#: slanted left edge at that row. Pinned (not derived from
#: SPACING_PX) so a future spacing-ladder tweak can't desync.
VOWEL_CHART_ROW_LABEL_GAP_PX: int = 10


# ---------------------------------------------------------------------------
# Cell positioning math (pair-shift)
# ---------------------------------------------------------------------------

#: Half-stride (px) the renderer shifts a paired cell off its
#: backness anchor so the unrounded mate sits left and the rounded
#: mate sits right. Single source here so a future BTN_W bump
#: can't desync the rounded/unrounded tangency contract.
VOWEL_PAIR_SHIFT_PX: float = (BTN_W + VOWEL_PAIR_GAP_PX) / 2


# ---------------------------------------------------------------------------
# Segment-grid: manner-class group headers (PLOSIVE, FRICATIVE, ...)
# ---------------------------------------------------------------------------

#: Font size (px) for the manner-class group header label.
SEG_GROUP_HEADER_FONT_PX: int = FONT_SIZE_LABEL_PX

#: Semibold matches the vowel chart's title weight.
SEG_GROUP_HEADER_FONT_WEIGHT: int = 600

#: Letter-spacing (px) on group headers.
SEG_GROUP_HEADER_LETTER_SPACING_PX: int = 1

#: Padding ``(top, right, bottom, left)`` around the manner-class
#: header. 2 px bottom leaves enough gap that the header doesn't
#: read as clipped, tight enough that the label belongs to the
#: row below it.
SEG_GROUP_HEADER_PADDING_PX: tuple[int, int, int, int] = (4, 2, 2, 2)

#: Vertical gap (px) between consecutive manner-class groups so
#: adjacent classes read as distinct sections.
SEG_GROUP_GAP_PX: int = SPACING_PX["md"]


# ---------------------------------------------------------------------------
# Feature row (+/- buttons + badge + feature name)
# ---------------------------------------------------------------------------

#: Vertical padding (px) inside a feature row. Tuned to keep the
#: desktop row-stride at 31 px (FEAT_ROW_H 30 + 1 spacing).
FEAT_ROW_PADDING_V_PX: int = 3

#: Horizontal padding (px) inside a feature row.
FEAT_ROW_PADDING_H_PX: int = SPACING_PX["md"]

#: Gap (px) between the feature label, +/- buttons, and badge.
FEAT_ROW_GAP_PX: int = SPACING_PX["xs"]

#: Border-radius (px) for the +/- buttons on a feature row.
FEAT_BTN_RADIUS_PX: int = 5

#: Compact-tier row height (px) when the feature count exceeds
#: FEAT_COMPACT_THRESHOLD and rows must shrink to fit the pane.
FEAT_ROW_H_COMPACT_PX: int = 26

#: Compact-tier vertical padding (px) inside a row.
FEAT_ROW_PADDING_V_COMPACT_PX: int = 2


# ---------------------------------------------------------------------------
# Segment-button border thickness ladder
# ---------------------------------------------------------------------------

#: Border thickness ladder for segment buttons and any other
#: chart element with a state-driven outline. Named so a future
#: HiDPI sweep is one constant edit.
BORDER_PX: dict[str, float] = {
    "thin": 1.0,
    "std": 1.5,
    "thick": 2.0,
}


# ---------------------------------------------------------------------------
# Stack inter-button gap (vertical)
# ---------------------------------------------------------------------------

#: Gap (px) between vertically stacked buttons inside a STACK
#: cell. Lives in presentation (not chart) so build.py can bake
#: it without importing the chart module.
VOWEL_CELL_STACK_GAP_PX: int = 1


# ---------------------------------------------------------------------------
# Contrast-set grid (3-4 entries differing on 2+ display features)
# ---------------------------------------------------------------------------

#: Row-gap (px) inside a contrast-set 2x2 grid. Matches the
#: column gap (``VOWEL_PAIR_GAP_PX``) so the grid reads balanced.
VOWEL_CHART_CONTRAST_SET_ROW_GAP_PX: int = 2


# ---------------------------------------------------------------------------
# Silhouette (trapezoid outline + container floor)
# ---------------------------------------------------------------------------

#: Stroke width (device px) for the trapezoid silhouette. 0.6 px
#: reads as a context cue rather than a frame, letting the
#: vowel buttons carry the visual weight; the prior 1.0 px stroke
#: competed with the cells for attention.
VOWEL_SILHOUETTE_STROKE_PX: float = 0.6

#: Silhouette outline corner radius as a fraction of the data
#: area width. Bumped to 0.024 alongside the thinner stroke so
#: the silhouette reads as a soft container rather than a hard
#: frame. Fraction (not pixels) so CSS clip-path resolves it
#: natively without a per-resize JS recompute.
VOWEL_SILHOUETTE_CORNER_RADIUS_FRAC: float = 0.024

#: Alpha (0..1) for the silhouette outline color.
VOWEL_SILHOUETTE_ALPHA: float = 0.70

#: Minimum data-area height so tiny inventories (5-vowel Spanish)
#: still draw a recognisable trapezoid.
VOWEL_CHART_DATA_MIN_H_PX: int = 8 * SEG_BTN_H

#: Maximum silhouette aspect ratio (width / height). When natural
#: sizing produces an over-wide silhouette (sparse inventories
#: like Spanish, MSA, Lango where dw is set by chrome but the
#: populated row count is small), ``build_vowel_chart_geometry``
#: grows ``natural_data_height_px`` until aspect lands at this
#: ceiling. The canonical IPA chart aspect is 10:7 (~1.43:1, per
#: the Wikipedia blank vowel trapezoid SVG at 1000x700). 1.8
#: empirically lets the "looks fine" cluster (Korean PHOIBLE
#: 1.81, Hayes 1.53, German 1.53) pass through unchanged while
#: catching the 2.35+ outliers (Spanish 2.35, MSA 3.29) that
#: read as visually over-stretched.
VOWEL_SILHOUETTE_MAX_ASPECT: float = 1.8


# ---------------------------------------------------------------------------
# Diphthong arrows (curved arrows from primary to secondary cell)
# ---------------------------------------------------------------------------

#: Stroke width (px) for the curved arrow path.
DIPHTHONG_ARROW_STROKE_PX: float = 1.0

#: Stroke + arrowhead opacity in diphthong display mode (arrows
#: are always-on in that mode; dimmed-other-arrows on hover is
#: handled in the renderer, not via an alpha constant).
DIPHTHONG_ARROW_FOCUSED_ALPHA: float = 0.95

#: Arrowhead length as a fraction of the data-area width so it
#: scales with the chart instead of pinning to pixels.
DIPHTHONG_ARROWHEAD_LEN_FRAC: float = 0.025

#: Arrowhead half-width perpendicular to the chord tangent.
DIPHTHONG_ARROWHEAD_HALF_FRAC: float = 0.014

#: Base lift for the quadratic-Bezier control point, as a
#: fraction of the chord length.
DIPHTHONG_LIFT_CHORD_FRAC: float = 0.18

#: Lift cap (fraction of data-area width). Keeps fan-out arrows
#: from the same source cell visually distinguishable.
DIPHTHONG_LIFT_WIDTH_FRAC_CAP: float = 0.08
